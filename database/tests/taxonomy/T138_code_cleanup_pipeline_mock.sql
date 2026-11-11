-- T138 skill / job-role code cleanup and change-history pipeline: executable MOCK for disposable databases only.
-- STATUS: DRAFT / NOT A MIGRATION / NOT APPROVED. NEVER run on Staging.
-- Work order: docs/work-orders/fifth-30/T138.md · Policy: docs/data/CODE_TAXONOMY_POLICY.md (T137)
--
-- Load order (disposable DB): security/DRAFT_00 -> migrations/0001 (as career_migrator) -> seeds/0001
--   -> tests/taxonomy/T137_code_taxonomy_mock.sql -> this file.
-- Mixed approach: the taxonomy (codes, aliases, status, change log) stays in the T137 mock schema
-- `taxonomy_mock`; the rows that get remapped are the REAL `career` tables from 0001 + seed.
-- Nothing here is a migration; `career` tables are not altered, only their rows change.
--
-- What the pipeline does (one entity type per run: 'skill' -> career.skills, 'job_role' -> career.job_roles)
--   1. preflight : stop before touching data if the taxonomy has loops, too-deep chains, violations,
--                  or a merge target that does not exist / is inactive in career.
--   2. status    : codes that are deprecated/merged in the taxonomy -> career.<table>.is_active = false.
--                  Rows are never deleted, so FKs (ON DELETE RESTRICT) and old ids stay valid.
--   3. remap     : current-state rows pointing at a merged code move to the surviving code.
--                  Duplicate (same owner already has the survivor) -> keep the higher value, drop the old row.
--                  Historical / AI-result tables are left as they are (decision 2026-11-09).
--   4. history   : every changed row is copied to remap_log BEFORE it changes (original_row), append-only.
-- Re-running is a no-op once everything points at live codes (idempotent).
--
-- Roles (disposable test cluster only)
--   t138_operator : may run preflight / run_cleanup / stage_terms and read the pipeline tables
--   everyone else : no access (career_app, career_reader, t137_reader, t137_curator)
SET client_encoding = 'UTF8';
BEGIN;

CREATE SCHEMA taxonomy_pipeline_mock;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't138_operator') THEN
        CREATE ROLE t138_operator NOLOGIN;
    END IF;
END $$;

-- ------------------------------------------------------------ tables
-- one row per pipeline run (dry runs included)
CREATE TABLE taxonomy_pipeline_mock.pipeline_runs (
    run_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    entity_type varchar(16) NOT NULL,
    mode varchar(8) NOT NULL,
    status varchar(8) NOT NULL DEFAULT 'running',
    taxonomy_version varchar(20),
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    run_by name NOT NULL DEFAULT session_user,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    CONSTRAINT run_entity_type CHECK (entity_type IN ('skill', 'job_role')),
    CONSTRAINT run_mode CHECK (mode IN ('dry_run', 'apply')),
    CONSTRAINT run_status CHECK (status IN ('running', 'ok', 'blocked'))
);

-- every career row the pipeline changed or removed, copied before the change
CREATE TABLE taxonomy_pipeline_mock.remap_log (
    log_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id bigint NOT NULL REFERENCES taxonomy_pipeline_mock.pipeline_runs (run_id),
    entity_type varchar(16) NOT NULL,
    table_name text NOT NULL,
    action varchar(20) NOT NULL,
    from_code varchar(64) NOT NULL,
    to_code varchar(64),
    original_row jsonb NOT NULL,
    kept_row jsonb,
    logged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT remap_action CHECK (action IN ('status_synced', 'remapped', 'conflict_merged')),
    CONSTRAINT remap_target CHECK ((action = 'status_synced') = (to_code IS NULL))
);
CREATE INDEX ix_remap_log_run ON taxonomy_pipeline_mock.remap_log (run_id);

CREATE FUNCTION taxonomy_pipeline_mock.remap_log_block() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'remap_log is append-only' USING ERRCODE = '42501';
END $$;
CREATE TRIGGER trg_remap_log_block BEFORE UPDATE OR DELETE ON taxonomy_pipeline_mock.remap_log
FOR EACH ROW EXECUTE FUNCTION taxonomy_pipeline_mock.remap_log_block();

