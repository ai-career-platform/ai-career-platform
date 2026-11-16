-- T137 skill / job-role standard code & alias policy: executable MOCK for disposable databases only.
-- STATUS: DRAFT / NOT A MIGRATION / NOT APPROVED. NEVER run on Staging.
-- Policy: docs/data/CODE_TAXONOMY_POLICY.md
--
-- Isolated schema `taxonomy_mock`; does not touch `career.skills` / `career.job_roles`.
-- Roles (created for the disposable test cluster only)
--   t137_reader  : search/autocomplete/matching APIs -> SELECT + resolve_term()
--   t137_curator : taxonomy maintainers               -> curator functions only (no direct DML)
--   table owner  : migrator
SET client_encoding = 'UTF8';
BEGIN;

CREATE SCHEMA taxonomy_mock;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't137_reader')  THEN CREATE ROLE t137_reader NOLOGIN;  END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't137_curator') THEN CREATE ROLE t137_curator NOLOGIN; END IF;
END $$;

-- ------------------------------------------------------------ normalization
-- lower case, NFKC, drop spaces . - _ / and brackets; KEEP + and # (C++ vs C#)
CREATE FUNCTION taxonomy_mock.normalize_term(p text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT regexp_replace(lower(normalize(btrim(p), NFKC)), '[[:space:]._/()\[\]-]+', '', 'g')
$$;

-- ------------------------------------------------------------ versions & codes
CREATE TABLE taxonomy_mock.taxonomy_versions (
    version     varchar(20) PRIMARY KEY,
    released_at timestamptz NOT NULL DEFAULT now(),
    note        text NOT NULL,
    CONSTRAINT version_format CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$')
);

CREATE TABLE taxonomy_mock.taxonomy_codes (
    entity_type    varchar(16) NOT NULL,
    code           varchar(64) NOT NULL,
    name_ko        varchar(160) NOT NULL,
    name_en        varchar(160) NOT NULL,
    status         varchar(16) NOT NULL DEFAULT 'active',
    replaced_by    varchar(64),
    introduced_in  varchar(20) NOT NULL REFERENCES taxonomy_mock.taxonomy_versions (version),
    deprecated_in  varchar(20) REFERENCES taxonomy_mock.taxonomy_versions (version),
    -- T05 B04/B05 keep only is_active (soft delete). status/replaced_by are T137 proposals; is_active is derived
    is_active      boolean GENERATED ALWAYS AS (status = 'active') STORED,
    PRIMARY KEY (entity_type, code),
    FOREIGN KEY (entity_type, replaced_by) REFERENCES taxonomy_mock.taxonomy_codes (entity_type, code),
    CONSTRAINT code_entity_type CHECK (entity_type IN ('skill', 'job_role')),
    CONSTRAINT code_format CHECK (code ~ '^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$'),
    CONSTRAINT code_status CHECK (status IN ('active', 'deprecated', 'merged')),
    CONSTRAINT code_status_replacement CHECK (
        (status = 'active' AND replaced_by IS NULL AND deprecated_in IS NULL)
        OR (status = 'deprecated' AND deprecated_in IS NOT NULL AND replaced_by IS DISTINCT FROM code)
        OR (status = 'merged' AND replaced_by IS NOT NULL AND replaced_by <> code AND deprecated_in IS NOT NULL)
    ),
    CONSTRAINT code_names_not_blank CHECK (length(btrim(name_ko)) > 0 AND length(btrim(name_en)) > 0)
);

-- ------------------------------------------------------------ aliases
CREATE TABLE taxonomy_mock.taxonomy_aliases (
    entity_type   varchar(16) NOT NULL,
    alias_norm    varchar(160) NOT NULL,
    alias_display varchar(160) NOT NULL,
    code          varchar(64) NOT NULL,
    kind          varchar(12) NOT NULL DEFAULT 'exact',
    PRIMARY KEY (entity_type, alias_norm, code),
    FOREIGN KEY (entity_type, code) REFERENCES taxonomy_mock.taxonomy_codes (entity_type, code),
    CONSTRAINT alias_kind CHECK (kind IN ('exact', 'ambiguous')),
    CONSTRAINT alias_norm_matches CHECK (alias_norm = taxonomy_mock.normalize_term(alias_display) AND alias_norm <> '')
);
-- an exact alias points to exactly one code
CREATE UNIQUE INDEX ux_alias_exact ON taxonomy_mock.taxonomy_aliases (entity_type, alias_norm) WHERE kind = 'exact';

-- alias integrity: no exact/ambiguous mix, no collision with another code's own code, never on merged codes
CREATE FUNCTION taxonomy_mock.aliases_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_aliases a
               WHERE a.entity_type = NEW.entity_type AND a.alias_norm = NEW.alias_norm
                 AND a.kind <> NEW.kind AND a.code <> NEW.code) THEN  -- same code = same row (PK); skip its old version on UPDATE
        RAISE EXCEPTION 'alias % mixes exact and ambiguous meanings', NEW.alias_display USING ERRCODE = '23505';
    END IF;
    IF EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_codes c
               WHERE c.entity_type = NEW.entity_type AND c.code <> NEW.code
                 AND taxonomy_mock.normalize_term(c.code) = NEW.alias_norm) THEN
        RAISE EXCEPTION 'alias % collides with another code', NEW.alias_display USING ERRCODE = '23505';
    END IF;
    IF EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_codes c
               WHERE c.entity_type = NEW.entity_type AND c.code = NEW.code AND c.status = 'merged') THEN
        RAISE EXCEPTION 'alias must point to the surviving code, not merged %', NEW.code USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_aliases_guard BEFORE INSERT OR UPDATE ON taxonomy_mock.taxonomy_aliases
    FOR EACH ROW EXECUTE FUNCTION taxonomy_mock.aliases_guard();

