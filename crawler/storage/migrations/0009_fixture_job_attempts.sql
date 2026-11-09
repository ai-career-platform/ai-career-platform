-- T154 STEP14: separate durable fixture attempt budget, manually applied only.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'T154 requires dedicated ai_career_crawler_training DB';
 END IF;
 IF to_regclass('crawler_training.keyword_jobs') IS NULL
    OR to_regclass('crawler_training.fixture_job_payloads') IS NULL THEN
  RAISE EXCEPTION 'Apply T151 and T154 0008 before 0009';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS crawler_training.fixture_job_attempts (
 job_id uuid PRIMARY KEY REFERENCES crawler_training.keyword_jobs(job_id),
 attempt_count smallint NOT NULL DEFAULT 1 CHECK (attempt_count BETWEEN 1 AND 3),
 state text NOT NULL DEFAULT 'IN_PROGRESS'
  CHECK (state IN ('IN_PROGRESS','RETRYABLE','STOPPED','COMPLETED')),
 last_error_code text CHECK (last_error_code IS NULL OR length(last_error_code) BETWEEN 1 AND 64),
 updated_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((state='IN_PROGRESS' OR state='COMPLETED') AND last_error_code IS NULL
         OR state IN ('RETRYABLE','STOPPED') AND last_error_code IS NOT NULL)
);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT,UPDATE ON crawler_training.fixture_job_attempts TO crawler_staging;
 END IF;
END $$;
COMMIT;
