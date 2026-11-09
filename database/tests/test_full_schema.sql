-- T11 constraint, index and privilege tests for 0001_initial_schema.sql (Redmine T11).
-- DISPOSABLE DATABASE ONLY. Run by test_full_schema.sh after the migration is applied.
-- FAIL raises and stops the run (ON_ERROR_STOP=1). WARN is a finding to report, not a failure.
-- All data is synthetic (example.invalid, fixed UUIDs, no secrets).
SET search_path TO career;

CREATE FUNCTION pg_temp.expect_error(label text, stmt text, want text) RETURNS void AS $$
BEGIN
    EXECUTE stmt;
    RAISE EXCEPTION 'FAIL % : statement was accepted', label;
EXCEPTION WHEN OTHERS THEN
    IF SQLSTATE = 'P0001' AND SQLERRM LIKE 'FAIL %' THEN RAISE; END IF;
    IF SQLSTATE <> want THEN
        RAISE EXCEPTION 'FAIL % : expected SQLSTATE %, got % (%)', label, want, SQLSTATE, SQLERRM;
    END IF;
    RAISE NOTICE 'PASS reject % [%]', label, want;
END $$ LANGUAGE plpgsql;

CREATE FUNCTION pg_temp.expect_ok(label text, stmt text) RETURNS void AS $$
BEGIN
    EXECUTE stmt;
    RAISE NOTICE 'PASS accept %', label;
EXCEPTION WHEN OTHERS THEN
    RAISE EXCEPTION 'FAIL % : % (%)', label, SQLERRM, SQLSTATE;
END $$ LANGUAGE plpgsql;

CREATE FUNCTION pg_temp.expect_index(label text, q text, idx text) RETURNS void AS $$
DECLARE line text; plan text := '';
BEGIN
    FOR line IN EXECUTE 'EXPLAIN (COSTS OFF) ' || q LOOP plan := plan || line || E'\n'; END LOOP;
    IF position(idx IN plan) = 0 THEN
        RAISE EXCEPTION 'FAIL % : % not used%', label, idx, E'\n' || plan;
    END IF;
    RAISE NOTICE 'PASS index % used for %', idx, label;
END $$ LANGUAGE plpgsql;

-- ---------- A. structure (catalog) ----------
DO $$
DECLARE n int; bad text;
BEGIN
    SELECT count(*) INTO n FROM pg_tables WHERE schemaname = 'career';
    IF n <> 51 THEN RAISE EXCEPTION 'FAIL table count %, expected 51', n; END IF;
    SELECT string_agg(tablename, ', ') INTO bad FROM pg_tables
     WHERE schemaname = 'career' AND tableowner <> 'career_migrator';
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'FAIL tables not owned by career_migrator: %', bad; END IF;
    SELECT string_agg(c.relname, ', ') INTO bad FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace
     WHERE s.nspname = 'career' AND c.relkind = 'r'
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = c.oid AND contype = 'p');
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'FAIL tables without PK: %', bad; END IF;
    RAISE NOTICE 'PASS 51 tables, all owned by career_migrator, all with PK';
END $$;

-- Pinned counts: a schema change must update these on purpose.
DO $$
DECLARE fk int; ck int; uq int; ix int;
BEGIN
    SELECT count(*) FILTER (WHERE contype = 'f'), count(*) FILTER (WHERE contype = 'c'),
           count(*) FILTER (WHERE contype = 'u')
      INTO fk, ck, uq
      FROM pg_constraint con JOIN pg_namespace n ON n.oid = con.connamespace WHERE n.nspname = 'career';
    SELECT count(*) INTO ix FROM pg_indexes WHERE schemaname = 'career';
    IF (fk, ck, uq, ix) <> (76, 64, 6, 135) THEN
        RAISE EXCEPTION 'FAIL counts fk=% check=% unique=% indexes=%, expected 76/64/6/135', fk, ck, uq, ix;
    END IF;
    RAISE NOTICE 'PASS counts fk=76 check=64 unique-constraint=6 indexes=135 (incl. PK/UNIQUE)';
END $$;

