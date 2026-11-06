-- AI Career Platform / T10 initial Seed·Fixture
-- SEED_REVISION: 0001 (2026-11-06)
-- STATUS: DRAFT. Disposable/local DB only. NOT approved for Staging (T12 gate).
-- TARGET SCHEMA: T05 data dictionary (database/DATA_DICTIONARY.md v0.2), validation DDL from
--                `python3 database/model/check_data_dictionary.py --ddl` (career.*). Seed fills 15 tables.
--
-- Data policy
--   * 100% synthetic. No real person, company, posting or confidential data.
--   * Emails use the reserved example.com domain; URLs use *.example.com.
--   * Timestamps are fixed literals (no now()) so re-runs produce identical rows.
--
-- Idempotency (upsert keys)
--   data_sources -> code            job_roles -> code        skills -> code
--   users      -> email_canonical   companies / job_postings -> deterministic uuid
--   link tables -> composite primary key
--   Deterministic uuid = md5('<seed namespace>:<natural key>')::uuid
--   Rows are only rewritten (and updated_at bumped) when the seed values change.
--
-- Insert order (parent -> child)
--   0 data_sources (synthetic_seed, T05 D-05)
--   1 job_roles, skills, companies, users
--   2 job_role_skills, user_profiles
--   3 job_postings
--   4 job_posting_skills, user_skills, user_job_bookmarks
--   5 roles, permissions -> role_permissions, user_roles
--
-- Run: psql -X -v ON_ERROR_STOP=1 -f database/seeds/0001_initial_seed.sql

-- File is UTF-8 (Korean names). Windows psql otherwise reads it as the console code page (e.g. UHC).
SET client_encoding = 'UTF8';

BEGIN;

-- ---------------------------------------------------------------- 0. data source
-- T05 C05: companies / job_postings must reference a data source. 1st phase = synthetic_seed only.
INSERT INTO career.data_sources (source_id, code, name, license_ref, retention_days, is_active, created_at, updated_at)
VALUES (md5('seed:data_source:synthetic_seed')::uuid, 'synthetic_seed', '합성 Seed 데이터 (T10)', NULL, NULL, true,
        timestamptz '2026-11-06 00:00:00+00', timestamptz '2026-11-06 00:00:00+00')
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name, updated_at = timestamptz '2026-11-06 00:00:00+00'
WHERE career.data_sources.name IS DISTINCT FROM EXCLUDED.name;

-- ---------------------------------------------------------------- 1. parents
-- 1-1 job_roles (30)
INSERT INTO career.job_roles (job_role_id, code, name, created_at, updated_at)
SELECT md5('seed:job_role:' || v.code)::uuid, v.code, v.name,
       timestamptz '2026-11-06 00:00:00+00', timestamptz '2026-11-06 00:00:00+00'
FROM (VALUES
    ('BACKEND_ENGINEER',        '백엔드 개발자'),
    ('FRONTEND_ENGINEER',       '프론트엔드 개발자'),
    ('FULLSTACK_ENGINEER',      '풀스택 개발자'),
    ('MOBILE_ANDROID_ENGINEER', '안드로이드 개발자'),
    ('MOBILE_IOS_ENGINEER',     'iOS 개발자'),
    ('DATA_ENGINEER',           '데이터 엔지니어'),
    ('DATA_ANALYST',            '데이터 분석가'),
    ('DATA_SCIENTIST',          '데이터 사이언티스트'),
    ('ML_ENGINEER',             '머신러닝 엔지니어'),
    ('MLOPS_ENGINEER',          'MLOps 엔지니어'),
    ('AI_RESEARCHER',           'AI 리서처'),
    ('LLM_APPLICATION_ENGINEER','LLM 애플리케이션 개발자'),
    ('DEVOPS_ENGINEER',         'DevOps 엔지니어'),
    ('CLOUD_ENGINEER',          '클라우드 엔지니어'),
    ('SRE',                     '사이트 신뢰성 엔지니어'),
    ('DBA',                     '데이터베이스 관리자'),
    ('SECURITY_ENGINEER',       '보안 엔지니어'),
    ('QA_ENGINEER',             'QA 엔지니어'),
    ('TEST_AUTOMATION_ENGINEER','테스트 자동화 엔지니어'),
    ('EMBEDDED_ENGINEER',       '임베디드 개발자'),
    ('GAME_CLIENT_ENGINEER',    '게임 클라이언트 개발자'),
    ('GAME_SERVER_ENGINEER',    '게임 서버 개발자'),
    ('PRODUCT_MANAGER',         '프로덕트 매니저'),
    ('PROJECT_MANAGER',         '프로젝트 매니저'),
    ('UX_DESIGNER',             'UX 디자이너'),
    ('UI_DESIGNER',             'UI 디자이너'),
    ('TECHNICAL_WRITER',        '테크니컬 라이터'),
    ('SOLUTIONS_ARCHITECT',     '솔루션 아키텍트'),
    ('BI_DEVELOPER',            'BI 개발자'),
    ('BLOCKCHAIN_ENGINEER',     '블록체인 개발자')
) AS v(code, name)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name, updated_at = timestamptz '2026-11-06 00:00:00+00'
WHERE career.job_roles.name IS DISTINCT FROM EXCLUDED.name;

