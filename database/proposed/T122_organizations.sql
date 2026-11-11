-- PROPOSED (T122) — NOT a migration. database/migrate.py does not read this folder.
-- Purpose: 기업 조직·소속·초대 데이터 계약(docs/enterprise/T122_COMPANY_MEMBERSHIP_CONTRACT.md).
--          역할·권한 판단 규칙은 T121(docs/enterprise/t121_role_matrix.json). 전역 역할(career.user_roles)은 바꾸지 않음.
-- Recovery: 신규 표 3개. 승인 전 적용하지 않음. 적용 후 문제 시 후속 migration 으로 제거(Destructive-Approval 필요).
-- 개인정보:
--   - organization_members.user_id ON DELETE CASCADE (탈퇴 시 소속 삭제).
--   - organization_invitations.email_canonical 은 초대받은 사람의 이메일 — 종료(수락·취소·만료) 30일 뒤 행 삭제(제안 purge, T122 §6).
--   - 초대 토큰은 원문을 저장하지 않고 SHA-256 해시만(token_hash). 토큰 원문은 메일로 1회만 전달.
-- 감사: 새 표를 만들지 않고 career.audit_events 에 action_code 'org.*' 로 남김(T122 §5).
-- 검증: backend/tests/test_t122_company_membership_contract.py (일회용 PG), T123 backend/tests.

CREATE TABLE career.organizations (
    organization_id uuid NOT NULL DEFAULT gen_random_uuid(),
    name varchar(200) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'pending',
    -- 수집된 회사 정보와의 선택적 연결(T121 D-6). 회사 행이 지워져도 조직은 남는다.
    linked_company_id uuid REFERENCES career.companies (company_id) ON DELETE SET NULL,
    created_by_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    verified_by_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    verified_at timestamptz,
    status_reason varchar(300),                   -- 반려·정지·종료 사유(운영자 기록, 개인정보 금지)
    closed_at timestamptz,
    version integer NOT NULL DEFAULT 1,           -- 낙관적 잠금
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id),
    CHECK (status IN ('pending', 'active', 'suspended', 'closed', 'rejected')),
    CHECK (length(btrim(name)) > 0),
    CHECK (status <> 'active' OR verified_at IS NOT NULL),
    CHECK ((status = 'closed') = (closed_at IS NOT NULL)),
    CHECK (version >= 1)
);
-- 같은 수집 회사에 열린(종료·반려 아님) 조직은 하나만 연결
CREATE UNIQUE INDEX ux_organizations_linked_company ON career.organizations (linked_company_id)
    WHERE linked_company_id IS NOT NULL AND status NOT IN ('closed', 'rejected');
CREATE INDEX ix_organizations_status ON career.organizations (status, created_at);

CREATE TABLE career.organization_members (
    organization_id uuid NOT NULL REFERENCES career.organizations (organization_id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    role varchar(20) NOT NULL,
    joined_at timestamptz NOT NULL DEFAULT now(),
    role_changed_at timestamptz NOT NULL DEFAULT now(),
    version integer NOT NULL DEFAULT 1,
    PRIMARY KEY (organization_id, user_id),       -- 같은 조직 중복 소속 금지. 다른 조직 다중 소속은 허용(T121 D-2)
    CHECK (role IN ('owner', 'member'))
);
-- 제외·탈퇴는 행 삭제(이력은 audit_events). 사용자별 소속 조회
CREATE INDEX ix_organization_members_user ON career.organization_members (user_id);
CREATE INDEX ix_organization_members_owner ON career.organization_members (organization_id) WHERE role = 'owner';

CREATE TABLE career.organization_invitations (
    invitation_id uuid NOT NULL DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES career.organizations (organization_id) ON DELETE CASCADE,
    email_canonical varchar(254) NOT NULL,
    role varchar(20) NOT NULL DEFAULT 'member',
    token_hash char(64) NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'pending',
    invited_by_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    accepted_by_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    resend_count smallint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    closed_at timestamptz,                        -- 수락·취소·만료 처리 시각
    PRIMARY KEY (invitation_id),
    UNIQUE (token_hash),
    CHECK (role IN ('owner', 'member')),
    CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    CHECK (email_canonical = lower(email_canonical) AND position('@' IN email_canonical) > 1),
    CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    CHECK (expires_at > created_at AND expires_at <= created_at + interval '7 days'),   -- TTL 최대 7일
    CHECK ((status = 'pending') = (closed_at IS NULL)),
    CHECK (status <> 'accepted' OR accepted_by_user_id IS NOT NULL OR closed_at IS NOT NULL),
    CHECK (resend_count BETWEEN 0 AND 5)
);
-- 같은 조직·같은 이메일에 대기 중 초대는 하나만(재전송은 같은 행의 token_hash·expires_at 교체)
CREATE UNIQUE INDEX ux_organization_invitations_pending ON career.organization_invitations (organization_id, email_canonical)
    WHERE status = 'pending';
CREATE INDEX ix_organization_invitations_email ON career.organization_invitations (email_canonical) WHERE status = 'pending';
CREATE INDEX ix_organization_invitations_purge ON career.organization_invitations (closed_at) WHERE status <> 'pending';
