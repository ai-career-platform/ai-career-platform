-- T65 검증용 합성 fixture. 일회용 DB 전용 (Staging·공용 DB 금지).
-- 선행: database/migrations/0001~0003 적용 + database/seeds/0001_initial_seed.sql (job_roles·skills 사용).
-- 모든 시각은 KST(+09)로 적고, 경계 사례는 계약 §6 표의 ID와 같다.
-- 기대 결과: database/market_metrics/t65_expected.json
SET client_encoding = 'UTF8';

BEGIN;

INSERT INTO career.data_sources (source_id, code, name, license_ref, retention_days, is_active)
VALUES (md5('t65:source')::uuid, 't65_fixture', 'T65 합성 지표 fixture', 'synthetic-test-only', NULL, true);

INSERT INTO career.companies (company_id, name, source_id)
VALUES (md5('t65:company')::uuid, 'T65 가상 기업', md5('t65:source')::uuid);

-- 공고: (id, 직무 code, status, published_at KST, created_at KST)
INSERT INTO career.job_postings (job_posting_id, company_id, job_role_id, source_id, title, status, published_at, created_at, updated_at)
SELECT md5('t65:posting:' || v.id)::uuid,
       md5('t65:company')::uuid,
       (SELECT job_role_id FROM career.job_roles WHERE code = v.role),
       md5('t65:source')::uuid,
       'T65 ' || v.id,
       v.status,
       v.published_at::timestamptz,
       v.created_at::timestamptz,
       v.created_at::timestamptz
FROM (VALUES
    -- 1주차 2026-10-05(월)~10-11(일)
    ('p1', 'BACKEND_ENGINEER',  'published', '2026-10-05 10:00+09', '2026-10-05 12:00+09'),
    ('p2', 'BACKEND_ENGINEER',  'published', '2026-10-06 10:00+09', '2026-10-06 12:00+09'),
    ('p3', 'BACKEND_ENGINEER',  'published', '2026-10-07 10:00+09', '2026-10-07 12:00+09'),
    ('p4', 'BACKEND_ENGINEER',  'published', '2026-10-08 10:00+09', '2026-10-08 12:00+09'),
    ('p5', 'FRONTEND_ENGINEER', 'published', '2026-10-09 10:00+09', '2026-10-09 12:00+09'),
    ('p6', NULL,                'published', '2026-10-11 23:30+09', '2026-10-11 23:40+09'),  -- E2 KST 주 마지막 시각, 직무 없음
    ('c1', 'BACKEND_ENGINEER',  'closed',    '2026-10-10 10:00+09', '2026-10-10 12:00+09'),  -- E3 마감 공고도 게시 이력으로 집계
    ('d1', 'BACKEND_ENGINEER',  'draft',     NULL,                  '2026-10-06 12:00+09'),  -- E4 draft 제외
    -- 2주차 2026-10-12~10-18
    ('p7', NULL,                'published', '2026-10-12 00:10+09', '2026-10-12 00:20+09'),  -- E2 UTC로는 10-11, KST로는 2주차
    ('p8', 'FRONTEND_ENGINEER', 'published', '2026-10-13 10:00+09', '2026-10-13 12:00+09'),
    -- 3주차 2026-10-19~10-25: 공고 없음, 수집 성공 기록만 있음 (E6 → 0)
    -- 4주차 2026-10-26~11-01: 수집 기록 없음. p9는 11-03에야 수집됨 (E7 늦게 들어온 공고)
    ('p9', 'BACKEND_ENGINEER',  'published', '2026-10-27 10:00+09', '2026-11-03 09:00+09'),
    -- 5주차 2026-11-02~11-08
    ('p10','BACKEND_ENGINEER',  'published', '2026-11-03 10:00+09', '2026-11-03 12:00+09'),
    ('p11','FRONTEND_ENGINEER', 'published', '2026-11-05 10:00+09', '2026-11-05 12:00+09')   -- E8 as_of 이후 게시
) AS v(id, role, status, published_at, created_at);

-- 공고별 요구 기술 (추출 시각은 공고 저장 시각과 같게 둔다)
INSERT INTO career.job_posting_skills (job_posting_id, skill_id, is_required, created_at)
SELECT md5('t65:posting:' || v.id)::uuid,
       (SELECT skill_id FROM career.skills WHERE code = v.skill),
       true,
       (SELECT created_at FROM career.job_postings WHERE job_posting_id = md5('t65:posting:' || v.id)::uuid)
FROM (VALUES
    ('p1', 'PYTHON'),
    ('p2', 'PYTHON'), ('p2', 'JAVA'),
    ('p3', 'PYTHON'),
    ('p4', 'JAVA'),
    ('p5', 'TYPESCRIPT'),
    ('p6', 'PYTHON'),
    ('c1', 'PYTHON'),
    ('d1', 'PYTHON'),
    ('p8', 'TYPESCRIPT')
) AS v(id, skill);

-- 수집 실행 기록: 3주차에 성공 1건(공고 0건), 4주차에 실패 1건(관측으로 보지 않음)
INSERT INTO career.ingestion_runs (ingestion_run_id, source_id, status, started_at, ended_at, fetched_count, error_summary)
VALUES (md5('t65:run:w3')::uuid, md5('t65:source')::uuid, 'succeeded', '2026-10-20 03:00+09', '2026-10-20 03:05+09', 0, NULL),
       (md5('t65:run:w4')::uuid, md5('t65:source')::uuid, 'failed',    '2026-10-27 03:00+09', '2026-10-27 03:01+09', 0, 'synthetic failure');

COMMIT;
