-- Purpose: T101 개인 지원 기록 표(사용자가 직접 기록하는 지원 준비·지원 상태). 채용사 공식 상태가 아님.
--          계약: docs/applications/T101_APPLICATION_TRACKING_CONTRACT.md. API(T102)는 JOB_APPLICATIONS_API=true 일 때만 열림.
-- Recovery: 신규 표 1개·인덱스 2개만 추가(기존 표·데이터 변경 없음). 실패 시 러너가 롤백.
--           적용 후 제거는 후속 migration(Destructive-Approval 필요)으로만 한다.
-- 개인정보: user_id ON DELETE CASCADE(T87 분류 DELETE — 탈퇴 purge 시 함께 삭제). memo 는 사용자가 쓴 자유 문장, 로그 금지.
-- 운영(GCP) 적용은 #344 절차와 별도 PM 승인 후에만 한다.

CREATE TABLE career.job_applications (
    application_id uuid NOT NULL DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES career.users (user_id) ON DELETE CASCADE,
    job_posting_id uuid REFERENCES career.job_postings (job_posting_id) ON DELETE SET NULL,
    posting_title varchar(240) NOT NULL,          -- 저장 시점 스냅샷(공고가 지워져도 기록이 의미를 잃지 않게)
    company_name varchar(200) NOT NULL,
    stage varchar(20) NOT NULL DEFAULT 'interested',
    applied_on date,                              -- 사용자가 지원했다고 기록한 날(KST)
    next_step_on date,                            -- 사용자가 적은 다음 일정(면접 등)
    memo text,
    version integer NOT NULL DEFAULT 1,           -- 낙관적 잠금(PATCH 의 version 과 다르면 409)
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    stage_changed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (application_id),
    UNIQUE (user_id, job_posting_id),             -- 같은 공고 중복 기록 금지(공고가 지워져 NULL 이 된 행끼리는 허용)
    CHECK (stage IN ('interested', 'preparing', 'applied', 'interviewing', 'offered', 'rejected', 'withdrawn')),
    CHECK (stage NOT IN ('interested', 'preparing') OR applied_on IS NULL),
    CHECK (stage NOT IN ('applied', 'interviewing', 'offered', 'rejected') OR applied_on IS NOT NULL),
    CHECK (applied_on IS NULL OR applied_on >= DATE '2000-01-01'),
    CHECK (next_step_on IS NULL OR next_step_on >= DATE '2000-01-01'),
    CHECK (memo IS NULL OR char_length(memo) <= 2000),
    CHECK (length(btrim(posting_title)) > 0 AND length(btrim(company_name)) > 0),
    CHECK (version >= 1)
);

-- 내 목록: 최근 수정순 keyset
CREATE INDEX ix_job_applications_user_updated
    ON career.job_applications (user_id, updated_at DESC, application_id DESC);
-- 공고 삭제 시 SET NULL 처리용
CREATE INDEX ix_job_applications_posting ON career.job_applications (job_posting_id);

COMMENT ON TABLE career.job_applications IS 'T101 사용자가 직접 기록한 지원 준비·지원 상태(채용사 공식 결과 아님)';

-- 앱 역할 권한(역할이 있는 환경에서만). 기본 권한(DRAFT_00)이 없는 환경(GCP 등)도 같은 결과가 되도록 명시한다.
DO $grants$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON career.job_applications TO career_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'career_reader') THEN
        GRANT SELECT ON career.job_applications TO career_reader;
    END IF;
END
$grants$;
