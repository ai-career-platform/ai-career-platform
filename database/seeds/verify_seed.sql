-- T10 seed verification (read-only). Every row must report ok = true.
-- Run: psql -X -v ON_ERROR_STOP=1 -f database/seeds/verify_seed.sql
SET client_encoding = 'UTF8';
WITH checks AS (
    -- expected row counts (seed rows only, identified by deterministic keys / naming)
    SELECT 'count data_sources synthetic_seed = 1' AS check_name,
           (SELECT count(*) FROM career.data_sources WHERE code = 'synthetic_seed') = 1 AS ok
    UNION ALL SELECT 'count roles = 2, permissions = 2, admin has both',
           (SELECT count(*) FROM career.roles WHERE code IN ('job_seeker','admin')) = 2
       AND (SELECT count(*) FROM career.permissions WHERE code IN ('admin.models.read','admin.audit.read')) = 2
       AND (SELECT count(*) FROM career.role_permissions rp JOIN career.roles r USING (role_id) WHERE r.code = 'admin') = 2
    UNION ALL SELECT 'user_roles: 20 job_seeker + 1 admin (seed-user-18)',
           (SELECT count(*) FILTER (WHERE r.code = 'job_seeker') = 20
               AND count(*) FILTER (WHERE r.code = 'admin') = 1
               AND bool_and(r.code <> 'admin' OR u.email = 'seed-user-18@example.com')
              FROM career.user_roles ur JOIN career.roles r USING (role_id) JOIN career.users u USING (user_id)
             WHERE u.email LIKE 'seed-user-__@example.com')
    UNION ALL SELECT 'count job_roles = 30',
           (SELECT count(*) FROM career.job_roles WHERE job_role_id = md5('seed:job_role:' || code)::uuid) = 30
    UNION ALL SELECT 'count skills = 100',
           (SELECT count(*) FROM career.skills WHERE skill_id = md5('seed:skill:' || code)::uuid) = 100
    UNION ALL SELECT 'count companies = 20',
           (SELECT count(*) FROM career.companies WHERE website_url LIKE 'https://company-__.example.com') = 20
    UNION ALL SELECT 'count users = 20 (18 active, 2 disabled)',
           (SELECT count(*) FILTER (WHERE status = 'active') = 18 AND count(*) FILTER (WHERE status = 'disabled') = 2
              FROM career.users WHERE email LIKE 'seed-user-__@example.com')
    UNION ALL SELECT 'count user_profiles = 18',
           (SELECT count(*) FROM career.user_profiles p JOIN career.users u USING (user_id)
              WHERE u.email LIKE 'seed-user-__@example.com') = 18
    UNION ALL SELECT 'count job_role_skills = 150',
           (SELECT count(*) FROM career.job_role_skills x JOIN career.job_roles jr USING (job_role_id)
             WHERE jr.job_role_id = md5('seed:job_role:' || jr.code)::uuid) = 150
    UNION ALL SELECT 'count job_postings = 100 (80/10/10)',
           (SELECT count(*) FILTER (WHERE status = 'published') = 80
               AND count(*) FILTER (WHERE status = 'draft') = 10
               AND count(*) FILTER (WHERE status = 'closed') = 10
              FROM career.job_postings WHERE title LIKE '[Seed] %')
    UNION ALL SELECT 'count job_posting_skills = 400',
           (SELECT count(*) FROM career.job_posting_skills x JOIN career.job_postings jp USING (job_posting_id)
             WHERE jp.title LIKE '[Seed] %') = 400
    UNION ALL SELECT 'count user_skills = 60',
           (SELECT count(*) FROM career.user_skills x JOIN career.users u USING (user_id)
             WHERE u.email LIKE 'seed-user-__@example.com') = 60
    UNION ALL SELECT 'count user_job_bookmarks = 32',
           (SELECT count(*) FROM career.user_job_bookmarks x JOIN career.users u USING (user_id)
             WHERE u.email LIKE 'seed-user-__@example.com') = 32

    -- duplicates by natural key (UNIQUE makes these impossible; kept as explicit evidence)
    UNION ALL SELECT 'duplicate job_role code = 0',
           NOT EXISTS (SELECT 1 FROM career.job_roles GROUP BY code HAVING count(*) > 1)
    UNION ALL SELECT 'duplicate skill code = 0',
           NOT EXISTS (SELECT 1 FROM career.skills GROUP BY code HAVING count(*) > 1)
    UNION ALL SELECT 'duplicate user email_canonical = 0',
           NOT EXISTS (SELECT 1 FROM career.users GROUP BY email_canonical HAVING count(*) > 1)
    UNION ALL SELECT 'seed email_canonical follows T05 rule (lowercase, no +tag)',
           NOT EXISTS (SELECT 1 FROM career.users WHERE email LIKE 'seed-user-%'
                       AND (email_canonical <> lower(email) OR split_part(email_canonical, '@', 1) LIKE '%+%'))
    UNION ALL SELECT 'duplicate company name = 0',
           NOT EXISTS (SELECT 1 FROM career.companies GROUP BY name HAVING count(*) > 1)

    -- orphan rows (FK enforced; explicit evidence for DoD "FK 깨짐 0")
    UNION ALL SELECT 'orphan job_postings.company_id = 0',
           NOT EXISTS (SELECT 1 FROM career.job_postings jp LEFT JOIN career.companies c USING (company_id) WHERE c.company_id IS NULL)
    UNION ALL SELECT 'orphan job_posting_skills = 0',
           NOT EXISTS (SELECT 1 FROM career.job_posting_skills x
                       LEFT JOIN career.job_postings jp USING (job_posting_id)
                       LEFT JOIN career.skills s USING (skill_id)
                       WHERE jp.job_posting_id IS NULL OR s.skill_id IS NULL)
    UNION ALL SELECT 'orphan user_skills = 0',
           NOT EXISTS (SELECT 1 FROM career.user_skills x
                       LEFT JOIN career.users u USING (user_id)
                       LEFT JOIN career.skills s USING (skill_id)
                       WHERE u.user_id IS NULL OR s.skill_id IS NULL)

    -- data rules
    UNION ALL SELECT 'every role has 5 skills with required_level 1..5',
           NOT EXISTS (SELECT 1 FROM career.job_roles r
                       LEFT JOIN career.job_role_skills x USING (job_role_id)
                       GROUP BY r.job_role_id
                       HAVING count(x.skill_id) <> 5 OR count(DISTINCT x.required_level) <> 5)
    UNION ALL SELECT 'companies and postings reference synthetic_seed source',
           NOT EXISTS (SELECT 1 FROM career.companies c JOIN career.data_sources d USING (source_id)
                       WHERE c.website_url LIKE 'https://company-__.example.com' AND d.code <> 'synthetic_seed')
       AND NOT EXISTS (SELECT 1 FROM career.job_postings jp JOIN career.data_sources d USING (source_id)
                       WHERE jp.title LIKE '[Seed] %' AND d.code <> 'synthetic_seed')
    UNION ALL SELECT 'posting skill required_level matches role default',
           NOT EXISTS (SELECT 1 FROM career.job_posting_skills ps
                       JOIN career.job_postings jp USING (job_posting_id)
                       JOIN career.job_role_skills rs ON rs.job_role_id = jp.job_role_id AND rs.skill_id = ps.skill_id
                       WHERE ps.required_level IS DISTINCT FROM rs.required_level)
    UNION ALL SELECT 'skill gap is positive for seeded user skills (required - proficiency = 1)',
           NOT EXISTS (SELECT 1 FROM career.user_skills us
                       JOIN career.job_role_skills rs USING (skill_id)
                       JOIN career.users u USING (user_id)
                       JOIN career.job_roles r ON r.job_role_id = rs.job_role_id
                       WHERE u.email LIKE 'seed-user-%' AND rs.required_level - us.proficiency <> 1
                         AND r.code = (SELECT code FROM career.job_roles ORDER BY code
                                       OFFSET (substring(u.email from 'seed-user-(\d+)')::int - 1) % 30 LIMIT 1))
    UNION ALL SELECT 'draft postings have no dates; others have both',
           NOT EXISTS (SELECT 1 FROM career.job_postings
                       WHERE (status = 'draft' AND (published_at IS NOT NULL OR expires_at IS NOT NULL))
                          OR (status <> 'draft' AND (published_at IS NULL OR expires_at IS NULL)))
    UNION ALL SELECT 'bookmarks point to published postings only',
           NOT EXISTS (SELECT 1 FROM career.user_job_bookmarks b JOIN career.job_postings jp USING (job_posting_id)
                       WHERE jp.status <> 'published')
    UNION ALL SELECT 'disabled users have no profile or bookmark',
           NOT EXISTS (SELECT 1 FROM career.users u
                       WHERE u.status = 'disabled'
                         AND (EXISTS (SELECT 1 FROM career.user_profiles p WHERE p.user_id = u.user_id)
                           OR EXISTS (SELECT 1 FROM career.user_job_bookmarks b WHERE b.user_id = u.user_id)))
    UNION ALL SELECT 'only reserved example domains are used (any synthetic tool)',
           NOT EXISTS (SELECT 1 FROM career.users WHERE email !~ '@example\.(com|test|invalid)$')
       AND NOT EXISTS (SELECT 1 FROM career.companies WHERE website_url !~ '^https://[a-z0-9.-]+\.example\.(com|test)$')
       AND NOT EXISTS (SELECT 1 FROM career.job_postings WHERE title LIKE '[Seed] %' AND source_url IS NOT NULL)

    -- sample lookups the APIs (T17/T18) will rely on
    UNION ALL SELECT 'lookup role BACKEND_ENGINEER -> top skill PYTHON',
           (SELECT s.code FROM career.job_roles r
              JOIN career.job_role_skills x USING (job_role_id) JOIN career.skills s USING (skill_id)
             WHERE r.code = 'BACKEND_ENGINEER' ORDER BY x.required_level DESC LIMIT 1) = 'PYTHON'
    UNION ALL SELECT 'lookup skill POSTGRESQL is used by >= 1 role',
           (SELECT count(*) FROM career.job_role_skills x JOIN career.skills s USING (skill_id)
             WHERE s.code = 'POSTGRESQL') >= 1
    UNION ALL SELECT 'lookup published postings with company and role = 80',
           (SELECT count(*) FROM career.job_postings jp
              JOIN career.companies c USING (company_id) JOIN career.job_roles r USING (job_role_id)
             WHERE jp.status = 'published' AND jp.title LIKE '[Seed] %') = 80
)
SELECT check_name, ok
FROM (
    SELECT 0 AS sort_key, check_name, ok FROM checks
    UNION ALL
    -- last row is the machine-readable verdict used by tests: SEED_VERIFY | t/f
    SELECT 1, 'SEED_VERIFY', bool_and(ok) FROM checks
) r
ORDER BY sort_key, ok, check_name;
