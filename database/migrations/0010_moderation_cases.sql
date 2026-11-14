-- Purpose: T80/T81 운영 콘텐츠 검수 — moderation_cases(검수 건), moderation_case_events(처리 이력, 추가만) +
--          대상 스냅샷 보호·대상 삭제 시 열린 건 자동 종료 트리거. 설계: docs/admin/MODERATION_IMPLEMENTATION_CONTRACT.md
--          §2.2 DDL 스케치 그대로 + 대상 유형 1개 추가: company_posting(0009 organization_job_postings, T125 기업 직접
--          등록 공고 — 계약 작성 후 생긴 표). 상태 모델: docs/admin/MODERATION_STATE_DIAGRAM.md.
--          API 는 ADMIN_MODERATION_API=true 일 때만 열림(기본 꺼짐). company_posting 건의 승인·반려는 T125 공고 전이와
--          한 트랜잭션에서만 반영된다(검수 결과와 공개 상태가 갈라지지 않게 — 별도 게시 경로 없음).
-- Recovery: 신규 표 2개 + 인덱스 + 함수 3개·트리거 2개만 추가(기존 표·행·열 변경 없음). 실패 시 러너가 롤백.
--           적용 후 제거는 후속 migration(Destructive-Approval 필요)으로만 한다.
-- 의존: 0001(users·job_postings·companies·user_documents·AI 결과 5표) + 0009(organization_job_postings).
-- 개인정보: 사용자 FK(content_owner_id·submitted_by·assignee_id·first_decider_id·decided_by·actor_user_id)는
--           ON DELETE SET NULL(계정 삭제를 막지 않고 행위자만 익명화). reviewer_note 는 관리자 전용 메모(응답·감사·이력에
--           넣지 않음). 신고자 정보·탐지 원문은 저장하지 않는다(flags 는 코드만). 이력 행은 갱신·삭제하지 않는다.
-- 권한 코드 admin.content.review 의 Seed 는 이 파일에 없다(PM 결정 §9-12 대기, API 는 admin 역할로 보호).
-- 운영(GCP) 적용은 #344 절차와 별도 PM 승인 후에만 한다.
-- 검증: backend/tests/test_t81_moderation_postgres.py (일회용 PG 18, CI).

