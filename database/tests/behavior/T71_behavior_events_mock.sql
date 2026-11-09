-- T71 behavior event & consent contract: executable MOCK for disposable databases only.
-- STATUS: DRAFT / NOT A MIGRATION / NOT APPROVED. NEVER run on Staging.
-- Contract: docs/data/BEHAVIOR_EVENT_CONTRACT.md
-- Follows T05 data dictionary v0.2: B09 consent_policies, B01 user_consents, F07 behavior_events
-- (user_id FK CASCADE, event_code, event_at, metadata). T71 adds the event catalog (allow-list),
-- the write function with consent check, erase-on-withdrawal and k-anonymous insights.
--
-- Isolated schema `behavior_mock` so it never collides with `career` or T08/T09 migrations.
-- Roles (created for the disposable test cluster only)
--   t71_ingest  : collection API (T72)       -> EXECUTE record_behavior_event() only
--   t71_consent : consent API (T31)          -> EXECUTE record_consent() only
--   t71_analyst : insights API/dashboard     -> SELECT insights_daily only (k-anonymous, no user_id)
--   table owner : migrator / privacy operator -> purge_expired()
SET client_encoding = 'UTF8';
BEGIN;

CREATE SCHEMA behavior_mock;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't71_ingest')  THEN CREATE ROLE t71_ingest NOLOGIN;  END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't71_consent') THEN CREATE ROLE t71_consent NOLOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't71_analyst') THEN CREATE ROLE t71_analyst NOLOGIN; END IF;
END $$;

-- ------------------------------------------------------------ T05 stand-ins
-- A01 users (only the key matters here)
CREATE TABLE behavior_mock.users (
    user_id uuid PRIMARY KEY
);

-- B09 consent_policies (T05 columns)
CREATE TABLE behavior_mock.consent_policies (
    policy_code  varchar(80) NOT NULL,
    version      varchar(40) NOT NULL,
    is_required  boolean NOT NULL,
    content_url  text NOT NULL,
    effective_at timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (policy_code, version)
);

INSERT INTO behavior_mock.consent_policies (policy_code, version, is_required, content_url, effective_at) VALUES
    ('behavior_tracking', '2026-11-v1', false, 'https://example.invalid/policies/behavior-tracking', '2026-11-01'),
    -- T71 proposal: a separate opt-in for behaviour-based personalization (not in T05 yet)
    ('personalization',   '2026-11-v1', false, 'https://example.invalid/policies/personalization',   '2026-11-01');

-- B01 user_consents (T05 columns): append-only history, latest row per (user, policy) is current
CREATE TABLE behavior_mock.user_consents (
    consent_id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES behavior_mock.users (user_id) ON DELETE CASCADE,
    policy_code    varchar(80) NOT NULL,
    policy_version varchar(40) NOT NULL,
    granted        boolean NOT NULL,
    recorded_at    timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (policy_code, policy_version) REFERENCES behavior_mock.consent_policies (policy_code, version) ON DELETE RESTRICT
);
CREATE INDEX ix_user_consents_current ON behavior_mock.user_consents (user_id, policy_code, recorded_at DESC);

-- ------------------------------------------------------------ T71: event catalog (allow-list)
CREATE TABLE behavior_mock.behavior_event_catalog (
    event_code           varchar(80) PRIMARY KEY,
    required_policy_code varchar(80) NOT NULL,
    allowed_keys         text[] NOT NULL,
    retain_for           interval NOT NULL,
    description          text NOT NULL,
    CONSTRAINT event_code_format CHECK (event_code ~ '^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$'),
    CONSTRAINT event_policy_known CHECK (required_policy_code IN ('behavior_tracking', 'personalization')),
    CONSTRAINT event_allowed_keys_limit CHECK (cardinality(allowed_keys) <= 10),
    CONSTRAINT event_retention_positive CHECK (retain_for >= interval '0')
);

INSERT INTO behavior_mock.behavior_event_catalog VALUES
    ('page.view',             'behavior_tracking', ARRAY['page_id','referrer_type'],                    interval '180 days', '화면 조회'),
    ('search.submit',         'behavior_tracking', ARRAY['search_type','filter_count','result_count'], interval '180 days', '검색 실행 (검색어 원문 금지)'),
    ('posting.view',          'behavior_tracking', ARRAY['job_posting_id','list_position'],            interval '180 days', '채용공고 상세 조회'),
    ('role.view',             'behavior_tracking', ARRAY['job_role_id'],                               interval '180 days', '직무 상세 조회'),
    ('skill_gap.view',        'behavior_tracking', ARRAY['job_role_id','gap_count'],                   interval '180 days', 'Skill Gap 결과 조회'),
    ('posting.bookmark',      'personalization',   ARRAY['job_posting_id'],                            interval '180 days', '공고 북마크 신호'),
    ('recommendation.click',  'personalization',   ARRAY['recommendation_id','rank'],                  interval '180 days', '추천 항목 클릭'),
    ('recommendation.dismiss','personalization',   ARRAY['recommendation_id','reason_code'],           interval '180 days', '추천 항목 숨김');

-- ------------------------------------------------------------ F07 behavior_events (T05 columns + 3 T71 columns)
CREATE TABLE behavior_mock.behavior_events (
    event_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL REFERENCES behavior_mock.users (user_id) ON DELETE CASCADE,
    event_code      varchar(80) NOT NULL REFERENCES behavior_mock.behavior_event_catalog (event_code),
    event_at        timestamptz NOT NULL DEFAULT now(),
    metadata        jsonb,
    -- T71 proposals (for T09): consent basis and fixed retention deadline
    policy_code     varchar(80) NOT NULL,
    policy_version  varchar(40) NOT NULL,
    retain_until    timestamptz NOT NULL,
    CONSTRAINT behavior_metadata_object CHECK (metadata IS NULL OR jsonb_typeof(metadata) = 'object'),
    CONSTRAINT behavior_metadata_size CHECK (metadata IS NULL OR octet_length(metadata::text) <= 1024)
);
CREATE INDEX ix_behavior_events_user ON behavior_mock.behavior_events (user_id, event_at DESC);
CREATE INDEX ix_behavior_events_code_time ON behavior_mock.behavior_events (event_code, event_at);

