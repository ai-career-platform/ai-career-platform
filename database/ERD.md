# AI Career Platform — 전체 ERD v0.2

> **자동 생성 파일 — 직접 수정하지 마세요.** 원본: [DATA_DICTIONARY.md](DATA_DICTIONARY.md) · 재생성: `python3 database/model/check_data_dictionary.py --write-erd`
> 테이블 50개, FK 75개. 영역별 그림은 영역 안의 테이블과, 다른 영역 테이블로 향하는 FK를 함께 보여줍니다.

## A. 계정·인증·권한

```mermaid
erDiagram
    USERS {
        uuid user_id PK
        varchar email
        varchar display_name
        varchar status
        timestamptz last_login_at
        timestamptz created_at
        timestamptz updated_at
    }
    USER_PROFILES {
        uuid user_id PK
        varchar headline
        text bio
        varchar location_text
        timestamptz created_at
        timestamptz updated_at
    }
    AUTH_IDENTITIES {
        uuid identity_id PK
        uuid user_id FK
        varchar provider
        varchar subject
        text password_hash
        timestamptz created_at
        timestamptz updated_at
    }
    AUTH_SESSIONS {
        uuid session_id PK
        uuid user_id FK
        char refresh_token_hash
        varchar user_agent
        timestamptz created_at
        timestamptz expires_at
        timestamptz revoked_at
    }
    ROLES {
        uuid role_id PK
        varchar code UK
        varchar name
        timestamptz created_at
    }
    PERMISSIONS {
        uuid permission_id PK
        varchar code UK
        text description
        timestamptz created_at
    }
    ROLE_PERMISSIONS {
        uuid role_id PK
        uuid permission_id PK
        timestamptz created_at
    }
    USER_ROLES {
        uuid user_id PK
        uuid role_id PK
        uuid granted_by_user_id FK
        timestamptz granted_at
    }
    ACCOUNT_DELETION_REQUESTS {
        uuid request_id PK
        uuid user_id FK
        varchar status
        timestamptz requested_at
        timestamptz scheduled_purge_at
        timestamptz completed_at
    }
    USERS ||--o| USER_PROFILES : user_id
    USERS ||--o{ AUTH_IDENTITIES : user_id
    USERS ||--o{ AUTH_SESSIONS : user_id
    ROLES ||--o{ ROLE_PERMISSIONS : role_id
    PERMISSIONS ||--o{ ROLE_PERMISSIONS : permission_id
    USERS ||--o{ USER_ROLES : user_id
    ROLES ||--o{ USER_ROLES : role_id
    USERS o|--o{ USER_ROLES : granted_by_user_id
    USERS o|--o{ ACCOUNT_DELETION_REQUESTS : user_id
```

## B. 동의·경력·역량·직무

```mermaid
erDiagram
    CONSENT_POLICIES {
        varchar policy_code PK
        varchar version PK
        boolean is_required
        text content_url
        timestamptz effective_at
        timestamptz created_at
    }
    USER_CONSENTS {
        uuid consent_id PK
        uuid user_id FK
        varchar policy_code
        varchar policy_version
        boolean granted
        timestamptz recorded_at
    }
    USER_EXPERIENCES {
        uuid experience_id PK
        uuid user_id FK
        varchar organization
        varchar title
        date start_date
        date end_date
        text description
        timestamptz created_at
        timestamptz updated_at
    }
    USER_PROJECTS {
        uuid project_id PK
        uuid user_id FK
        varchar title
        text summary
        date start_date
        date end_date
        timestamptz created_at
        timestamptz updated_at
    }
    USER_PROJECT_SKILLS {
        uuid project_id PK
        uuid skill_id PK
        timestamptz created_at
    }
    JOB_ROLES {
        uuid job_role_id PK
        varchar code UK
        varchar name
        text description
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }
    SKILLS {
        uuid skill_id PK
        varchar code UK
        varchar name
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }
    JOB_ROLE_SKILLS {
        uuid job_role_id PK
        uuid skill_id PK
        smallint required_level
        timestamptz created_at
    }
    USER_SKILLS {
        uuid user_id PK
        uuid skill_id PK
        smallint proficiency
        timestamptz created_at
        timestamptz updated_at
    }
    USER_TARGET_ROLES {
        uuid user_id PK
        uuid job_role_id PK
        smallint priority
        timestamptz created_at
        timestamptz updated_at
    }
    USERS ||--o{ USER_CONSENTS : user_id
    CONSENT_POLICIES ||--o{ USER_CONSENTS : "policy_code, policy_version"
    USERS ||--o{ USER_EXPERIENCES : user_id
    USERS ||--o{ USER_PROJECTS : user_id
    USER_PROJECTS ||--o{ USER_PROJECT_SKILLS : project_id
    SKILLS ||--o{ USER_PROJECT_SKILLS : skill_id
    JOB_ROLES ||--o{ JOB_ROLE_SKILLS : job_role_id
    SKILLS ||--o{ JOB_ROLE_SKILLS : skill_id
    USERS ||--o{ USER_SKILLS : user_id
    SKILLS ||--o{ USER_SKILLS : skill_id
    USERS ||--o{ USER_TARGET_ROLES : user_id
    JOB_ROLES ||--o{ USER_TARGET_ROLES : job_role_id
```

