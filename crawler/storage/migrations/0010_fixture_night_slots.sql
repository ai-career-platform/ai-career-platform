-- T154 STEP21: additive, manual-only synthetic fixture night-slot ledger.
-- This migration DOES NOT enable any timer, service, or live crawler.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'Night slot ledger requires dedicated crawler DB';
 END IF;
 IF to_regclass('crawler_training.fixture_job_attempts') IS NULL THEN
  RAISE EXCEPTION 'Apply migration 0009 first';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS crawler_training.fixture_night_slots (
 night_date date NOT NULL,
 slot_index smallint NOT NULL CHECK (slot_index BETWEEN 0 AND 21),
 job_id uuid NOT NULL REFERENCES crawler_training.keyword_jobs(job_id),
 reserved_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (night_date,slot_index),
 UNIQUE (night_date,job_id)
);
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT ON crawler_training.fixture_night_slots TO crawler_staging;
 END IF;
END $$;
COMMIT;
