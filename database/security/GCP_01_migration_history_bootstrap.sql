-- #344 PROPOSED, NOT APPLIED. Migration ledger bootstrap + 0001 baseline for the GCP Cloud SQL
-- database ai_career_poc. Rehearsed only on disposable PostgreSQL 18.3 in CI
-- (database/tests/test_t344_gcp_pg18_rehearsal.py). Production use needs separate PM approval.
--
-- Differs from DRAFT_01_migration_history.sql only in the owner role:
--   GCP has no career_migrator role. Objects in schema career are owned by ai_career_poc (NOLOGIN),
--   so the ledger is owned by ai_career_poc too and the runner is used with --role ai_career_poc.
-- Run as a LOGIN role that is a member of ai_career_poc (no superuser needed):
--   psql -X -v ON_ERROR_STOP=1 -d ai_career_poc \
--        -v baseline_checksum=<sha256 of 0001, CRLF->LF, as migrate.py computes> \
--        -v approval=GCP-PROD-344-<id> -f GCP_01_migration_history_bootstrap.sql
-- Creates no roles and no passwords, and touches no table in schema career.
-- Idempotent: once the 0001 baseline row exists, re-running changes nothing (also after 0002/0003).

\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL ROLE ai_career_poc;

-- Record 0001 as a baseline only when schema career is exactly the 0001 state.
DO $guard$
BEGIN
  IF current_database() <> 'ai_career_poc' THEN
    RAISE EXCEPTION 'wrong database: %', current_database();
  END IF;
  IF to_regclass('career_migration.schema_migrations') IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM career_migration.schema_migrations WHERE version = '0001') THEN
      RAISE NOTICE 'baseline 0001 already recorded; nothing to check';
      RETURN;
    END IF;
  END IF;
  IF to_regclass('career.users') IS NULL THEN
    RAISE EXCEPTION '0001 schema not found; baseline would be wrong';
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'career'
             AND table_name IN ('market_observations', 'market_forecasts') AND column_name = 'skill_id') THEN
    RAISE EXCEPTION '0003 objects already present; baseline would be wrong';
  END IF;
  IF (SELECT is_nullable FROM information_schema.columns WHERE table_schema = 'career'
      AND table_name = 'account_deletion_requests' AND column_name = 'scheduled_purge_at') IS DISTINCT FROM 'NO' THEN
    RAISE EXCEPTION '0002 already present; baseline would be wrong';
  END IF;
END $guard$;

CREATE SCHEMA IF NOT EXISTS career_migration AUTHORIZATION ai_career_poc;
REVOKE ALL ON SCHEMA career_migration FROM PUBLIC;
GRANT USAGE ON SCHEMA career_migration TO career_reader;

-- Same definition as DRAFT_01_migration_history.sql (the CI rehearsal compares them).
CREATE TABLE IF NOT EXISTS career_migration.schema_migrations (
    version        char(4)      PRIMARY KEY,
    name           varchar(120) NOT NULL,
    checksum       char(64)     NOT NULL,
    target_env     varchar(16)  NOT NULL,
    approval_ref   varchar(64),
    applied_by     text         NOT NULL DEFAULT session_user,
    applied_at     timestamptz  NOT NULL DEFAULT now(),
    execution_ms   integer      NOT NULL,
    runner_version varchar(16)  NOT NULL,
    CONSTRAINT schema_migrations_version_digits CHECK (version ~ '^[0-9]{4}$'),
    CONSTRAINT schema_migrations_checksum_hex CHECK (checksum ~ '^[0-9a-f]{64}$'),
    CONSTRAINT schema_migrations_target_env CHECK (target_env IN ('local', 'ci', 'staging')),
    CONSTRAINT schema_migrations_staging_approval
        CHECK (target_env <> 'staging' OR approval_ref IS NOT NULL)
);
ALTER TABLE career_migration.schema_migrations OWNER TO ai_career_poc;
REVOKE ALL ON career_migration.schema_migrations FROM PUBLIC;
GRANT SELECT ON career_migration.schema_migrations TO career_reader;

-- 0001 was created outside the runner. Record it as a baseline, not as an execution.
INSERT INTO career_migration.schema_migrations
    (version, name, checksum, target_env, approval_ref, execution_ms, runner_version)
VALUES ('0001', 'initial_schema', :'baseline_checksum', 'staging', :'approval', 0, 'baseline')
ON CONFLICT (version) DO NOTHING;

COMMIT;
