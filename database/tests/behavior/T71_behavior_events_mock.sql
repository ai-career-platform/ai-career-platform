-- T71 behavior event & consent contract: executable MOCK for disposable databases only.
-- STATUS: DRAFT / NOT A MIGRATION / NOT APPROVED. NEVER run on Staging.
-- Contract: docs/data/BEHAVIOR_EVENT_CONTRACT.md
--
-- Isolated schema `behavior_mock` so it never collides with `career` or T08/T09 migrations.
-- Roles (created for the disposable test cluster only)
--   t71_ingest  : collection API (T72)       -> EXECUTE record_behavior_event() only
--   t71_consent : consent API (T31)          -> EXECUTE record_consent() only
--   t71_analyst : insights API/dashboard     -> SELECT insights_daily only (k-anonymous)
--   table owner : migrator / privacy operator -> erase_subject(), purge_expired()
SET client_encoding = 'UTF8';
BEGIN;

CREATE SCHEMA behavior_mock;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't71_ingest')  THEN CREATE ROLE t71_ingest NOLOGIN;  END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't71_consent') THEN CREATE ROLE t71_consent NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't71_analyst') THEN CREATE ROLE t71_analyst NOLOGIN; END IF;
END $$;

-- ------------------------------------------------------------ consent policies
CREATE TABLE behavior_mock.consent_policies (
    policy_code     varchar(80) PRIMARY KEY,
    current_version varchar(40) NOT NULL,
    purpose         text NOT NULL,
    CONSTRAINT policy_code_format CHECK (policy_code ~ '^[a-z][a-z0-9_]*$')
);

INSERT INTO behavior_mock.consent_policies VALUES
    ('behavior_analytics', '2026-11-v1', '서비스 이용 통계·화면 개선 (집계로만 사용)'),
    ('personalization',    '2026-11-v1', '행동 기반 추천·개인화');

-- consent history is append-only; the latest row per (user, policy) is the current state
CREATE TABLE behavior_mock.user_consents (
    consent_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL,
    policy_code    varchar(80) NOT NULL REFERENCES behavior_mock.consent_policies (policy_code),
    policy_version varchar(40) NOT NULL,
    granted        boolean NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    source         varchar(20) NOT NULL,
    CONSTRAINT consent_source_check CHECK (source IN ('signup', 'settings', 'banner', 'account_deletion', 'admin_correction'))
);
CREATE INDEX ix_user_consents_current ON behavior_mock.user_consents (user_id, policy_code, recorded_at DESC);

-- ------------------------------------------------------------ event catalog (allow-list)
CREATE TABLE behavior_mock.behavior_event_catalog (
    event_code           varchar(80) PRIMARY KEY,
    required_policy_code varchar(80) NOT NULL REFERENCES behavior_mock.consent_policies (policy_code),
    allowed_keys         text[] NOT NULL,
    retain_for           interval NOT NULL,
    description          text NOT NULL,
    CONSTRAINT event_code_format CHECK (event_code ~ '^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$'),
    CONSTRAINT event_allowed_keys_limit CHECK (cardinality(allowed_keys) <= 10),
    CONSTRAINT event_retention_positive CHECK (retain_for >= interval '0')
);

INSERT INTO behavior_mock.behavior_event_catalog VALUES
    ('page.view',             'behavior_analytics', ARRAY['page_id','referrer_type'],              interval '180 days', '화면 조회'),
    ('search.submit',         'behavior_analytics', ARRAY['search_type','filter_count','result_count'], interval '180 days', '검색 실행 (검색어 원문 금지)'),
    ('posting.view',          'behavior_analytics', ARRAY['job_posting_id','list_position'],       interval '180 days', '채용공고 상세 조회'),
    ('role.view',             'behavior_analytics', ARRAY['job_role_id'],                          interval '180 days', '직무 상세 조회'),
    ('skill_gap.view',        'behavior_analytics', ARRAY['job_role_id','gap_count'],              interval '180 days', 'Skill Gap 결과 조회'),
    ('posting.bookmark',      'personalization',    ARRAY['job_posting_id'],                       interval '365 days', '공고 북마크 신호'),
    ('recommendation.click',  'personalization',    ARRAY['recommendation_id','rank'],             interval '365 days', '추천 항목 클릭'),
    ('recommendation.dismiss','personalization',    ARRAY['recommendation_id','reason_code'],      interval '365 days', '추천 항목 숨김');

