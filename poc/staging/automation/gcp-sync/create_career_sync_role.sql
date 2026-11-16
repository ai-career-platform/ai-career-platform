-- #337 / GOAL_2: create the dedicated least-privilege sync login on the GCP ai_career_poc database.
-- Run ONCE, with PM approval C, as the Cloud SQL admin user (postgres / cloudsqlsuperuser member),
-- connected to database ai_career_poc. Then run target_grants.sql as the career schema owner.
--
-- The password is NEVER written in this file, a shell argument or a log. Set it interactively:
--   psql ... -d ai_career_poc -f create_career_sync_role.sql
--   psql ... -d ai_career_poc -c '\password career_sync'      (prompts twice, sends a SCRAM hash)
-- or in Cloud Console (SQL > Users) as a built-in user, then run only the ALTER/GRANT parts below.
-- Re-running is harmless.
DO $$ BEGIN
 IF current_database() <> 'ai_career_poc' THEN
  RAISE EXCEPTION 'Connect to ai_career_poc';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_sync') THEN
  CREATE ROLE career_sync LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
 END IF;
END $$;
-- Never a member of an admin role; few sessions; bounded statements.
ALTER ROLE career_sync NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 3;
ALTER ROLE career_sync IN DATABASE ai_career_poc SET statement_timeout = '120s';
ALTER ROLE career_sync IN DATABASE ai_career_poc SET lock_timeout = '10s';
ALTER ROLE career_sync IN DATABASE ai_career_poc SET idle_in_transaction_session_timeout = '60s';
GRANT CONNECT ON DATABASE ai_career_poc TO career_sync;
-- Verification (expect: f,f,f,f and 3):
SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolconnlimit FROM pg_roles WHERE rolname = 'career_sync';
-- Removal (rollback of this file, after DROP OWNED / REVOKE in each database):
--   REVOKE ALL ON ALL TABLES IN SCHEMA career FROM career_sync; REVOKE USAGE ON SCHEMA career FROM career_sync;
--   REVOKE CONNECT ON DATABASE ai_career_poc FROM career_sync; DROP ROLE career_sync;