## C. 기업·공고·데이터 출처

```mermaid
erDiagram
    DATA_SOURCES {
        uuid source_id PK
        varchar code UK
        varchar name
        text license_ref
        integer retention_days
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }
    COMPANIES {
        uuid company_id PK
        varchar name
        text website_url
        text description
        uuid source_id FK
        timestamptz created_at
        timestamptz updated_at
    }
    JOB_POSTINGS {
        uuid job_posting_id PK
        uuid company_id FK
        uuid job_role_id FK
        uuid source_id FK
        varchar title
        text description
        varchar employment_type
        varchar location_text
        text source_url
        varchar status
        timestamptz published_at
        timestamptz expires_at
        timestamptz created_at
        timestamptz updated_at
    }
    JOB_POSTING_SKILLS {
        uuid job_posting_id PK
        uuid skill_id PK
        boolean is_required
        smallint required_level
        timestamptz created_at
    }
    USER_JOB_BOOKMARKS {
        uuid user_id PK
        uuid job_posting_id PK
        timestamptz created_at
    }
    JOB_POSTING_EXTERNAL_REFS {
        uuid source_id PK
        varchar external_id PK
        uuid job_posting_id FK
        timestamptz first_seen_at
        timestamptz last_seen_at
    }
    INGESTION_RUNS {
        uuid ingestion_run_id PK
        uuid source_id FK
        varchar status
        timestamptz started_at
        timestamptz ended_at
        integer fetched_count
        text error_summary
    }
    DATA_SOURCES ||--o{ COMPANIES : source_id
    COMPANIES ||--o{ JOB_POSTINGS : company_id
    JOB_ROLES o|--o{ JOB_POSTINGS : job_role_id
    DATA_SOURCES ||--o{ JOB_POSTINGS : source_id
    JOB_POSTINGS ||--o{ JOB_POSTING_SKILLS : job_posting_id
    SKILLS ||--o{ JOB_POSTING_SKILLS : skill_id
    USERS ||--o{ USER_JOB_BOOKMARKS : user_id
    JOB_POSTINGS ||--o{ USER_JOB_BOOKMARKS : job_posting_id
    DATA_SOURCES ||--o{ JOB_POSTING_EXTERNAL_REFS : source_id
    JOB_POSTINGS ||--o{ JOB_POSTING_EXTERNAL_REFS : job_posting_id
    DATA_SOURCES ||--o{ INGESTION_RUNS : source_id
```

## D. 매칭·Skill Gap·추천·모델

