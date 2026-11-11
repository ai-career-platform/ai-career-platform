-- T149 용량 측정용 합성 활동 행. 일회용 로컬 DB 전용입니다.
--
-- T147 합성 데이터 공장은 사용자·회사·공고·기술·북마크만 만듭니다. 시간이 갈수록 커지는 이벤트성 표
-- (행동 이벤트·감사·AI 사용량·세션·추천·문서 메타데이터)는 여기서 합성 행을 넣고, **행당 바이트만** 실측합니다.
-- 아래 :per_* 값은 행당 바이트를 재기 위한 **표본 수**일 뿐입니다. 실제 성장 가정(사용자당 월 활동량)은
-- docs/ops/capacity/t149_assumptions.json 에 따로 있고, 근거(basis)를 표시합니다.
--
--   psql -X -v ON_ERROR_STOP=1 -d t149_local_sN -f scripts/ops/t149_activity_rows.sql
--
-- 안전: DB 이름이 t149_local_ 로 시작하지 않으면 아무것도 쓰지 않고 중단합니다.
\set ON_ERROR_STOP on
DO $$
BEGIN
    IF current_database() NOT LIKE 't149\_local\_%' THEN
        RAISE EXCEPTION 'T149 activity rows refused: database % is not a disposable t149_local_* database', current_database();
    END IF;
END $$;

\set per_behavior 60
\set per_audit 12
\set per_ai 8
\set per_session 6
\set per_reco_run 4
\set per_reco_item 10
\set per_document 2

BEGIN;
INSERT INTO career.model_versions (model_code, version, kind, description)
SELECT 't149_synthetic', '0', 'rule', 'T149 capacity measurement only'
WHERE NOT EXISTS (SELECT 1 FROM career.model_versions WHERE model_code = 't149_synthetic');

CREATE TEMP TABLE t149_users AS
SELECT user_id, row_number() OVER (ORDER BY user_id) AS n FROM career.users WHERE email_canonical LIKE 'synth-%@example.test';

INSERT INTO career.behavior_events (user_id, event_code, event_at, metadata)
SELECT u.user_id, (ARRAY['job_view', 'job_search', 'bookmark_add', 'recommendation_view'])[1 + (g % 4)],
       timestamptz '2026-11-01 00:00:00+09' + (g * interval '37 minutes'),
       jsonb_build_object('surface', 'web', 'position', g % 20)
FROM t149_users u CROSS JOIN generate_series(1, :per_behavior) g;

INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, resource_id, request_id, occurred_at)
SELECT u.user_id, (ARRAY['auth.login', 'profile.update', 'document.upload', 'consent.update'])[1 + (g % 4)], 'user', u.user_id,
       md5(u.user_id::text || g)::varchar(32), timestamptz '2026-11-01 00:00:00+09' + (g * interval '2 hours')
FROM t149_users u CROSS JOIN generate_series(1, :per_audit) g;

INSERT INTO career.ai_usage_records (user_id, model_version_id, provider_model, feature_code, input_tokens, output_tokens,
                                     estimated_cost_usd, latency_ms, occurred_at)
SELECT u.user_id, m.model_version_id, 'synthetic-model', (ARRAY['document_analysis', 'rag_answer', 'agent'])[1 + (g % 3)],
       2000, 500, 0, 1200, timestamptz '2026-11-01 00:00:00+09' + (g * interval '3 hours')
FROM t149_users u CROSS JOIN generate_series(1, :per_ai) g
CROSS JOIN (SELECT model_version_id FROM career.model_versions WHERE model_code = 't149_synthetic') m;

INSERT INTO career.auth_sessions (user_id, refresh_token_hash, user_agent, created_at, expires_at)
SELECT u.user_id, encode(sha256((u.user_id::text || g)::bytea), 'hex'),
       'Mozilla/5.0 (synthetic T149) AppleWebKit/537.36 Chrome/131.0 Safari/537.36',
       timestamptz '2026-11-01 00:00:00+09' + (g * interval '1 day'), timestamptz '2026-11-15 00:00:00+09' + (g * interval '1 day')
FROM t149_users u CROSS JOIN generate_series(1, :per_session) g;

INSERT INTO career.user_documents (owner_user_id, kind, original_filename, mime_type, size_bytes, storage_key, checksum_sha256, status)
SELECT u.user_id, (ARRAY['resume', 'portfolio'])[1 + (g % 2)], 'synthetic-' || g || '.pdf', 'application/pdf', 350000,
       md5(u.user_id::text || 'doc' || g), encode(sha256((u.user_id::text || 'doc' || g)::bytea), 'hex'), 'ready'
FROM t149_users u CROSS JOIN generate_series(1, :per_document) g;

CREATE TEMP TABLE t149_runs AS
SELECT gen_random_uuid() AS recommendation_run_id, u.user_id, g
FROM t149_users u CROSS JOIN generate_series(1, :per_reco_run) g;
INSERT INTO career.recommendation_runs (recommendation_run_id, user_id, model_version_id, status, generated_at)
SELECT r.recommendation_run_id, r.user_id, m.model_version_id, 'completed', timestamptz '2026-11-01 00:00:00+09' + (r.g * interval '7 days')
FROM t149_runs r CROSS JOIN (SELECT model_version_id FROM career.model_versions WHERE model_code = 't149_synthetic') m;

INSERT INTO career.recommendation_items (recommendation_run_id, job_posting_id, rank, score, reason)
SELECT ranked.recommendation_run_id, ranked.job_posting_id, ranked.rank, 90 - ranked.rank,
       '보유 기술과 직무 요구 기술이 겹칩니다 (합성 설명, T149 측정용).'
FROM (
    SELECT r.recommendation_run_id, p.job_posting_id,
           row_number() OVER (PARTITION BY r.recommendation_run_id ORDER BY p.job_posting_id) AS rank
    FROM t149_runs r
    CROSS JOIN LATERAL (
        SELECT job_posting_id FROM career.job_postings ORDER BY job_posting_id
        OFFSET ((hashtext(r.recommendation_run_id::text) & 1023) % GREATEST((SELECT count(*) FROM career.job_postings) - :per_reco_item, 1))
        LIMIT :per_reco_item
    ) p
) ranked;
COMMIT;
ANALYZE;
