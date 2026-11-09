-- T154 STEP07: immutable fixture payload per existing T151 job; manual-only.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'T154 requires isolated crawler training database';
 END IF;
 IF to_regclass('crawler_training.keyword_jobs') IS NULL THEN
  RAISE EXCEPTION 'Apply T151 migration first';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS crawler_training.fixture_job_payloads (
 job_id uuid PRIMARY KEY REFERENCES crawler_training.keyword_jobs(job_id),
 keyword_id bigint NOT NULL REFERENCES crawler_training.search_keywords(keyword_id),
 posting_ids text[] NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK (cardinality(posting_ids) BETWEEN 1 AND 10),
 CHECK (array_position(posting_ids, NULL) IS NULL),
 CHECK (array_to_string(posting_ids, ',') ~ '^[0-9]+(,[0-9]+)*$')
);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT ON crawler_training.fixture_job_payloads TO crawler_staging;
 END IF;
END $$;
COMMIT;