-- raw terms (posting tags, user input) that could not be mapped to exactly one code
CREATE TABLE taxonomy_pipeline_mock.term_review_queue (
    entity_type varchar(16) NOT NULL,
    source varchar(40) NOT NULL,
    term_norm varchar(160) NOT NULL,
    term_display varchar(160) NOT NULL,
    reason varchar(12) NOT NULL,
    candidates varchar(64)[] NOT NULL DEFAULT '{}',
    status varchar(12) NOT NULL DEFAULT 'pending',
    seen_count integer NOT NULL DEFAULT 1,
    first_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (entity_type, source, term_norm),
    CONSTRAINT review_reason CHECK (reason IN ('ambiguous', 'not_found')),
    CONSTRAINT review_status CHECK (status IN ('pending', 'resolved', 'ignored')),
    CONSTRAINT review_candidates CHECK ((reason = 'ambiguous') = (cardinality(candidates) >= 2))
);

-- ------------------------------------------------------------ helpers
-- career table that holds the codes of an entity type
CREATE FUNCTION taxonomy_pipeline_mock.career_code_table(p_entity_type varchar) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$
    SELECT CASE p_entity_type WHEN 'skill' THEN 'career.skills' WHEN 'job_role' THEN 'career.job_roles' END
$$;

-- every merged code with the live code at the end of its replacement chain.
-- reaches_active = false means the chain loops or is deeper than 5 (preflight blocks on it).
CREATE FUNCTION taxonomy_pipeline_mock.canonical_map(p_entity_type varchar)
RETURNS TABLE (from_code varchar, to_code varchar, depth int, reaches_active boolean)
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE walk AS (
        SELECT c.code AS start_code, c.replaced_by AS cur, 1 AS depth, ARRAY[c.code]::varchar[] AS seen
        FROM taxonomy_mock.taxonomy_codes c
        WHERE c.entity_type = p_entity_type AND c.status = 'merged'
        UNION ALL
        SELECT w.start_code, n.replaced_by, w.depth + 1, w.seen || w.cur
        FROM walk w
        JOIN taxonomy_mock.taxonomy_codes n ON n.entity_type = p_entity_type AND n.code = w.cur
        WHERE n.status = 'merged' AND w.depth < 6 AND NOT (w.cur = ANY (w.seen))
    ), last_step AS (
        SELECT DISTINCT ON (start_code) start_code, cur, depth
        FROM walk ORDER BY start_code, depth DESC
    )
    SELECT l.start_code, l.cur, l.depth,
           (t.status = 'active' AND l.depth <= 5) IS TRUE
    FROM last_step l
    LEFT JOIN taxonomy_mock.taxonomy_codes t ON t.entity_type = p_entity_type AND t.code = l.cur
$$;

