-- #337 least-privilege grants for the career_sync role on the GCP ai_career_poc database.
-- Run as the career schema owner (ai_career_poc) after the LOGIN role exists. No DELETE, no DDL.
-- Re-running is harmless (GRANT is idempotent).
GRANT USAGE ON SCHEMA career TO career_sync;
GRANT SELECT ON career.data_sources TO career_sync;
GRANT SELECT, INSERT ON career.companies TO career_sync;
GRANT SELECT, INSERT ON career.job_postings TO career_sync;
GRANT UPDATE (company_id, title, employment_type, location_text, source_url, status, published_at, expires_at, updated_at)
    ON career.job_postings TO career_sync;
GRANT SELECT, INSERT ON career.job_posting_external_refs TO career_sync;
GRANT UPDATE (last_seen_at) ON career.job_posting_external_refs TO career_sync;
GRANT SELECT, INSERT ON career.ingestion_runs TO career_sync;
GRANT UPDATE (status, ended_at, error_summary) ON career.ingestion_runs TO career_sync;
