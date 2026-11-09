-- Purpose: Create the initial career schema from the T05 data dictionary (Redmine #1522).
-- Recovery: The runner rolls back a failed apply. After commit, use a corrective migration
-- or restore the verified pre-migration backup.
-- Source: database/DATA_DICTIONARY.md, T05 merge a004efb.

CREATE TABLE career.users (
    user_id uuid NOT NULL DEFAULT gen_random_uuid(),
    email varchar(254) NOT NULL,
    email_canonical varchar(254) NOT NULL,
    display_name varchar(100) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'active',
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id),
    CHECK (status IN ('active', 'disabled')),
    CHECK (length(btrim(email)) > 0 AND email = btrim(email)),
    CHECK (email_canonical = lower(email_canonical) AND position('+' in split_part(email_canonical, '@', 1)) = 0)
);
CREATE UNIQUE INDEX ix_users_1 ON career.users (email_canonical);

CREATE TABLE career.roles (
    role_id uuid NOT NULL DEFAULT gen_random_uuid(),
    code varchar(64) NOT NULL UNIQUE,
    name varchar(120) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role_id)
);

CREATE TABLE career.permissions (
    permission_id uuid NOT NULL DEFAULT gen_random_uuid(),
    code varchar(100) NOT NULL UNIQUE,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (permission_id)
);

CREATE TABLE career.job_roles (
    job_role_id uuid NOT NULL DEFAULT gen_random_uuid(),
    code varchar(64) NOT NULL UNIQUE,
    name varchar(160) NOT NULL,
    description text,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_role_id),
    CHECK (length(btrim(code)) > 0)
);

CREATE TABLE career.skills (
    skill_id uuid NOT NULL DEFAULT gen_random_uuid(),
    code varchar(64) NOT NULL UNIQUE,
    name varchar(160) NOT NULL,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (skill_id),
    CHECK (length(btrim(code)) > 0)
);
CREATE INDEX ix_skills_1 ON career.skills (lower(name));

CREATE TABLE career.consent_policies (
    policy_code varchar(80) NOT NULL,
    version varchar(40) NOT NULL,
    is_required boolean NOT NULL,
    content_url text NOT NULL,
    effective_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (policy_code, version)
);

CREATE TABLE career.data_sources (
    source_id uuid NOT NULL DEFAULT gen_random_uuid(),
    code varchar(80) NOT NULL UNIQUE,
    name varchar(160) NOT NULL,
    license_ref text,
    retention_days integer,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id),
    CHECK (retention_days IS NULL OR retention_days > 0),
    CHECK (code = 'synthetic_seed' OR license_ref IS NOT NULL)
);

CREATE TABLE career.model_versions (
    model_version_id uuid NOT NULL DEFAULT gen_random_uuid(),
    model_code varchar(100) NOT NULL,
    version varchar(80) NOT NULL,
    kind varchar(20) NOT NULL,
    artifact_ref text,
    description text,
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model_version_id),
    CHECK (kind IN ('rule', 'ml', 'llm'))
);
CREATE UNIQUE INDEX ix_model_versions_1 ON career.model_versions (model_code, version);

CREATE TABLE career.user_profiles (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    headline varchar(200),
    bio text,
    location_text varchar(120),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id),
    CHECK (bio IS NULL OR length(bio) <= 5000)
);

CREATE TABLE career.auth_identities (
    identity_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    provider varchar(40) NOT NULL,
    subject varchar(255) NOT NULL,
    password_hash text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (identity_id),
    CHECK (provider = 'local' OR password_hash IS NULL)
);
CREATE UNIQUE INDEX ix_auth_identities_1 ON career.auth_identities (provider, subject);
CREATE INDEX ix_auth_identities_2 ON career.auth_identities (user_id);