-- codes are never deleted and never renamed; replacement chains must not loop
CREATE FUNCTION taxonomy_mock.codes_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    cur varchar(64);
    depth int := 0;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'codes are never deleted; deprecate or merge instead' USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.code <> OLD.code OR NEW.entity_type <> OLD.entity_type) THEN
        RAISE EXCEPTION 'code values are immutable (% -> %)', OLD.code, NEW.code USING ERRCODE = '42501';
    END IF;
    IF TG_OP = 'UPDATE' AND OLD.status <> 'active' AND NEW.status = 'active' THEN
        RAISE EXCEPTION 'retired code % cannot be reactivated; add a new code', OLD.code USING ERRCODE = '23514';
    END IF;
    cur := NEW.replaced_by;
    WHILE cur IS NOT NULL LOOP
        depth := depth + 1;
        IF cur = NEW.code OR depth > 5 THEN
            RAISE EXCEPTION 'replacement chain of % loops or is too deep', NEW.code USING ERRCODE = '23514';
        END IF;
        SELECT replaced_by INTO cur FROM taxonomy_mock.taxonomy_codes
        WHERE entity_type = NEW.entity_type AND code = cur;
    END LOOP;
    RETURN NEW;
END $$;
CREATE TRIGGER trg_codes_guard BEFORE INSERT OR UPDATE OR DELETE ON taxonomy_mock.taxonomy_codes
    FOR EACH ROW EXECUTE FUNCTION taxonomy_mock.codes_guard();

-- ------------------------------------------------------------ change log (append-only)
CREATE TABLE taxonomy_mock.taxonomy_change_log (
    change_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version      varchar(20) NOT NULL REFERENCES taxonomy_mock.taxonomy_versions (version),
    entity_type  varchar(16) NOT NULL,
    code         varchar(64) NOT NULL,
    change_type  varchar(20) NOT NULL,
    detail       jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason       text NOT NULL,
    changed_by   name NOT NULL DEFAULT session_user,
    changed_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT change_type_check CHECK (change_type IN ('add', 'rename', 'alias_add', 'deprecate', 'merge')),
    CONSTRAINT change_reason_not_blank CHECK (length(btrim(reason)) >= 5)
);
CREATE FUNCTION taxonomy_mock.change_log_block() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'taxonomy_change_log is append-only' USING ERRCODE = '42501';
END $$;
CREATE TRIGGER trg_change_log_block BEFORE UPDATE OR DELETE ON taxonomy_mock.taxonomy_change_log
    FOR EACH ROW EXECUTE FUNCTION taxonomy_mock.change_log_block();