-- 1-2 skills (100)
INSERT INTO career.skills (skill_id, code, name, created_at, updated_at)
SELECT md5('seed:skill:' || v.code)::uuid, v.code, v.name,
       timestamptz '2026-11-06 00:00:00+00', timestamptz '2026-11-06 00:00:00+00'
FROM (VALUES
    -- languages (15)
    ('PYTHON','Python'), ('JAVA','Java'), ('KOTLIN','Kotlin'), ('JAVASCRIPT','JavaScript'),
    ('TYPESCRIPT','TypeScript'), ('GO','Go'), ('RUST','Rust'), ('C','C'), ('CPP','C++'),
    ('CSHARP','C#'), ('SWIFT','Swift'), ('SQL','SQL'), ('R','R'), ('SCALA','Scala'), ('SOLIDITY','Solidity'),
    -- backend (12)
    ('FASTAPI','FastAPI'), ('DJANGO','Django'), ('FLASK','Flask'), ('SPRING_BOOT','Spring Boot'),
    ('NODEJS','Node.js'), ('NESTJS','NestJS'), ('EXPRESS','Express'), ('REST_API','REST API 설계'),
    ('GRAPHQL','GraphQL'), ('GRPC','gRPC'), ('SQLALCHEMY','SQLAlchemy'), ('JPA','JPA/Hibernate'),
    -- frontend / mobile (12)
    ('REACT','React'), ('NEXTJS','Next.js'), ('VUE','Vue.js'), ('HTML_CSS','HTML/CSS'),
    ('TAILWIND_CSS','Tailwind CSS'), ('REDUX','Redux'), ('WEB_ACCESSIBILITY','웹 접근성'),
    ('ANDROID_SDK','Android SDK'), ('JETPACK_COMPOSE','Jetpack Compose'), ('SWIFTUI','SwiftUI'),
    ('FLUTTER','Flutter'), ('REACT_NATIVE','React Native'),
    -- data / db (14)
    ('POSTGRESQL','PostgreSQL'), ('MYSQL','MySQL'), ('ORACLE_DB','Oracle Database'), ('MONGODB','MongoDB'),
    ('REDIS','Redis'), ('ELASTICSEARCH','Elasticsearch'), ('KAFKA','Apache Kafka'), ('SPARK','Apache Spark'),
    ('AIRFLOW','Apache Airflow'), ('DBT','dbt'), ('PANDAS','pandas'), ('DATA_MODELING','데이터 모델링'),
    ('DB_TUNING','DB 성능 튜닝'), ('ETL','ETL 파이프라인'),
    -- ai / ml (14)
    ('MACHINE_LEARNING','머신러닝'), ('DEEP_LEARNING','딥러닝'), ('SCIKIT_LEARN','scikit-learn'),
    ('PYTORCH','PyTorch'), ('TENSORFLOW','TensorFlow'), ('NLP','자연어 처리'), ('COMPUTER_VISION','컴퓨터 비전'),
    ('LLM','대규모 언어 모델 활용'), ('RAG','RAG'), ('PROMPT_ENGINEERING','프롬프트 엔지니어링'),
    ('MLFLOW','MLflow'), ('FEATURE_ENGINEERING','피처 엔지니어링'), ('STATISTICS','통계'),
    ('VECTOR_DB','벡터 데이터베이스'),
    -- infra / ops (13)
    ('DOCKER','Docker'), ('KUBERNETES','Kubernetes'), ('AWS','AWS'), ('GCP','Google Cloud'),
    ('AZURE','Microsoft Azure'), ('TERRAFORM','Terraform'), ('LINUX','Linux'), ('GITHUB_ACTIONS','GitHub Actions'),
    ('CI_CD','CI/CD'), ('PROMETHEUS','Prometheus'), ('GRAFANA','Grafana'), ('NGINX','Nginx'), ('NETWORKING','네트워크 기초'),
    -- security / quality (8)
    ('APP_SECURITY','애플리케이션 보안'), ('OWASP','OWASP Top 10'), ('IAM','접근 권한 관리(IAM)'),
    ('PENETRATION_TEST','모의 해킹'), ('TEST_AUTOMATION','테스트 자동화'), ('PYTEST','pytest'),
    ('SELENIUM','Selenium'), ('PLAYWRIGHT','Playwright'),
    -- product / design / collaboration (12)
    ('GIT','Git'), ('AGILE','애자일/스크럼'), ('JIRA','Jira'), ('PRODUCT_PLANNING','서비스 기획'),
    ('DATA_DRIVEN_DECISION','데이터 기반 의사결정'), ('FIGMA','Figma'), ('UX_RESEARCH','UX 리서치'),
    ('UI_DESIGN','UI 디자인'), ('TECHNICAL_WRITING','기술 문서 작성'), ('TABLEAU','Tableau'),
    ('UNITY','Unity'), ('UNREAL','Unreal Engine')
) AS v(code, name)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name, updated_at = timestamptz '2026-11-06 00:00:00+00'
WHERE career.skills.name IS DISTINCT FROM EXCLUDED.name;

