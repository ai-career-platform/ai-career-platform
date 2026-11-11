-- PROPOSED (T99) — NOT a migration. database/migrate.py does not read this folder.
-- Purpose: T98 고급 검색(PROPOSED) 조합의 응답 시간 유지. 효과는 docs/search/T99_ADVANCED_SEARCH_IMPLEMENTATION.md §4 (격리 DB 측정).
-- Recovery: 인덱스만 추가(데이터 변경 없음). 문제 시 후속 migration 에서 DROP INDEX (Destructive-Approval 필요).
-- 공유 Staging 에 승인 없이 만들지 않음. 운영 적용 시 CONCURRENTLY 로 만들어야 하므로(러너는 CONCURRENTLY 금지)
-- 적용 절차는 PM·DB 담당 결정 필요. 검증: backend/tests/test_t99_job_search_postgres.py, backend/perf/t99_search_bench.py

-- [선택·비권장] 고용형태 필터 + 최신순 (게시 중 공고만). 10만 건 측정에서 기존 ix_job_postings_3 대비 이득 없음
CREATE INDEX ix_job_postings_t99_employment
    ON career.job_postings (employment_type, published_at DESC, job_posting_id DESC) WHERE status = 'published';

-- [선택·비권장] 지역 필터: location_text 첫 단어. 10만 건 측정에서 드문 지역 p95 가 오히려 늘어남(1.5→5.4 ms).
--   app/repositories/job_postings.py region_token() 과 같은 식이어야 사용됨
CREATE INDEX ix_job_postings_t99_region
    ON career.job_postings ((split_part(regexp_replace(btrim(location_text), '\s+', ' ', 'g'), ' ', 1)) text_pattern_ops)
    WHERE status = 'published';

-- [권장] 마감 임박순 keyset(마감일 없음 = +infinity) — p95 134→20 ms(게시 중), 124→1.6 ms(마감 포함).
--   마감 포함 목록(status IN published, closed)에도 쓰이도록 조건을 넓힘
CREATE INDEX ix_job_postings_t99_expires
    ON career.job_postings ((coalesce(expires_at, 'infinity'::timestamptz)), job_posting_id)
    WHERE status IN ('published', 'closed');
