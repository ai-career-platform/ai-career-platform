-- T142 PROPOSED DDL — 내 데이터 반출 요청(T141 정책). 승인 전 migration 아님. 운영·Staging에 적용 금지.
-- 검증: 일회용 DB에서 0001~0003 뒤에 적용(backend/tests/test_t142_proposed_ddl_postgres.py).
-- 롤백: DROP TABLE career.data_export_downloads, career.data_reauth_grants, career.data_subject_requests;

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
    CHECK (size_bytes IS NULL OR size_bytes BETWEEN 0 AND 52428800 OR status = 'failed')
);
-- 유형별 열린 요청 1건(동시 요청 → 하나만 성공, 나머지 23505 → 409 CONFLICT)
CREATE UNIQUE INDEX ux_data_subject_requests_open ON career.data_subject_requests (user_id, request_type)
    WHERE status IN ('pending_verification', 'received', 'in_progress', 'failed', 'completed');
CREATE INDEX ix_data_subject_requests_queue ON career.data_subject_requests (status, created_at)
    WHERE status = 'received';
CREATE INDEX ix_data_subject_requests_user ON career.data_subject_requests (user_id, created_at DESC);

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