-- ------------------------------------------------------------ pseudonymous subject key
-- secret lives in an owner-only table in this mock; real system: secret manager + app-side HMAC
CREATE TABLE behavior_mock.pseudonym_secret (
    key_id  smallint PRIMARY KEY,
    secret  bytea NOT NULL
);
INSERT INTO behavior_mock.pseudonym_secret VALUES (1, gen_random_uuid()::text::bytea || gen_random_uuid()::text::bytea);

CREATE FUNCTION behavior_mock.subject_key(p_user_id uuid) RETURNS char(64)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = behavior_mock, pg_temp AS $$
    SELECT encode(sha256(s.secret || uuid_send(p_user_id)), 'hex')
    FROM behavior_mock.pseudonym_secret s WHERE s.key_id = 1
$$;

-- ------------------------------------------------------------ behavior_events
CREATE TABLE behavior_mock.behavior_events (
    event_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_code      varchar(80) NOT NULL REFERENCES behavior_mock.behavior_event_catalog (event_code),
    subject_key     char(64) NOT NULL,          -- keyed hash of user_id, never the raw id
    occurred_at     timestamptz NOT NULL,
    received_at     timestamptz NOT NULL,
    properties      jsonb NOT NULL DEFAULT '{}'::jsonb,
    policy_code     varchar(80) NOT NULL,
    policy_version  varchar(40) NOT NULL,
    retain_until    timestamptz NOT NULL,
    CONSTRAINT behavior_subject_key_format CHECK (subject_key ~ '^[0-9a-f]{64}$'),
    CONSTRAINT behavior_properties_object CHECK (jsonb_typeof(properties) = 'object'),
    CONSTRAINT behavior_properties_size CHECK (octet_length(properties::text) <= 1024)
);
CREATE INDEX ix_behavior_events_subject ON behavior_mock.behavior_events (subject_key);
CREATE INDEX ix_behavior_events_code_time ON behavior_mock.behavior_events (event_code, occurred_at);

-- ------------------------------------------------------------ current consent
CREATE FUNCTION behavior_mock.current_consent(p_user_id uuid, p_policy varchar)
RETURNS TABLE (granted boolean, policy_version varchar)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = behavior_mock, pg_temp AS $$
    SELECT c.granted, c.policy_version
    FROM behavior_mock.user_consents c
    WHERE c.user_id = p_user_id AND c.policy_code = p_policy
    ORDER BY c.recorded_at DESC, c.consent_id DESC
    LIMIT 1
$$;