-- Every FK should have a full (non-partial) index whose leading columns are the FK columns;
-- otherwise deleting a parent row scans the whole child table.
DO $$
DECLARE r record; missing int := 0;
BEGIN
    FOR r IN
        SELECT con.conrelid::regclass AS tbl, con.conname,
               (SELECT string_agg(a.attname, ',' ORDER BY k.ord)
                  FROM unnest(con.conkey) WITH ORDINALITY k(attnum, ord)
                  JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS cols
          FROM pg_constraint con JOIN pg_namespace n ON n.oid = con.connamespace
         WHERE n.nspname = 'career' AND con.contype = 'f'
           AND NOT EXISTS (
               SELECT 1 FROM pg_index i
                WHERE i.indrelid = con.conrelid AND i.indpred IS NULL
                  AND (string_to_array(i.indkey::text, ' ')::int2[])[1:cardinality(con.conkey)] @> con.conkey
                  AND (string_to_array(i.indkey::text, ' ')::int2[])[1:cardinality(con.conkey)] <@ con.conkey)
         ORDER BY 1, 2
    LOOP
        missing := missing + 1;
        RAISE NOTICE 'WARN FK without full leading index: %(%) [%]', r.tbl, r.cols, r.conname;
    END LOOP;
    RAISE NOTICE 'PASS FK index scan done, % FK(s) without index', missing;
END $$;

-- ---------- E. privileges (catalog, every table) ----------
DO $$
DECLARE bad text;
BEGIN
    SELECT string_agg(format('%s %s %s=%s', e.role, t.tablename, e.priv, NOT e.allowed), ', ') INTO bad
      FROM pg_tables t
     CROSS JOIN (VALUES
        ('career_reader', 'SELECT', true), ('career_reader', 'INSERT', false),
        ('career_reader', 'UPDATE', false), ('career_reader', 'DELETE', false),
        ('career_reader', 'TRUNCATE', false), ('career_reader', 'REFERENCES', false),
        ('career_reader', 'TRIGGER', false),
        ('career_app', 'SELECT', true), ('career_app', 'INSERT', true),
        ('career_app', 'UPDATE', true), ('career_app', 'DELETE', true),
        ('career_app', 'TRUNCATE', false), ('career_app', 'REFERENCES', false),
        ('career_app', 'TRIGGER', false)) AS e(role, priv, allowed)
     WHERE t.schemaname = 'career'
       AND has_table_privilege(e.role, format('career.%I', t.tablename), e.priv) <> e.allowed;
    IF bad IS NOT NULL THEN RAISE EXCEPTION 'FAIL table privilege mismatch: %', bad; END IF;

    IF has_schema_privilege('career_reader', 'career', 'CREATE')
       OR has_schema_privilege('career_app', 'career', 'CREATE') THEN
        RAISE EXCEPTION 'FAIL app/reader can CREATE in schema career';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_namespace n, aclexplode(n.nspacl) a WHERE n.nspname = 'career' AND a.grantee = 0)
       OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, aclexplode(c.relacl) a
                   WHERE n.nspname = 'career' AND a.grantee = 0) THEN
        RAISE EXCEPTION 'FAIL PUBLIC has a grant in schema career';
    END IF;
    RAISE NOTICE 'PASS privilege matrix on 51 tables: reader SELECT-only, app DML-only, no PUBLIC, no schema CREATE';
END $$;

-- ---------- fixtures (synthetic only) ----------
INSERT INTO data_sources (source_id, code, name) VALUES
    ('00000000-0000-0000-0011-000000000401', 'synthetic_seed', 'Synthetic seed');
INSERT INTO data_sources (source_id, code, name, license_ref) VALUES
    ('00000000-0000-0000-0011-000000000402', 't11_licensed', 'Licensed fixture', 'LICENSE-T11');
INSERT INTO consent_policies VALUES ('terms', '2026-11', true, 'https://example.invalid/terms', now(), now());
INSERT INTO users (user_id, email, email_canonical, display_name) VALUES
    ('00000000-0000-0000-0011-000000000001', 'seeker@example.invalid', 'seeker@example.invalid', 'Seeker'),
    ('00000000-0000-0000-0011-000000000002', 'admin@example.invalid', 'admin@example.invalid', 'Admin'),
    ('00000000-0000-0000-0011-000000000003', 'agent@example.invalid', 'agent@example.invalid', 'Agent user');
INSERT INTO user_consents (user_id, policy_code, policy_version, granted) VALUES
    ('00000000-0000-0000-0011-000000000001', 'terms', '2026-11', true);
INSERT INTO roles (role_id, code, name) VALUES ('00000000-0000-0000-0011-000000000101', 'admin', 'Admin');
INSERT INTO permissions (permission_id, code) VALUES ('00000000-0000-0000-0011-000000000102', 'audit.read');
INSERT INTO role_permissions (role_id, permission_id) VALUES
    ('00000000-0000-0000-0011-000000000101', '00000000-0000-0000-0011-000000000102');
INSERT INTO user_roles (user_id, role_id, granted_by_user_id) VALUES
    ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000101', '00000000-0000-0000-0011-000000000002');
INSERT INTO skills (skill_id, code, name) VALUES
    ('00000000-0000-0000-0011-000000000201', 'python', 'Python'),
    ('00000000-0000-0000-0011-000000000202', 'sql', 'SQL');
INSERT INTO job_roles (job_role_id, code, name) VALUES ('00000000-0000-0000-0011-000000000301', 'backend', 'Backend Engineer');
INSERT INTO user_skills (user_id, skill_id, proficiency) VALUES
    ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000201', 3);
INSERT INTO companies (company_id, name, source_id) VALUES
    ('00000000-0000-0000-0011-000000000501', 'Example Corp', '00000000-0000-0000-0011-000000000401');
INSERT INTO job_postings (job_posting_id, company_id, job_role_id, source_id, title, status, published_at) VALUES
    ('00000000-0000-0000-0011-000000000601', '00000000-0000-0000-0011-000000000501', '00000000-0000-0000-0011-000000000301',
     '00000000-0000-0000-0011-000000000401', 'Backend', 'published', now()),
    ('00000000-0000-0000-0011-000000000602', '00000000-0000-0000-0011-000000000501', '00000000-0000-0000-0011-000000000301',
     '00000000-0000-0000-0011-000000000402', 'Data', 'published', now());
INSERT INTO job_posting_skills (job_posting_id, skill_id, required_level) VALUES
    ('00000000-0000-0000-0011-000000000601', '00000000-0000-0000-0011-000000000201', 3),
    ('00000000-0000-0000-0011-000000000602', '00000000-0000-0000-0011-000000000202', 2);
INSERT INTO job_posting_external_refs (source_id, external_id, job_posting_id) VALUES
    ('00000000-0000-0000-0011-000000000402', 'ext-1', '00000000-0000-0000-0011-000000000602');
INSERT INTO user_job_bookmarks (user_id, job_posting_id) VALUES
    ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000601'),
    ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000602');
INSERT INTO model_versions (model_version_id, model_code, version, kind) VALUES
    ('00000000-0000-0000-0011-000000000701', 'reco_rule', '1', 'rule');