-- ------------------------------------------------------------ read API: resolve a user/posting term
-- match_type: code | alias | ambiguous | not_found ; canonical_code follows merges to the live code
CREATE FUNCTION taxonomy_mock.resolve_term(p_entity_type varchar, p_term text)
RETURNS TABLE (input_code varchar, canonical_code varchar, match_type text, is_deprecated boolean)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = taxonomy_mock, pg_temp AS $$
    WITH RECURSIVE n AS (
        SELECT taxonomy_mock.normalize_term(p_term) AS t
    ), hits AS (
        SELECT c.code, 'code'::text AS match_type FROM taxonomy_mock.taxonomy_codes c, n
        WHERE c.entity_type = p_entity_type AND taxonomy_mock.normalize_term(c.code) = n.t
        UNION
        SELECT a.code, CASE a.kind WHEN 'exact' THEN 'alias' ELSE 'ambiguous' END
        FROM taxonomy_mock.taxonomy_aliases a, n
        WHERE a.entity_type = p_entity_type AND a.alias_norm = n.t
          AND NOT EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_codes c2
                          WHERE c2.entity_type = p_entity_type AND taxonomy_mock.normalize_term(c2.code) = n.t)
    ), chain AS (
        SELECT h.code AS start_code, c.code AS cur, c.replaced_by, c.status, h.match_type, 0 AS depth
        FROM hits h JOIN taxonomy_mock.taxonomy_codes c ON c.entity_type = p_entity_type AND c.code = h.code
        UNION ALL
        SELECT ch.start_code, c.code, c.replaced_by, c.status, ch.match_type, ch.depth + 1
        FROM chain ch JOIN taxonomy_mock.taxonomy_codes c ON c.entity_type = p_entity_type AND c.code = ch.replaced_by
        WHERE ch.depth < 5
    )
    SELECT s.start_code, f.cur, s.match_type, s.status <> 'active'
    FROM (SELECT DISTINCT ON (start_code) start_code, status, match_type FROM chain ORDER BY start_code, depth) s
    JOIN (SELECT DISTINCT ON (start_code) start_code, cur FROM chain ORDER BY start_code, depth DESC) f USING (start_code)
    UNION ALL
    SELECT NULL, NULL, 'not_found', NULL WHERE NOT EXISTS (SELECT 1 FROM hits)
    ORDER BY 2
$$;

-- ------------------------------------------------------------ curator API (only way to change data)
CREATE FUNCTION taxonomy_mock.require_version(p_version varchar) RETURNS void
LANGUAGE plpgsql STABLE AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_versions WHERE version = p_version) THEN
        RAISE EXCEPTION 'unknown taxonomy version %', p_version USING ERRCODE = '22023';
    END IF;
END $$;

CREATE FUNCTION taxonomy_mock.add_code(p_entity_type varchar, p_code varchar, p_name_ko varchar, p_name_en varchar,
                                       p_version varchar, p_reason text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = taxonomy_mock, pg_temp AS $$
BEGIN
    PERFORM taxonomy_mock.require_version(p_version);
    IF EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_aliases
               WHERE entity_type = p_entity_type AND alias_norm = taxonomy_mock.normalize_term(p_code)) THEN
        RAISE EXCEPTION 'new code % collides with an existing alias', p_code USING ERRCODE = '23505';
    END IF;
    INSERT INTO taxonomy_mock.taxonomy_codes (entity_type, code, name_ko, name_en, introduced_in)
    VALUES (p_entity_type, p_code, p_name_ko, p_name_en, p_version);
    INSERT INTO taxonomy_mock.taxonomy_change_log (version, entity_type, code, change_type, detail, reason)
    VALUES (p_version, p_entity_type, p_code, 'add', jsonb_build_object('name_ko', p_name_ko, 'name_en', p_name_en), p_reason);