-- ------------------------------------------------------------ 1. preflight
-- severity 'block' stops run_cleanup before any change; 'warn' is reported only.
CREATE FUNCTION taxonomy_pipeline_mock.preflight(p_entity_type varchar)
RETURNS TABLE (severity text, check_name text, code varchar, detail text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = taxonomy_pipeline_mock, pg_temp AS $$
BEGIN
    IF taxonomy_pipeline_mock.career_code_table(p_entity_type) IS NULL THEN
        RAISE EXCEPTION 'unknown entity type %', p_entity_type USING ERRCODE = '22023';
    END IF;

    -- T137 consistency report (merged -> non-active survivor, alias on merged code, ...)
    RETURN QUERY
        SELECT 'block', 'taxonomy_violation', v.code, v.problem
        FROM taxonomy_mock.validate_taxonomy() v WHERE v.entity_type = p_entity_type;

    -- replacement chains that loop or go deeper than 5 (T137 triggers can be bypassed by an owner)
    RETURN QUERY
        SELECT 'block', 'chain_loop_or_too_deep', m.from_code,
               format('chain from %s does not reach an active code within 5 steps', m.from_code)
        FROM taxonomy_pipeline_mock.canonical_map(p_entity_type) m WHERE NOT m.reaches_active;

    -- FK side: a merge target must exist and be active in career, otherwise rows cannot move there
    RETURN QUERY
        SELECT 'block', 'target_missing_in_career', m.to_code,
               format('%s -> %s: target code not found in %s', m.from_code, m.to_code,
                      taxonomy_pipeline_mock.career_code_table(p_entity_type))
        FROM taxonomy_pipeline_mock.canonical_map(p_entity_type) m
        WHERE m.reaches_active AND NOT EXISTS (
            SELECT 1 FROM career.skills s WHERE p_entity_type = 'skill' AND s.code = m.to_code
            UNION ALL
            SELECT 1 FROM career.job_roles r WHERE p_entity_type = 'job_role' AND r.code = m.to_code);

    RETURN QUERY
        SELECT 'block', 'target_inactive_in_career', m.to_code,
               format('%s -> %s: target code is inactive in career', m.from_code, m.to_code)
        FROM taxonomy_pipeline_mock.canonical_map(p_entity_type) m
        WHERE m.reaches_active AND EXISTS (
            SELECT 1 FROM career.skills s WHERE p_entity_type = 'skill' AND s.code = m.to_code AND NOT s.is_active
            UNION ALL
            SELECT 1 FROM career.job_roles r WHERE p_entity_type = 'job_role' AND r.code = m.to_code AND NOT r.is_active);

    -- informational: active career codes the taxonomy does not know yet (curator follow-up)
    RETURN QUERY
        SELECT 'warn', 'career_code_not_in_taxonomy', x.code, 'add it to the taxonomy baseline'
        FROM (SELECT s.code FROM career.skills s WHERE p_entity_type = 'skill' AND s.is_active
              UNION ALL
              SELECT r.code FROM career.job_roles r WHERE p_entity_type = 'job_role' AND r.is_active) x
        WHERE NOT EXISTS (SELECT 1 FROM taxonomy_mock.taxonomy_codes t
                          WHERE t.entity_type = p_entity_type AND t.code = x.code);
END $$;

-- ------------------------------------------------------------ 2-4. cleanup steps (internal)
-- Each step logs the original row first, then changes it. Returns the number of rows changed.

CREATE FUNCTION taxonomy_pipeline_mock.sync_status(p_run bigint, p_entity_type varchar) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE
    n integer;
BEGIN
    IF p_entity_type = 'skill' THEN
        WITH retired AS (
            SELECT s.* FROM career.skills s
            JOIN taxonomy_mock.taxonomy_codes t ON t.entity_type = 'skill' AND t.code = s.code
            WHERE t.status <> 'active' AND s.is_active
        ), logged AS (
            INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, original_row)
            SELECT p_run, 'skill', 'career.skills', 'status_synced', r.code, to_jsonb(r) FROM retired r
        )
        UPDATE career.skills s SET is_active = false, updated_at = now()
        FROM retired r WHERE s.skill_id = r.skill_id;
    ELSE
        WITH retired AS (
            SELECT j.* FROM career.job_roles j
            JOIN taxonomy_mock.taxonomy_codes t ON t.entity_type = 'job_role' AND t.code = j.code
            WHERE t.status <> 'active' AND j.is_active
        ), logged AS (
            INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, original_row)
            SELECT p_run, 'job_role', 'career.job_roles', 'status_synced', r.code, to_jsonb(r) FROM retired r
        )
        UPDATE career.job_roles j SET is_active = false, updated_at = now()
        FROM retired r WHERE j.job_role_id = r.job_role_id;
    END IF;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END $$;

-- skill references: user_skills, job_posting_skills, job_role_skills, user_project_skills
CREATE FUNCTION taxonomy_pipeline_mock.remap_skills(p_run bigint, p_from uuid, p_to uuid,
                                                    p_from_code varchar, p_to_code varchar)
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    k record;
    c jsonb := '{}'::jsonb;
    n_remap integer;
    n_conf integer;
