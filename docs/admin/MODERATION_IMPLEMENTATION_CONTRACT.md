# T80 → T81·T82 운영 콘텐츠 검수 구현 계약 (제안)

> 상태: **PROPOSED / 구현 전 리뷰용** · 기능: F-027 · 정책: [MODERATION_POLICY.md](MODERATION_POLICY.md) · 상태 모델: [MODERATION_STATE_DIAGRAM.md](MODERATION_STATE_DIAGRAM.md)
> 이 문서의 API 경로·테이블·컬럼·권한 코드·action_code는 **모두 제안**이다. 기존 확정 계약은 `FACT`로 표시한다.
> **OpenAPI(`docs/api/openapi.yaml`)·`schema.gen.ts`·Migration은 이 PR에서 바꾸지 않는다.** 구현 전에 §7 선행 작업이 끝나야 한다.

## 1. 검수 대상 유형

`target_type`(PROPOSED)은 참조하는 테이블 하나와 1:1로 대응한다. AI 결과는 테이블마다 따로 둔다. 정책 §2.1의 "대상 4"는 마지막 5개 유형의 묶음이다.

| `target_type` | 대상 (정책 §2.1) | 참조 (FACT: 0001 테이블·기본키) | 대상별 FK 칸 | 게시 전 효과 | 게시 후 반려 효과 |
|---|---|---|---|---|---|
| `job_posting` | 1·2 외부·기업 공고 | `job_postings.job_posting_id` | `job_posting_id` | 승인 시 `draft → published` | 공개 철회 (`closed`로는 불가, §5) |
| `company` | 1 외부 기업 | `companies.company_id` | `company_id` | 승인 시 공고 노출 허용 | 기업·소속 공고 노출 철회 (OPEN) |
| `shared_document` | 3 공용 RAG 자료 | `user_documents.document_id` (`visibility='shared'`) | `document_id` | 승인 시 RAG 색인 허용 | 색인 제거·공개 철회 |
| `document_analysis` | 4 신고된 AI 결과 | `document_analyses.analysis_id` | `analysis_id` | (없음) | 결과 숨김 표시 |
| `retrieval_run` | 4 | `retrieval_runs.retrieval_run_id` | `retrieval_run_id` | (없음) | 결과 숨김 표시 |
| `agent_run` | 4 | `agent_runs.agent_run_id` | `agent_run_id` | (없음) | 결과 숨김 표시 |
| `match_evaluation` | 4 | `match_evaluations.match_id` | `match_id` | (없음) | 결과 숨김 표시 |
| `recommendation_run` | 4 | `recommendation_runs.recommendation_run_id` | `recommendation_run_id` | (없음) | 결과 숨김 표시 |

PR #181 첫 커밋의 `content_type` + `ai_result_kind` + `ai_result_id`(다형 ID, FK 불가)는 **폐기**한다. 다형 ID는 DB가 참조 무결성을 보장할 수 없으므로, 유형마다 실제 FK 칸을 둔다.

## 2. 검수 건 데이터 구조 (PROPOSED)

### 2.1 대상 참조 설계 — 삭제를 막지 않으면서 이력을 보존

PR #181 첫 커밋은 "유형에 맞는 FK 칸 하나만 채움(CHECK)"과 "FK `ON DELETE SET NULL`"을 함께 적었다. 이 둘은 충돌한다. 대상이 지워지면 FK가 NULL이 되고 CHECK가 깨져 **원본 삭제 자체가 실패**한다. 다음처럼 바꾼다.