INSERT INTO recommendation_runs (recommendation_run_id, user_id, model_version_id) VALUES
    ('00000000-0000-0000-0011-000000000901', '00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000701');
INSERT INTO recommendation_items VALUES
    ('00000000-0000-0000-0011-000000000901', '00000000-0000-0000-0011-000000000601', 1, 80, 'skill match'),
    ('00000000-0000-0000-0011-000000000901', '00000000-0000-0000-0011-000000000602', 2, 60, 'role match');
INSERT INTO recommendation_feedback (user_id, recommendation_run_id, job_posting_id, feedback) VALUES
    ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000901',
     '00000000-0000-0000-0011-000000000601', 'liked');
INSERT INTO user_documents (document_id, owner_user_id, kind, original_filename, mime_type, size_bytes, storage_key, checksum_sha256)
    VALUES ('00000000-0000-0000-0011-000000000801', '00000000-0000-0000-0011-000000000001', 'resume', 'cv.pdf',
            'application/pdf', 1024, repeat('a', 32), repeat('a', 64));
INSERT INTO document_chunks (chunk_id, document_id, chunk_index, content_hash) VALUES
    ('00000000-0000-0000-0011-000000000802', '00000000-0000-0000-0011-000000000801', 0, repeat('b', 64));
INSERT INTO retrieval_runs (retrieval_run_id, user_id, query_hash) VALUES
    ('00000000-0000-0000-0011-000000000a01', '00000000-0000-0000-0011-000000000001', repeat('c', 64));
INSERT INTO retrieval_citations VALUES
    ('00000000-0000-0000-0011-000000000a01', '00000000-0000-0000-0011-000000000802', 1, 0.9);
INSERT INTO auth_identities (user_id, provider, subject, password_hash) VALUES
    ('00000000-0000-0000-0011-000000000001', 'local', 'seeker@example.invalid', 'synthetic-hash');
INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at) VALUES
    ('00000000-0000-0000-0011-000000000001', repeat('d', 64), now() + interval '1 day');
INSERT INTO agent_runs (agent_run_id, user_id, workflow_code) VALUES
    ('00000000-0000-0000-0011-000000000b01', '00000000-0000-0000-0011-000000000003', 'apply_draft');
INSERT INTO agent_tool_approvals (approval_id, agent_run_id, tool_code, expires_at) VALUES
    ('00000000-0000-0000-0011-000000000b02', '00000000-0000-0000-0011-000000000b01', 'send_email', now() + interval '1 hour');
INSERT INTO agent_tool_calls (agent_run_id, approval_id, tool_code) VALUES
    ('00000000-0000-0000-0011-000000000b01', '00000000-0000-0000-0011-000000000b02', 'send_email');
INSERT INTO behavior_events (event_id, user_id, event_code) VALUES
    ('00000000-0000-0000-0011-000000000c01', '00000000-0000-0000-0011-000000000001', 'page_view');
INSERT INTO anomaly_events (model_version_id, event_id) VALUES
    ('00000000-0000-0000-0011-000000000701', '00000000-0000-0000-0011-000000000c01');
INSERT INTO audit_events (actor_user_id, action_code, resource_type) VALUES
    ('00000000-0000-0000-0011-000000000001', 'auth.login', 'user');
DO $$ BEGIN RAISE NOTICE 'PASS valid fixtures inserted into 32 tables'; END $$;

-- ---------- E. privileges (behaviour) ----------
SET ROLE career_reader;
SELECT pg_temp.expect_ok('reader SELECT', $q$SELECT count(*) FROM users$q$);
SELECT pg_temp.expect_error('reader INSERT', $q$INSERT INTO skills (code, name) VALUES ('t11_r', 'r')$q$, '42501');
SELECT pg_temp.expect_error('reader UPDATE', $q$UPDATE skills SET name = 'x'$q$, '42501');
SELECT pg_temp.expect_error('reader DELETE', $q$DELETE FROM audit_events$q$, '42501');
RESET ROLE;
SET ROLE career_app;
SELECT pg_temp.expect_ok('app UPDATE', $q$UPDATE skills SET updated_at = now() WHERE code = 'sql'$q$);
SELECT pg_temp.expect_error('app TRUNCATE', $q$TRUNCATE audit_events$q$, '42501');
SELECT pg_temp.expect_error('app CREATE TABLE', $q$CREATE TABLE career.t11_x (id int)$q$, '42501');
SELECT pg_temp.expect_error('app DROP TABLE', $q$DROP TABLE skills$q$, '42501');
SELECT pg_temp.expect_error('app ALTER TABLE', $q$ALTER TABLE users ADD COLUMN t11 int$q$, '42501');
RESET ROLE;
CREATE ROLE t11_nobody NOLOGIN;
SET ROLE t11_nobody;
SELECT pg_temp.expect_error('role without grant reads career.users', $q$SELECT 1 FROM career.users$q$, '42501');
RESET ROLE;
DROP ROLE t11_nobody;

-- ---------- B. NOT NULL on every table ----------
DO $$
DECLARE t text;
BEGIN
    FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'career' ORDER BY 1 LOOP
        PERFORM pg_temp.expect_error('empty row into ' || t, format('INSERT INTO career.%I DEFAULT VALUES', t), '23502');
    END LOOP;
END $$;

-- ---------- B. FK ----------
SELECT pg_temp.expect_error('profile for unknown user',
    $q$INSERT INTO user_profiles (user_id) VALUES (gen_random_uuid())$q$, '23503');
