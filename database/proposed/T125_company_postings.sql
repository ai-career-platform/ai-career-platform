-- PROPOSED (T125/T126) — NOT a migration. database/migrate.py does not read this folder.
-- Purpose: 기업 공고 작성·검수 저장소(backend/app/services/company_postings.py 의 MemoryPostingRepository·
--          MemoryPublicPostings 를 SQL 로 바꿀 때의 데이터 계약). 상태 기계는 docs/enterprise/t125_posting_state_machine.json,
--          설계 설명은 docs/enterprise/T125_T128_DB_DESIGN.md.
-- 설계 선택: career.job_postings 에 상태를 추가하지 않고 **별도 표 organization_job_postings** 에서 작성·검수한다.
--          공개 표 job_postings 에는 운영 승인(posting.publish) 때만 행이 생기거나 바뀐다(P-INV-3).
--          → 공개 API(T18·T99, repositories/job_postings.py 의 _is_open·VISIBLE_STATUSES)는 바꾸지 않아도
--            초안·검수 중·반려 공고를 볼 수 없다(그 행이 job_postings 에 아예 없음).
-- 의존: 0001~0003 + database/proposed/T122_organizations.sql(organizations). T122 보다 먼저 적용할 수 없다.
-- 사전 데이터(승인 후 seed, 이 파일에 없음): career.data_sources code='company_direct'(license_ref = 조직 게시 약관 버전, T125 D-6).
-- Recovery: 신규 표 3개 + 함수·제약 트리거 1개. 승인 전 적용하지 않음. 적용 후 문제 시 후속 migration 으로 제거
--          (Destructive-Approval 필요). 이미 생긴 job_postings(company_direct) 행은 status='closed' 로 내린 뒤 제거.
-- 개인정보:
--   - 공고 내용은 조직 데이터(개인정보 아님). 개인 연락처 게시는 반려 사유(personal_contact_info).
--   - created_by_user_id, organization_job_posting_events.actor_user_id 는 사람 연결 → ON DELETE SET NULL(탈퇴 시 익명화).
--   - reason_note·detail 은 운영 기록(개인정보 입력 금지).
-- 감사: 서비스의 repo.audit 행(action_code, actor, posting_id, organization_id, detail, occurred_at)을 그대로 담는
--       organization_job_posting_events 를 둔다(career.audit_events 에는 detail 열이 없음). 행 삭제 안 함.
-- 검증: backend/tests/test_t125_t128_proposed_ddl_postgres.py (일회용 PG).

-- 직접 등록 공고의 공개 회사 행. job_postings.company_id 가 NOT NULL 이므로 조직마다 career.companies 행 하나
-- (source = company_direct)를 첫 게시 때 만들어 연결한다. 수집 회사(organizations.linked_company_id)와 섞지 않는다.
CREATE TABLE career.organization_public_companies (
    organization_id uuid NOT NULL REFERENCES career.organizations (organization_id) ON DELETE RESTRICT,
    company_id uuid NOT NULL REFERENCES career.companies (company_id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id),
    UNIQUE (company_id)
);