-- 1-3 companies (20, fictional)
INSERT INTO career.companies (company_id, name, website_url, description, source_id, created_at, updated_at)
SELECT md5('seed:company:' || lpad(g::text, 2, '0'))::uuid,
       '가상기업 ' || lpad(g::text, 2, '0') || ' (Seed)',
       'https://company-' || lpad(g::text, 2, '0') || '.example.com',
       '합성 기업 데이터입니다. 실제 기업과 무관합니다.',
       md5('seed:data_source:synthetic_seed')::uuid,
       timestamptz '2026-11-06 00:00:00+00', timestamptz '2026-11-06 00:00:00+00'
FROM generate_series(1, 20) AS g
ON CONFLICT (company_id) DO UPDATE
SET name = EXCLUDED.name, website_url = EXCLUDED.website_url, description = EXCLUDED.description,
    source_id = EXCLUDED.source_id, updated_at = timestamptz '2026-11-06 00:00:00+00'
WHERE (career.companies.name, career.companies.website_url, career.companies.description, career.companies.source_id)
      IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.website_url, EXCLUDED.description, EXCLUDED.source_id);

-- 1-4 users (20 synthetic; 19, 20 are 'disabled' for negative-path tests)
-- T05 A01: email_canonical is the unique key (lowercase, no '+tag'); seed emails are already canonical.
INSERT INTO career.users (user_id, email, email_canonical, display_name, status, created_at, updated_at)
SELECT md5('seed:user:' || lpad(g::text, 2, '0'))::uuid,
       'seed-user-' || lpad(g::text, 2, '0') || '@example.com',
       'seed-user-' || lpad(g::text, 2, '0') || '@example.com',
       '테스트사용자' || lpad(g::text, 2, '0'),
       CASE WHEN g >= 19 THEN 'disabled' ELSE 'active' END,
       timestamptz '2026-11-06 00:00:00+00', timestamptz '2026-11-06 00:00:00+00'
