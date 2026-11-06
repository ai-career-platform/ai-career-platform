-- T05 contract cases for the validation DDL generated from DATA_DICTIONARY.md.
-- DISPOSABLE DATABASE ONLY. Every case raises on failure (ON_ERROR_STOP=1).
SET search_path TO career;

CREATE FUNCTION pg_temp.expect_error(label text, stmt text) RETURNS void AS $$
BEGIN
    EXECUTE stmt;
    RAISE EXCEPTION 'FAIL % : statement was accepted', label;
EXCEPTION
    WHEN check_violation OR foreign_key_violation OR unique_violation OR not_null_violation THEN
        RAISE NOTICE 'PASS reject %', label;
END $$ LANGUAGE plpgsql;

-- ---------- fixtures (synthetic only) ----------
INSERT INTO data_sources (source_id, code, name) VALUES
    ('00000000-0000-0000-0000-0000000000c5', 'synthetic_seed', 'Synthetic seed');
INSERT INTO consent_policies VALUES
    ('terms', '2026-11', true, 'https://example.invalid/terms', now(), now());
INSERT INTO users (user_id, email, display_name) VALUES
    ('00000000-0000-0000-0000-0000000000a1', 'seeker@example.invalid', 'Seeker'),
    ('00000000-0000-0000-0000-0000000000a2', 'admin@example.invalid', 'Admin');
INSERT INTO user_profiles (user_id, headline) VALUES ('00000000-0000-0000-0000-0000000000a1', 'Backend');
INSERT INTO user_consents (user_id, policy_code, policy_version, granted)
    VALUES ('00000000-0000-0000-0000-0000000000a1', 'terms', '2026-11', true);
INSERT INTO skills (skill_id, code, name) VALUES
    ('00000000-0000-0000-0000-0000000000b5', 'python', 'Python');
INSERT INTO job_roles (job_role_id, code, name) VALUES
    ('00000000-0000-0000-0000-0000000000b4', 'backend', 'Backend Engineer'),
    ('00000000-0000-0000-0000-0000000000b6', 'data', 'Data Engineer'),
    ('00000000-0000-0000-0000-0000000000b7', 'ml', 'ML Engineer'),
    ('00000000-0000-0000-0000-0000000000b8', 'frontend', 'Frontend Engineer');
INSERT INTO job_role_skills VALUES
    ('00000000-0000-0000-0000-0000000000b4', '00000000-0000-0000-0000-0000000000b5', 4, now());
INSERT INTO user_skills (user_id, skill_id, proficiency) VALUES
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b5', 2);
INSERT INTO user_target_roles (user_id, job_role_id, priority) VALUES
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b4', 1),
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b6', 2),
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b7', 3);
INSERT INTO companies (company_id, name, source_id) VALUES
    ('00000000-0000-0000-0000-0000000000c1', 'Example Corp', '00000000-0000-0000-0000-0000000000c5');
INSERT INTO job_postings (job_posting_id, company_id, job_role_id, source_id, title, status, published_at) VALUES
    ('00000000-0000-0000-0000-0000000000c2', '00000000-0000-0000-0000-0000000000c1',
     '00000000-0000-0000-0000-0000000000b4', '00000000-0000-0000-0000-0000000000c5', 'Backend', 'published', now());
INSERT INTO user_job_bookmarks VALUES
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000c2', now());
INSERT INTO model_versions (model_version_id, model_code, version, kind) VALUES
    ('00000000-0000-0000-0000-0000000000d1', 'skill_gap_rule', '1', 'rule');
INSERT INTO skill_gap_assessments (assessment_id, user_id, job_role_id, model_version_id) VALUES
    ('00000000-0000-0000-0000-0000000000d3', '00000000-0000-0000-0000-0000000000a1',
     '00000000-0000-0000-0000-0000000000b4', '00000000-0000-0000-0000-0000000000d1');
INSERT INTO skill_gap_items VALUES
    ('00000000-0000-0000-0000-0000000000d3', '00000000-0000-0000-0000-0000000000b5', 4, 2, 2);
INSERT INTO match_evaluations (user_id, job_posting_id, model_version_id, score) VALUES
    ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000c2',
     '00000000-0000-0000-0000-0000000000d1', 62.5);
INSERT INTO account_deletion_requests (request_id, user_id, scheduled_purge_at) VALUES
    ('00000000-0000-0000-0000-0000000000a9', '00000000-0000-0000-0000-0000000000a1', now() + interval '30 days');