| 구성 | 역할 |
|---|---|
| `target_type`, `target_id` (NOT NULL, **FK 아님**, 이후 불변) | 무엇을 검수했는지에 대한 영구 스냅샷. 대상이 지워져도 이력에 남는다 |
| 대상별 FK 칸 8개 (NULL 허용, `ON DELETE SET NULL`) | 살아 있는 동안의 참조 무결성. 대상이 지워지면 NULL이 된다 |
| CHECK `ck_moderation_cases_target_columns` | 채워진 FK 칸은 **최대 1개**이고, 채워졌다면 `target_type`에 맞는 칸이며 `= target_id`. **NULL은 허용**하므로 삭제로 비는 것은 막지 않는다 |
| `BEFORE INSERT` 트리거 | 생성 시에는 유형에 맞는 FK 칸이 `target_id`와 같은 값으로 **반드시** 채워져 있어야 한다 → 없는 대상·잘못된 유형으로는 건을 만들 수 없다 (FK가 존재를 보장) |
| `BEFORE UPDATE` 트리거 | `ON DELETE SET NULL`로 FK 칸이 비면, 그 건이 열린 상태(PENDING·IN_REVIEW·APPEALED)일 때 `CLOSED` / `close_reason='TARGET_DELETED'`로 바꾸고 `version+1`. 종료된 건(APPROVED·REJECTED·CLOSED)은 상태를 그대로 둔다. 스냅샷(`target_type`, `target_id`) 변경은 거부 |
| `AFTER UPDATE` 트리거 | 위 자동 종료 시 `moderation_case_events`에 `CLOSE`/`TARGET_DELETED`(actor NULL=system) 1행 |
| 사용자 FK (`content_owner_id`, `submitted_by`, `assignee_id`, `first_decider_id`, `decided_by`) | `ON DELETE SET NULL` — 계정 삭제를 막지 않고 행위자만 익명화 |

열린 건 중복 방지 UNIQUE는 FK 칸이 아니라 스냅샷 `(target_type, target_id, review_trigger)`에 건다. 그래야 대상이 지워진 뒤에도 규칙이 흔들리지 않는다.

**대상 삭제 트랜잭션 순서**

| 경로 | 순서 |
|---|---|
| 서비스가 대상을 지울 때 (관리자 공고 삭제, 공용 자료 삭제 등) | ① 대상 행 `SELECT … FOR UPDATE` → ② 그 대상의 열린 건 `SELECT … FOR UPDATE` → ③ 열린 건을 `CLOSED(TARGET_DELETED)`로 전이 (이벤트 + 감사, 행위자 기록) → ④ 대상 `DELETE` (FK 칸 SET NULL, CHECK 통과) → ⑤ Commit. 실패하면 전부 롤백 |
| DB CASCADE로 지워질 때 (계정 삭제 → `user_documents`·AI 결과 CASCADE, FACT) | 서비스를 거치지 않으므로 ④에서 `BEFORE UPDATE` 트리거가 열린 건을 닫고, `AFTER UPDATE` 트리거가 이력을 남긴다. 계정 삭제 트랜잭션과 함께 커밋·롤백된다. 감사 기록은 계정 삭제 작업의 감사가 맡는다 |

**잠금 순서 규칙:** 모든 경로에서 **대상 행 → 검수 건 행** 순서로 잠근다(§3). 결정의 콘텐츠 효과(`draft → published`)도 대상을 바꾸므로, 순서가 다르면 삭제와 결정이 서로를 기다리는 교착이 생긴다.

### 2.2 DDL 스케치 (PROPOSED — Migration 파일 아님)

아래는 계약을 검증하기 위한 스케치다. 실제 Migration은 T05 데이터 사전 갱신과 T08 절차로 따로 만든다. `docs/admin/test_moderation_state_model.py`가 이 블록을 읽어 정적으로 검사한다. opt-in 환경변수를 주면 일회용 PostgreSQL 18에서 실행해 삭제 시나리오까지 확인한다.