FROM generate_series(1, 20) AS g
ON CONFLICT (email_canonical) DO UPDATE
SET display_name = EXCLUDED.display_name, status = EXCLUDED.status,
    updated_at = timestamptz '2026-11-06 00:00:00+00'
WHERE (career.users.display_name, career.users.status)
      IS DISTINCT FROM (EXCLUDED.display_name, EXCLUDED.status);

-- ---------------------------------------------------------------- 2. children of parents
-- 2-1 job_role_skills: array order = required_level 5,4,3,2,1 (T05 B06: same 1~5 scale as proficiency)
INSERT INTO career.job_role_skills (job_role_id, skill_id, required_level, created_at)
SELECT r.job_role_id, s.skill_id, (6 - m.ord)::smallint, timestamptz '2026-11-06 00:00:00+00'
FROM (VALUES
    ('BACKEND_ENGINEER',        ARRAY['PYTHON','FASTAPI','POSTGRESQL','REST_API','DOCKER']),
    ('FRONTEND_ENGINEER',       ARRAY['TYPESCRIPT','REACT','HTML_CSS','NEXTJS','WEB_ACCESSIBILITY']),
    ('FULLSTACK_ENGINEER',      ARRAY['TYPESCRIPT','REACT','NODEJS','POSTGRESQL','DOCKER']),
    ('MOBILE_ANDROID_ENGINEER', ARRAY['KOTLIN','ANDROID_SDK','JETPACK_COMPOSE','REST_API','GIT']),
    ('MOBILE_IOS_ENGINEER',     ARRAY['SWIFT','SWIFTUI','REST_API','GIT','CI_CD']),
    ('DATA_ENGINEER',           ARRAY['PYTHON','SQL','SPARK','AIRFLOW','KAFKA']),
    ('DATA_ANALYST',            ARRAY['SQL','PYTHON','PANDAS','TABLEAU','STATISTICS']),
    ('DATA_SCIENTIST',          ARRAY['PYTHON','STATISTICS','MACHINE_LEARNING','SCIKIT_LEARN','PANDAS']),
    ('ML_ENGINEER',             ARRAY['PYTHON','PYTORCH','MACHINE_LEARNING','FEATURE_ENGINEERING','DOCKER']),
    ('MLOPS_ENGINEER',          ARRAY['MLFLOW','KUBERNETES','DOCKER','CI_CD','PYTHON']),
    ('AI_RESEARCHER',           ARRAY['DEEP_LEARNING','PYTORCH','NLP','STATISTICS','PYTHON']),
    ('LLM_APPLICATION_ENGINEER',ARRAY['LLM','RAG','PYTHON','VECTOR_DB','PROMPT_ENGINEERING']),
    ('DEVOPS_ENGINEER',         ARRAY['DOCKER','KUBERNETES','CI_CD','TERRAFORM','LINUX']),
    ('CLOUD_ENGINEER',          ARRAY['AWS','TERRAFORM','NETWORKING','LINUX','IAM']),
    ('SRE',                     ARRAY['LINUX','PROMETHEUS','GRAFANA','KUBERNETES','GO']),
    ('DBA',                     ARRAY['POSTGRESQL','DB_TUNING','SQL','DATA_MODELING','LINUX']),
    ('SECURITY_ENGINEER',       ARRAY['APP_SECURITY','OWASP','IAM','PENETRATION_TEST','NETWORKING']),
    ('QA_ENGINEER',             ARRAY['TEST_AUTOMATION','PYTEST','PLAYWRIGHT','JIRA','SQL']),
    ('TEST_AUTOMATION_ENGINEER',ARRAY['TEST_AUTOMATION','SELENIUM','PLAYWRIGHT','PYTHON','CI_CD']),
    ('EMBEDDED_ENGINEER',       ARRAY['C','CPP','LINUX','RUST','GIT']),
    ('GAME_CLIENT_ENGINEER',    ARRAY['CSHARP','UNITY','CPP','UNREAL','GIT']),
    ('GAME_SERVER_ENGINEER',    ARRAY['CPP','CSHARP','REDIS','MYSQL','NETWORKING']),
    ('PRODUCT_MANAGER',         ARRAY['PRODUCT_PLANNING','DATA_DRIVEN_DECISION','AGILE','UX_RESEARCH','JIRA']),
    ('PROJECT_MANAGER',         ARRAY['AGILE','JIRA','PRODUCT_PLANNING','TECHNICAL_WRITING','GIT']),
    ('UX_DESIGNER',             ARRAY['UX_RESEARCH','FIGMA','UI_DESIGN','WEB_ACCESSIBILITY','PRODUCT_PLANNING']),
    ('UI_DESIGNER',             ARRAY['UI_DESIGN','FIGMA','HTML_CSS','WEB_ACCESSIBILITY','TAILWIND_CSS']),
    ('TECHNICAL_WRITER',        ARRAY['TECHNICAL_WRITING','GIT','REST_API','AGILE','JIRA']),
    ('SOLUTIONS_ARCHITECT',     ARRAY['AWS','NETWORKING','KUBERNETES','DATA_MODELING','APP_SECURITY']),
    ('BI_DEVELOPER',            ARRAY['SQL','TABLEAU','DBT','DATA_MODELING','ETL']),
    ('BLOCKCHAIN_ENGINEER',     ARRAY['SOLIDITY','GO','TYPESCRIPT','APP_SECURITY','DOCKER'])
) AS v(role_code, skill_codes)
CROSS JOIN LATERAL unnest(v.skill_codes) WITH ORDINALITY AS m(skill_code, ord)
JOIN career.job_roles r ON r.code = v.role_code
JOIN career.skills s ON s.code = m.skill_code
ON CONFLICT (job_role_id, skill_id) DO UPDATE
SET required_level = EXCLUDED.required_level
WHERE career.job_role_skills.required_level IS DISTINCT FROM EXCLUDED.required_level;