```mermaid
erDiagram
    MODEL_VERSIONS {
        uuid model_version_id PK
        varchar model_code
        varchar version
        varchar kind
        text artifact_ref
        text description
        timestamptz approved_at
        timestamptz created_at
    }
    MATCH_EVALUATIONS {
        uuid match_id PK
        uuid user_id FK
        uuid job_posting_id FK
        uuid job_role_id FK
        uuid model_version_id FK
        varchar status
        numeric score
        smallint matched_skill_count
        smallint missing_skill_count
        text limitations
        timestamptz evaluated_at
    }
    SKILL_GAP_ASSESSMENTS {
        uuid assessment_id PK
        uuid user_id FK
        uuid job_role_id FK
        uuid model_version_id FK
        timestamptz evaluated_at
    }
    SKILL_GAP_ITEMS {
        uuid assessment_id PK
        uuid skill_id PK
        smallint required_level
        smallint observed_level
        smallint gap
    }
    RECOMMENDATION_RUNS {
        uuid recommendation_run_id PK
        uuid user_id FK
        uuid model_version_id FK
        varchar status
        timestamptz generated_at
    }
    RECOMMENDATION_ITEMS {
        uuid recommendation_run_id PK
        uuid job_posting_id PK
        integer rank
        numeric score
        text reason
    }
    RECOMMENDATION_FEEDBACK {
        uuid feedback_id PK
        uuid user_id FK
        uuid recommendation_run_id FK
        uuid job_posting_id FK
        varchar feedback
        timestamptz created_at
    }
    MODEL_EVALUATIONS {
        uuid model_evaluation_id PK
        uuid model_version_id FK
        text dataset_ref
        varchar metric_code
        numeric metric_value
        boolean leakage_checked
        timestamptz evaluated_at
    }
    USERS ||--o{ MATCH_EVALUATIONS : user_id
    JOB_POSTINGS o|--o{ MATCH_EVALUATIONS : job_posting_id
    JOB_ROLES o|--o{ MATCH_EVALUATIONS : job_role_id
    MODEL_VERSIONS ||--o{ MATCH_EVALUATIONS : model_version_id
    USERS ||--o{ SKILL_GAP_ASSESSMENTS : user_id
    JOB_ROLES ||--o{ SKILL_GAP_ASSESSMENTS : job_role_id
    MODEL_VERSIONS ||--o{ SKILL_GAP_ASSESSMENTS : model_version_id
    SKILL_GAP_ASSESSMENTS ||--o{ SKILL_GAP_ITEMS : assessment_id
    SKILLS ||--o{ SKILL_GAP_ITEMS : skill_id
    USERS ||--o{ RECOMMENDATION_RUNS : user_id
    MODEL_VERSIONS ||--o{ RECOMMENDATION_RUNS : model_version_id
    RECOMMENDATION_RUNS ||--o{ RECOMMENDATION_ITEMS : recommendation_run_id
    JOB_POSTINGS ||--o{ RECOMMENDATION_ITEMS : job_posting_id
    USERS ||--o{ RECOMMENDATION_FEEDBACK : user_id
    RECOMMENDATION_RUNS o|--o{ RECOMMENDATION_FEEDBACK : recommendation_run_id
    JOB_POSTINGS ||--o{ RECOMMENDATION_FEEDBACK : job_posting_id
    MODEL_VERSIONS ||--o{ MODEL_EVALUATIONS : model_version_id
```

## E. 문서·RAG

```mermaid
erDiagram
    USER_DOCUMENTS {
        uuid document_id PK
        uuid owner_user_id FK
        varchar kind
        varchar original_filename
        varchar mime_type
        bigint size_bytes
        text storage_key
        char checksum_sha256
        varchar visibility
        varchar status
        timestamptz created_at
        timestamptz updated_at
    }
    DOCUMENT_ANALYSES {
        uuid analysis_id PK
        uuid document_id FK
        uuid model_version_id FK
        varchar analysis_type
        varchar status
        jsonb result
        varchar error_code
        timestamptz requested_at
        timestamptz completed_at
    }
    DOCUMENT_CHUNKS {
        uuid chunk_id PK
        uuid document_id FK
        integer chunk_index
        char content_hash
        text index_ref
        timestamptz created_at
    }
    RETRIEVAL_RUNS {
        uuid retrieval_run_id PK
        uuid user_id FK
        uuid model_version_id FK
        char query_hash
        varchar status
        timestamptz started_at
        timestamptz ended_at
    }
    RETRIEVAL_CITATIONS {
        uuid retrieval_run_id PK
        uuid chunk_id PK
        integer rank
        numeric score
    }
    USERS ||--o{ USER_DOCUMENTS : owner_user_id
    USER_DOCUMENTS ||--o{ DOCUMENT_ANALYSES : document_id
    MODEL_VERSIONS ||--o{ DOCUMENT_ANALYSES : model_version_id
    USER_DOCUMENTS ||--o{ DOCUMENT_CHUNKS : document_id
    USERS ||--o{ RETRIEVAL_RUNS : user_id
    MODEL_VERSIONS o|--o{ RETRIEVAL_RUNS : model_version_id
    RETRIEVAL_RUNS ||--o{ RETRIEVAL_CITATIONS : retrieval_run_id
    DOCUMENT_CHUNKS ||--o{ RETRIEVAL_CITATIONS : chunk_id
```