```sql
-- T80 PROPOSED sketch. Requires 0001. Not a migration.
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
        'document_analysis', 'retrieval_run', 'agent_run', 'match_evaluation', 'recommendation_run')),
    CONSTRAINT ck_moderation_cases_target_columns CHECK (
        num_nonnulls(job_posting_id, company_id, document_id, analysis_id, retrieval_run_id, agent_run_id,
                     match_id, recommendation_run_id) <= 1
        AND (job_posting_id IS NULL OR (target_type = 'job_posting' AND job_posting_id = target_id))
        AND (company_id IS NULL OR (target_type = 'company' AND company_id = target_id))
        AND (document_id IS NULL OR (target_type = 'shared_document' AND document_id = target_id))
        AND (analysis_id IS NULL OR (target_type = 'document_analysis' AND analysis_id = target_id))
        AND (retrieval_run_id IS NULL OR (target_type = 'retrieval_run' AND retrieval_run_id = target_id))
        AND (agent_run_id IS NULL OR (target_type = 'agent_run' AND agent_run_id = target_id))
        AND (match_id IS NULL OR (target_type = 'match_evaluation' AND match_id = target_id))
        AND (recommendation_run_id IS NULL OR (target_type = 'recommendation_run' AND recommendation_run_id = target_id))),
    CONSTRAINT ck_moderation_cases_trigger CHECK (review_trigger IN ('PRE_PUBLISH', 'REPORT', 'EXPIRY', 'SOURCE_CHANGE')),
    CONSTRAINT ck_moderation_cases_status CHECK (status IN ('PENDING', 'IN_REVIEW', 'APPROVED', 'REJECTED', 'APPEALED', 'CLOSED')),
    CONSTRAINT ck_moderation_cases_priority CHECK (priority IN (1, 2, 3)),
    CONSTRAINT ck_moderation_cases_appeal_count CHECK (appeal_count IN (0, 1)),
    CONSTRAINT ck_moderation_cases_appealed CHECK (status <> 'APPEALED' OR appeal_count = 1),
    CONSTRAINT ck_moderation_cases_assignee CHECK ((status = 'IN_REVIEW') = (assignee_id IS NOT NULL)),
    CONSTRAINT ck_moderation_cases_rejected_reason CHECK (status <> 'REJECTED' OR reason_code IS NOT NULL),
    CONSTRAINT ck_moderation_cases_other_note CHECK (reason_code IS DISTINCT FROM 'OTHER' OR reviewer_note IS NOT NULL),
    CONSTRAINT ck_moderation_cases_closed CHECK ((status = 'CLOSED') = (close_reason IS NOT NULL)),
    CONSTRAINT ck_moderation_cases_close_reason CHECK (close_reason IS NULL
        OR close_reason IN ('WITHDRAWN', 'TARGET_DELETED', 'SUPERSEDED'))
);
CREATE UNIQUE INDEX ix_moderation_cases_open_target ON career.moderation_cases (target_type, target_id, review_trigger)
    WHERE status IN ('PENDING', 'IN_REVIEW', 'APPEALED');
CREATE INDEX ix_moderation_cases_queue ON career.moderation_cases (status, priority, due_at);

CREATE TABLE career.moderation_case_events (
    event_id uuid NOT NULL DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES career.moderation_cases (case_id) ON DELETE RESTRICT,
    from_status varchar(16),
    to_status varchar(16) NOT NULL,
    event varchar(24) NOT NULL,
    actor_user_id uuid REFERENCES career.users (user_id) ON DELETE SET NULL,
    reason_code varchar(32),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id)
);

CREATE FUNCTION career.moderation_case_live_target(c career.moderation_cases) RETURNS uuid
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE c.target_type
        WHEN 'job_posting' THEN c.job_posting_id WHEN 'company' THEN c.company_id
        WHEN 'shared_document' THEN c.document_id WHEN 'document_analysis' THEN c.analysis_id
        WHEN 'retrieval_run' THEN c.retrieval_run_id WHEN 'agent_run' THEN c.agent_run_id
        WHEN 'match_evaluation' THEN c.match_id WHEN 'recommendation_run' THEN c.recommendation_run_id END
$$;

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
```

