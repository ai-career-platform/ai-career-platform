-- Purpose: T141/T142 내 데이터 반출(export) 요청·재인증 허가·1회용 다운로드 토큰·반출 묶음(짧은 보관).
--          계약: docs/privacy/T141_DATA_SUBJECT_REQUEST_POLICY.md, docs/privacy/T142_PERSONAL_DATA_EXPORT_API.md.
--          API(T142)는 PERSONAL_DATA_REQUESTS_API=true 일 때만 열림(기본 꺼짐). 처리 worker 는 수동 실행만(스케줄 없음).
-- Recovery: 신규 표 4개·인덱스만 추가(기존 표·데이터 변경 없음). 실패 시 러너가 롤백.
--           적용 후 제거는 후속 migration(Destructive-Approval 필요)으로만 한다.
-- 개인정보: 재인증·다운로드 토큰은 SHA-256 해시만 저장(원문 저장 안 함). 반출 묶음(bytea)은 완료 후 최대 24시간,
--           첫 다운로드·만료 때 즉시 삭제. 사용자 삭제 시 묶음·재인증 허가는 CASCADE, 요청 이력은 SET NULL(익명화, D-INV8).
--           career_reader 에는 요청 상태 표만 읽기 권한(토큰 해시·묶음 표는 주지 않음).
-- 운영(GCP) 적용은 #344 절차와 별도 PM 승인 후에만 한다.
-- 검증: backend/tests/test_t142_proposed_ddl_postgres.py, backend/tests/test_t142_personal_data_requests_postgres.py (일회용 PostgreSQL 18).

CREATE TABLE career.data_subject_requests (
    request_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,      -- 탈퇴 시 익명화 보존(D-INV8)
    request_type varchar(20) NOT NULL,
    channel varchar(20) NOT NULL DEFAULT 'self_service',
    status varchar(30) NOT NULL,
    attempts smallint NOT NULL DEFAULT 0,
    reason_code varchar(40),
    handled_by uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    expires_at timestamptz,
    size_bytes bigint,
    artifact_sha256 char(64),
    PRIMARY KEY (request_id),
    CHECK (request_type IN ('access', 'rectification', 'erasure', 'export')),
    CHECK (channel IN ('self_service', 'assisted')),
    CHECK (status IN ('pending_verification', 'received', 'in_progress', 'completed', 'failed',
                      'rejected', 'cancelled', 'expired', 'closed')),
    CHECK (attempts BETWEEN 0 AND 3),
    CHECK (status NOT IN ('rejected', 'failed') OR reason_code IS NOT NULL),                  -- D-INV4
    CHECK (handled_by IS NULL OR user_id IS NULL OR handled_by <> user_id),                   -- D-INV5
    CHECK (status <> 'completed' OR completed_at IS NOT NULL),
    CHECK (request_type <> 'export' OR status <> 'completed' OR expires_at IS NOT NULL),
    CHECK (expires_at IS NULL OR completed_at IS NULL OR expires_at <= completed_at + interval '24 hours'),
    CHECK (size_bytes IS NULL OR size_bytes BETWEEN 0 AND 52428800 OR status = 'failed'),
    CHECK (artifact_sha256 IS NULL OR artifact_sha256 ~ '^[0-9a-f]{64}$')
);
-- 유형별 열린 요청 1건(동시 요청 → 하나만 성공, 나머지 23505 → 409 CONFLICT)
CREATE UNIQUE INDEX ux_data_subject_requests_open ON career.data_subject_requests (user_id, request_type)
    WHERE status IN ('pending_verification', 'received', 'in_progress', 'failed', 'completed');
CREATE INDEX ix_data_subject_requests_queue ON career.data_subject_requests (status, created_at)
    WHERE status = 'received';
CREATE INDEX ix_data_subject_requests_user ON career.data_subject_requests (user_id, created_at DESC);
-- 만료 대상(completed + expires_at) 조회
CREATE INDEX ix_data_subject_requests_expiry ON career.data_subject_requests (expires_at)
    WHERE status = 'completed';

-- 재인증: 세션에 묶인 10분짜리 허가. 토큰 원문은 저장하지 않는다.
CREATE TABLE career.data_reauth_grants (
    token_hash char(64) NOT NULL,
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    session_id uuid NOT NULL REFERENCES career.auth_sessions (session_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (token_hash),
    CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '10 minutes')
);
CREATE INDEX ix_data_reauth_grants_user ON career.data_reauth_grants (user_id);
CREATE INDEX ix_data_reauth_grants_session ON career.data_reauth_grants (session_id);
CREATE INDEX ix_data_reauth_grants_expires ON career.data_reauth_grants (expires_at);

-- 1회용 다운로드 토큰(10분, 요청당 하나). 사용하면 used_at 기록.
CREATE TABLE career.data_export_downloads (
    token_hash char(64) NOT NULL,
    request_id uuid NOT NULL REFERENCES career.data_subject_requests (request_id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    PRIMARY KEY (token_hash),
    CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '10 minutes'),
    CHECK (used_at IS NULL OR used_at >= created_at)
);
CREATE UNIQUE INDEX ux_data_export_downloads_live ON career.data_export_downloads (request_id) WHERE used_at IS NULL;
CREATE INDEX ix_data_export_downloads_request ON career.data_export_downloads (request_id);

-- 반출 묶음(JSON). 최대 50 MiB·완료 후 최대 24시간. 첫 다운로드 성공·만료 때 행을 지운다.
-- 다운로드 1회 소모와 묶음 삭제가 같은 트랜잭션에서 일어나도록 DB 에 둔다(파일 저장소와 어긋남 없음).
CREATE TABLE career.data_export_artifacts (
    request_id uuid NOT NULL REFERENCES career.data_subject_requests (request_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    content bytea NOT NULL,
    size_bytes bigint NOT NULL,
    content_sha256 char(64) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    PRIMARY KEY (request_id),
    CHECK (size_bytes = octet_length(content) AND size_bytes BETWEEN 0 AND 52428800),
    CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '24 hours')
);
CREATE INDEX ix_data_export_artifacts_user ON career.data_export_artifacts (user_id);
CREATE INDEX ix_data_export_artifacts_expires ON career.data_export_artifacts (expires_at);

COMMENT ON TABLE career.data_subject_requests IS 'T141/T142 정보주체 요청(반출). 탈퇴 시 user_id SET NULL 로 익명화 보존';
COMMENT ON TABLE career.data_reauth_grants IS 'T142 재인증 허가(세션 묶음, 10분). 토큰 SHA-256 해시만';
COMMENT ON TABLE career.data_export_downloads IS 'T142 1회용 다운로드 토큰(10분). 토큰 SHA-256 해시만';
COMMENT ON TABLE career.data_export_artifacts IS 'T142 반출 묶음(최대 50 MiB, 최대 24시간). 첫 다운로드·만료 시 삭제';

-- 앱 역할 권한(역할이 있는 환경에서만). 기본 권한(DRAFT_00)이 없는 환경(GCP 등)도 같은 결과가 되도록 명시한다.
DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON career.data_subject_requests TO career_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON career.data_reauth_grants TO career_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON career.data_export_downloads TO career_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON career.data_export_artifacts TO career_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_reader') THEN
        GRANT SELECT ON career.data_subject_requests TO career_reader;
    END IF;
END
$grants$;