CREATE TABLE career.organization_job_postings (
    posting_id uuid NOT NULL DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES career.organizations (organization_id) ON DELETE RESTRICT,
    status varchar(20) NOT NULL DEFAULT 'draft',
    title varchar(240) NOT NULL,
    description text,
    employment_type varchar(24),
    location_text varchar(120),
    apply_url varchar(500),
    expires_at timestamptz,
    version integer NOT NULL DEFAULT 1,           -- 낙관적 잠금(P-INV-7)
    created_by_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    reason_code varchar(40),                      -- 반려·내림 사유(P-INV-4)
    reason_note varchar(500),
    revision_of uuid,                             -- 게시 중 공고의 수정본이면 원본 posting_id
    public_posting_id uuid REFERENCES career.job_postings (job_posting_id) ON DELETE RESTRICT,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (posting_id),
    UNIQUE (organization_id, posting_id),         -- 수정본이 같은 조직 원본만 가리키게(아래 FK)
    UNIQUE (public_posting_id),                   -- 공개 행 하나에 기업 공고 하나
    FOREIGN KEY (organization_id, revision_of)
        REFERENCES career.organization_job_postings (organization_id, posting_id) ON DELETE RESTRICT,
    CHECK (status IN ('draft', 'pending_review', 'rejected', 'published', 'closed', 'expired', 'taken_down')),
    CHECK (length(btrim(title)) > 0),
    CHECK (description IS NULL OR length(description) <= 20000),
    CHECK (employment_type IS NULL OR employment_type IN ('full_time', 'contract', 'intern', 'part_time')),
    CHECK (apply_url IS NULL OR apply_url ~ '^https://[^\s/$.?#].[^\s]*$'),
    CHECK (version >= 1),
    CHECK (revision_of IS NULL OR revision_of <> posting_id),
    -- 검수 요청 이후 상태는 필수 항목(REQUIRED) 완비. 초안만 비어 있을 수 있다.
    CHECK (status = 'draft' OR (nullif(btrim(description), '') IS NOT NULL AND employment_type IS NOT NULL
                                AND nullif(btrim(location_text), '') IS NOT NULL AND expires_at IS NOT NULL)),
    -- 사유 코드: 반려·내림 상태에서만, 상태별 허용 목록(T125 JSON reject/takedown_reason_codes)
    CHECK (CASE status
             WHEN 'rejected' THEN reason_code IN ('missing_required_info', 'discriminatory_requirement',
                 'personal_contact_info', 'misleading_terms', 'not_a_job_posting', 'duplicate_posting',
                 'unverified_link', 'other')
             WHEN 'taken_down' THEN reason_code IN ('legal_request', 'fraud_suspected', 'discriminatory_requirement',
                 'organization_suspended', 'other')
             ELSE reason_code IS NULL END),
    CHECK (NOT (status = 'rejected' AND reason_code = 'other') OR length(btrim(coalesce(reason_note, ''))) > 0),
    -- 게시된 적이 있는 상태만 published_at 을 가진다
    CHECK ((status IN ('published', 'closed', 'expired', 'taken_down')) = (published_at IS NOT NULL)),
    CHECK (published_at IS NULL OR expires_at IS NULL OR expires_at > published_at),
    -- 공개 행 연결: 게시 전 상태(초안·검수 중·반려)와 수정본은 절대 공개 행을 갖지 않는다(P-INV-3)
    CHECK (status NOT IN ('draft', 'pending_review', 'rejected') OR public_posting_id IS NULL),
    CHECK (revision_of IS NULL OR public_posting_id IS NULL),
    CHECK (status <> 'published' OR revision_of IS NOT NULL OR public_posting_id IS NOT NULL)
);
-- 기업 목록(list: organization_id, updated_at DESC)
CREATE INDEX ix_organization_job_postings_org ON career.organization_job_postings (organization_id, updated_at DESC);
-- 운영 검수 대기열(queue: status='pending_review' ORDER BY updated_at)
CREATE INDEX ix_organization_job_postings_queue ON career.organization_job_postings (updated_at)
    WHERE status = 'pending_review';
-- 만료 처리(expire_due: status='published' AND expires_at <= now)
CREATE INDEX ix_organization_job_postings_expire ON career.organization_job_postings (expires_at)
    WHERE status = 'published';
-- 원본마다 열린 수정본은 하나만(revise: "an open revision exists")
CREATE UNIQUE INDEX ux_organization_job_postings_open_revision ON career.organization_job_postings (revision_of)
    WHERE revision_of IS NOT NULL AND status IN ('draft', 'pending_review', 'rejected');

-- 공개 행 정합성: 기업 공고가 게시 상태가 아니면 연결된 job_postings 행도 published 가 아니어야 한다.
-- 같은 트랜잭션 안에서 순서와 관계없이 커밋 시점에 검사(DEFERRABLE INITIALLY DEFERRED).
CREATE OR REPLACE FUNCTION career.organization_job_postings_public_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.public_posting_id IS NOT NULL AND NEW.status <> 'published' AND EXISTS (
        SELECT 1 FROM career.job_postings jp
        WHERE jp.job_posting_id = NEW.public_posting_id AND jp.status = 'published') THEN
        RAISE EXCEPTION 'organization posting % is % but public posting % is still published',
            NEW.posting_id, NEW.status, NEW.public_posting_id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_organization_job_postings_public_guard ON career.organization_job_postings;
CREATE CONSTRAINT TRIGGER trg_organization_job_postings_public_guard
    AFTER INSERT OR UPDATE ON career.organization_job_postings
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION career.organization_job_postings_public_guard();

-- 감사 이력(MemoryPostingRepository.audit 과 같은 모양). 갱신·삭제하지 않는다.
CREATE TABLE career.organization_job_posting_events (
    event_id uuid NOT NULL DEFAULT gen_random_uuid(),
    posting_id uuid NOT NULL REFERENCES career.organization_job_postings (posting_id) ON DELETE RESTRICT,
    organization_id uuid NOT NULL REFERENCES career.organizations (organization_id) ON DELETE RESTRICT,
    action_code varchar(40) NOT NULL,
    actor_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    detail varchar(80) NOT NULL DEFAULT '',       -- 사유 코드 또는 수정본의 원본 posting_id
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id),
    CHECK (action_code IN ('posting.draft_create', 'posting.draft_edit', 'posting.revision_create',
                           'posting.submit_review', 'posting.withdraw_review', 'posting.publish', 'posting.reject',
                           'posting.close', 'posting.takedown', 'system.expire')),
    CHECK (action_code <> 'system.expire' OR actor_user_id IS NULL)
);
CREATE INDEX ix_organization_job_posting_events_posting ON career.organization_job_posting_events (posting_id, occurred_at);
CREATE INDEX ix_organization_job_posting_events_org ON career.organization_job_posting_events (organization_id, occurred_at DESC);