- 서비스 경로(§2.1 ③)에서 먼저 닫힌 건은 `OLD.status = 'CLOSED'`라서 트리거가 이벤트를 다시 만들지 않는다. 서비스가 행위자와 함께 이미 기록했기 때문이다.
- 컬럼 이름 `review_trigger`: SQL 예약어와 헷갈리지 않도록 `trigger` 대신 쓴다. API 필드 이름은 `trigger`를 유지해도 된다.

### 2.3 컬럼 설명

| 컬럼 | 규칙 |
|---|---|
| `target_type`, `target_id` | §2.1 스냅샷. 변경 불가 (트리거) |
| 대상별 FK 8칸 | §1 표. 생성 시 유형에 맞는 칸만 채움 |
| `review_trigger` | `PRE_PUBLISH`, `REPORT`, `EXPIRY`, `SOURCE_CHANGE` |
| `status` | 상태 모델 §2의 6개 |
| `priority` | 1(긴급)·2(신고)·3(게시 전) |
| `content_owner_id` | 접수 시점 소유자 스냅샷 (자기 검수 판정용). 외부 수집은 NULL |
| `submitted_by` | 요청자 (system이면 NULL) |
| `assignee_id` | IN_REVIEW에서만 값 (CHECK) |
| `first_decider_id` | 최초 APPROVE·REJECT 때 기록, 이후 불변 |
| `decided_by`, `decided_at` | 마지막 결정 |
| `reason_code` | 정책 §5.1 코드. REJECTED면 필수 (CHECK) |
| `reviewer_note` | 관리자 전용 메모, 500자. `reason_code='OTHER'`면 필수 (CHECK) |
| `appeal_count` | 0 또는 1. **이의제기 접수(T08)에서 0 → 1**. 이후 줄지 않는다. APPEALED면 반드시 1 (CHECK) |
| `appealed_at` | T08 시각 |
| `flags` | 자동 표시 코드만 (`PII_PATTERN`, `DUPLICATE_SUSPECT`, `BANNED_TERM`). 탐지 원문은 저장하지 않음 |
| `report_count` | 같은 열린 REPORT 건에 들어온 신고 수 |
| `due_at` | 접수 시 우선순위 기한으로 계산 (정책 §6) |
| `close_reason` | `WITHDRAWN`, `TARGET_DELETED`, `SUPERSEDED`. CLOSED면 필수 (CHECK) |
| `version` | 낙관적 동시성. 전이마다 +1 (트리거 자동 종료 포함) |

### 2.4 `career.moderation_case_events` (신규 — 이력, 추가만)

DDL은 §2.2에 있다. `actor_user_id`가 NULL이면 system이다.
- 메모·진술 원문은 넣지 않는다.
- 검수 건은 지우지 않으므로 FK는 `ON DELETE RESTRICT`다. 보존 기간은 정책 §10에서 정한다(OPEN).
- 0001 `audit_events`에 결과·사유 칸이 없는 동안 결정 이력의 기준 기록이 된다.

### 2.5 `career.content_reports` (신규 — 신고 기능이 승인될 때만)

`report_id`, `case_id`, `reporter_id`, `report_reason_code`(정책 §5.1 코드), `consented_to_review`(bool, 본인 AI 결과 신고 시 열람 고지 동의), `created_at`.

- 같은 사용자가 같은 열린 건을 다시 신고하면 UNIQUE `(case_id, reporter_id)`로 막는다. 이때 신고 수는 늘리지 않는다.
- 신고자 신원은 관리자 상세 화면에서도 기본으로 숨긴다(PROPOSED).

## 3. 상태·전이

상태 모델 문서의 전이표(T01~T13)가 기준이다. 구현 규칙:

