-- AI Career Platform / D2 preparation (D1-8)
-- STATUS: DRAFT ONLY. NOT APPROVED. NOT EXECUTED.
-- REQUIRES: approved MVP contract, verified backup/restore,
--           PostgreSQL 18.1, career schema owned by approved migrator.
-- CAUTION: DO NOT run this on live Staging until D1 approval.
-- Schema / roles / privileges / seed / revision ledger are intentionally NOT managed here.
-- This file is one non-idempotent initial migration candidate; running twice should fail.
-- Applied by a separately authorized migrator within controlled maintenance.
BEGIN;

CREATE TABLE career.users (
    user_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(254) NOT NULL UNIQUE,
    display_name varchar(100) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled')),
    CONSTRAINT users_email_not_blank CHECK (length(btrim(email)) > 0)
);

CREATE TABLE career.user_profiles (
    user_id uuid PRIMARY KEY REFERENCES career.users(user_id) ON DELETE RESTRICT,
    headline varchar(200),
    bio text,
    location_text varchar(120),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE career.companies (
    company_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(200) NOT NULL,
    website_url text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT companies_name_not_blank CHECK (length(btrim(name)) > 0)
);

CREATE TABLE career.job_roles (
    job_role_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code varchar(64) NOT NULL UNIQUE,
    name varchar(160) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT job_roles_code_not_blank CHECK (length(btrim(code)) > 0)
);

CREATE TABLE career.skills (
    skill_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code varchar(64) NOT NULL UNIQUE,
    name varchar(160) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT skills_code_not_blank CHECK (length(btrim(code)) > 0)
);

CREATE TABLE career.job_role_skills (
    job_role_id uuid NOT NULL REFERENCES career.job_roles(job_role_id) ON DELETE RESTRICT,
    skill_id uuid NOT NULL REFERENCES career.skills(skill_id) ON DELETE RESTRICT,
    importance smallint,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_role_id, skill_id),
    CONSTRAINT job_role_skills_importance_check CHECK (importance BETWEEN 1 AND 5)
);

CREATE TABLE career.user_skills (
    user_id uuid NOT NULL REFERENCES career.users(user_id) ON DELETE RESTRICT,
    skill_id uuid NOT NULL REFERENCES career.skills(skill_id) ON DELETE RESTRICT,
    proficiency smallint,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, skill_id),
    CONSTRAINT user_skills_proficiency_check CHECK (proficiency BETWEEN 1 AND 5)
);

CREATE TABLE career.job_postings (
    job_posting_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES career.companies(company_id) ON DELETE RESTRICT,
    job_role_id uuid REFERENCES career.job_roles(job_role_id) ON DELETE RESTRICT,
    title varchar(240) NOT NULL,
    description text,
    source_url text,
    published_at timestamptz,
    expires_at timestamptz,
    status varchar(20) NOT NULL DEFAULT 'draft',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT job_postings_title_not_blank CHECK (length(btrim(title)) > 0),
    CONSTRAINT job_postings_status_check CHECK (status IN ('draft', 'published', 'closed')),
    CONSTRAINT job_postings_date_check CHECK (
        published_at IS NULL OR expires_at IS NULL OR expires_at >= published_at
    )
);

CREATE TABLE career.job_posting_skills (
    job_posting_id uuid NOT NULL REFERENCES career.job_postings(job_posting_id) ON DELETE RESTRICT,
    skill_id uuid NOT NULL REFERENCES career.skills(skill_id) ON DELETE RESTRICT,
    is_required boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_posting_id, skill_id)
);

CREATE TABLE career.user_job_bookmarks (
    user_id uuid NOT NULL REFERENCES career.users(user_id) ON DELETE RESTRICT,
    job_posting_id uuid NOT NULL REFERENCES career.job_postings(job_posting_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, job_posting_id)
);

-- FK referencing columns are not automatically indexed by PostgreSQL.
-- Optional index choices here are based on common relationship lookups,
-- not measured query plans. Reassess before approval.
CREATE INDEX ix_job_postings_company_id ON career.job_postings (company_id);
CREATE INDEX ix_job_postings_job_role_id ON career.job_postings (job_role_id);
CREATE INDEX ix_job_role_skills_skill_id ON career.job_role_skills (skill_id);
CREATE INDEX ix_user_skills_skill_id ON career.user_skills (skill_id);
CREATE INDEX ix_job_posting_skills_skill_id ON career.job_posting_skills (skill_id);
CREATE INDEX ix_user_job_bookmarks_job_posting_id ON career.user_job_bookmarks (job_posting_id);

COMMIT;
