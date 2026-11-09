-- Explicit migration ONLY in the isolated crawler database. Never startup DDL.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'Isolated crawler database required';
 END IF;
END $$;
CREATE TABLE IF NOT EXISTS crawler_training.schedules (
 schedule_id text PRIMARY KEY,
 source_id text NOT NULL UNIQUE CHECK (source_id='jobkorea'),
 enabled boolean NOT NULL DEFAULT false,
 timezone text NOT NULL DEFAULT 'Asia/Seoul' CHECK(timezone='Asia/Seoul'),
 local_time time NOT NULL DEFAULT '03:00',
 mode text NOT NULL DEFAULT 'fixture' CHECK(mode IN ('fixture','live')),
 target_urls jsonb NOT NULL DEFAULT '[]',
 approval jsonb,
 next_run_at timestamptz NOT NULL,
 last_run_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS crawler_training.runs (
 run_id uuid PRIMARY KEY,
 schedule_id text NOT NULL REFERENCES crawler_training.schedules(schedule_id),
 source_id text NOT NULL CHECK(source_id='jobkorea'),
 trigger text NOT NULL CHECK(trigger IN ('scheduled','retry')),
 mode text NOT NULL CHECK(mode IN ('fixture','live')),
 scheduled_for timestamptz NOT NULL,
 attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 3),
 status text NOT NULL CHECK(status IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED','CANCELLED')),
 started_at timestamptz NOT NULL,
 ended_at timestamptz,
 heartbeat_at timestamptz NOT NULL,
 retry_at timestamptz,
 fetched_count integer CHECK(fetched_count>=0),
 inserted_count integer CHECK(inserted_count>=0),
 updated_count integer CHECK(updated_count>=0),
 duplicate_count integer CHECK(duplicate_count>=0),
 failed_count integer CHECK(failed_count>=0),
 error_code text,
 UNIQUE(schedule_id,scheduled_for,attempt)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_running_crawler_source
 ON crawler_training.runs(source_id) WHERE status='RUNNING';
CREATE TABLE IF NOT EXISTS crawler_training.run_events (
 event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES crawler_training.runs(run_id),
 occurred_at timestamptz NOT NULL DEFAULT now(),
 level text NOT NULL CHECK(level IN ('INFO','WARNING','ERROR')),
 event_type text NOT NULL,
 safe_message text NOT NULL
);
INSERT INTO crawler_training.schedules(schedule_id,source_id,next_run_at)
VALUES ('jobkorea-daily','jobkorea',
 ((date_trunc('day',now() AT TIME ZONE 'Asia/Seoul')+interval '1 day 3 hours') AT TIME ZONE 'Asia/Seoul'))
ON CONFLICT DO NOTHING;
-- Support a separately owned migration: runtime never requires table ownership
-- or CREATE privileges. Do not create/change roles as part of this migration.
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,UPDATE ON crawler_training.schedules TO crawler_staging;
  GRANT SELECT,INSERT,UPDATE ON crawler_training.runs TO crawler_staging;
  GRANT SELECT,INSERT ON crawler_training.run_events TO crawler_staging;
  GRANT USAGE,SELECT ON SEQUENCE crawler_training.run_events_event_id_seq TO crawler_staging;
 END IF;
END $$;
COMMIT;