INSERT INTO audit_events (actor_user_id, action_code, resource_type) VALUES
    ('00000000-0000-0000-0000-0000000000a1', 'account.deletion_requested', 'user');
DO $$ BEGIN RAISE NOTICE 'PASS normal fixtures inserted'; END $$;

-- ---------- rejection cases ----------
SELECT pg_temp.expect_error('email must be normalized',
    $q$INSERT INTO users (email, display_name) VALUES ('Upper@Example.invalid', 'x')$q$);
SELECT pg_temp.expect_error('duplicate email',
    $q$INSERT INTO users (email, display_name) VALUES ('seeker@example.invalid', 'x')$q$);
SELECT pg_temp.expect_error('consent to unknown policy version',
    $q$INSERT INTO user_consents (user_id, policy_code, policy_version, granted)
       VALUES ('00000000-0000-0000-0000-0000000000a1', 'terms', '1999-01', true)$q$);
SELECT pg_temp.expect_error('4th target role (max 3, F-009)',
    $q$INSERT INTO user_target_roles (user_id, job_role_id, priority)
       VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b8', 4)$q$);
SELECT pg_temp.expect_error('duplicate target priority',
    $q$INSERT INTO user_target_roles (user_id, job_role_id, priority)
       VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b8', 1)$q$);
SELECT pg_temp.expect_error('proficiency out of 1..5',
    $q$UPDATE user_skills SET proficiency = 6$q$);
SELECT pg_temp.expect_error('match needs exactly one of posting/role',
    $q$INSERT INTO match_evaluations (user_id, job_posting_id, job_role_id, model_version_id, score)
       VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000c2',
               '00000000-0000-0000-0000-0000000000b4', '00000000-0000-0000-0000-0000000000d1', 1)$q$);
SELECT pg_temp.expect_error('match score above 100',
    $q$INSERT INTO match_evaluations (user_id, job_role_id, model_version_id, score)
       VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b4',
               '00000000-0000-0000-0000-0000000000d1', 120)$q$);
SELECT pg_temp.expect_error('skill gap arithmetic mismatch',
    $q$UPDATE skill_gap_items SET gap = 3$q$);
SELECT pg_temp.expect_error('second open deletion request',
    $q$INSERT INTO account_deletion_requests (user_id, scheduled_purge_at)
       VALUES ('00000000-0000-0000-0000-0000000000a1', now() + interval '30 days')$q$);
SELECT pg_temp.expect_error('external source without license',
    $q$INSERT INTO data_sources (code, name) VALUES ('job_board_x', 'X')$q$);
SELECT pg_temp.expect_error('published posting without published_at',
    $q$UPDATE job_postings SET published_at = NULL$q$);
SELECT pg_temp.expect_error('delete skill still used by a user (RESTRICT)',
    $q$DELETE FROM skills WHERE code = 'python'$q$);
SELECT pg_temp.expect_error('delete model version still referenced (RESTRICT)',
    $q$DELETE FROM model_versions$q$);

-- ---------- account purge (D-06 draft): personal rows go, audit is anonymized ----------
DELETE FROM users WHERE user_id = '00000000-0000-0000-0000-0000000000a1';
DO $$
DECLARE leftover int;
BEGIN
    SELECT (SELECT count(*) FROM user_profiles) + (SELECT count(*) FROM user_skills)
         + (SELECT count(*) FROM user_target_roles) + (SELECT count(*) FROM user_consents)
         + (SELECT count(*) FROM user_job_bookmarks) + (SELECT count(*) FROM skill_gap_items)
         + (SELECT count(*) FROM match_evaluations) INTO leftover;
    IF leftover <> 0 THEN RAISE EXCEPTION 'FAIL purge left % personal rows', leftover; END IF;
    IF EXISTS (SELECT 1 FROM audit_events WHERE actor_user_id IS NOT NULL) THEN
        RAISE EXCEPTION 'FAIL audit actor not anonymized'; END IF;
    IF NOT EXISTS (SELECT 1 FROM audit_events) THEN RAISE EXCEPTION 'FAIL audit row lost'; END IF;
    IF NOT EXISTS (SELECT 1 FROM account_deletion_requests WHERE user_id IS NULL) THEN
        RAISE EXCEPTION 'FAIL deletion request evidence lost'; END IF;
    IF NOT EXISTS (SELECT 1 FROM job_postings) OR NOT EXISTS (SELECT 1 FROM skills) THEN
        RAISE EXCEPTION 'FAIL catalog rows removed by purge'; END IF;
    RAISE NOTICE 'PASS account purge cascades personal data, keeps catalog, anonymizes audit';
END $$;
