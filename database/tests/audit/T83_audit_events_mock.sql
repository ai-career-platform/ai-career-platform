-- T83 audit event contract: executable MOCK for disposable databases only.
-- STATUS: DRAFT / NOT A MIGRATION / NOT APPROVED. NEVER run on Staging.
-- Contract: docs/security/AUDIT_EVENT_CONTRACT.md
--
-- Uses its own schema `audit_mock` so it never collides with the `career` schema
-- or with migrations owned by T08/T09. When the contract is approved, the real
-- table goes into an approved migration (T08 process), not this file.
--
-- Roles (cluster-wide; created here for the disposable test cluster only)
--   t83_audit_writer : application write path  -> INSERT only
--   t83_audit_reader : admin audit API (T84)    -> SELECT only
--   table owner      : migrator; may run purge_expired()
SET client_encoding = 'UTF8';
BEGIN;

CREATE SCHEMA audit_mock;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't83_audit_writer') THEN
        CREATE ROLE t83_audit_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't83_audit_reader') THEN
        CREATE ROLE t83_audit_reader NOLOGIN;
    END IF;
END $$;

-- ------------------------------------------------------------ retention policy
CREATE TABLE audit_mock.audit_retention_policies (
    retention_class varchar(32) PRIMARY KEY,
    retain_for interval NOT NULL,
    note text NOT NULL,
    CONSTRAINT retention_positive CHECK (retain_for >= interval '0')
);

INSERT INTO audit_mock.audit_retention_policies (retention_class, retain_for, note) VALUES
    ('security', interval '2 years', '인증·권한·관리자 조치·개인정보 접근 (접속기록 보관 기준 후보, 법무 확인 필요)'),
    ('standard', interval '1 year',  '일반 데이터 변경 (프로필·북마크 등)'),
    ('ai_agent', interval '1 year',  'AI/Agent 실행·승인·도구 호출 요약');

-- ------------------------------------------------------------ forbidden content
-- true when any object key at any depth looks like a secret / credential / raw content
CREATE FUNCTION audit_mock.has_forbidden_key(j jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE STRICT AS $$
    WITH RECURSIVE node(v) AS (
        SELECT j
        UNION ALL
        SELECT child.value
        FROM node
        CROSS JOIN LATERAL (
            SELECT value FROM jsonb_each(CASE WHEN jsonb_typeof(node.v) = 'object' THEN node.v ELSE '{}'::jsonb END)
            UNION ALL
            SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(node.v) = 'array' THEN node.v ELSE '[]'::jsonb END)
        ) AS child
    )
    SELECT EXISTS (
        SELECT 1
        FROM node
        CROSS JOIN LATERAL jsonb_object_keys(CASE WHEN jsonb_typeof(node.v) = 'object' THEN node.v ELSE '{}'::jsonb END) AS k
        WHERE lower(k) ~ '(passw|secret|token|api_?key|authorization|cookie|session|credential|private_?key|otp)'
           OR lower(k) IN ('email', 'phone', 'resume_text', 'document_text', 'prompt', 'completion', 'ssn', 'rrn')
    )
$$;

