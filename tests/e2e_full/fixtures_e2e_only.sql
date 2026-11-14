-- ============================================================================================
-- FULL-SYSTEM E2E — TEST-ONLY FIXTURES. 운영·Staging·GCP 에 절대 적용하지 않는다.
-- 적용 주체: tests/e2e_full/run_full_e2e.py 가 방금 만든 일회용 DB(e2e_full_system)에만 넣는다.
-- 모든 값은 합성(example.invalid). 개인정보·운영 데이터 없음.
--
-- 왜 fixture 인가(운영 seed 가 아닌 이유):
--   * consent_policies terms/privacy  : 회원가입(T15) 필수 약관. 운영 약관 버전은 PM 승인 사항.
--   * consent_policies public_profile : T128 공개 포트폴리오 동의 약관(정책 승인 전, migration 0007 주석 참고).
--   * data_sources company_direct     : T125 D-5 게시 약관 승인 전(migration 0009 주석 참고). 없으면 승인이 503.
--   * data_sources jobkorea_live + 수집 draft 공고 : 크롤러(gcp_sync) 가 남기는 '수집됐지만 비공개(draft)' 공고 모양.
--     공개 목록·상세에 나오면 안 된다(시나리오 D).
-- ============================================================================================

INSERT INTO career.consent_policies (policy_code, version, is_required, content_url, effective_at) VALUES
    ('terms', 'e2e-2026-11', true, 'https://example.invalid/e2e/terms', now() - interval '1 day'),
    ('privacy', 'e2e-2026-11', true, 'https://example.invalid/e2e/privacy', now() - interval '1 day'),
    ('public_profile', 'e2e-pp-1', false, 'https://example.invalid/e2e/public-profile', now() - interval '1 day');

INSERT INTO career.data_sources (code, name, license_ref) VALUES
    ('company_direct', 'E2E 기업 직접 등록(fixture)', 'e2e-t125-terms-fixture-1'),
    ('jobkorea_live', 'E2E 잡코리아 수집 모양(fixture)', 'e2e-crawler-fixture-1');

INSERT INTO career.companies (company_id, name, source_id)
SELECT 'e2e00000-0000-4000-8000-00000000c001', 'E2E 수집 회사(fixture)', source_id
FROM career.data_sources WHERE code = 'jobkorea_live';

-- 수집 draft 공고(공개 금지). 제목에 고유 표식을 넣어 공개 목록·검색에서 찾는다.
INSERT INTO career.job_postings (job_posting_id, company_id, source_id, title, description, status, source_url)
SELECT 'e2e00000-0000-4000-8000-00000000d001', 'e2e00000-0000-4000-8000-00000000c001', source_id,
       'E2EJOBKOREADRAFT 수집 초안 공고', 'E2E fixture: crawled but not published', 'draft',
       'https://example.invalid/e2e/jobkorea/1'
FROM career.data_sources WHERE code = 'jobkorea_live';
