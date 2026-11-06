-- D2-4: DRAFT. Test in isolated PostgreSQL only before Staging approval.
-- Run as an authorized DB administrator before DRAFT_0001_initial_schema.sql.
-- Creates NOLOGIN privilege roles; actual LOGIN principals and password provisioning
-- are deliberately out of scope and MUST NOT be embedded in Git.
-- Scope limited to database-scoped schema "career"; existing public untouched.

BEGIN;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_admin') THEN
        CREATE ROLE career_admin NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_migrator') THEN
        CREATE ROLE career_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_app') THEN
        CREATE ROLE career_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_reader') THEN
        CREATE ROLE career_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
END
$$;

-- Prevent default public access to newly created application schema.
CREATE SCHEMA IF NOT EXISTS career AUTHORIZATION career_admin;
REVOKE ALL ON SCHEMA career FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA career TO career_migrator;
GRANT USAGE ON SCHEMA career TO career_app, career_reader;

-- Permissions for tables created by career_migrator in the future.
-- Must be executed by a role authorized to alter career_migrator defaults.
ALTER DEFAULT PRIVILEGES FOR ROLE career_migrator IN SCHEMA career
  GRANT SELECT ON TABLES TO career_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE career_migrator IN SCHEMA career
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO career_app;
COMMIT;
