-- PROPOSED OPTION (T99) — NOT a migration, NOT recommended until D-5 (T98) is decided.
-- Purpose: 제목·기업명 부분 일치(ILIKE '%…%')용 trigram GIN. pg_trgm 확장 설치가 필요합니다(Staging·운영 권한 확인 필요).
-- Recovery: DROP INDEX 두 개 (+ 필요 시 DROP EXTENSION) — Destructive-Approval 필요.
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_job_postings_t99_title_trgm ON career.job_postings USING gin (title gin_trgm_ops);
CREATE INDEX ix_companies_t99_name_trgm ON career.companies USING gin (name gin_trgm_ops);