-- ------------------------------------------------------------ current consent (latest row wins)
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
    p_user_id uuid, p_event_code varchar, p_event_at timestamptz, p_metadata jsonb DEFAULT '{}'::jsonb
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
    IF p_event_at > clock_timestamp() + interval '5 minutes'
       OR p_event_at < clock_timestamp() - interval '7 days' THEN
        RAISE EXCEPTION 'event_at out of accepted window' USING ERRCODE = '22023';
    END IF;
    IF p_metadata IS NULL OR jsonb_typeof(p_metadata) <> 'object' THEN
        RAISE EXCEPTION 'metadata must be an object' USING ERRCODE = '22023';
    END IF;
    FOR k, v IN SELECT key, value FROM jsonb_each(p_metadata) LOOP
        IF NOT (k = ANY (cat.allowed_keys)) THEN
            RAISE EXCEPTION 'metadata key % is not allowed for %', k, p_event_code USING ERRCODE = '22023';
        END IF;
        IF jsonb_typeof(v) = 'number' OR jsonb_typeof(v) = 'boolean' THEN
            CONTINUE;
        ELSIF jsonb_typeof(v) = 'string' AND (v #>> '{}') ~ '^[A-Za-z0-9_.:-]{1,64}$' THEN
            CONTINUE;   -- ids and codes only: no spaces, so no free text / sentences
        ELSE
            RAISE EXCEPTION 'metadata % must be a number, boolean, id or code', k USING ERRCODE = '22023';
        END IF;
    END LOOP;

    -- Serialize collection and consent changes for this user. Hold the same row
    -- lock until commit so withdrawal cannot miss an uncommitted event insert.
    PERFORM 1 FROM behavior_mock.users WHERE user_id = p_user_id FOR UPDATE;
    SELECT * INTO cons FROM behavior_mock.current_consent(p_user_id, cat.required_policy_code);
    IF NOT FOUND OR cons.granted IS NOT TRUE THEN
        RETURN 'blocked_no_consent';
    END IF;

    INSERT INTO behavior_mock.behavior_events
        (user_id, event_code, event_at, metadata, policy_code, policy_version, retain_until)
    VALUES
        (p_user_id, p_event_code, p_event_at, NULLIF(p_metadata, '{}'::jsonb),
         cat.required_policy_code, cons.policy_version, clock_timestamp() + cat.retain_for);
    RETURN 'stored';
END $$;

-- ------------------------------------------------------------ consent changes: withdrawal deletes data
-- uses the latest effective version of the policy; only non-required policies (T05 FR-ACC-006)
CREATE FUNCTION behavior_mock.record_consent(p_user_id uuid, p_policy_code varchar, p_granted boolean)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = behavior_mock, pg_temp AS $$
DECLARE
    pol     behavior_mock.consent_policies%ROWTYPE;
    removed bigint := 0;
BEGIN
    -- Same lock/order as record_behavior_event; also coordinates user deletion.
    PERFORM 1 FROM behavior_mock.users WHERE user_id = p_user_id FOR UPDATE;
    SELECT * INTO pol FROM behavior_mock.consent_policies
    WHERE policy_code = p_policy_code AND effective_at <= now()
    ORDER BY effective_at DESC LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown policy_code %', p_policy_code USING ERRCODE = '22023';
    END IF;
    IF pol.is_required THEN
        RAISE EXCEPTION 'required policy % cannot be changed after signup', p_policy_code USING ERRCODE = '22023';
    END IF;
    INSERT INTO behavior_mock.user_consents (user_id, policy_code, policy_version, granted)
    VALUES (p_user_id, p_policy_code, pol.version, p_granted);
    IF NOT p_granted THEN
        DELETE FROM behavior_mock.behavior_events WHERE user_id = p_user_id AND policy_code = p_policy_code;
        GET DIAGNOSTICS removed = ROW_COUNT;
    END IF;
    RETURN removed;   -- number of events erased because of the withdrawal
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
SELECT (e.event_at AT TIME ZONE 'UTC')::date AS day_utc,
       e.event_code,
       count(*) AS event_count,
       count(DISTINCT e.user_id) AS user_count
FROM behavior_mock.behavior_events e
GROUP BY 1, 2
HAVING count(DISTINCT e.user_id) >= 5;   -- k = 5: smaller groups are suppressed

-- ------------------------------------------------------------ privileges
REVOKE ALL ON SCHEMA behavior_mock FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA behavior_mock FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA behavior_mock FROM PUBLIC;

GRANT USAGE ON SCHEMA behavior_mock TO t71_ingest, t71_consent, t71_analyst;
GRANT EXECUTE ON FUNCTION behavior_mock.record_behavior_event(uuid, varchar, timestamptz, jsonb) TO t71_ingest;
GRANT EXECUTE ON FUNCTION behavior_mock.record_consent(uuid, varchar, boolean) TO t71_consent;
GRANT SELECT ON behavior_mock.insights_daily TO t71_analyst;
GRANT SELECT ON behavior_mock.behavior_event_catalog, behavior_mock.consent_policies TO t71_ingest, t71_consent, t71_analyst;

COMMIT;
