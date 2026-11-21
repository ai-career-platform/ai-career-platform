-- Purpose: T125/T126/T127 기업 공고 작성·운영 검수 — organization_public_companies, organization_job_postings,
--          organization_job_posting_events + 공개 행 정합성 제약 트리거. 설계: PR #349
--          (database/proposed/T125_company_postings.sql, docs/enterprise/T125_T128_DB_DESIGN.md) 그대로.
--          상태 기계: docs/enterprise/t125_posting_state_machine.json. API 는 COMPANY_POSTINGS_API=true 일 때만 열림(기본 꺼짐).
--          공개 표 career.job_postings 에는 운영 승인(posting.publish) 트랜잭션 안에서만 행이 생기거나 바뀐다(P-INV-3).
--          초안·검수 중·반려·수정본은 공개 행을 가질 수 없다(CHECK). 수집 공고(jobkorea_live 등)와 섞지 않는다
--          (회사 행은 조직마다 source=company_direct 로 따로 만든다, organizations.linked_company_id 와 별개).
-- Recovery: 신규 표 3개 + 인덱스 + 함수·제약 트리거 1개만 추가(기존 표·행·열 변경 없음). 실패 시 러너가 롤백.
--           적용 후 제거는 후속 migration(Destructive-Approval 필요)으로만 한다. 이미 생긴 job_postings(company_direct)
--           행은 status='closed' 로 내린 뒤 제거한다.
-- 의존: 0001(companies·job_postings·data_sources·users) + 0008(organizations).
-- 사전 데이터(이 파일에 없음, 승인 후 별도 seed): career.data_sources code='company_direct'
--           (license_ref = 조직 게시 약관 버전, T125 D-5). 행이 없으면 승인(게시)이 503 으로 실패하고 아무것도 공개되지 않는다.
-- 개인정보: 공고 내용은 조직 데이터. created_by_user_id·actor_user_id 는 ON DELETE SET NULL(탈퇴 시 익명화).
--           reason_note·detail 은 운영 기록(개인정보 입력 금지). 이벤트 행은 갱신·삭제하지 않는다.
-- 운영(GCP) 적용은 #344 절차와 별도 PM 승인 후에만 한다.
-- 검증: backend/tests/test_t126_company_postings_postgres.py (일회용 PG 18, CI).

-- 직접 등록 공고의 공개 회사 행. job_postings.company_id 가 NOT NULL 이므로 조직마다 career.companies 행 하나
-- (source = company_direct)를 첫 게시 때 만들어 연결한다.
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
CREATE FUNCTION career.organization_job_postings_public_guard() RETURNS trigger
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
CREATE CONSTRAINT TRIGGER trg_organization_job_postings_public_guard
    AFTER INSERT OR UPDATE ON career.organization_job_postings
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION career.organization_job_postings_public_guard();

-- 감사 이력(서비스 repo.audit 과 같은 모양, career.audit_events 에는 detail 열이 없음). 갱신·삭제하지 않는다.
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

COMMENT ON TABLE career.organization_job_postings IS 'T125 기업 직접 등록 공고(작성·검수). 공개 행은 운영 승인 때만 job_postings 에 생김';
COMMENT ON TABLE career.organization_public_companies IS 'T125 조직 → 공개용 company_direct 회사 행(수집 회사와 별개)';

-- 앱 역할 권한(역할이 있는 환경에서만). 기본 권한(DRAFT_00)이 없는 환경(GCP 등)에서도 같은 결과가 되도록 명시한다.
-- 이 파일은 이벤트 표에 UPDATE·DELETE 를 명시하지 않는다(앱 코드는 INSERT 만 한다).
DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_app') THEN
        GRANT SELECT, INSERT, UPDATE ON career.organization_job_postings, career.organization_public_companies
            TO career_app;
        GRANT SELECT, INSERT ON career.organization_job_posting_events TO career_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_reader') THEN
        GRANT SELECT ON career.organization_job_postings, career.organization_public_companies,
            career.organization_job_posting_events TO career_reader;
    END IF;
END
$grants$;