-- 2-2 user_profiles (active users 1..18 only; disabled users have none)
--     user g aims at the g-th seed role by code order ((g-1)%30), same rule as user_skills
WITH seed_roles AS (
    SELECT name, row_number() OVER (ORDER BY code) - 1 AS idx
    FROM career.job_roles
    WHERE job_role_id = md5('seed:job_role:' || code)::uuid
)
INSERT INTO career.user_profiles (user_id, headline, bio, location_text, created_at, updated_at)
SELECT u.user_id,
       r.name || ' 지망 (Seed)',
       '합성 테스트 데이터입니다. 실제 인물과 무관합니다.',
       (ARRAY['서울','경기','인천','부산','대전','원격'])[1 + (g - 1) % 6],
       timestamptz '2026-11-06 00:00:00+00', timestamptz '2026-11-06 00:00:00+00'
FROM generate_series(1, 18) AS g
JOIN career.users u ON u.email = 'seed-user-' || lpad(g::text, 2, '0') || '@example.com'
JOIN seed_roles r ON r.idx = (g - 1) % 30
ON CONFLICT (user_id) DO UPDATE
SET headline = EXCLUDED.headline, bio = EXCLUDED.bio, location_text = EXCLUDED.location_text,
    updated_at = timestamptz '2026-11-06 00:00:00+00'
WHERE (career.user_profiles.headline, career.user_profiles.bio, career.user_profiles.location_text)
      IS DISTINCT FROM (EXCLUDED.headline, EXCLUDED.bio, EXCLUDED.location_text);