-- ------------------------------------------------------------ write path: record_behavior_event
-- returns 'stored' or 'blocked_no_consent'; raises on contract violations (invalid input)
CREATE FUNCTION behavior_mock.record_behavior_event(
    p_user_id uuid, p_event_code varchar, p_occurred_at timestamptz, p_properties jsonb DEFAULT '{}'::jsonb
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = behavior_mock, pg_temp AS $$
DECLARE
    cat   behavior_mock.behavior_event_catalog%ROWTYPE;
    cons  record;
    k     text;
    v     jsonb;
BEGIN
    IF p_user_id IS NULL THEN
        RAISE EXCEPTION 'anonymous tracking is not allowed' USING ERRCODE = '22023';
    END IF;
    SELECT * INTO cat FROM behavior_mock.behavior_event_catalog WHERE event_code = p_event_code;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown event_code %', p_event_code USING ERRCODE = '22023';
    END IF;
    IF p_occurred_at > clock_timestamp() + interval '5 minutes'
       OR p_occurred_at < clock_timestamp() - interval '7 days' THEN
        RAISE EXCEPTION 'occurred_at out of accepted window' USING ERRCODE = '22023';
    END IF;
    IF p_properties IS NULL OR jsonb_typeof(p_properties) <> 'object' THEN
        RAISE EXCEPTION 'properties must be an object' USING ERRCODE = '22023';
    END IF;
    FOR k, v IN SELECT key, value FROM jsonb_each(p_properties) LOOP
        IF NOT (k = ANY (cat.allowed_keys)) THEN
            RAISE EXCEPTION 'property % is not allowed for %', k, p_event_code USING ERRCODE = '22023';
        END IF;
        IF jsonb_typeof(v) = 'number' OR jsonb_typeof(v) = 'boolean' THEN
            CONTINUE;
        ELSIF jsonb_typeof(v) = 'string' AND (v #>> '{}') ~ '^[A-Za-z0-9_.:-]{1,64}$' THEN
            CONTINUE;   -- ids and codes only: no spaces, so no free text / sentences
        ELSE
            RAISE EXCEPTION 'property % must be a number, boolean, id or code', k USING ERRCODE = '22023';
        END IF;
    END LOOP;

    SELECT * INTO cons FROM behavior_mock.current_consent(p_user_id, cat.required_policy_code);
    IF NOT FOUND OR cons.granted IS NOT TRUE THEN
        RETURN 'blocked_no_consent';
    END IF;

    INSERT INTO behavior_mock.behavior_events
        (event_code, subject_key, occurred_at, received_at, properties, policy_code, policy_version, retain_until)
    VALUES
        (p_event_code, behavior_mock.subject_key(p_user_id), p_occurred_at, clock_timestamp(), p_properties,
         cat.required_policy_code, cons.policy_version, clock_timestamp() + cat.retain_for);
    RETURN 'stored';
END $$;

-- ------------------------------------------------------------ consent changes: withdrawal deletes data
CREATE FUNCTION behavior_mock.record_consent(
    p_user_id uuid, p_policy_code varchar, p_granted boolean, p_source varchar DEFAULT 'settings'
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = behavior_mock, pg_temp AS $$
DECLARE
    v_version varchar;
    removed   bigint := 0;
BEGIN
    SELECT current_version INTO v_version FROM behavior_mock.consent_policies WHERE policy_code = p_policy_code;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown policy_code %', p_policy_code USING ERRCODE = '22023';
    END IF;
    INSERT INTO behavior_mock.user_consents (user_id, policy_code, policy_version, granted, source)
    VALUES (p_user_id, p_policy_code, v_version, p_granted, p_source);
    IF NOT p_granted THEN
        DELETE FROM behavior_mock.behavior_events
        WHERE subject_key = behavior_mock.subject_key(p_user_id) AND policy_code = p_policy_code;
        GET DIAGNOSTICS removed = ROW_COUNT;
    END IF;
    RETURN removed;   -- number of events erased because of the withdrawal
END $$;

-- account deletion: withdraw every policy and erase every event of the subject
CREATE FUNCTION behavior_mock.erase_subject(p_user_id uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = behavior_mock, pg_temp AS $$
DECLARE
    removed bigint;
BEGIN
    INSERT INTO behavior_mock.user_consents (user_id, policy_code, policy_version, granted, source)
    SELECT p_user_id, policy_code, current_version, false, 'account_deletion' FROM behavior_mock.consent_policies;
    DELETE FROM behavior_mock.behavior_events WHERE subject_key = behavior_mock.subject_key(p_user_id);
    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END $$;

CREATE FUNCTION behavior_mock.purge_expired() RETURNS bigint
LANGUAGE plpgsql AS $$
DECLARE
    removed bigint;
BEGIN
    DELETE FROM behavior_mock.behavior_events WHERE retain_until <= clock_timestamp();
    GET DIAGNOSTICS removed = ROW_COUNT;
    RETURN removed;
END $$;

-- ------------------------------------------------------------ read path: k-anonymous aggregates only
CREATE VIEW behavior_mock.insights_daily WITH (security_barrier = true) AS
SELECT (e.occurred_at AT TIME ZONE 'UTC')::date AS day_utc,
       e.event_code,
       count(*) AS event_count,
       count(DISTINCT e.subject_key) AS subject_count
FROM behavior_mock.behavior_events e
GROUP BY 1, 2
HAVING count(DISTINCT e.subject_key) >= 5;   -- k = 5: smaller groups are suppressed

-- ------------------------------------------------------------ privileges
REVOKE ALL ON SCHEMA behavior_mock FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA behavior_mock FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA behavior_mock FROM PUBLIC;

GRANT USAGE ON SCHEMA behavior_mock TO t71_ingest, t71_consent, t71_analyst;
GRANT EXECUTE ON FUNCTION behavior_mock.record_behavior_event(uuid, varchar, timestamptz, jsonb) TO t71_ingest;
GRANT EXECUTE ON FUNCTION behavior_mock.record_consent(uuid, varchar, boolean, varchar) TO t71_consent;
GRANT SELECT ON behavior_mock.insights_daily TO t71_analyst;
GRANT SELECT ON behavior_mock.behavior_event_catalog, behavior_mock.consent_policies TO t71_ingest, t71_consent, t71_analyst;

COMMIT;