CREATE TABLE career.moderation_cases (
    case_id uuid NOT NULL DEFAULT gen_random_uuid(),
    target_type varchar(32) NOT NULL,
    target_id uuid NOT NULL,
    job_posting_id uuid REFERENCES career.job_postings (job_posting_id) ON DELETE SET NULL,
    company_id uuid REFERENCES career.companies (company_id) ON DELETE SET NULL,
    document_id uuid REFERENCES career.user_documents (document_id) ON DELETE SET NULL,
    analysis_id uuid REFERENCES career.document_analyses (analysis_id) ON DELETE SET NULL,
    retrieval_run_id uuid REFERENCES career.retrieval_runs (retrieval_run_id) ON DELETE SET NULL,
    agent_run_id uuid REFERENCES career.agent_runs (agent_run_id) ON DELETE SET NULL,
    match_id uuid REFERENCES career.match_evaluations (match_id) ON DELETE SET NULL,
    recommendation_run_id uuid REFERENCES career.recommendation_runs (recommendation_run_id) ON DELETE SET NULL,
    company_posting_id uuid REFERENCES career.organization_job_postings (posting_id) ON DELETE SET NULL,
    review_trigger varchar(16) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'PENDING',
    priority smallint NOT NULL,
    content_owner_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    submitted_by uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    assignee_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    first_decider_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    decided_by uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    decided_at timestamptz,
    reason_code varchar(32),
    reviewer_note varchar(500),
    appeal_count smallint NOT NULL DEFAULT 0,
    appealed_at timestamptz,
    flags text[],
    report_count integer NOT NULL DEFAULT 0,
    due_at timestamptz NOT NULL,
    close_reason varchar(32),
    version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (case_id),
    CONSTRAINT ck_moderation_cases_target_type CHECK (target_type IN ('job_posting', 'company', 'shared_document',
        'document_analysis', 'retrieval_run', 'agent_run', 'match_evaluation', 'recommendation_run',
        'company_posting')),
    CONSTRAINT ck_moderation_cases_target_columns CHECK (
        num_nonnulls(job_posting_id, company_id, document_id, analysis_id, retrieval_run_id, agent_run_id,
                     match_id, recommendation_run_id, company_posting_id) <= 1
        AND (job_posting_id IS NULL OR (target_type = 'job_posting' AND job_posting_id = target_id))
        AND (company_id IS NULL OR (target_type = 'company' AND company_id = target_id))
        AND (document_id IS NULL OR (target_type = 'shared_document' AND document_id = target_id))
        AND (analysis_id IS NULL OR (target_type = 'document_analysis' AND analysis_id = target_id))
        AND (retrieval_run_id IS NULL OR (target_type = 'retrieval_run' AND retrieval_run_id = target_id))
        AND (agent_run_id IS NULL OR (target_type = 'agent_run' AND agent_run_id = target_id))
        AND (match_id IS NULL OR (target_type = 'match_evaluation' AND match_id = target_id))
        AND (recommendation_run_id IS NULL OR (target_type = 'recommendation_run' AND recommendation_run_id = target_id))
        AND (company_posting_id IS NULL OR (target_type = 'company_posting' AND company_posting_id = target_id))),
    CONSTRAINT ck_moderation_cases_trigger CHECK (review_trigger IN ('PRE_PUBLISH', 'REPORT', 'EXPIRY', 'SOURCE_CHANGE')),
    CONSTRAINT ck_moderation_cases_status CHECK (status IN ('PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'APPEALED', 'CLOSED')),
    CONSTRAINT ck_moderation_cases_priority CHECK (priority IN (1, 2, 3)),
    CONSTRAINT ck_moderation_cases_appeal_count CHECK (appeal_count IN (0, 1)),
    CONSTRAINT ck_moderation_cases_appealed CHECK (status <> 'APPEALED' OR appeal_count = 1),
    CONSTRAINT ck_moderation_cases_assignee CHECK ((status = 'IN_REVIEW') = (assignee_id IS NOT NULL)),
    CONSTRAINT ck_moderation_cases_rejected_reason CHECK (status <> 'REJECTED' OR reason_code IS NOT NULL),
    CONSTRAINT ck_moderation_cases_reason_code CHECK (reason_code IS NULL OR reason_code IN ('RIGHTS_UNCLEAR',
        'INACCURATE', 'PERSONAL_DATA', 'HARMFUL', 'DISCRIMINATORY', 'DUPLICATE', 'EXPIRED', 'MALWARE', 'OTHER')),
    CONSTRAINT ck_moderation_cases_other_note CHECK (reason_code IS DISTINCT FROM 'OTHER' OR reviewer_note IS NOT NULL),
    CONSTRAINT ck_moderation_cases_closed CHECK ((status = 'CLOSED') = (close_reason IS NOT NULL)),
    CONSTRAINT ck_moderation_cases_close_reason CHECK (close_reason IS NULL
        OR close_reason IN ('WITHDRAWN', 'TARGET_DELETED', 'SUPERSEDED')),
    CONSTRAINT ck_moderation_cases_version CHECK (version >= 1),
    CONSTRAINT ck_moderation_cases_report_count CHECK (report_count >= 0)
);
-- 같은 (대상, 계기)의 열린 건은 하나만(SUBMIT 중복은 기존 건 반환)
CREATE UNIQUE INDEX ix_moderation_cases_open_target ON career.moderation_cases (target_type, target_id, review_trigger)
    WHERE status IN ('PENDING', 'IN_REVIEW', 'APPEALED');
-- 큐 정렬(priority, due_at, case_id) — keyset cursor
CREATE INDEX ix_moderation_cases_queue ON career.moderation_cases (status, priority, due_at, case_id);
CREATE INDEX ix_moderation_cases_order ON career.moderation_cases (priority, due_at, case_id);

CREATE TABLE career.moderation_case_events (
    event_id uuid NOT NULL DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES career.moderation_cases (case_id) ON DELETE RESTRICT,
    from_status varchar(16),
    to_status varchar(16) NOT NULL,
    event varchar(24) NOT NULL,
    actor_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    reason_code varchar(32),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id),
    CONSTRAINT ck_moderation_case_events_event CHECK (event IN ('SUBMIT', 'ASSIGN', 'REASSIGN', 'RELEASE',
        'RELEASE_APPEAL', 'APPROVE', 'REJECT', 'APPEAL', 'WITHDRAW_APPEAL', 'CLOSE')),
    CONSTRAINT ck_moderation_case_events_to CHECK (to_status IN ('PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED',
        'APPEALED', 'CLOSED'))
);
CREATE INDEX ix_moderation_case_events_case ON career.moderation_case_events (case_id, occurred_at);

CREATE FUNCTION career.moderation_case_live_target(c career.moderation_cases) RETURNS uuid
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE c.target_type
        WHEN 'job_posting' THEN c.job_posting_id WHEN 'company' THEN c.company_id
        WHEN 'shared_document' THEN c.document_id WHEN 'document_analysis' THEN c.analysis_id
        WHEN 'retrieval_run' THEN c.retrieval_run_id WHEN 'agent_run' THEN c.agent_run_id
        WHEN 'match_evaluation' THEN c.match_id WHEN 'recommendation_run' THEN c.recommendation_run_id
        WHEN 'company_posting' THEN c.company_posting_id END
$$;

-- INSERT: 유형에 맞는 FK 칸이 target_id 로 채워져야 한다(없는 대상·잘못된 유형으로 건을 만들 수 없음).
-- UPDATE: 스냅샷 불변. ON DELETE SET NULL 로 대상 칸이 비면 열린 건을 CLOSED(TARGET_DELETED)로 닫는다.
CREATE FUNCTION career.moderation_cases_target_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF career.moderation_case_live_target(NEW) IS DISTINCT FROM NEW.target_id THEN
            RAISE EXCEPTION 'moderation case must reference its target through the % column', NEW.target_type
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.target_type IS DISTINCT FROM OLD.target_type OR NEW.target_id IS DISTINCT FROM OLD.target_id THEN
        RAISE EXCEPTION 'moderation case target snapshot is immutable' USING ERRCODE = '23514';
    END IF;
    IF career.moderation_case_live_target(OLD) IS NOT NULL AND career.moderation_case_live_target(NEW) IS NULL
       AND OLD.status IN ('PENDING', 'IN_REVIEW', 'APPEALED') THEN
        NEW.status := 'CLOSED';
        NEW.close_reason := 'TARGET_DELETED';
        NEW.assignee_id := NULL;
        NEW.version := OLD.version + 1;
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END $$;

CREATE FUNCTION career.moderation_cases_target_closed_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status <> 'CLOSED' AND NEW.status = 'CLOSED' AND NEW.close_reason = 'TARGET_DELETED'
       AND career.moderation_case_live_target(NEW) IS NULL THEN
        INSERT INTO career.moderation_case_events (case_id, from_status, to_status, event, reason_code)
        VALUES (NEW.case_id, OLD.status, 'CLOSED', 'CLOSE', 'TARGET_DELETED');
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER moderation_cases_target_guard BEFORE INSERT OR UPDATE ON career.moderation_cases
    FOR EACH ROW EXECUTE FUNCTION career.moderation_cases_target_guard();
CREATE TRIGGER moderation_cases_target_closed_event AFTER UPDATE ON career.moderation_cases
    FOR EACH ROW EXECUTE FUNCTION career.moderation_cases_target_closed_event();

COMMENT ON TABLE career.moderation_cases IS 'T80/T81 운영 콘텐츠 검수 건. target_type·target_id 는 불변 스냅샷, 대상별 FK 는 SET NULL';
COMMENT ON TABLE career.moderation_case_events IS 'T81 검수 건 처리 이력(추가만, 메모·진술 원문 없음, actor NULL=system)';

-- 앱 역할 권한(역할이 있는 환경에서만). 이력 표는 INSERT 만(앱은 갱신·삭제하지 않는다). 검수 건은 지우지 않는다.
DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_app') THEN
        GRANT SELECT, INSERT, UPDATE ON career.moderation_cases TO career_app;
        GRANT SELECT, INSERT ON career.moderation_case_events TO career_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_reader') THEN
        GRANT SELECT ON career.moderation_cases, career.moderation_case_events TO career_reader;
    END IF;
END
$grants$;