-- ---------------------------------------------------------------- 3. job_postings (100)
-- posting n: company ((n-1)%20)+1, role = n-th seed role by code order ((n-1)%30)
-- status: n%10=0 -> draft (10), n%10=9 -> closed (10), else published (80)
WITH seed_roles AS (
    SELECT job_role_id, code, name, row_number() OVER (ORDER BY code) - 1 AS idx
    FROM career.job_roles
    WHERE job_role_id = md5('seed:job_role:' || code)::uuid
), p AS (
    SELECT n,
           md5('seed:job_posting:' || lpad(n::text, 3, '0'))::uuid AS job_posting_id,
           md5('seed:company:' || lpad((((n - 1) % 20) + 1)::text, 2, '0'))::uuid AS company_id,
           CASE WHEN n % 10 = 0 THEN 'draft' WHEN n % 10 = 9 THEN 'closed' ELSE 'published' END AS status,
           timestamptz '2026-10-01 00:00:00+00' + make_interval(days => (n - 1) % 30) AS base_at
    FROM generate_series(1, 100) AS n
)
INSERT INTO career.job_postings (job_posting_id, company_id, job_role_id, source_id, title, description,
                                 employment_type, location_text,
                                 source_url, published_at, expires_at, status, created_at, updated_at)
SELECT p.job_posting_id, p.company_id, r.job_role_id, md5('seed:data_source:synthetic_seed')::uuid,
       '[Seed] ' || r.name || ' 채용 #' || lpad(p.n::text, 3, '0'),
       '합성 채용공고입니다. 실제 기업·공고와 무관합니다.',
       (ARRAY['full_time','full_time','full_time','contract','intern'])[1 + (p.n - 1) % 5],
       (ARRAY['서울','경기','부산','대전','원격'])[1 + (p.n - 1) % 5],
       NULL,
       CASE WHEN p.status = 'draft' THEN NULL ELSE p.base_at END,
       CASE WHEN p.status = 'draft' THEN NULL ELSE p.base_at + interval '45 days' END,
       p.status,
       timestamptz '2026-11-06 00:00:00+00', timestamptz '2026-11-06 00:00:00+00'
FROM p
JOIN seed_roles r ON r.idx = (p.n - 1) % 30
ON CONFLICT (job_posting_id) DO UPDATE
SET company_id = EXCLUDED.company_id, job_role_id = EXCLUDED.job_role_id, source_id = EXCLUDED.source_id,
    employment_type = EXCLUDED.employment_type, location_text = EXCLUDED.location_text, title = EXCLUDED.title,
    description = EXCLUDED.description, source_url = EXCLUDED.source_url,
    published_at = EXCLUDED.published_at, expires_at = EXCLUDED.expires_at, status = EXCLUDED.status,
    updated_at = timestamptz '2026-11-06 00:00:00+00'
WHERE (career.job_postings.company_id, career.job_postings.job_role_id, career.job_postings.source_id,
       career.job_postings.employment_type, career.job_postings.location_text, career.job_postings.title,
       career.job_postings.description, career.job_postings.source_url, career.job_postings.published_at,
       career.job_postings.expires_at, career.job_postings.status)
      IS DISTINCT FROM
      (EXCLUDED.company_id, EXCLUDED.job_role_id, EXCLUDED.source_id,
       EXCLUDED.employment_type, EXCLUDED.location_text, EXCLUDED.title, EXCLUDED.description,
       EXCLUDED.source_url, EXCLUDED.published_at, EXCLUDED.expires_at, EXCLUDED.status);

-- ---------------------------------------------------------------- 4. link tables
-- 4-1 job_posting_skills: role's top-4 skills; required_level >= 4 required, else preferred.
--     required_level copies the role default (T05 C03 allows NULL = role default; explicit here for tests)
INSERT INTO career.job_posting_skills (job_posting_id, skill_id, is_required, required_level, created_at)
SELECT jp.job_posting_id, jrs.skill_id, (jrs.required_level >= 4), jrs.required_level, timestamptz '2026-11-06 00:00:00+00'
FROM career.job_postings jp
JOIN career.job_role_skills jrs ON jrs.job_role_id = jp.job_role_id AND jrs.required_level >= 2
WHERE jp.job_posting_id IN (
    SELECT md5('seed:job_posting:' || lpad(n::text, 3, '0'))::uuid FROM generate_series(1, 100) AS n)
ON CONFLICT (job_posting_id, skill_id) DO UPDATE
SET is_required = EXCLUDED.is_required, required_level = EXCLUDED.required_level
WHERE (career.job_posting_skills.is_required, career.job_posting_skills.required_level)
      IS DISTINCT FROM (EXCLUDED.is_required, EXCLUDED.required_level);