BEGIN
    -- user_skills: duplicate -> keep the higher proficiency
    n_conf := 0;
    FOR r IN SELECT * FROM career.user_skills WHERE skill_id = p_from ORDER BY user_id FOR UPDATE LOOP
        SELECT * INTO k FROM career.user_skills WHERE user_id = r.user_id AND skill_id = p_to FOR UPDATE;
        IF FOUND THEN
            INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row, kept_row)
            VALUES (p_run, 'skill', 'career.user_skills', 'conflict_merged', p_from_code, p_to_code, to_jsonb(r), to_jsonb(k));
            DELETE FROM career.user_skills WHERE user_id = r.user_id AND skill_id = p_from;
            UPDATE career.user_skills SET proficiency = greatest(k.proficiency, r.proficiency), updated_at = now()
            WHERE user_id = r.user_id AND skill_id = p_to
              AND proficiency IS DISTINCT FROM greatest(k.proficiency, r.proficiency);
            n_conf := n_conf + 1;
        END IF;
    END LOOP;
    WITH moved AS (
        INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row)
        SELECT p_run, 'skill', 'career.user_skills', 'remapped', p_from_code, p_to_code, to_jsonb(u)
        FROM career.user_skills u WHERE u.skill_id = p_from
    )
    UPDATE career.user_skills SET skill_id = p_to, updated_at = now() WHERE skill_id = p_from;
    GET DIAGNOSTICS n_remap = ROW_COUNT;
    c := c || jsonb_build_object('career.user_skills', jsonb_build_object('remapped', n_remap, 'conflict_merged', n_conf));

    -- job_posting_skills: duplicate -> required if either was, higher required_level
    n_conf := 0;
    FOR r IN SELECT * FROM career.job_posting_skills WHERE skill_id = p_from ORDER BY job_posting_id FOR UPDATE LOOP
        SELECT * INTO k FROM career.job_posting_skills WHERE job_posting_id = r.job_posting_id AND skill_id = p_to FOR UPDATE;
        IF FOUND THEN
            INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row, kept_row)
            VALUES (p_run, 'skill', 'career.job_posting_skills', 'conflict_merged', p_from_code, p_to_code, to_jsonb(r), to_jsonb(k));
            DELETE FROM career.job_posting_skills WHERE job_posting_id = r.job_posting_id AND skill_id = p_from;
            UPDATE career.job_posting_skills
            SET is_required = k.is_required OR r.is_required,
                required_level = greatest(k.required_level, r.required_level)
            WHERE job_posting_id = r.job_posting_id AND skill_id = p_to;
            n_conf := n_conf + 1;
        END IF;
    END LOOP;
    WITH moved AS (
        INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row)
        SELECT p_run, 'skill', 'career.job_posting_skills', 'remapped', p_from_code, p_to_code, to_jsonb(j)
        FROM career.job_posting_skills j WHERE j.skill_id = p_from
    )
    UPDATE career.job_posting_skills SET skill_id = p_to WHERE skill_id = p_from;
    GET DIAGNOSTICS n_remap = ROW_COUNT;
    c := c || jsonb_build_object('career.job_posting_skills', jsonb_build_object('remapped', n_remap, 'conflict_merged', n_conf));

    -- job_role_skills: duplicate -> higher required_level
    n_conf := 0;
    FOR r IN SELECT * FROM career.job_role_skills WHERE skill_id = p_from ORDER BY job_role_id FOR UPDATE LOOP
        SELECT * INTO k FROM career.job_role_skills WHERE job_role_id = r.job_role_id AND skill_id = p_to FOR UPDATE;
        IF FOUND THEN
            INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row, kept_row)
            VALUES (p_run, 'skill', 'career.job_role_skills', 'conflict_merged', p_from_code, p_to_code, to_jsonb(r), to_jsonb(k));
            DELETE FROM career.job_role_skills WHERE job_role_id = r.job_role_id AND skill_id = p_from;
            UPDATE career.job_role_skills SET required_level = greatest(k.required_level, r.required_level)
            WHERE job_role_id = r.job_role_id AND skill_id = p_to;
            n_conf := n_conf + 1;
        END IF;
    END LOOP;
    WITH moved AS (
        INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row)
        SELECT p_run, 'skill', 'career.job_role_skills', 'remapped', p_from_code, p_to_code, to_jsonb(j)
        FROM career.job_role_skills j WHERE j.skill_id = p_from
    )
    UPDATE career.job_role_skills SET skill_id = p_to WHERE skill_id = p_from;
    GET DIAGNOSTICS n_remap = ROW_COUNT;
    c := c || jsonb_build_object('career.job_role_skills', jsonb_build_object('remapped', n_remap, 'conflict_merged', n_conf));

    -- user_project_skills: duplicate -> nothing to compare, just drop the old row
    n_conf := 0;
    FOR r IN SELECT * FROM career.user_project_skills WHERE skill_id = p_from ORDER BY project_id FOR UPDATE LOOP
        SELECT * INTO k FROM career.user_project_skills WHERE project_id = r.project_id AND skill_id = p_to FOR UPDATE;
        IF FOUND THEN
            INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row, kept_row)
            VALUES (p_run, 'skill', 'career.user_project_skills', 'conflict_merged', p_from_code, p_to_code, to_jsonb(r), to_jsonb(k));
            DELETE FROM career.user_project_skills WHERE project_id = r.project_id AND skill_id = p_from;
            n_conf := n_conf + 1;
        END IF;
    END LOOP;
    WITH moved AS (
        INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row)
        SELECT p_run, 'skill', 'career.user_project_skills', 'remapped', p_from_code, p_to_code, to_jsonb(j)
        FROM career.user_project_skills j WHERE j.skill_id = p_from
    )
    UPDATE career.user_project_skills SET skill_id = p_to WHERE skill_id = p_from;
    GET DIAGNOSTICS n_remap = ROW_COUNT;
    c := c || jsonb_build_object('career.user_project_skills', jsonb_build_object('remapped', n_remap, 'conflict_merged', n_conf));

    RETURN c;