1. **한 트랜잭션, 정해진 잠금 순서.** 순서:
   1. 대상 행 `SELECT … FOR UPDATE` (콘텐츠 효과가 있는 전이일 때)
   2. 검수 건 행 `SELECT … FOR UPDATE`
   3. 상태·version·가드 확인
   4. 갱신 (`version+1`)
   5. `moderation_case_events` 1행
   6. 감사 이벤트
   7. 콘텐츠 효과 (공개 전환·색인)
   8. Commit

   대상 → 건 순서는 §2.1 삭제 경로와 같다.
2. **가드는 서버가 DB 값으로 판단한다:**
   - `not self`: `actor ≠ content_owner_id`, `actor ≠ submitted_by`
   - `not first_decider`: `actor ≠ first_decider_id`
   - `appeal_count`, `decided_at + 14일`
3. **이의제기 횟수는 접수 시점에 센다:** T08 APPEAL이 `appeal_count`를 0 → 1로 올리고 `appealed_at`을 기록한다. 같은 트랜잭션에서 상태도 APPEALED로 바꾼다.
   - 재검토 배정(T09)은 횟수를 바꾸지 않는다.
   - 이유: "이의제기 1회"는 **신청 횟수**에 대한 규칙이다. 배정 시점에 세면 접수~배정 사이에 `appeal_count=0`인 APPEALED가 생긴다. 그러면 "재검토 단계" 판정(T03·T05·T06·T07의 `appeal_count == 1`)과 1회 제한이 배정 여부에 따라 흔들린다.
   - 이의제기 철회(T13)는 REJECTED로 되돌리지만 `appeal_count`는 1로 남아 재신청할 수 없다.
4. 요청 본문의 `version`이 현재 값과 다르면 409 `CONFLICT`를 반환하고 아무것도 바꾸지 않는다.
5. 콘텐츠 효과(공개 전환·색인)가 실패하면 상태 변경도 함께 롤백한다.

## 4. API 후보 (PROPOSED — T06 OpenAPI 재추가 필요)

FACT: v0.1 `GET·POST /admin/reviews`는 v0.2에서 삭제됐다. 아래는 새 이름의 제안이다. 경로 이름은 T06 담당 결정(**OPEN**).

| 메서드·경로 | 권한 | 전이 | 성공 |
|---|---|---|---|
| `GET /api/v1/admin/moderation-cases?status&target_type&priority&overdue&cursor` | `admin.content.review` | — | 200 목록 (cursor, 신고자 신원·메모 원문 제외) |
| `GET /api/v1/admin/moderation-cases/{case_id}` | `admin.content.review` | — | 200 상세 (+이력, 열람 감사) |
| `POST /api/v1/admin/moderation-cases/{case_id}/assignment` `{version, assignee_id?}` | `admin.content.review` | T02·T03·T09 | 200 |
| `DELETE /api/v1/admin/moderation-cases/{case_id}/assignment` `{version}` | 담당자 또는 `admin.content.review` | T04·T05 | 200 |
| `POST /api/v1/admin/moderation-cases/{case_id}/decision` `{version, decision: APPROVE\|REJECT, reason_code?, note?}` | 담당자 | T06·T07 | 200 |
| `POST /api/v1/admin/moderation-cases/{case_id}/temporary-hide` `{version, hidden: bool}` | `admin.content.review`, not self | (상태 변화 없음, 게시 후 건) | 200 |
| `GET /api/v1/me/moderation-cases` | 로그인 | — | 200 자기 콘텐츠 건 (상태·사유 코드·표준 문구만) |
| `POST /api/v1/me/moderation-cases/{case_id}/appeal` `{version, statement}` | 소유자 | T08 | 200 |
| `POST /api/v1/me/moderation-cases/{case_id}/withdrawal` `{version}` | 소유자 | PENDING이면 T10(→CLOSED), APPEALED면 T13(→REJECTED, 재신청 불가) | 200 |
| `POST /api/v1/content-reports` `{target_type, target_id, reason_code, consent}` | 로그인 | T01 (REPORT) | 201 새 건 / 200 기존 열린 건 |