CREATE TABLE career.auth_sessions (
    session_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    refresh_token_hash char(64) NOT NULL,
    user_agent varchar(300),
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    PRIMARY KEY (session_id),
    CHECK (expires_at > created_at)
);
CREATE UNIQUE INDEX ix_auth_sessions_1 ON career.auth_sessions (refresh_token_hash);
CREATE INDEX ix_auth_sessions_2 ON career.auth_sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE career.role_permissions (
    role_id uuid NOT NULL REFERENCES career.roles (role_id) ON DELETE CASCADE,
    permission_id uuid NOT NULL REFERENCES career.permissions (permission_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (role_id, permission_id)
);
CREATE INDEX ix_role_permissions_1 ON career.role_permissions (permission_id);

CREATE TABLE career.user_roles (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    role_id uuid NOT NULL REFERENCES career.roles (role_id) ON DELETE RESTRICT,
    granted_by_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);
CREATE INDEX ix_user_roles_1 ON career.user_roles (role_id);

CREATE TABLE career.account_deletion_requests (
    request_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    status varchar(20) NOT NULL DEFAULT 'requested',
    requested_at timestamptz NOT NULL DEFAULT now(),
    scheduled_purge_at timestamptz NOT NULL,
    completed_at timestamptz,
    PRIMARY KEY (request_id),
    CHECK (status IN ('requested', 'cancelled', 'completed')),
    CHECK (scheduled_purge_at >= requested_at),
    CHECK (status <> 'completed' OR completed_at IS NOT NULL)
);
CREATE UNIQUE INDEX ix_account_deletion_requests_1 ON career.account_deletion_requests (user_id) WHERE status = 'requested';
CREATE INDEX ix_account_deletion_requests_2 ON career.account_deletion_requests (status, scheduled_purge_at);

CREATE TABLE career.password_reset_tokens (
    token_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    token_hash char(64) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    PRIMARY KEY (token_id),
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '30 minutes'),
    CHECK (used_at IS NULL OR used_at >= created_at)
);
CREATE INDEX ix_password_reset_tokens_1 ON career.password_reset_tokens (user_id) WHERE used_at IS NULL;

CREATE TABLE career.user_consents (
    consent_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    policy_code varchar(80) NOT NULL,
    policy_version varchar(40) NOT NULL,
    granted boolean NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (consent_id),
    FOREIGN KEY (policy_code, policy_version) REFERENCES career.consent_policies (policy_code, version) ON DELETE RESTRICT
);
CREATE INDEX ix_user_consents_1 ON career.user_consents (user_id, policy_code, recorded_at DESC);

CREATE TABLE career.user_experiences (
    experience_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    organization varchar(200) NOT NULL,
    title varchar(200) NOT NULL,
    start_date date,
    end_date date,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (experience_id),
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX ix_user_experiences_1 ON career.user_experiences (user_id);

CREATE TABLE career.user_projects (
    project_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    title varchar(200) NOT NULL,
    summary text,
    start_date date,
    end_date date,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id),
    CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX ix_user_projects_1 ON career.user_projects (user_id);

CREATE TABLE career.job_role_skills (
    job_role_id uuid NOT NULL REFERENCES career.job_roles (job_role_id) ON DELETE CASCADE,
    skill_id uuid NOT NULL REFERENCES career.skills (skill_id) ON DELETE RESTRICT,
    required_level smallint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_role_id, skill_id),
    CHECK (required_level BETWEEN 1 AND 5)
);
CREATE INDEX ix_job_role_skills_1 ON career.job_role_skills (skill_id);

CREATE TABLE career.user_skills (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    skill_id uuid NOT NULL REFERENCES career.skills (skill_id) ON DELETE RESTRICT,
    proficiency smallint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, skill_id),
    CHECK (proficiency BETWEEN 1 AND 5)
);
CREATE INDEX ix_user_skills_1 ON career.user_skills (skill_id);

CREATE TABLE career.user_target_roles (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    job_role_id uuid NOT NULL REFERENCES career.job_roles (job_role_id) ON DELETE RESTRICT,
    priority smallint NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, job_role_id),
    CHECK (priority BETWEEN 1 AND 3)
);
CREATE UNIQUE INDEX ix_user_target_roles_1 ON career.user_target_roles (user_id, priority);
CREATE INDEX ix_user_target_roles_2 ON career.user_target_roles (job_role_id);

