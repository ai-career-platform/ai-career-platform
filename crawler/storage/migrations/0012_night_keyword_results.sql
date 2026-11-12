-- CRAWLER_NIGHT_01: per-keyword night job results and one summary notice per night.
-- Explicit/manual migration for the isolated crawler DB only. NEVER applied at startup.
-- Not applied to Staging by this PR; Staging application requires separate DB approval.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'Dedicated ai_career_crawler_training database required';
 END IF;
 IF to_regclass('crawler_training.keyword_jobs') IS NULL
    OR to_regclass('crawler_training.keyword_checkpoints') IS NULL THEN
  RAISE EXCEPTION 'Apply 0003 and 0007 first';
 END IF;
END $$;

-- keyword_jobs keeps the lifecycle (PENDING/RUNNING/FETCHED/COMPLETED/FAILED);
-- this row keeps what the job did. One row per night job attempt.
CREATE TABLE IF NOT EXISTS crawler_training.night_job_results (
 job_id uuid PRIMARY KEY REFERENCES crawler_training.keyword_jobs(job_id),
 keyword_id bigint NOT NULL REFERENCES crawler_training.search_keywords(keyword_id),
 night_date date NOT NULL,
 attempt smallint NOT NULL CHECK (attempt BETWEEN 1 AND 3),
 mode text NOT NULL CHECK (mode = 'live'),
 outcome text NOT NULL DEFAULT 'RUNNING'
  CHECK (outcome IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED')),
 http_requests integer CHECK (http_requests >= 0),
 fetched integer CHECK (fetched >= 0),
 inserted integer CHECK (inserted >= 0),
 updated integer CHECK (updated >= 0),
 unchanged integer CHECK (unchanged >= 0),
 duplicates integer CHECK (duplicates >= 0),
 failed integer CHECK (failed >= 0),
 error_code text CHECK (error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
 started_at timestamptz NOT NULL DEFAULT now(),
 ended_at timestamptz,
 slack_notified_at timestamptz,
 UNIQUE (night_date, keyword_id, attempt),
 CHECK (outcome = 'RUNNING' AND ended_at IS NULL OR outcome <> 'RUNNING' AND ended_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS night_job_results_night_idx
 ON crawler_training.night_job_results(night_date, keyword_id);
-- At most one RUNNING night job at any time (single sequential worker).
CREATE UNIQUE INDEX IF NOT EXISTS night_job_results_one_running
 ON crawler_training.night_job_results((true)) WHERE outcome = 'RUNNING';

CREATE TABLE IF NOT EXISTS crawler_training.night_summaries (
 night_date date PRIMARY KEY,
 claimed_at timestamptz NOT NULL DEFAULT now(),
 http_status integer
);

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT,UPDATE ON crawler_training.night_job_results TO crawler_staging;
  GRANT SELECT,INSERT,UPDATE ON crawler_training.night_summaries TO crawler_staging;
 END IF;
END $$;
COMMIT;
-- Rollback (manual, only while unused):
--   DROP TABLE IF EXISTS crawler_training.night_summaries;
--   DROP TABLE IF EXISTS crawler_training.night_job_results;
