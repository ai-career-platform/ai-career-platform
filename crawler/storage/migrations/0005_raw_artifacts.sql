-- T152: explicit, manual-only isolated crawler migration.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
   RAISE EXCEPTION 'T152 requires isolated crawler training database';
 END IF;
 IF to_regclass('crawler_training.search_keywords') IS NULL THEN
   RAISE EXCEPTION 'T151 migration required';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS crawler_training.raw_artifacts (
 artifact_id uuid PRIMARY KEY,
 keyword_id bigint NOT NULL REFERENCES crawler_training.search_keywords(keyword_id),
 job_id uuid REFERENCES crawler_training.keyword_jobs(job_id),
 kind text NOT NULL CHECK (kind IN ('list','detail')),
 source_url text NOT NULL CHECK (length(source_url) BETWEEN 1 AND 2048),
 http_status smallint NOT NULL CHECK (http_status BETWEEN 100 AND 599),
 content_type text NOT NULL CHECK (content_type IN ('text/html','application/xhtml+xml')),
 byte_size integer NOT NULL CHECK (byte_size BETWEEN 1 AND 2000000),
 sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
 storage_key text NOT NULL CHECK (length(storage_key) BETWEEN 1 AND 256),
 captured_at timestamptz NOT NULL DEFAULT now(),
 mode text NOT NULL DEFAULT 'synthetic_fixture_only'
   CHECK (mode = 'synthetic_fixture_only'),
 UNIQUE (keyword_id,kind,source_url,sha256)
);
CREATE INDEX IF NOT EXISTS t152_raw_artifacts_keyword_time
 ON crawler_training.raw_artifacts(keyword_id,captured_at DESC);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT ON crawler_training.raw_artifacts TO crawler_staging;
 END IF;
END $$;
COMMIT;
