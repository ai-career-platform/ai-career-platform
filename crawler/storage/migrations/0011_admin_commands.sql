-- T155: append-only ledger for authenticated crawler admin commands.
-- Explicit/manual migration for the isolated crawler DB only. NEVER applied at startup.
-- Not applied to Staging by this PR; Staging application requires separate approval.
BEGIN;
DO $$ BEGIN
 IF current_database() <> 'ai_career_crawler_training' THEN
  RAISE EXCEPTION 'Dedicated ai_career_crawler_training database required';
 END IF;
 IF to_regclass('crawler_training.keyword_jobs') IS NULL
    OR to_regclass('crawler_training.schedules') IS NULL THEN
  RAISE EXCEPTION 'Apply 0002/0003 first';
 END IF;
END $$;

CREATE TABLE IF NOT EXISTS crawler_training.admin_commands (
 command_id uuid PRIMARY KEY,
 idempotency_key text NOT NULL UNIQUE
  CHECK (length(idempotency_key) BETWEEN 1 AND 200 AND idempotency_key = btrim(idempotency_key)),
 request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
 actor text NOT NULL CHECK (length(actor) BETWEEN 1 AND 128),
 command_type text NOT NULL CHECK (command_type IN ('RUN','STOP','RETRY','SCHEDULE_UPDATE')),
 target text NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
 outcome text NOT NULL CHECK (outcome IN ('ACCEPTED','REFUSED')),
 reason text NOT NULL CHECK (length(reason) BETWEEN 1 AND 64),
 result jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS t155_admin_commands_recent
 ON crawler_training.admin_commands(created_at DESC, command_id);

-- Runtime role may only read and append: no UPDATE/DELETE grant (append-only ledger).
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='crawler_staging') THEN
  GRANT SELECT,INSERT ON crawler_training.admin_commands TO crawler_staging;
 END IF;
END $$;
COMMIT;
-- Rollback (manual, only while the table is unused):
--   DROP TABLE IF EXISTS crawler_training.admin_commands;
