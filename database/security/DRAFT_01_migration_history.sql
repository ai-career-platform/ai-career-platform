-- T08: DRAFT. Migration history (schema ledger) bootstrap.
-- Run as an authorized DB administrator AFTER DRAFT_00_create_roles_schema.sql
-- and BEFORE the first `python database/migrate.py apply`.
-- Idempotent: safe to re-run. Contains no passwords and no LOGIN principals.
--
-- Why a separate schema?
--   career_app receives default CRUD privileges on every table that
--   career_migrator creates in schema "career". The ledger must not be
--   writable by the application, so it lives in "career_migration",
--   which career_app cannot use at all.

BEGIN;

CREATE SCHEMA IF NOT EXISTS career_migration AUTHORIZATION career_migrator;
REVOKE ALL ON SCHEMA career_migration FROM PUBLIC;
GRANT USAGE ON SCHEMA career_migration TO career_reader;

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

ALTER TABLE career_migration.schema_migrations OWNER TO career_migrator;
REVOKE ALL ON career_migration.schema_migrations FROM PUBLIC;
GRANT SELECT ON career_migration.schema_migrations TO career_reader;

COMMIT;
