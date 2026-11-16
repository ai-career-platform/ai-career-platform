-- GOAL_3 (AI_CAREER_CRAWLER_LIVE_GCP_1000): paginated keyword harvest runs, per-page supply
-- metrics and per-posting decisions. harvest_items is also the provenance ledger the GCP sync
-- uses in local-source mode: only postings written by a LIVE harvest run can be selected.
-- Explicit/manual migration for the isolated crawler DB only. NEVER applied at startup.
-- Not applied to Staging by this PR; Staging application requires separate DB approval.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'Dedicated ai_career_crawler_training database required';
 END IF;
 IF to_regclass('crawler_training.postings') IS NULL THEN
  RAISE EXCEPTION 'Apply local_training_schema.sql first';
 END IF;
END $$;

CREATE TABLE IF NOT EXISTS crawler_training.harvest_runs (
 run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 mode text NOT NULL CHECK (mode IN ('fixture','live')),
 source_code text NOT NULL,
 status text NOT NULL DEFAULT 'RUNNING'
  CHECK (status IN ('RUNNING','SUCCEEDED','PARTIAL','STOPPED','FAILED')),
 stop_reason text CHECK (stop_reason IS NULL OR stop_reason ~ '^[A-Z][A-Z0-9_]{0,63}$'),
 limits jsonb NOT NULL,
 http_requests integer NOT NULL DEFAULT 0 CHECK (http_requests >= 0),
 search_pages integer NOT NULL DEFAULT 0 CHECK (search_pages >= 0),
 links_seen integer NOT NULL DEFAULT 0 CHECK (links_seen >= 0),
 new_found integer NOT NULL DEFAULT 0 CHECK (new_found >= 0),
 known_found integer NOT NULL DEFAULT 0 CHECK (known_found >= 0),
 cross_duplicates integer NOT NULL DEFAULT 0 CHECK (cross_duplicates >= 0),
 details_planned integer NOT NULL DEFAULT 0 CHECK (details_planned >= 0),
 inserted integer NOT NULL DEFAULT 0 CHECK (inserted >= 0),
 updated integer NOT NULL DEFAULT 0 CHECK (updated >= 0),
 unchanged integer NOT NULL DEFAULT 0 CHECK (unchanged >= 0),
 failed integer NOT NULL DEFAULT 0 CHECK (failed >= 0),
 keyword_stats jsonb,
 started_at timestamptz NOT NULL DEFAULT now(),
 ended_at timestamptz,
 CHECK (status = 'RUNNING' AND ended_at IS NULL OR status <> 'RUNNING' AND ended_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS harvest_runs_started_idx ON crawler_training.harvest_runs(started_at);
-- One harvest at a time (also serialized by the dispatcher advisory lock 642/0).
CREATE UNIQUE INDEX IF NOT EXISTS harvest_runs_one_running
 ON crawler_training.harvest_runs((true)) WHERE status = 'RUNNING';

CREATE TABLE IF NOT EXISTS crawler_training.harvest_pages (
 run_id uuid NOT NULL REFERENCES crawler_training.harvest_runs(run_id),
 keyword text NOT NULL,
 page_no integer NOT NULL CHECK (page_no >= 1),
 links integer NOT NULL CHECK (links >= 0),
 new_ids integer NOT NULL CHECK (new_ids >= 0),
 known_ids integer NOT NULL CHECK (known_ids >= 0),
 cross_duplicates integer NOT NULL CHECK (cross_duplicates >= 0),
 error_code text CHECK (error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
 fetched_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (run_id, keyword, page_no)
);

CREATE TABLE IF NOT EXISTS crawler_training.harvest_items (
 run_id uuid NOT NULL REFERENCES crawler_training.harvest_runs(run_id),
 source_code text NOT NULL,
 external_posting_id text NOT NULL,
 keyword text NOT NULL,
 page_no integer NOT NULL CHECK (page_no >= 1),
 decision text NOT NULL CHECK (decision IN ('new','revisit')),
 outcome text CHECK (outcome IN ('inserted','updated','unchanged','failed')),
 error_code text CHECK (error_code IS NULL OR error_code ~ '^[A-Za-z][A-Za-z0-9_]{0,63}$'),
 checked_at timestamptz,
 PRIMARY KEY (run_id, source_code, external_posting_id)
);
CREATE INDEX IF NOT EXISTS harvest_items_posting_idx
 ON crawler_training.harvest_items(source_code, external_posting_id, checked_at);

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT,UPDATE ON crawler_training.harvest_runs TO crawler_staging;
  GRANT SELECT,INSERT ON crawler_training.harvest_pages TO crawler_staging;
  GRANT SELECT,INSERT,UPDATE ON crawler_training.harvest_items TO crawler_staging;
 END IF;
END $$;
COMMIT;
-- Rollback (manual, only while unused):
--   DROP TABLE IF EXISTS crawler_training.harvest_items;
--   DROP TABLE IF EXISTS crawler_training.harvest_pages;
--   DROP TABLE IF EXISTS crawler_training.harvest_runs;