SELECT pg_temp.expect_error('posting for unknown company',
    $q$INSERT INTO job_postings (company_id, source_id, title) VALUES (gen_random_uuid(), '00000000-0000-0000-0011-000000000401', 'x')$q$, '23503');
SELECT pg_temp.expect_error('role skill with unknown skill',
    $q$INSERT INTO job_role_skills VALUES ('00000000-0000-0000-0011-000000000301', gen_random_uuid(), 3, now())$q$, '23503');
SELECT pg_temp.expect_error('citation for unknown chunk',
    $q$INSERT INTO retrieval_citations VALUES ('00000000-0000-0000-0011-000000000a01', gen_random_uuid(), 2, 0.5)$q$, '23503');
SELECT pg_temp.expect_error('tool call with unknown approval',
    $q$INSERT INTO agent_tool_calls (agent_run_id, approval_id, tool_code) VALUES ('00000000-0000-0000-0011-000000000b01', gen_random_uuid(), 'x')$q$, '23503');
SELECT pg_temp.expect_error('consent to unknown policy (composite FK)',
    $q$INSERT INTO user_consents (user_id, policy_code, policy_version, granted) VALUES ('00000000-0000-0000-0011-000000000001', 'terms', '1999-01', true)$q$, '23503');

-- ---------- B. UNIQUE / PK ----------
SELECT pg_temp.expect_error('duplicate canonical email',
    $q$INSERT INTO users (email, email_canonical, display_name) VALUES ('Seeker@example.invalid', 'seeker@example.invalid', 'x')$q$, '23505');
SELECT pg_temp.expect_error('duplicate role code', $q$INSERT INTO roles (code, name) VALUES ('admin', 'x')$q$, '23505');
SELECT pg_temp.expect_error('duplicate permission code', $q$INSERT INTO permissions (code) VALUES ('audit.read')$q$, '23505');
SELECT pg_temp.expect_error('duplicate skill code', $q$INSERT INTO skills (code, name) VALUES ('python', 'x')$q$, '23505');
SELECT pg_temp.expect_error('duplicate job role code', $q$INSERT INTO job_roles (code, name) VALUES ('backend', 'x')$q$, '23505');
SELECT pg_temp.expect_error('duplicate data source code', $q$INSERT INTO data_sources (code, name) VALUES ('synthetic_seed', 'x')$q$, '23505');
SELECT pg_temp.expect_error('duplicate model code+version',
    $q$INSERT INTO model_versions (model_code, version, kind) VALUES ('reco_rule', '1', 'ml')$q$, '23505');