END $$;

-- job role references: user_target_roles, job_postings
CREATE FUNCTION taxonomy_pipeline_mock.remap_job_roles(p_run bigint, p_from uuid, p_to uuid,
                                                       p_from_code varchar, p_to_code varchar)
RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    r record;
    k record;
    c jsonb := '{}'::jsonb;
    n_remap integer;
    n_conf integer := 0;
BEGIN
    -- user_target_roles: duplicate -> keep the higher priority (1 = first choice, so the smaller number).
    -- The old row is deleted first so UNIQUE (user_id, priority) cannot collide.
    FOR r IN SELECT * FROM career.user_target_roles WHERE job_role_id = p_from ORDER BY user_id FOR UPDATE LOOP
        SELECT * INTO k FROM career.user_target_roles WHERE user_id = r.user_id AND job_role_id = p_to FOR UPDATE;
        IF FOUND THEN
            INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row, kept_row)
            VALUES (p_run, 'job_role', 'career.user_target_roles', 'conflict_merged', p_from_code, p_to_code, to_jsonb(r), to_jsonb(k));
            DELETE FROM career.user_target_roles WHERE user_id = r.user_id AND job_role_id = p_from;
            UPDATE career.user_target_roles SET priority = least(k.priority, r.priority), updated_at = now()
            WHERE user_id = r.user_id AND job_role_id = p_to AND priority <> least(k.priority, r.priority);
            n_conf := n_conf + 1;
        END IF;
    END LOOP;
    WITH moved AS (
        INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row)
        SELECT p_run, 'job_role', 'career.user_target_roles', 'remapped', p_from_code, p_to_code, to_jsonb(u)
        FROM career.user_target_roles u WHERE u.job_role_id = p_from
    )
    UPDATE career.user_target_roles SET job_role_id = p_to, updated_at = now() WHERE job_role_id = p_from;
    GET DIAGNOSTICS n_remap = ROW_COUNT;
    c := c || jsonb_build_object('career.user_target_roles', jsonb_build_object('remapped', n_remap, 'conflict_merged', n_conf));

    -- job_postings: one role per posting, no duplicate possible
    WITH moved AS (
        INSERT INTO taxonomy_pipeline_mock.remap_log (run_id, entity_type, table_name, action, from_code, to_code, original_row)
        SELECT p_run, 'job_role', 'career.job_postings', 'remapped', p_from_code, p_to_code, to_jsonb(j)
        FROM career.job_postings j WHERE j.job_role_id = p_from
    )
    UPDATE career.job_postings SET job_role_id = p_to, updated_at = now() WHERE job_role_id = p_from;
    GET DIAGNOSTICS n_remap = ROW_COUNT;
    c := c || jsonb_build_object('career.job_postings', jsonb_build_object('remapped', n_remap, 'conflict_merged', 0));

    RETURN c;
END $$;