## F. Agent·시장·행동 분석·운영

```mermaid
erDiagram
    AGENT_RUNS {
        uuid agent_run_id PK
        uuid user_id FK
        varchar workflow_code
        varchar idempotency_key
        varchar status
        timestamptz started_at
        timestamptz ended_at
    }
    AGENT_TOOL_APPROVALS {
        uuid approval_id PK
        uuid agent_run_id FK
        varchar tool_code
        varchar decision
        uuid approver_user_id FK
        text reason
        timestamptz requested_at
        timestamptz decided_at
        timestamptz expires_at
    }
    AGENT_TOOL_CALLS {
        uuid tool_call_id PK
        uuid agent_run_id FK
        uuid approval_id FK
        varchar tool_code
        varchar status
        timestamptz started_at
        timestamptz ended_at
    }
    MARKET_OBSERVATIONS {
        uuid observation_id PK
        uuid source_id FK
        uuid job_role_id FK
        date observed_on
        varchar period
        varchar metric_code
        numeric metric_value
        timestamptz created_at
    }
    MARKET_FORECASTS {
        uuid forecast_id PK
        uuid model_version_id FK
        uuid job_role_id FK
        date forecast_for
        varchar metric_code
        numeric predicted_value
        numeric lower_bound
        numeric upper_bound
        timestamptz created_at
    }
    BEHAVIOR_EVENTS {
        uuid event_id PK
        uuid user_id FK
        varchar event_code
        timestamptz event_at
        jsonb metadata
    }
    USER_SEGMENTS {
        uuid segment_id PK
        uuid model_version_id FK
        varchar segment_code
        varchar label
        timestamptz created_at
    }
    USER_SEGMENT_ASSIGNMENTS {
        uuid user_id PK
        uuid segment_id PK
        timestamptz assigned_at
    }
    ANOMALY_EVENTS {
        uuid anomaly_id PK
        uuid model_version_id FK
        uuid event_id FK
        numeric score
        varchar status
        timestamptz detected_at
    }
    AUDIT_EVENTS {
        uuid audit_event_id PK
        uuid actor_user_id FK
        varchar action_code
        varchar resource_type
        uuid resource_id
        varchar request_id
        timestamptz occurred_at
    }
    AI_USAGE_RECORDS {
        uuid usage_id PK
        uuid user_id FK
        uuid model_version_id FK
        varchar provider_model
        varchar feature_code
        integer input_tokens
        integer output_tokens
        numeric estimated_cost_usd
        integer latency_ms
        timestamptz occurred_at
    }
    USERS ||--o{ AGENT_RUNS : user_id
    AGENT_RUNS ||--o{ AGENT_TOOL_APPROVALS : agent_run_id
    USERS o|--o{ AGENT_TOOL_APPROVALS : approver_user_id
    AGENT_RUNS ||--o{ AGENT_TOOL_CALLS : agent_run_id
    AGENT_TOOL_APPROVALS o|--o{ AGENT_TOOL_CALLS : approval_id
    DATA_SOURCES ||--o{ MARKET_OBSERVATIONS : source_id
    JOB_ROLES o|--o{ MARKET_OBSERVATIONS : job_role_id
    MODEL_VERSIONS ||--o{ MARKET_FORECASTS : model_version_id
    JOB_ROLES o|--o{ MARKET_FORECASTS : job_role_id
    USERS ||--o{ BEHAVIOR_EVENTS : user_id
    MODEL_VERSIONS ||--o{ USER_SEGMENTS : model_version_id
    USERS ||--o{ USER_SEGMENT_ASSIGNMENTS : user_id
    USER_SEGMENTS ||--o{ USER_SEGMENT_ASSIGNMENTS : segment_id
    MODEL_VERSIONS ||--o{ ANOMALY_EVENTS : model_version_id
    BEHAVIOR_EVENTS o|--o{ ANOMALY_EVENTS : event_id
    USERS o|--o{ AUDIT_EVENTS : actor_user_id
    USERS o|--o{ AI_USAGE_RECORDS : user_id
    MODEL_VERSIONS o|--o{ AI_USAGE_RECORDS : model_version_id
```