CREATE TABLE career.companies (
    company_id uuid NOT NULL DEFAULT gen_random_uuid(),
    name varchar(200) NOT NULL,
    website_url text,
    description text,
    source_id uuid NOT NULL REFERENCES career.data_sources (source_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id),
    CHECK (length(btrim(name)) > 0)
);
CREATE INDEX ix_companies_1 ON career.companies (lower(name));

CREATE TABLE career.ingestion_runs (
    ingestion_run_id uuid NOT NULL DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES career.data_sources (source_id) ON DELETE RESTRICT,
    status varchar(24) NOT NULL DEFAULT 'running',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    fetched_count integer NOT NULL DEFAULT 0,
    error_summary text,
    PRIMARY KEY (ingestion_run_id),
    CHECK (status IN ('running', 'succeeded', 'failed')),
    CHECK (fetched_count >= 0),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
);
CREATE INDEX ix_ingestion_runs_1 ON career.ingestion_runs (source_id, started_at DESC);

CREATE TABLE career.skill_gap_assessments (
    assessment_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    job_role_id uuid NOT NULL REFERENCES career.job_roles (job_role_id) ON DELETE RESTRICT,
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (assessment_id)
);
CREATE INDEX ix_skill_gap_assessments_1 ON career.skill_gap_assessments (user_id, evaluated_at DESC);
CREATE INDEX ix_skill_gap_assessments_2 ON career.skill_gap_assessments (job_role_id);
CREATE INDEX ix_skill_gap_assessments_3 ON career.skill_gap_assessments (model_version_id);

CREATE TABLE career.recommendation_runs (
    recommendation_run_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    status varchar(20) NOT NULL DEFAULT 'completed',
    generated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (recommendation_run_id),
    CHECK (status IN ('pending', 'completed', 'failed', 'fallback'))
);
CREATE INDEX ix_recommendation_runs_1 ON career.recommendation_runs (user_id, generated_at DESC);
CREATE INDEX ix_recommendation_runs_2 ON career.recommendation_runs (model_version_id);

CREATE TABLE career.user_documents (
    document_id uuid NOT NULL DEFAULT gen_random_uuid(),
    owner_user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    kind varchar(40) NOT NULL,
    original_filename varchar(255) NOT NULL,
    mime_type varchar(100) NOT NULL,
    size_bytes bigint NOT NULL,
    storage_key varchar(64) NOT NULL,
    checksum_sha256 char(64) NOT NULL,
    visibility varchar(24) NOT NULL DEFAULT 'private',
    status varchar(20) NOT NULL DEFAULT 'uploaded',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (document_id),
    CHECK (kind IN ('resume', 'portfolio', 'career_guide')),
    CHECK (visibility IN ('private', 'shared')),
    CHECK (status IN ('uploaded', 'scanning', 'ready', 'rejected', 'deleting')),
    CHECK (size_bytes > 0),
    CHECK (storage_key ~ '^[0-9a-f]{32,64}$')
);
CREATE UNIQUE INDEX ix_user_documents_1 ON career.user_documents (storage_key);
CREATE INDEX ix_user_documents_2 ON career.user_documents (owner_user_id, created_at DESC);
CREATE INDEX ix_user_documents_3 ON career.user_documents (visibility) WHERE visibility = 'shared';

CREATE TABLE career.retrieval_runs (
    retrieval_run_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    model_version_id uuid REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    query_hash char(64) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'running',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    PRIMARY KEY (retrieval_run_id),
    CHECK (status IN ('running', 'answered', 'no_evidence', 'failed'))
);
CREATE INDEX ix_retrieval_runs_1 ON career.retrieval_runs (user_id, started_at DESC);
CREATE INDEX ix_retrieval_runs_2 ON career.retrieval_runs (model_version_id);