-- ------------------------------------------------------------ run_cleanup (entry point)
-- mode 'dry_run' does all the work inside a savepoint and rolls it back, so the counts are exact
-- but no career row and no remap_log row is kept. Returns the run row (status ok | blocked).
CREATE FUNCTION taxonomy_pipeline_mock.run_cleanup(p_entity_type varchar, p_mode varchar DEFAULT 'dry_run')
RETURNS taxonomy_pipeline_mock.pipeline_runs
LANGUAGE plpgsql SECURITY DEFINER SET search_path = taxonomy_pipeline_mock, pg_temp AS $$
DECLARE
    v_run taxonomy_pipeline_mock.pipeline_runs;
    v_blocks jsonb;
    v_warns integer;
    v_tables jsonb := '{}'::jsonb;
    v_status integer := 0;
    v_pairs integer := 0;
    v_part jsonb;
    m record;
    f uuid;
    t uuid;
BEGIN
    IF p_mode NOT IN ('dry_run', 'apply') THEN
        RAISE EXCEPTION 'mode must be dry_run or apply, got %', p_mode USING ERRCODE = '22023';
    END IF;
    IF taxonomy_pipeline_mock.career_code_table(p_entity_type) IS NULL THEN
        RAISE EXCEPTION 'unknown entity type %', p_entity_type USING ERRCODE = '22023';
    END IF;

    -- one cleanup per entity type at a time
    PERFORM pg_advisory_xact_lock(hashtext('t138_code_cleanup'), hashtext(p_entity_type));

    INSERT INTO taxonomy_pipeline_mock.pipeline_runs (entity_type, mode, taxonomy_version)
    VALUES (p_entity_type, p_mode,
            (SELECT max(version) FROM taxonomy_mock.taxonomy_versions))
    RETURNING * INTO v_run;

    SELECT coalesce(jsonb_agg(jsonb_build_object('check', check_name, 'code', code, 'detail', detail)), '[]'::jsonb)
      INTO v_blocks
      FROM taxonomy_pipeline_mock.preflight(p_entity_type) WHERE severity = 'block';
    SELECT count(*) INTO v_warns FROM taxonomy_pipeline_mock.preflight(p_entity_type) WHERE severity = 'warn';

    IF jsonb_array_length(v_blocks) > 0 THEN
        UPDATE taxonomy_pipeline_mock.pipeline_runs
        SET status = 'blocked', finished_at = clock_timestamp(),
            summary = jsonb_build_object('blocked_by', v_blocks, 'warnings', v_warns)
        WHERE run_id = v_run.run_id RETURNING * INTO v_run;
        RETURN v_run;
    END IF;

    BEGIN
        v_status := taxonomy_pipeline_mock.sync_status(v_run.run_id, p_entity_type);

        FOR m IN SELECT * FROM taxonomy_pipeline_mock.canonical_map(p_entity_type) ORDER BY from_code LOOP
            IF p_entity_type = 'skill' THEN
                SELECT skill_id INTO f FROM career.skills WHERE code = m.from_code;
                SELECT skill_id INTO t FROM career.skills WHERE code = m.to_code;
            ELSE
                SELECT job_role_id INTO f FROM career.job_roles WHERE code = m.from_code;
                SELECT job_role_id INTO t FROM career.job_roles WHERE code = m.to_code;
            END IF;
            CONTINUE WHEN f IS NULL;  -- merged code never reached career: nothing points at it
            v_pairs := v_pairs + 1;
            IF p_entity_type = 'skill' THEN
                v_part := taxonomy_pipeline_mock.remap_skills(v_run.run_id, f, t, m.from_code, m.to_code);
            ELSE
                v_part := taxonomy_pipeline_mock.remap_job_roles(v_run.run_id, f, t, m.from_code, m.to_code);
            END IF;
            -- add this pair's counts to the per-table totals
            SELECT coalesce(jsonb_object_agg(key, jsonb_build_object(
                       'remapped', coalesce((v_tables -> key ->> 'remapped')::int, 0) + (value ->> 'remapped')::int,
                       'conflict_merged', coalesce((v_tables -> key ->> 'conflict_merged')::int, 0) + (value ->> 'conflict_merged')::int)), '{}'::jsonb)
              INTO v_part FROM jsonb_each(v_part);
            v_tables := v_tables || v_part;
        END LOOP;

        IF p_mode = 'dry_run' THEN
            RAISE EXCEPTION 'T138_DRY_RUN_ROLLBACK' USING ERRCODE = 'P0001';
        END IF;
    EXCEPTION
        WHEN raise_exception THEN
            IF SQLERRM <> 'T138_DRY_RUN_ROLLBACK' THEN
                RAISE;
            END IF;
            -- dry run: everything inside the block (career changes and remap_log rows) is rolled back
    END;

    UPDATE taxonomy_pipeline_mock.pipeline_runs
    SET status = 'ok', finished_at = clock_timestamp(),
        summary = jsonb_build_object('status_synced', v_status, 'merged_codes_found', v_pairs,
                                     'tables', v_tables, 'warnings', v_warns)
    WHERE run_id = v_run.run_id RETURNING * INTO v_run;
    RETURN v_run;