- 게시 전 SUBMIT는 콘텐츠 생성 경로가 서버 안에서 만든다(수집 배치·기업 공고 등록·공용 자료 업로드). 별도 공개 API는 두지 않는다(PROPOSED).
- 사용자 경로(`/me/...`)는 `user_id`를 받지 않는다(FACT: API 계약 §1.3).

### 오류 응답 (FACT: 기존 오류 카탈로그만 사용, 새 코드 없음)

| 상황 | HTTP·code |
|---|---|
| 토큰 없음·만료 | 401 `UNAUTHENTICATED` / `TOKEN_EXPIRED` |
| 권한 코드 없음, 자기 콘텐츠 담당·결정·임시 비공개, 재검토 단계 최초 결정자, 담당자 아닌 결정 | 403 `FORBIDDEN` (`log_detail`에 SELF_REVIEW 등 내부 사유) |
| 없는 건, 일반 사용자의 남의 건 | 404 `NOT_FOUND` |
| 결정 완료·종료 건 변경, 이의제기 2회째, 14일 경과 | 409 `APPROVAL_CLOSED` |
| 허용되지 않은 전이, version 불일치 | 409 `CONFLICT` |
| 사유 코드 없음·모름, OTHER 메모 없음, 메모 500자 초과, 검수 대상이 아닌 target_type, 신고 동의 누락 | 422 `VALIDATION_FAILED` |
| JSON 형식 오류 | 400 `MALFORMED_JSON` |
| DB 오류 (전체 롤백) | 503 `DEPENDENCY_UNAVAILABLE` |

## 5. 기존 테이블 재사용

| 기존 (FACT) | 재사용 | 필요한 변경 (PROPOSED, Migration) |
|---|---|---|
| `job_postings.status` draft·published·closed | 게시 전 대기 = `draft`, 승인 = `published` | **게시 중단에 `closed`를 쓸 수 없다**: T18 공고 API는 `published`·`closed`를 모두 노출한다(FACT, `backend/app/repositories/job_postings.py` `VISIBLE_STATUSES`). 그래서 `moderation_hold boolean` 같은 별도 표시와 조회 조건 추가가 필요하다. 형식은 **OPEN**. 기업 공고 등록자 컬럼은 T121 |
| `companies` | 대상 식별 | 노출 철회 표현 (OPEN) |
| `user_documents.visibility/status/owner_user_id` | 공용 자료 식별, 자기 검수 판정, 업로드 자동 검증 실패(`rejected`) | 색인 허용 여부를 검수 승인과 연결 (RAG 색인기 조건) |
| AI 결과 5개 테이블 | 신고 대상 식별, 각 테이블 FK 칸으로 참조 (§1) | 결과 숨김 표시 컬럼 (OPEN). 계정 삭제 시 CASCADE로 지워지므로 §2.1 트리거 경로 적용 |
| `roles`·`permissions`·`role_permissions` | `admin` 역할 재사용 | 권한 `admin.content.review` 추가 (Seed·Migration) |
| `audit_events` | 이벤트 기록 | T83 제안 컬럼(result·reason_code 등)은 T84 Migration 의존 |
| 신규 | — | `moderation_cases`, `moderation_case_events`, (승인 시) `content_reports` |