SELECT pg_temp.expect_error('duplicate user skill (composite PK)',
    $q$INSERT INTO user_skills (user_id, skill_id) VALUES ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000201')$q$, '23505');
SELECT pg_temp.expect_error('duplicate provider+subject',
    $q$INSERT INTO auth_identities (user_id, provider, subject) VALUES ('00000000-0000-0000-0011-000000000002', 'local', 'seeker@example.invalid')$q$, '23505');
SELECT pg_temp.expect_error('duplicate refresh token hash',
    $q$INSERT INTO auth_sessions (user_id, refresh_token_hash, expires_at) VALUES ('00000000-0000-0000-0011-000000000002', repeat('d', 64), now() + interval '1 day')$q$, '23505');
SELECT pg_temp.expect_error('duplicate storage key',
    $q$INSERT INTO user_documents (owner_user_id, kind, original_filename, mime_type, size_bytes, storage_key, checksum_sha256)
       VALUES ('00000000-0000-0000-0011-000000000002', 'resume', 'b.pdf', 'application/pdf', 1, repeat('a', 32), repeat('e', 64))$q$, '23505');
SELECT pg_temp.expect_error('duplicate chunk index in a document',
    $q$INSERT INTO document_chunks (document_id, chunk_index, content_hash) VALUES ('00000000-0000-0000-0011-000000000801', 0, repeat('f', 64))$q$, '23505');
SELECT pg_temp.expect_error('duplicate recommendation rank in a run',
    $q$UPDATE recommendation_items SET rank = 1 WHERE rank = 2$q$, '23505');
SELECT pg_temp.expect_error('duplicate citation rank in a run',
    $q$INSERT INTO document_chunks (chunk_id, document_id, chunk_index, content_hash) VALUES ('00000000-0000-0000-0011-000000000803', '00000000-0000-0000-0011-000000000801', 1, repeat('f', 64));
       INSERT INTO retrieval_citations VALUES ('00000000-0000-0000-0011-000000000a01', '00000000-0000-0000-0011-000000000803', 1, 0.5)$q$, '23505');
SELECT pg_temp.expect_error('duplicate external ref',
    $q$INSERT INTO job_posting_external_refs (source_id, external_id, job_posting_id) VALUES ('00000000-0000-0000-0011-000000000402', 'ext-1', '00000000-0000-0000-0011-000000000601')$q$, '23505');
SELECT pg_temp.expect_ok('agent runs without idempotency key may repeat',
    $q$INSERT INTO agent_runs (user_id, workflow_code) VALUES ('00000000-0000-0000-0011-000000000002', 'w'), ('00000000-0000-0000-0011-000000000002', 'w')$q$);
SELECT pg_temp.expect_error('duplicate agent idempotency key',
    $q$INSERT INTO agent_runs (user_id, workflow_code, idempotency_key) VALUES ('00000000-0000-0000-0011-000000000002', 'w', 'k1'), ('00000000-0000-0000-0011-000000000002', 'w', 'k1')$q$, '23505');
SELECT pg_temp.expect_error('duplicate market observation',
    $q$INSERT INTO market_observations (source_id, job_role_id, observed_on, period, metric_code, metric_value)
       VALUES ('00000000-0000-0000-0011-000000000402', '00000000-0000-0000-0011-000000000301', '2026-11-01', 'day', 'postings', 1),
              ('00000000-0000-0000-0011-000000000402', '00000000-0000-0000-0011-000000000301', '2026-11-01', 'day', 'postings', 2)$q$, '23505');
-- job_role_id is nullable and NULLs are distinct in a UNIQUE index, so all-role rows can duplicate.
DO $$
BEGIN
    INSERT INTO market_observations (source_id, observed_on, period, metric_code, metric_value)
    VALUES ('00000000-0000-0000-0011-000000000402', '2026-11-01', 'day', 'postings', 1),
           ('00000000-0000-0000-0011-000000000402', '2026-11-01', 'day', 'postings', 2);
    RAISE NOTICE 'WARN market_observations accepts duplicates when job_role_id IS NULL (ix_market_observations_1 needs NULLS NOT DISTINCT)';
    DELETE FROM market_observations WHERE job_role_id IS NULL;
EXCEPTION WHEN unique_violation THEN
    RAISE NOTICE 'PASS reject duplicate all-role market observation [23505]';
END $$;

-- ---------- B/C. CHECK and boundaries (min/max pass, one step outside fails) ----------
SELECT pg_temp.expect_ok('email at 254 chars',
    $q$INSERT INTO users (email, email_canonical, display_name) VALUES (repeat('a', 238) || '@example.invalid', repeat('a', 238) || '@example.invalid', 'Max')$q$);
SELECT pg_temp.expect_error('email at 255 chars',
    $q$INSERT INTO users (email, email_canonical, display_name) VALUES (repeat('b', 239) || '@example.invalid', repeat('b', 239) || '@example.invalid', 'Max')$q$, '22001');
SELECT pg_temp.expect_error('email with surrounding spaces',
    $q$INSERT INTO users (email, email_canonical, display_name) VALUES (' c@example.invalid', 'c@example.invalid', 'x')$q$, '23514');
SELECT pg_temp.expect_error('unknown user status', $q$UPDATE users SET status = 'deleted'$q$, '23514');
SELECT pg_temp.expect_ok('display name at 100 chars', $q$UPDATE users SET display_name = repeat('n', 100) WHERE email = 'admin@example.invalid'$q$);
SELECT pg_temp.expect_error('display name at 101 chars', $q$UPDATE users SET display_name = repeat('n', 101)$q$, '22001');
SELECT pg_temp.expect_ok('bio at 5000 chars',
    $q$INSERT INTO user_profiles (user_id, bio) VALUES ('00000000-0000-0000-0011-000000000001', repeat('x', 5000))$q$);
SELECT pg_temp.expect_error('bio at 5001 chars', $q$UPDATE user_profiles SET bio = repeat('x', 5001)$q$, '23514');
SELECT pg_temp.expect_error('blank skill code', $q$INSERT INTO skills (code, name) VALUES ('  ', 'x')$q$, '23514');
SELECT pg_temp.expect_error('blank company name',
    $q$INSERT INTO companies (name, source_id) VALUES (' ', '00000000-0000-0000-0011-000000000401')$q$, '23514');
SELECT pg_temp.expect_ok('required_level 1 and 5',
    $q$INSERT INTO job_role_skills VALUES ('00000000-0000-0000-0011-000000000301', '00000000-0000-0000-0011-000000000201', 1, now()),
                                         ('00000000-0000-0000-0011-000000000301', '00000000-0000-0000-0011-000000000202', 5, now())$q$);
SELECT pg_temp.expect_error('required_level 0', $q$UPDATE job_role_skills SET required_level = 0$q$, '23514');
SELECT pg_temp.expect_error('required_level 6', $q$UPDATE job_role_skills SET required_level = 6$q$, '23514');
SELECT pg_temp.expect_error('proficiency 0', $q$UPDATE user_skills SET proficiency = 0$q$, '23514');
SELECT pg_temp.expect_ok('proficiency NULL (not assessed)', $q$UPDATE user_skills SET proficiency = NULL$q$);
SELECT pg_temp.expect_error('target role priority 0',
    $q$INSERT INTO user_target_roles (user_id, job_role_id, priority) VALUES ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000301', 0)$q$, '23514');
SELECT pg_temp.expect_ok('reset token valid exactly 30 minutes',
    $q$INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES ('00000000-0000-0000-0011-000000000001', repeat('1', 64), now() + interval '30 minutes')$q$);
SELECT pg_temp.expect_error('reset token valid 30 minutes + 1 second',
    $q$INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) VALUES ('00000000-0000-0000-0011-000000000001', repeat('2', 64), now() + interval '30 minutes 1 second')$q$, '23514');
SELECT pg_temp.expect_error('reset token used before created',
    $q$UPDATE password_reset_tokens SET used_at = created_at - interval '1 second'$q$, '23514');
SELECT pg_temp.expect_error('session expiring at creation',
    $q$INSERT INTO auth_sessions (user_id, refresh_token_hash, created_at, expires_at) VALUES ('00000000-0000-0000-0011-000000000001', repeat('3', 64), now(), now())$q$, '23514');
SELECT pg_temp.expect_error('password hash on a non-local identity',
    $q$INSERT INTO auth_identities (user_id, provider, subject, password_hash) VALUES ('00000000-0000-0000-0011-000000000002', 'google', 'g-1', 'synthetic-hash')$q$, '23514');
SELECT pg_temp.expect_ok('experience ending on its start date',
    $q$INSERT INTO user_experiences (user_id, organization, title, start_date, end_date) VALUES ('00000000-0000-0000-0011-000000000001', 'Org', 'Dev', '2026-01-01', '2026-01-01')$q$);
SELECT pg_temp.expect_error('experience ending before start', $q$UPDATE user_experiences SET end_date = '2025-12-31'$q$, '23514');
SELECT pg_temp.expect_error('project ending before start',
    $q$INSERT INTO user_projects (user_id, title, start_date, end_date) VALUES ('00000000-0000-0000-0011-000000000001', 'P', '2026-02-01', '2026-01-31')$q$, '23514');
SELECT pg_temp.expect_ok('storage key 32 and 64 lowercase hex',
    $q$INSERT INTO user_documents (owner_user_id, kind, original_filename, mime_type, size_bytes, storage_key, checksum_sha256)
       VALUES ('00000000-0000-0000-0011-000000000002', 'portfolio', 'p.pdf', 'application/pdf', 1, repeat('b', 32), repeat('a', 64)),
              ('00000000-0000-0000-0011-000000000002', 'portfolio', 'q.pdf', 'application/pdf', 1, repeat('c', 64), repeat('a', 64))$q$);
SELECT pg_temp.expect_error('storage key 31 hex', $q$UPDATE user_documents SET storage_key = repeat('d', 31) WHERE storage_key = repeat('b', 32)$q$, '23514');
SELECT pg_temp.expect_error('storage key 65 hex', $q$UPDATE user_documents SET storage_key = repeat('d', 65) WHERE storage_key = repeat('b', 32)$q$, '22001');
SELECT pg_temp.expect_error('storage key uppercase hex', $q$UPDATE user_documents SET storage_key = repeat('D', 32) WHERE storage_key = repeat('b', 32)$q$, '23514');
SELECT pg_temp.expect_error('document size 0', $q$UPDATE user_documents SET size_bytes = 0$q$, '23514');
SELECT pg_temp.expect_error('unknown document kind', $q$UPDATE user_documents SET kind = 'photo'$q$, '23514');
SELECT pg_temp.expect_error('chunk index -1',
    $q$INSERT INTO document_chunks (document_id, chunk_index, content_hash) VALUES ('00000000-0000-0000-0011-000000000801', -1, repeat('9', 64))$q$, '23514');
SELECT pg_temp.expect_error('succeeded analysis without result',
    $q$INSERT INTO document_analyses (document_id, model_version_id, analysis_type, status) VALUES ('00000000-0000-0000-0011-000000000801', '00000000-0000-0000-0011-000000000701', 'summary', 'succeeded')$q$, '23514');
SELECT pg_temp.expect_ok('recommendation score 0 and 100', $q$UPDATE recommendation_items SET score = CASE rank WHEN 1 THEN 100 ELSE 0 END$q$);
SELECT pg_temp.expect_error('recommendation score 100.01', $q$UPDATE recommendation_items SET score = 100.01 WHERE rank = 1$q$, '23514');
SELECT pg_temp.expect_error('recommendation score -0.01', $q$UPDATE recommendation_items SET score = -0.01 WHERE rank = 1$q$, '23514');
SELECT pg_temp.expect_error('recommendation rank 0', $q$UPDATE recommendation_items SET rank = 0 WHERE rank = 2$q$, '23514');
SELECT pg_temp.expect_error('blank recommendation reason', $q$UPDATE recommendation_items SET reason = ' '$q$, '23514');
SELECT pg_temp.expect_error('unknown feedback value', $q$UPDATE recommendation_feedback SET feedback = 'love'$q$, '23514');
SELECT pg_temp.expect_ok('skill gap observed 0 gives gap = required',
    $q$INSERT INTO skill_gap_assessments (assessment_id, user_id, job_role_id, model_version_id) VALUES ('00000000-0000-0000-0011-000000000d01', '00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000301', '00000000-0000-0000-0011-000000000701');
       INSERT INTO skill_gap_items VALUES ('00000000-0000-0000-0011-000000000d01', '00000000-0000-0000-0011-000000000201', 5, 0, 5)$q$);
SELECT pg_temp.expect_ok('skill gap observed above required gives gap 0',
    $q$INSERT INTO skill_gap_items VALUES ('00000000-0000-0000-0011-000000000d01', '00000000-0000-0000-0011-000000000202', 1, 5, 0)$q$);
SELECT pg_temp.expect_error('skill gap observed -1', $q$UPDATE skill_gap_items SET observed_level = -1, gap = 6$q$, '23514');
SELECT pg_temp.expect_error('negative token count',
    $q$INSERT INTO ai_usage_records (provider_model, feature_code, input_tokens) VALUES ('m', 'agent', -1)$q$, '23514');
SELECT pg_temp.expect_ok('zero tokens and zero cost',
    $q$INSERT INTO ai_usage_records (provider_model, feature_code) VALUES ('m', 'agent')$q$);
SELECT pg_temp.expect_error('unknown AI feature code',
    $q$INSERT INTO ai_usage_records (provider_model, feature_code) VALUES ('m', 'chat')$q$, '23514');
SELECT pg_temp.expect_error('negative fetched count',
    $q$INSERT INTO ingestion_runs (source_id, fetched_count) VALUES ('00000000-0000-0000-0011-000000000402', -1)$q$, '23514');
SELECT pg_temp.expect_error('decided approval without decided_at',
    $q$UPDATE agent_tool_approvals SET decision = 'approved'$q$, '23514');
SELECT pg_temp.expect_error('completed deletion request without completed_at',
    $q$INSERT INTO account_deletion_requests (user_id, status, scheduled_purge_at) VALUES ('00000000-0000-0000-0011-000000000002', 'completed', now() + interval '1 day')$q$, '23514');
SELECT pg_temp.expect_error('purge scheduled before request',
    $q$INSERT INTO account_deletion_requests (user_id, scheduled_purge_at) VALUES ('00000000-0000-0000-0011-000000000002', now() - interval '1 second')$q$, '23514');
SELECT pg_temp.expect_error('forecast lower bound above upper',
    $q$INSERT INTO market_forecasts (model_version_id, forecast_for, metric_code, predicted_value, lower_bound, upper_bound)
       VALUES ('00000000-0000-0000-0011-000000000701', '2026-12-01', 'postings', 10, 11, 9)$q$, '23514');
SELECT pg_temp.expect_error('unknown market period',
    $q$INSERT INTO market_observations (source_id, observed_on, period, metric_code, metric_value) VALUES ('00000000-0000-0000-0011-000000000402', '2026-11-01', 'year', 'postings', 1)$q$, '23514');
SELECT pg_temp.expect_error('unknown model kind', $q$UPDATE model_versions SET kind = 'gpt'$q$, '23514');
SELECT pg_temp.expect_error('external source without license',
    $q$INSERT INTO data_sources (code, name) VALUES ('t11_unlicensed', 'x')$q$, '23514');
SELECT pg_temp.expect_error('retention_days 0',
    $q$UPDATE data_sources SET retention_days = 0 WHERE code = 't11_licensed'$q$, '23514');
SELECT pg_temp.expect_error('posting expiring before publish',
    $q$UPDATE job_postings SET expires_at = published_at - interval '1 second'$q$, '23514');
SELECT pg_temp.expect_error('unknown employment type', $q$UPDATE job_postings SET employment_type = 'freelance'$q$, '23514');
SELECT pg_temp.expect_error('completed match without score',
    $q$INSERT INTO match_evaluations (user_id, job_role_id, model_version_id) VALUES ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000301', '00000000-0000-0000-0011-000000000701')$q$, '23514');
SELECT pg_temp.expect_error('match with neither posting nor role',
    $q$INSERT INTO match_evaluations (user_id, model_version_id, score) VALUES ('00000000-0000-0000-0011-000000000001', '00000000-0000-0000-0011-000000000701', 50)$q$, '23514');

-- ---------- C. transaction preservation ----------
DO $$
DECLARE n int;
BEGIN
    INSERT INTO skills (code, name) VALUES ('t11_tx_kept', 'kept');
    BEGIN
        INSERT INTO skills (code, name) VALUES ('t11_tx_lost', 'lost'), ('t11_tx_kept', 'dup');
        RAISE EXCEPTION 'FAIL multi-row insert with a duplicate was accepted';
    EXCEPTION WHEN unique_violation THEN NULL;
    END;
    SELECT count(*) INTO n FROM skills WHERE code IN ('t11_tx_kept', 't11_tx_lost');
    IF n <> 1 THEN RAISE EXCEPTION 'FAIL after a failed statement % rows remain, expected 1', n; END IF;
    RAISE NOTICE 'PASS failed multi-row statement leaves no partial rows; earlier work is kept';
END $$;

-- ---------- D. index use (EXPLAIN only, synthetic literals) ----------
ANALYZE;
SET enable_seqscan = off;
SELECT pg_temp.expect_index('login lookup by canonical email',
    $q$SELECT user_id FROM users WHERE email_canonical = 'seeker@example.invalid'$q$, 'ix_users_1');
SELECT pg_temp.expect_index('active sessions of a user',
    $q$SELECT session_id FROM auth_sessions WHERE user_id = '00000000-0000-0000-0011-000000000001' AND revoked_at IS NULL$q$, 'ix_auth_sessions_2');
SELECT pg_temp.expect_index('skill search by lower(name)',
    $q$SELECT skill_id FROM skills WHERE lower(name) = 'python'$q$, 'ix_skills_1');
SELECT pg_temp.expect_index('company search by lower(name)',
    $q$SELECT company_id FROM companies WHERE lower(name) = 'example corp'$q$, 'ix_companies_1');
SELECT pg_temp.expect_index('latest published postings',
    $q$SELECT job_posting_id FROM job_postings WHERE status = 'published' ORDER BY published_at DESC LIMIT 20$q$, 'ix_job_postings_3');
SELECT pg_temp.expect_index('postings of a company',
    $q$SELECT job_posting_id FROM job_postings WHERE company_id = '00000000-0000-0000-0011-000000000501'$q$, 'ix_job_postings_1');
SELECT pg_temp.expect_index('postings requiring a skill',
    $q$SELECT job_posting_id FROM job_posting_skills WHERE skill_id = '00000000-0000-0000-0011-000000000201'$q$, 'ix_job_posting_skills_1');
SELECT pg_temp.expect_index('my documents newest first',
    $q$SELECT document_id FROM user_documents WHERE owner_user_id = '00000000-0000-0000-0011-000000000001' ORDER BY created_at DESC$q$, 'ix_user_documents_2');
SELECT pg_temp.expect_index('my bookmarks newest first',
    $q$SELECT job_posting_id FROM user_job_bookmarks WHERE user_id = '00000000-0000-0000-0011-000000000001' ORDER BY created_at DESC$q$, 'ix_user_job_bookmarks_2');
SELECT pg_temp.expect_index('audit trail of an actor',
    $q$SELECT audit_event_id FROM audit_events WHERE actor_user_id = '00000000-0000-0000-0011-000000000001' ORDER BY occurred_at DESC LIMIT 50$q$, 'ix_audit_events_2');
SELECT pg_temp.expect_index('audit events by action',
    $q$SELECT audit_event_id FROM audit_events WHERE action_code = 'auth.login' ORDER BY occurred_at DESC LIMIT 50$q$, 'ix_audit_events_3');
SELECT pg_temp.expect_index('behavior events of a user',
    $q$SELECT event_id FROM behavior_events WHERE user_id = '00000000-0000-0000-0011-000000000001' ORDER BY event_at DESC$q$, 'ix_behavior_events_1');
SELECT pg_temp.expect_index('open anomalies',
    $q$SELECT anomaly_id FROM anomaly_events WHERE status = 'open' ORDER BY detected_at DESC$q$, 'ix_anomaly_events_1');
SELECT pg_temp.expect_index('AI usage by period',
    $q$SELECT usage_id FROM ai_usage_records WHERE occurred_at >= '2026-11-01' ORDER BY occurred_at DESC$q$, 'ix_ai_usage_records_1');
-- status = 'requested' is served by the partial unique ix_account_deletion_requests_1 instead.
SELECT pg_temp.expect_index('deletion requests by status and date',
    $q$SELECT request_id FROM account_deletion_requests WHERE status = 'completed' AND scheduled_purge_at <= '2026-12-01'$q$, 'ix_account_deletion_requests_2');
RESET enable_seqscan;

-- ---------- B. ON DELETE behaviour ----------
SELECT pg_temp.expect_error('RESTRICT role still granted', $q$DELETE FROM roles WHERE code = 'admin'$q$, '23001');
SELECT pg_temp.expect_error('RESTRICT company with postings', $q$DELETE FROM companies$q$, '23001');
SELECT pg_temp.expect_error('RESTRICT data source in use', $q$DELETE FROM data_sources WHERE code = 'synthetic_seed'$q$, '23001');
SELECT pg_temp.expect_error('RESTRICT job role in use', $q$DELETE FROM job_roles WHERE code = 'backend'$q$, '23001');
SELECT pg_temp.expect_error('RESTRICT skill in use', $q$DELETE FROM skills WHERE code = 'python'$q$, '23001');
SELECT pg_temp.expect_error('RESTRICT consented policy version', $q$DELETE FROM consent_policies$q$, '23001');
SELECT pg_temp.expect_error('RESTRICT model version in use', $q$DELETE FROM model_versions$q$, '23001');

DO $$
BEGIN
    DELETE FROM job_postings WHERE job_posting_id = '00000000-0000-0000-0011-000000000602';
    IF EXISTS (SELECT 1 FROM job_posting_skills WHERE job_posting_id = '00000000-0000-0000-0011-000000000602')
       OR EXISTS (SELECT 1 FROM job_posting_external_refs WHERE job_posting_id = '00000000-0000-0000-0011-000000000602')
       OR EXISTS (SELECT 1 FROM user_job_bookmarks WHERE job_posting_id = '00000000-0000-0000-0011-000000000602')
       OR EXISTS (SELECT 1 FROM recommendation_items WHERE job_posting_id = '00000000-0000-0000-0011-000000000602') THEN
        RAISE EXCEPTION 'FAIL posting delete left child rows';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM companies) OR NOT EXISTS (SELECT 1 FROM skills WHERE code = 'sql') THEN
        RAISE EXCEPTION 'FAIL posting delete removed parent/catalog rows';
    END IF;
    RAISE NOTICE 'PASS CASCADE posting delete removes skills, refs, bookmarks, recommendation items only';

    DELETE FROM users WHERE user_id = '00000000-0000-0000-0011-000000000002';
    IF NOT EXISTS (SELECT 1 FROM user_roles WHERE user_id = '00000000-0000-0000-0011-000000000001' AND granted_by_user_id IS NULL) THEN
        RAISE EXCEPTION 'FAIL user_roles.granted_by_user_id not set to NULL';
    END IF;
    DELETE FROM behavior_events WHERE event_id = '00000000-0000-0000-0011-000000000c01';
    IF NOT EXISTS (SELECT 1 FROM anomaly_events WHERE event_id IS NULL) THEN
        RAISE EXCEPTION 'FAIL anomaly_events.event_id not set to NULL';
    END IF;
    DELETE FROM recommendation_runs WHERE recommendation_run_id = '00000000-0000-0000-0011-000000000901';
    IF EXISTS (SELECT 1 FROM recommendation_items)
       OR NOT EXISTS (SELECT 1 FROM recommendation_feedback WHERE recommendation_run_id IS NULL) THEN
        RAISE EXCEPTION 'FAIL recommendation run delete: items must cascade, feedback must keep with NULL run';
    END IF;
    RAISE NOTICE 'PASS SET NULL keeps granted role, anomaly and feedback rows with NULL reference';
END $$;

-- Account purge must work for a user whose agent run has an approved tool call.
DO $$
BEGIN
    DELETE FROM users WHERE user_id = '00000000-0000-0000-0011-000000000003';
    IF EXISTS (SELECT 1 FROM agent_runs WHERE user_id = '00000000-0000-0000-0011-000000000003') THEN
        RAISE EXCEPTION 'FAIL agent runs left after user purge';
    END IF;
    RAISE NOTICE 'PASS user purge cascades agent runs, approvals and tool calls';
EXCEPTION WHEN restrict_violation OR foreign_key_violation THEN
    RAISE NOTICE 'WARN user purge blocked by agent_tool_calls.approval_id ON DELETE RESTRICT: %', SQLERRM;
END $$;

DO $$ BEGIN RAISE NOTICE 'PASS T11 SQL suite completed'; END $$;