CREATE TABLE career.agent_runs (
    agent_run_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    workflow_code varchar(80) NOT NULL,
    idempotency_key varchar(100),
    status varchar(24) NOT NULL DEFAULT 'queued',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    PRIMARY KEY (agent_run_id),
    CHECK (status IN ('queued', 'running', 'awaiting_approval', 'succeeded', 'failed', 'rejected', 'timed_out'))
);
CREATE UNIQUE INDEX ix_agent_runs_1 ON career.agent_runs (user_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_agent_runs_2 ON career.agent_runs (user_id, started_at DESC);

CREATE TABLE career.model_evaluations (
    model_evaluation_id uuid NOT NULL DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE CASCADE,
    dataset_ref text NOT NULL,
    metric_code varchar(80) NOT NULL,
    metric_value numeric NOT NULL,
    leakage_checked boolean NOT NULL DEFAULT false,
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (model_evaluation_id)
);
CREATE INDEX ix_model_evaluations_1 ON career.model_evaluations (model_version_id, metric_code);

CREATE TABLE career.market_observations (
    observation_id uuid NOT NULL DEFAULT gen_random_uuid(),
    source_id uuid NOT NULL REFERENCES career.data_sources (source_id) ON DELETE RESTRICT,
    job_role_id uuid REFERENCES career.job_roles (job_role_id) ON DELETE RESTRICT,
    observed_on date NOT NULL,
    period varchar(10) NOT NULL,
    metric_code varchar(80) NOT NULL,
    metric_value numeric NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (observation_id),
    CHECK (period IN ('day', 'week', 'month'))
);
CREATE UNIQUE INDEX ix_market_observations_1 ON career.market_observations (source_id, job_role_id, metric_code, period, observed_on);
CREATE INDEX ix_market_observations_2 ON career.market_observations (job_role_id, metric_code, observed_on);

CREATE TABLE career.market_forecasts (
    forecast_id uuid NOT NULL DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    job_role_id uuid REFERENCES career.job_roles (job_role_id) ON DELETE RESTRICT,
    forecast_for date NOT NULL,
    metric_code varchar(80) NOT NULL,
    predicted_value numeric NOT NULL,
    lower_bound numeric,
    upper_bound numeric,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (forecast_id),
    CHECK (lower_bound IS NULL OR upper_bound IS NULL OR lower_bound <= upper_bound)
);
CREATE INDEX ix_market_forecasts_1 ON career.market_forecasts (model_version_id);
CREATE INDEX ix_market_forecasts_2 ON career.market_forecasts (job_role_id, metric_code, forecast_for);

CREATE TABLE career.behavior_events (
    event_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    event_code varchar(80) NOT NULL,
    event_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb,
    PRIMARY KEY (event_id)
);
CREATE INDEX ix_behavior_events_1 ON career.behavior_events (user_id, event_at DESC);
CREATE INDEX ix_behavior_events_2 ON career.behavior_events (event_code, event_at);

CREATE TABLE career.user_segments (
    segment_id uuid NOT NULL DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    segment_code varchar(80) NOT NULL,
    label varchar(160) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (segment_id)
);
CREATE UNIQUE INDEX ix_user_segments_1 ON career.user_segments (model_version_id, segment_code);

CREATE TABLE career.audit_events (
    audit_event_id uuid NOT NULL DEFAULT gen_random_uuid(),
    actor_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    action_code varchar(100) NOT NULL,
    resource_type varchar(80) NOT NULL,
    resource_id uuid,
    request_id varchar(64),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (audit_event_id)
);
CREATE INDEX ix_audit_events_1 ON career.audit_events (occurred_at DESC);
CREATE INDEX ix_audit_events_2 ON career.audit_events (actor_user_id, occurred_at DESC);
CREATE INDEX ix_audit_events_3 ON career.audit_events (action_code, occurred_at DESC);

CREATE TABLE career.ai_usage_records (
    usage_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    model_version_id uuid REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    provider_model varchar(100) NOT NULL,
    feature_code varchar(40) NOT NULL,
    input_tokens integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    estimated_cost_usd numeric(18,6) NOT NULL DEFAULT 0,
    latency_ms integer,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (usage_id),
    CHECK (feature_code IN ('document_analysis', 'rag_answer', 'agent')),
    CHECK (input_tokens >= 0 AND output_tokens >= 0 AND estimated_cost_usd >= 0),
    CHECK (latency_ms IS NULL OR latency_ms >= 0)
);
CREATE INDEX ix_ai_usage_records_1 ON career.ai_usage_records (occurred_at DESC);
CREATE INDEX ix_ai_usage_records_2 ON career.ai_usage_records (user_id, occurred_at DESC);
CREATE INDEX ix_ai_usage_records_3 ON career.ai_usage_records (model_version_id);

CREATE TABLE career.user_project_skills (
    project_id uuid NOT NULL REFERENCES career.user_projects (project_id) ON DELETE CASCADE,
    skill_id uuid NOT NULL REFERENCES career.skills (skill_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, skill_id)
);
CREATE INDEX ix_user_project_skills_1 ON career.user_project_skills (skill_id);

CREATE TABLE career.job_postings (
    job_posting_id uuid NOT NULL DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES career.companies (company_id) ON DELETE RESTRICT,
    job_role_id uuid REFERENCES career.job_roles (job_role_id) ON DELETE RESTRICT,
    source_id uuid NOT NULL REFERENCES career.data_sources (source_id) ON DELETE RESTRICT,
    title varchar(240) NOT NULL,
    description text,
    employment_type varchar(24),
    location_text varchar(120),
    source_url text,
    status varchar(20) NOT NULL DEFAULT 'draft',
    published_at timestamptz,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_posting_id),
    CHECK (length(btrim(title)) > 0),
    CHECK (status IN ('draft', 'published', 'closed')),
    CHECK (employment_type IS NULL OR employment_type IN ('full_time', 'contract', 'intern', 'part_time')),
    CHECK (published_at IS NULL OR expires_at IS NULL OR expires_at >= published_at),
    CHECK (status <> 'published' OR published_at IS NOT NULL)
);
CREATE INDEX ix_job_postings_1 ON career.job_postings (company_id);
CREATE INDEX ix_job_postings_2 ON career.job_postings (job_role_id);
CREATE INDEX ix_job_postings_3 ON career.job_postings (status, published_at DESC);