→ **신규 Migration 필요: 예.** 0001과 겹치지 않는 새 번호로 만들고, T08 러너 절차를 따른다. Staging 적용은 현재 Migration 이력 기준선 HOLD(#178) 해소 후 가능하다.

## 6. 감사 이벤트 (PROPOSED, T83 계약에 등록 필요)

| 전이 | action_code | resource_type | 비고 |
|---|---|---|---|
| T01 SUBMIT (사용자 신고) | `content.review.report` | `moderation_case` | 신규 코드 제안 |
| T01 SUBMIT (게시 전, system) | `content.review.request` | `moderation_case` | 신규 코드 제안 |
| T02·T03·T04·T05·T09 배정·변경·해제 | `admin.content.review` | `moderation_case` | FACT 코드 재사용, `reason_code`에 `ASSIGN` 등 이벤트명 |
| T06·T07 승인·반려 | `admin.content.review` | `moderation_case` | 사유 코드만 기록 |
| 임시 비공개 | `admin.content.review` | `moderation_case` | |
| 상세 열람 (특히 본인 AI 결과) | `admin.content.review` | `moderation_case` | 열람도 기록 |
| T08 이의제기, T10·T13 철회 | `content.review.appeal`, `content.review.withdraw` | `moderation_case` | 신규 코드 제안 |
| T11·T12 대상 삭제로 종료 | 서비스 경로: `admin.content.review` / CASCADE 경로: 계정 삭제 작업의 감사 + `moderation_case_events` | `moderation_case` | §2.1 |

- 기록하지 않는다: 메모·이의제기 진술 원문, 콘텐츠 본문, 신고자 상세, 토큰.
- 감사 기록 실패 → 전이 롤백. 감사 없는 결정은 없다.

## 7. 선행 작업과 의존성

| 선행 | 필요한 결과 | 현재 (2026-11-10) |
|---|---|---|
| PM 승인 | 이 정책·상태 모델 승인 | 미승인 |
| T04 요구사항 | F-027을 1차 제외 → 포함, 검수·신고 FR 추가 | F-027 제외 (FACT) |
| T05 데이터 사전 + T08 Migration | §2·§5 테이블·컬럼 | 없음 |
| T06 OpenAPI | §4 경로·DTO 추가, 추적 검사 통과 | `/admin/reviews` 삭제 상태 |
| T83·T84 | §6 action_code 등록, 감사 컬럼 | 계약 DRAFT, 컬럼 미반영 |
| T15 인증·권한 | `require_permissions` 재사용 | 구현됨 (FACT) |
| T18 공고 API | 게시 중단 표시를 조회 조건에 반영 | 구현됨. 현재 `published`·`closed` 노출 (FACT) |
| T61·T62 | 외부 수집 공고 권리·수집 | T61 게이트 |
| T121 | 기업 담당자 역할·공고 등록자 | 미착수 |
| 신고 기능 | 요구사항·화면·`content_reports` | 없음 (OPEN) |
| Staging Migration 이력 기준선 | Staging 적용 전제 | HOLD (#178) |

T81(검수 큐·조치 API)은 PM 승인, T04·T05·T06 갱신이 끝난 뒤 착수한다. 그 전에는 mock 계약까지만 가능하다. T82(검수 UI)는 T81 계약을 따른다.

## 8. 구현 시 필수 테스트 (T81 인수 기준 제안)

- 전이표 13개 정상 경로와 허용하지 않는 전이 7종 (409 코드 구분)
- 대상 삭제: 서비스 경로(열린 건 먼저 CLOSED) / CASCADE 경로(계정 삭제 → 트리거 자동 CLOSED + 이력) 모두 원본 삭제가 성공하고 `target_id` 이력이 남음, 종료된 건 상태 불변
- 이의제기 접수 즉시 `appeal_count=1`, 철회 후 재신청 409
- 자기 콘텐츠 담당·결정 403, 관리자 1명일 때 PENDING 유지(HOLD 표시)
- 재검토 단계 최초 결정자 403, 이의제기 2회째·14일 경과 409
- 동시 결정 2건 → 1건만 반영, 다른 1건 409 (실제 PostgreSQL, 행 잠금)
- 중복 검수 요청·중복 신고 → 기존 건 반환, 신고 수 1회만 증가
- 사유 코드 없음·OTHER 메모 없음 422, 감사 기록에 메모 원문 없음
- 감사 기록·콘텐츠 효과 실패 시 상태 변경 롤백
- 일반 사용자의 남의 건 404, 비로그인 401
- 기한 초과 시 상태 자동 변경 없음