-- ------------------------------------------------------------ audit_events
CREATE TABLE audit_mock.audit_events (
    audit_seq        bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    audit_event_id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at      timestamptz NOT NULL,                 -- when the action happened (app clock)
    recorded_at      timestamptz NOT NULL DEFAULT now(),   -- forced by trigger (DB clock)
    actor_type       varchar(16) NOT NULL,
    actor_user_id    uuid,                                 -- no FK on purpose, see contract §4
    action_code      varchar(100) NOT NULL,
    resource_type    varchar(80) NOT NULL,
    resource_id      uuid,
    result           varchar(16) NOT NULL,
    reason_code      varchar(80),
    correlation_id   varchar(64) NOT NULL,                 -- = API request_id
    client_ip_hash   char(64),                             -- keyed hash, never raw IP
    changed_fields   text[],                               -- field NAMES only, never values
    metadata         jsonb,
    retention_class  varchar(32) NOT NULL REFERENCES audit_mock.audit_retention_policies (retention_class),
    retain_until     timestamptz NOT NULL DEFAULT 'infinity', -- forced by trigger
    row_hash         char(64) NOT NULL DEFAULT '',          -- forced by trigger

    CONSTRAINT audit_actor_type_check CHECK (actor_type IN ('user', 'admin', 'system', 'ai_agent', 'service')),
    CONSTRAINT audit_actor_user_required CHECK (actor_type NOT IN ('user', 'admin') OR actor_user_id IS NOT NULL),
    CONSTRAINT audit_action_code_format CHECK (action_code ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$'),
    CONSTRAINT audit_resource_type_format CHECK (resource_type ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT audit_result_check CHECK (result IN ('success', 'denied', 'failed')),
    CONSTRAINT audit_reason_required CHECK (result = 'success' OR reason_code IS NOT NULL),
    CONSTRAINT audit_reason_code_format CHECK (reason_code IS NULL OR reason_code ~ '^[A-Z][A-Z0-9_]*$'),
    CONSTRAINT audit_correlation_format CHECK (correlation_id ~ '^[A-Za-z0-9._:-]{8,64}$'),
    CONSTRAINT audit_ip_hash_format CHECK (client_ip_hash IS NULL OR client_ip_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT audit_changed_fields_names CHECK (
        changed_fields IS NULL
        OR (cardinality(changed_fields) <= 50
            AND array_to_string(changed_fields, ',') ~ '^[a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*$')
    ),
    CONSTRAINT audit_metadata_object CHECK (metadata IS NULL OR jsonb_typeof(metadata) = 'object'),
    CONSTRAINT audit_metadata_size CHECK (metadata IS NULL OR octet_length(metadata::text) <= 4096),
    CONSTRAINT audit_metadata_no_forbidden_keys CHECK (metadata IS NULL OR NOT audit_mock.has_forbidden_key(metadata)),
    CONSTRAINT audit_metadata_no_email_values CHECK (
        metadata IS NULL OR metadata::text !~ '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}'
    ),
    CONSTRAINT audit_occurred_not_future CHECK (occurred_at <= recorded_at + interval '5 minutes')
);

CREATE INDEX ix_audit_events_occurred_at ON audit_mock.audit_events (occurred_at DESC);
CREATE INDEX ix_audit_events_actor ON audit_mock.audit_events (actor_user_id, occurred_at DESC);
CREATE INDEX ix_audit_events_resource ON audit_mock.audit_events (resource_type, resource_id);
CREATE INDEX ix_audit_events_correlation ON audit_mock.audit_events (correlation_id);

-- canonical content hash (timezone independent). Detects silent edits of stored rows.
CREATE FUNCTION audit_mock.compute_row_hash(e audit_mock.audit_events) RETURNS char(64)
LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(convert_to(concat_ws('|',
        e.audit_event_id::text,
        extract(epoch FROM e.occurred_at)::text,
        extract(epoch FROM e.recorded_at)::text,
        e.actor_type, coalesce(e.actor_user_id::text, ''),
        e.action_code, e.resource_type, coalesce(e.resource_id::text, ''),
        e.result, coalesce(e.reason_code, ''), e.correlation_id,
        coalesce(e.client_ip_hash, ''), coalesce(e.changed_fields::text, ''),
        coalesce(e.metadata::text, ''), e.retention_class,
        extract(epoch FROM e.retain_until)::text
    ), 'UTF8')), 'hex')
$$;

-- BEFORE INSERT: DB owns recorded_at / retain_until / row_hash (client values ignored)
CREATE FUNCTION audit_mock.audit_events_before_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.recorded_at := now();
    SELECT NEW.recorded_at + p.retain_for INTO NEW.retain_until
    FROM audit_mock.audit_retention_policies p
    WHERE p.retention_class = NEW.retention_class;
    IF NEW.retain_until IS NULL THEN
        RAISE EXCEPTION 'unknown retention_class %', NEW.retention_class USING ERRCODE = '23503';
    END IF;
    NEW.row_hash := audit_mock.compute_row_hash(NEW);
    RETURN NEW;
END $$;

-- append-only guard: UPDATE always rejected; DELETE only through purge_expired()
CREATE FUNCTION audit_mock.audit_events_block_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE'
       AND current_setting('audit_mock.purge_in_progress', true) = 'on'
       AND OLD.retain_until <= now() THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit_events is append-only (% rejected)', TG_OP USING ERRCODE = '42501';
END $$;

CREATE FUNCTION audit_mock.audit_events_block_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only (TRUNCATE rejected)' USING ERRCODE = '42501';
END $$;

CREATE TRIGGER trg_audit_events_before_insert
    BEFORE INSERT ON audit_mock.audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_mock.audit_events_before_insert();
CREATE TRIGGER trg_audit_events_block_change
    BEFORE UPDATE OR DELETE ON audit_mock.audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_mock.audit_events_block_change();
CREATE TRIGGER trg_audit_events_block_truncate
    BEFORE TRUNCATE ON audit_mock.audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_mock.audit_events_block_truncate();

-- retention purge: owner/migrator only, deletes expired rows only, returns count
CREATE FUNCTION audit_mock.purge_expired() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    deleted bigint;
BEGIN
    PERFORM set_config('audit_mock.purge_in_progress', 'on', true);
    DELETE FROM audit_mock.audit_events WHERE retain_until <= now();
    GET DIAGNOSTICS deleted = ROW_COUNT;
    PERFORM set_config('audit_mock.purge_in_progress', 'off', true);
    RETURN deleted;
END $$;

-- integrity check used by operators / T84: rows whose stored hash no longer matches
CREATE FUNCTION audit_mock.find_tampered_rows()
RETURNS TABLE (audit_seq bigint, audit_event_id uuid)
LANGUAGE sql STABLE AS $$
    SELECT e.audit_seq, e.audit_event_id
    FROM audit_mock.audit_events e
    WHERE e.row_hash <> audit_mock.compute_row_hash(e)
    ORDER BY e.audit_seq
$$;

-- ------------------------------------------------------------ privileges
REVOKE ALL ON SCHEMA audit_mock FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA audit_mock FROM PUBLIC;
REVOKE ALL ON FUNCTION audit_mock.purge_expired() FROM PUBLIC;

GRANT USAGE ON SCHEMA audit_mock TO t83_audit_writer, t83_audit_reader;
GRANT INSERT ON audit_mock.audit_events TO t83_audit_writer;
GRANT SELECT ON audit_mock.audit_retention_policies TO t83_audit_writer, t83_audit_reader;
GRANT SELECT ON audit_mock.audit_events TO t83_audit_reader;
GRANT EXECUTE ON FUNCTION audit_mock.find_tampered_rows() TO t83_audit_reader;

COMMIT;