CREATE TABLE career.skill_gap_items (
    assessment_id uuid NOT NULL REFERENCES career.skill_gap_assessments (assessment_id) ON DELETE CASCADE,
    skill_id uuid NOT NULL REFERENCES career.skills (skill_id) ON DELETE RESTRICT,
    required_level smallint NOT NULL,
    observed_level smallint NOT NULL,
    gap smallint NOT NULL,
    PRIMARY KEY (assessment_id, skill_id),
    CHECK (required_level BETWEEN 1 AND 5),
    CHECK (observed_level BETWEEN 0 AND 5),
    CHECK (gap = greatest(required_level - observed_level, 0))
);
CREATE INDEX ix_skill_gap_items_1 ON career.skill_gap_items (skill_id);

CREATE TABLE career.document_analyses (
    analysis_id uuid NOT NULL DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES career.user_documents (document_id) ON DELETE CASCADE,
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    analysis_type varchar(40) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'queued',
    result jsonb,
    error_code varchar(60),
    requested_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY (analysis_id),
    CHECK (analysis_type IN ('skill_extraction', 'summary')),
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    CHECK (status <> 'succeeded' OR result IS NOT NULL)
);
CREATE INDEX ix_document_analyses_1 ON career.document_analyses (document_id, requested_at DESC);
CREATE INDEX ix_document_analyses_2 ON career.document_analyses (model_version_id);

CREATE TABLE career.document_chunks (
    chunk_id uuid NOT NULL DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES career.user_documents (document_id) ON DELETE CASCADE,
    chunk_index integer NOT NULL,
    content_hash char(64) NOT NULL,
    index_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (chunk_id),
    CHECK (chunk_index >= 0)
);
CREATE UNIQUE INDEX ix_document_chunks_1 ON career.document_chunks (document_id, chunk_index);

