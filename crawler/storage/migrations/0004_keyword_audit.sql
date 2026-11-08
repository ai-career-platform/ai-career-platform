-- T151 STEP04: explicit/manual audit ledger migration (after 0003).
-- Does not modify existing postings, schedules, runs, run_events or 0003 tables.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'Dedicated ai_career_crawler_training database required';
 END IF;
 IF to_regclass('crawler_training.search_keywords') IS NULL THEN
  RAISE EXCEPTION 'Apply 0003_keywords_jobs.sql first';
 END IF;
END $$;

CREATE TABLE IF NOT EXISTS crawler_training.keyword_audit_events (
 audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 keyword_id bigint NOT NULL REFERENCES crawler_training.search_keywords(keyword_id),
 actor text NOT NULL CHECK (length(actor) BETWEEN 1 AND 128),
 action text NOT NULL CHECK (action IN ('CREATE','EDIT','SET_ENABLED','SOFT_DELETE')),
 before_state jsonb,
 after_state jsonb NOT NULL,
 occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS t151_keyword_audit_by_keyword
 ON crawler_training.keyword_audit_events(keyword_id,occurred_at DESC,audit_id DESC);
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT ON crawler_training.keyword_audit_events TO crawler_staging;
  GRANT USAGE,SELECT ON SEQUENCE crawler_training.keyword_audit_events_audit_id_seq TO crawler_staging;
 END IF;
END $$;
COMMIT;
