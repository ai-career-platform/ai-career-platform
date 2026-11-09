-- T154 STEP02: crawler-only keyword success checkpoint. Manual migration.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'T154 requires dedicated crawler training database';
 END IF;
 IF to_regclass('crawler_training.search_keywords') IS NULL
    OR to_regclass('crawler_training.keyword_jobs') IS NULL THEN
  RAISE EXCEPTION 'T151 schema must be applied first';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS crawler_training.keyword_checkpoints (
 keyword_id bigint PRIMARY KEY REFERENCES crawler_training.search_keywords(keyword_id),
 last_success_at timestamptz NOT NULL,
 last_completed_job_id uuid NOT NULL REFERENCES crawler_training.keyword_jobs(job_id),
 updated_at timestamptz NOT NULL DEFAULT now()
);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT,UPDATE ON crawler_training.keyword_checkpoints TO crawler_staging;
 END IF;
END $$;
COMMIT;