CREATE TABLE career.agent_tool_approvals (
    approval_id uuid NOT NULL DEFAULT gen_random_uuid(),
    agent_run_id uuid NOT NULL REFERENCES career.agent_runs (agent_run_id) ON DELETE CASCADE,
    tool_code varchar(100) NOT NULL,
    decision varchar(24) NOT NULL DEFAULT 'pending',
    approver_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    reason text,
    requested_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (approval_id),
    CHECK (decision IN ('pending', 'approved', 'rejected', 'expired')),
    CHECK (decision = 'pending' OR decided_at IS NOT NULL)
);
CREATE INDEX ix_agent_tool_approvals_1 ON career.agent_tool_approvals (agent_run_id);
CREATE INDEX ix_agent_tool_approvals_2 ON career.agent_tool_approvals (approver_user_id);

CREATE TABLE career.user_segment_assignments (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    segment_id uuid NOT NULL REFERENCES career.user_segments (segment_id) ON DELETE CASCADE,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, segment_id)
);
CREATE INDEX ix_user_segment_assignments_1 ON career.user_segment_assignments (segment_id);

CREATE TABLE career.anomaly_events (
    anomaly_id uuid NOT NULL DEFAULT gen_random_uuid(),
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    event_id uuid REFERENCES career.behavior_events (event_id) ON DELETE SET NULL,
    score numeric,
    status varchar(20) NOT NULL DEFAULT 'open',
    detected_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (anomaly_id),
    CHECK (status IN ('open', 'false_positive', 'resolved'))
);
CREATE INDEX ix_anomaly_events_1 ON career.anomaly_events (status, detected_at DESC);
CREATE INDEX ix_anomaly_events_2 ON career.anomaly_events (model_version_id);
CREATE INDEX ix_anomaly_events_3 ON career.anomaly_events (event_id);

CREATE TABLE career.job_posting_skills (
    job_posting_id uuid NOT NULL REFERENCES career.job_postings (job_posting_id) ON DELETE CASCADE,
    skill_id uuid NOT NULL REFERENCES career.skills (skill_id) ON DELETE RESTRICT,
    is_required boolean NOT NULL DEFAULT true,
    required_level smallint,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_posting_id, skill_id),
    CHECK (required_level BETWEEN 1 AND 5)
);
CREATE INDEX ix_job_posting_skills_1 ON career.job_posting_skills (skill_id);

CREATE TABLE career.user_job_bookmarks (
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    job_posting_id uuid NOT NULL REFERENCES career.job_postings (job_posting_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, job_posting_id)
);
CREATE INDEX ix_user_job_bookmarks_1 ON career.user_job_bookmarks (job_posting_id);
CREATE INDEX ix_user_job_bookmarks_2 ON career.user_job_bookmarks (user_id, created_at DESC);

CREATE TABLE career.job_posting_external_refs (
    source_id uuid NOT NULL REFERENCES career.data_sources (source_id) ON DELETE RESTRICT,
    external_id varchar(240) NOT NULL,
    job_posting_id uuid NOT NULL REFERENCES career.job_postings (job_posting_id) ON DELETE CASCADE,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, external_id)
);
CREATE INDEX ix_job_posting_external_refs_1 ON career.job_posting_external_refs (job_posting_id);