END $$;

CREATE FUNCTION taxonomy_mock.add_alias(p_entity_type varchar, p_alias text, p_code varchar, p_kind varchar,
                                        p_version varchar, p_reason text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = taxonomy_mock, pg_temp AS $$
BEGIN
    PERFORM taxonomy_mock.require_version(p_version);
    INSERT INTO taxonomy_mock.taxonomy_aliases (entity_type, alias_norm, alias_display, code, kind)
    VALUES (p_entity_type, taxonomy_mock.normalize_term(p_alias), p_alias, p_code, p_kind);
    INSERT INTO taxonomy_mock.taxonomy_change_log (version, entity_type, code, change_type, detail, reason)
    VALUES (p_version, p_entity_type, p_code, 'alias_add', jsonb_build_object('alias', p_alias, 'kind', p_kind), p_reason);
END $$;

-- merge: old code stays resolvable, aliases move to the survivor, old code becomes an exact alias target via code match
CREATE FUNCTION taxonomy_mock.merge_code(p_entity_type varchar, p_from varchar, p_into varchar,
                                         p_version varchar, p_reason text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = taxonomy_mock, pg_temp AS $$
DECLARE
    from_status varchar;
    demoted     text[];
BEGIN
    PERFORM taxonomy_mock.require_version(p_version);
    IF NOT EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_codes
                   WHERE entity_type = p_entity_type AND code = p_into AND status = 'active') THEN
        RAISE EXCEPTION 'merge target % must be an active code', p_into USING ERRCODE = '23514';
    END IF;
    -- an already merged code keeps its first survivor; re-merging would silently rewrite
    -- replaced_by / deprecated_in (deprecated -> merged is allowed: a replacement was found later)
    SELECT status INTO from_status FROM taxonomy_mock.taxonomy_codes
    WHERE entity_type = p_entity_type AND code = p_from;
    IF from_status IS NULL THEN
        RAISE EXCEPTION 'unknown code %', p_from USING ERRCODE = '22023';
    ELSIF from_status = 'merged' THEN
        RAISE EXCEPTION 'code % is already merged; it cannot be merged again', p_from USING ERRCODE = '23514';
    END IF;
    -- move aliases to the survivor by re-pointing them (an INSERT copy would hit the
    -- one-code-per-exact-alias index and be skipped silently). First drop redundant ones:
    -- aliases equal to a code's own spelling (e.g. 'go lang' == GOLANG; code matching already
    -- resolves them) and aliases the survivor already has.
    DELETE FROM taxonomy_mock.taxonomy_aliases a
    WHERE a.entity_type = p_entity_type AND a.code = p_from
      AND (EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_codes c
                   WHERE c.entity_type = p_entity_type AND c.code <> p_into
                     AND taxonomy_mock.normalize_term(c.code) = a.alias_norm)
           OR EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_aliases s
                      WHERE s.entity_type = p_entity_type AND s.code = p_into AND s.alias_norm = a.alias_norm));
    UPDATE taxonomy_mock.taxonomy_aliases SET code = p_into
    WHERE entity_type = p_entity_type AND code = p_from;
    -- an ambiguous alias whose other meaning was just merged away now has one meaning:
    -- make it exact so resolve_term auto-resolves it and validate_taxonomy stays clean
    WITH single AS (
        UPDATE taxonomy_mock.taxonomy_aliases a SET kind = 'exact'
        WHERE a.entity_type = p_entity_type AND a.code = p_into AND a.kind = 'ambiguous'
          AND (SELECT count(*) FROM taxonomy_mock.taxonomy_aliases o
               WHERE o.entity_type = a.entity_type AND o.alias_norm = a.alias_norm) = 1
        RETURNING a.alias_display
    )
    SELECT array_agg(alias_display ORDER BY alias_display) INTO demoted FROM single;
    UPDATE taxonomy_mock.taxonomy_codes
    SET status = 'merged', replaced_by = p_into, deprecated_in = p_version
    WHERE entity_type = p_entity_type AND code = p_from;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown code %', p_from USING ERRCODE = '22023';
    END IF;
    INSERT INTO taxonomy_mock.taxonomy_change_log (version, entity_type, code, change_type, detail, reason)
    VALUES (p_version, p_entity_type, p_from, 'merge',
            jsonb_build_object('into', p_into, 'aliases_made_exact', coalesce(demoted, '{}'::text[])), p_reason);