-- 4-2 user_skills: user g owns the top-3 skills of role ((g-1)%30), proficiency 4,3,2 (one below required)
WITH seed_roles AS (
    SELECT job_role_id, row_number() OVER (ORDER BY code) - 1 AS idx
    FROM career.job_roles
    WHERE job_role_id = md5('seed:job_role:' || code)::uuid
)
INSERT INTO career.user_skills (user_id, skill_id, proficiency, created_at)
SELECT md5('seed:user:' || lpad(g::text, 2, '0'))::uuid, jrs.skill_id,
       (jrs.required_level - 1)::smallint, timestamptz '2026-11-06 00:00:00+00'
FROM generate_series(1, 20) AS g
JOIN seed_roles r ON r.idx = (g - 1) % 30
JOIN career.job_role_skills jrs ON jrs.job_role_id = r.job_role_id AND jrs.required_level >= 3
ON CONFLICT (user_id, skill_id) DO UPDATE
SET proficiency = EXCLUDED.proficiency
WHERE career.user_skills.proficiency IS DISTINCT FROM EXCLUDED.proficiency;

-- 4-3 user_job_bookmarks: active users 1..18 bookmark postings g and g+20 (both published)
INSERT INTO career.user_job_bookmarks (user_id, job_posting_id, created_at)
SELECT md5('seed:user:' || lpad(g::text, 2, '0'))::uuid,
       md5('seed:job_posting:' || lpad(pn::text, 3, '0'))::uuid,
       timestamptz '2026-11-06 00:00:00+00'
FROM generate_series(1, 18) AS g
CROSS JOIN LATERAL (VALUES (g), (g + 20)) AS b(pn)
WHERE pn % 10 NOT IN (0, 9)
ON CONFLICT (user_id, job_posting_id) DO NOTHING;

-- ---------------------------------------------------------------- 5. service roles (T05 A05~A08, "Seed 관리")
-- roles: requirement overview §5 (job_seeker, admin). permissions: only the examples named in
-- DATA_DICTIONARY A06; the full permission list is not decided yet (see README).
INSERT INTO career.roles (role_id, code, name, created_at)
SELECT md5('seed:role:' || v.code)::uuid, v.code, v.name, timestamptz '2026-11-06 00:00:00+00'
FROM (VALUES ('job_seeker', '구직자'), ('admin', '운영 관리자')) AS v(code, name)
ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
WHERE career.roles.name IS DISTINCT FROM EXCLUDED.name;

INSERT INTO career.permissions (permission_id, code, description, created_at)
SELECT md5('seed:permission:' || v.code)::uuid, v.code, v.description, timestamptz '2026-11-06 00:00:00+00'
FROM (VALUES ('admin.models.read', '모델 버전·평가 조회'), ('admin.audit.read', '감사 기록 조회')) AS v(code, description)
ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
WHERE career.permissions.description IS DISTINCT FROM EXCLUDED.description;

INSERT INTO career.role_permissions (role_id, permission_id, created_at)
SELECT r.role_id, p.permission_id, timestamptz '2026-11-06 00:00:00+00'
FROM career.roles r CROSS JOIN career.permissions p
WHERE r.code = 'admin' AND p.code IN ('admin.models.read', 'admin.audit.read')
ON CONFLICT (role_id, permission_id) DO NOTHING;

-- every seed user is a job_seeker (default role, granted_by NULL); seed-user-18 is also admin
INSERT INTO career.user_roles (user_id, role_id, granted_by_user_id, granted_at)
SELECT u.user_id, r.role_id, NULL, timestamptz '2026-11-06 00:00:00+00'
FROM career.users u
JOIN career.roles r ON r.code = 'job_seeker'
                    OR (r.code = 'admin' AND u.email = 'seed-user-18@example.com')
WHERE u.email LIKE 'seed-user-__@example.com'
ON CONFLICT (user_id, role_id) DO NOTHING;

COMMIT;