CREATE TABLE career.match_evaluations (
    match_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    job_posting_id uuid REFERENCES career.job_postings (job_posting_id) ON DELETE CASCADE,
    job_role_id uuid REFERENCES career.job_roles (job_role_id) ON DELETE RESTRICT,
    model_version_id uuid NOT NULL REFERENCES career.model_versions (model_version_id) ON DELETE RESTRICT,
    status varchar(20) NOT NULL DEFAULT 'completed',
    score numeric(5,2),
    matched_skill_count smallint,
    missing_skill_count smallint,
    limitations text,
    evaluated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id),
    CHECK (num_nonnulls(job_posting_id, job_role_id) = 1),
    CHECK (status IN ('pending', 'completed', 'failed')),
    CHECK (score IS NULL OR score BETWEEN 0 AND 100),
    CHECK (status <> 'completed' OR score IS NOT NULL)
);
CREATE INDEX ix_match_evaluations_1 ON career.match_evaluations (user_id, evaluated_at DESC);
CREATE INDEX ix_match_evaluations_2 ON career.match_evaluations (job_posting_id);
CREATE INDEX ix_match_evaluations_3 ON career.match_evaluations (job_role_id);
CREATE INDEX ix_match_evaluations_4 ON career.match_evaluations (model_version_id);

CREATE TABLE career.recommendation_items (
    recommendation_run_id uuid NOT NULL REFERENCES career.recommendation_runs (recommendation_run_id) ON DELETE CASCADE,
    job_posting_id uuid NOT NULL REFERENCES career.job_postings (job_posting_id) ON DELETE CASCADE,
    rank integer NOT NULL,
    score numeric(5,2),
    reason text NOT NULL,
    PRIMARY KEY (recommendation_run_id, job_posting_id),
    CHECK (rank >= 1),
    CHECK (score IS NULL OR score BETWEEN 0 AND 100),
    CHECK (length(btrim(reason)) > 0)
);
CREATE UNIQUE INDEX ix_recommendation_items_1 ON career.recommendation_items (recommendation_run_id, rank);
CREATE INDEX ix_recommendation_items_2 ON career.recommendation_items (job_posting_id);

CREATE TABLE career.recommendation_feedback (
    feedback_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    recommendation_run_id uuid REFERENCES career.recommendation_runs (recommendation_run_id) ON DELETE SET NULL,
    job_posting_id uuid NOT NULL REFERENCES career.job_postings (job_posting_id) ON DELETE CASCADE,
    feedback varchar(24) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (feedback_id),
    CHECK (feedback IN ('liked', 'not_interested', 'cleared'))
);
CREATE INDEX ix_recommendation_feedback_1 ON career.recommendation_feedback (user_id, job_posting_id, created_at DESC);
CREATE INDEX ix_recommendation_feedback_2 ON career.recommendation_feedback (recommendation_run_id);
CREATE INDEX ix_recommendation_feedback_3 ON career.recommendation_feedback (job_posting_id);

CREATE TABLE career.retrieval_citations (
    retrieval_run_id uuid NOT NULL REFERENCES career.retrieval_runs (retrieval_run_id) ON DELETE CASCADE,
    chunk_id uuid NOT NULL REFERENCES career.document_chunks (chunk_id) ON DELETE CASCADE,
    rank integer NOT NULL,
    score numeric(8,5),
    PRIMARY KEY (retrieval_run_id, chunk_id),
    CHECK (rank >= 1)
);
CREATE UNIQUE INDEX ix_retrieval_citations_1 ON career.retrieval_citations (retrieval_run_id, rank);
CREATE INDEX ix_retrieval_citations_2 ON career.retrieval_citations (chunk_id);

CREATE TABLE career.agent_tool_calls (
    tool_call_id uuid NOT NULL DEFAULT gen_random_uuid(),
    agent_run_id uuid NOT NULL REFERENCES career.agent_runs (agent_run_id) ON DELETE CASCADE,
    approval_id uuid REFERENCES career.agent_tool_approvals (approval_id) ON DELETE RESTRICT,
    tool_code varchar(100) NOT NULL,
    status varchar(24) NOT NULL DEFAULT 'running',
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    PRIMARY KEY (tool_call_id),
    CHECK (status IN ('running', 'succeeded', 'failed'))
);
CREATE INDEX ix_agent_tool_calls_1 ON career.agent_tool_calls (agent_run_id);
CREATE INDEX ix_agent_tool_calls_2 ON career.agent_tool_calls (approval_id);