END $$;

-- ------------------------------------------------------------ stage_terms (raw term -> code)
-- Maps raw terms with T137 resolve_term. exact/code hits return the live code; ambiguous and
-- unknown terms go to term_review_queue (never auto-picked, policy §3). Re-staging the same term
-- only bumps seen_count / last_seen_at.
CREATE FUNCTION taxonomy_pipeline_mock.stage_terms(p_entity_type varchar, p_source varchar, p_terms text[])
RETURNS TABLE (term text, canonical_code varchar, match_type text, queued boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = taxonomy_pipeline_mock, pg_temp AS $$
DECLARE
    v_term text;
    v_hits record;
BEGIN
    IF taxonomy_pipeline_mock.career_code_table(p_entity_type) IS NULL THEN
        RAISE EXCEPTION 'unknown entity type %', p_entity_type USING ERRCODE = '22023';
    END IF;
    IF p_source IS NULL OR length(btrim(p_source)) = 0 THEN
        RAISE EXCEPTION 'source is required' USING ERRCODE = '22023';
    END IF;

    FOREACH v_term IN ARRAY p_terms LOOP
        CONTINUE WHEN v_term IS NULL OR taxonomy_mock.normalize_term(v_term) = '';
        SELECT min(r.match_type) AS match_type,
               array_agg(DISTINCT r.canonical_code ORDER BY r.canonical_code)
                   FILTER (WHERE r.canonical_code IS NOT NULL) AS codes
          INTO v_hits
          FROM taxonomy_mock.resolve_term(p_entity_type, v_term) r;

        -- one live code -> mapped (an ambiguous alias whose meanings were merged into one also lands here)
        IF v_hits.match_type <> 'not_found' AND cardinality(v_hits.codes) = 1 THEN
            term := v_term; canonical_code := v_hits.codes[1]; match_type := v_hits.match_type; queued := false;
        ELSE
            INSERT INTO taxonomy_pipeline_mock.term_review_queue
                (entity_type, source, term_norm, term_display, reason, candidates)
            VALUES (p_entity_type, p_source, taxonomy_mock.normalize_term(v_term), v_term,
                    CASE WHEN v_hits.match_type = 'not_found' THEN 'not_found' ELSE 'ambiguous' END,
                    CASE WHEN v_hits.match_type = 'not_found' THEN '{}' ELSE coalesce(v_hits.codes, '{}') END)
            ON CONFLICT (entity_type, source, term_norm) DO UPDATE
                SET seen_count = term_review_queue.seen_count + 1, last_seen_at = clock_timestamp();
            term := v_term; canonical_code := NULL;
            match_type := CASE WHEN v_hits.match_type = 'not_found' THEN 'not_found' ELSE 'ambiguous' END;
            queued := true;
        END IF;
        RETURN NEXT;
    END LOOP;
END $$;

-- ------------------------------------------------------------ privileges
REVOKE ALL ON SCHEMA taxonomy_pipeline_mock FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA taxonomy_pipeline_mock FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA taxonomy_pipeline_mock FROM PUBLIC;
GRANT USAGE ON SCHEMA taxonomy_pipeline_mock TO t138_operator;
GRANT SELECT ON taxonomy_pipeline_mock.pipeline_runs, taxonomy_pipeline_mock.remap_log,
               taxonomy_pipeline_mock.term_review_queue TO t138_operator;
GRANT EXECUTE ON FUNCTION
    taxonomy_pipeline_mock.preflight(varchar),
    taxonomy_pipeline_mock.run_cleanup(varchar, varchar),
    taxonomy_pipeline_mock.stage_terms(varchar, varchar, text[])
TO t138_operator;

COMMIT;