END $$;

CREATE FUNCTION taxonomy_mock.deprecate_code(p_entity_type varchar, p_code varchar, p_version varchar, p_reason text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = taxonomy_mock, pg_temp AS $$
BEGIN
    PERFORM taxonomy_mock.require_version(p_version);
    UPDATE taxonomy_mock.taxonomy_codes SET status = 'deprecated', deprecated_in = p_version
    WHERE entity_type = p_entity_type AND code = p_code AND status = 'active';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'active code % not found', p_code USING ERRCODE = '22023';
    END IF;
    INSERT INTO taxonomy_mock.taxonomy_change_log (version, entity_type, code, change_type, reason)
    VALUES (p_version, p_entity_type, p_code, 'deprecate', p_reason);
END $$;

-- consistency report used by CI / curators: returns one row per violation (expect zero rows)
CREATE FUNCTION taxonomy_mock.validate_taxonomy()
RETURNS TABLE (problem text, entity_type varchar, code varchar)
LANGUAGE sql STABLE AS $$
    SELECT 'merged code points to a non-active survivor', c.entity_type, c.code
    FROM taxonomy_mock.taxonomy_codes c
    JOIN taxonomy_mock.taxonomy_codes r ON r.entity_type = c.entity_type AND r.code = c.replaced_by
    WHERE c.status = 'merged' AND r.status <> 'active'
    UNION ALL
    SELECT 'alias points to a merged code', a.entity_type, a.code
    FROM taxonomy_mock.taxonomy_aliases a
    JOIN taxonomy_mock.taxonomy_codes c ON c.entity_type = a.entity_type AND c.code = a.code
    WHERE c.status = 'merged'
    UNION ALL
    SELECT 'ambiguous alias with a single meaning', a.entity_type, min(a.code)
    FROM taxonomy_mock.taxonomy_aliases a WHERE a.kind = 'ambiguous'
    GROUP BY a.entity_type, a.alias_norm HAVING count(*) < 2
    UNION ALL
    SELECT 'duplicate active English name', c.entity_type, min(c.code)
    FROM taxonomy_mock.taxonomy_codes c WHERE c.status = 'active'
    GROUP BY c.entity_type, taxonomy_mock.normalize_term(c.name_en) HAVING count(*) > 1
$$;

-- ------------------------------------------------------------ privileges
REVOKE ALL ON SCHEMA taxonomy_mock FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA taxonomy_mock FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA taxonomy_mock FROM PUBLIC;
GRANT USAGE ON SCHEMA taxonomy_mock TO t137_reader, t137_curator;
GRANT SELECT ON taxonomy_mock.taxonomy_codes, taxonomy_mock.taxonomy_aliases, taxonomy_mock.taxonomy_versions
    TO t137_reader, t137_curator;
GRANT SELECT ON taxonomy_mock.taxonomy_change_log TO t137_curator;
GRANT EXECUTE ON FUNCTION taxonomy_mock.normalize_term(text), taxonomy_mock.resolve_term(varchar, text)
    TO t137_reader, t137_curator;
GRANT EXECUTE ON FUNCTION
    taxonomy_mock.add_code(varchar, varchar, varchar, varchar, varchar, text),
    taxonomy_mock.add_alias(varchar, text, varchar, varchar, varchar, text),
    taxonomy_mock.merge_code(varchar, varchar, varchar, varchar, text),
    taxonomy_mock.deprecate_code(varchar, varchar, varchar, text),
    taxonomy_mock.validate_taxonomy()
    TO t137_curator;

-- ------------------------------------------------------------ sample data (codes follow T10 seed)
INSERT INTO taxonomy_mock.taxonomy_versions (version, note) VALUES
    ('1.0.0', '초기 기준선 (T10 Seed 코드)'),
    ('1.1.0', '코드 추가'),
    ('2.0.0', '병합·폐기 포함 (major)');

INSERT INTO taxonomy_mock.taxonomy_codes (entity_type, code, name_ko, name_en, introduced_in) VALUES
    ('skill', 'PYTHON', '파이썬', 'Python', '1.0.0'),
    ('skill', 'JAVASCRIPT', '자바스크립트', 'JavaScript', '1.0.0'),
    ('skill', 'TYPESCRIPT', '타입스크립트', 'TypeScript', '1.0.0'),
    ('skill', 'NODEJS', '노드JS', 'Node.js', '1.0.0'),
    ('skill', 'REACT', '리액트', 'React', '1.0.0'),
    ('skill', 'REACT_NATIVE', '리액트 네이티브', 'React Native', '1.0.0'),
    ('skill', 'GO', 'Go 언어', 'Go', '1.0.0'),
    ('skill', 'CPP', 'C++', 'C++', '1.0.0'),
    ('skill', 'CSHARP', 'C#', 'C#', '1.0.0'),
    ('skill', 'SPRING_BOOT', '스프링 부트', 'Spring Boot', '1.0.0'),
    ('skill', 'SPRING_FRAMEWORK', '스프링 프레임워크', 'Spring Framework', '1.0.0'),
    ('skill', 'POSTGRESQL', 'PostgreSQL', 'PostgreSQL', '1.0.0'),
    ('skill', 'KUBERNETES', '쿠버네티스', 'Kubernetes', '1.0.0'),
    ('job_role', 'BACKEND_ENGINEER', '백엔드 개발자', 'Backend Engineer', '1.0.0'),
    ('job_role', 'FRONTEND_ENGINEER', '프론트엔드 개발자', 'Frontend Engineer', '1.0.0'),
    ('job_role', 'ML_ENGINEER', '머신러닝 엔지니어', 'Machine Learning Engineer', '1.0.0');

INSERT INTO taxonomy_mock.taxonomy_aliases (entity_type, alias_norm, alias_display, code, kind)
SELECT v.entity_type, taxonomy_mock.normalize_term(v.alias), v.alias, v.code, v.kind
FROM (VALUES
    ('skill', '파이썬', 'PYTHON', 'exact'), ('skill', 'py', 'PYTHON', 'exact'),
    ('skill', 'JS', 'JAVASCRIPT', 'exact'), ('skill', '자바스크립트', 'JAVASCRIPT', 'exact'),
    ('skill', 'TS', 'TYPESCRIPT', 'exact'),
    ('skill', 'Node.js', 'NODEJS', 'exact'), ('skill', '노드', 'NODEJS', 'exact'),
    ('skill', 'React.js', 'REACT', 'exact'), ('skill', '리액트', 'REACT', 'exact'),
    ('skill', 'C++', 'CPP', 'exact'), ('skill', 'C#', 'CSHARP', 'exact'),
    ('skill', 'Postgres', 'POSTGRESQL', 'exact'),
    ('skill', 'k8s', 'KUBERNETES', 'exact'), ('skill', '쿠버네티스', 'KUBERNETES', 'exact'),
    ('skill', 'Spring', 'SPRING_BOOT', 'ambiguous'), ('skill', 'Spring', 'SPRING_FRAMEWORK', 'ambiguous'),
    ('skill', '스프링', 'SPRING_BOOT', 'ambiguous'), ('skill', '스프링', 'SPRING_FRAMEWORK', 'ambiguous'),
    ('job_role', '백엔드', 'BACKEND_ENGINEER', 'exact'), ('job_role', '서버 개발자', 'BACKEND_ENGINEER', 'exact'),
    ('job_role', 'MLE', 'ML_ENGINEER', 'exact')
) AS v(entity_type, alias, code, kind);

COMMIT;
