# T80 → T81·T82 운영 콘텐츠 검수 구현 계약 (제안)

> 상태: **PROPOSED / 구현 전 리뷰용** · 기능: F-027 · 정책: [MODERATION_POLICY.md](MODERATION_POLICY.md) · 상태 모델: [MODERATION_STATE_DIAGRAM.md](MODERATION_STATE_DIAGRAM.md)
> 이 문서의 API 경로·테이블·컬럼·권한 코드·action_code는 **모두 제안**이다. 기존 확정 계약은 `FACT`로 표시한다.
> **OpenAPI(`docs/api/openapi.yaml`)·`schema.gen.ts`·Migration은 이 PR에서 바꾸지 않는다.** 구현 전에 §7 선행 작업이 끝나야 한다.

## 1. 콘텐츠 유형

| `content_type` (PROPOSED) | 대상 (정책 §2.1) | 참조 테이블 (FACT) | 게시 전 효과 | 게시 후 반려 효과 |
|---|---|---|---|---|
| `job_posting` | 1·2 외부·기업 공고 | `job_postings.job_posting_id` | 승인 시 `draft → published` | 공개 철회 (`closed`로는 불가, §5) |
| `company` | 1 외부 기업 | `companies.company_id` | 승인 시 공고 노출 허용 | 기업·소속 공고 노출 철회 (OPEN) |
| `shared_document` | 3 공용 RAG 자료 | `user_documents.document_id` (`visibility='shared'`) | 승인 시 RAG 색인 허용 | 색인 제거·공개 철회 |
| `ai_result` | 4 신고된 AI 결과 | `document_analyses`, `retrieval_runs`, `agent_runs`, `match_evaluations`, `recommendation_runs` 중 하나 | (게시 전 없음) | 그 결과 숨김 표시 |

`ai_result`는 `ai_result_kind`(위 테이블 이름)로 세분한다(PROPOSED).

## 2. 검수 건 데이터 구조 (PROPOSED)

### 2.1 `career.moderation_cases` (신규 테이블 — Migration 필요)

| 컬럼 | 타입 | 규칙 |
|---|---|---|
| `case_id` | uuid PK | `gen_random_uuid()` |
| `content_type` | varchar(32) | §1 값만 (CHECK) |
| `job_posting_id` / `company_id` / `document_id` / `ai_result_kind` + `ai_result_id` | uuid FK (NULL 허용) | **content_type에 맞는 칸 하나만** 채움 (CHECK). FK `ON DELETE SET NULL` + 서비스가 건을 `CLOSED(TARGET_DELETED)`로 닫음. 다형 `content_id` 단일 칸보다 참조 무결성을 지킬 수 있어 권장 |
| `trigger` | varchar(16) | `PRE_PUBLISH`, `REPORT`, `EXPIRY`, `SOURCE_CHANGE` |
| `status` | varchar(16) | 상태 모델 §2의 6개 (CHECK) |
| `priority` | smallint | 1(긴급)·2(신고)·3(게시 전) |
| `content_owner_id` | uuid FK users NULL | 접수 시점 소유자 스냅샷 (자기 검수 판정용). 외부 수집은 NULL |
| `submitted_by` | uuid FK users NULL | 요청자 (system이면 NULL) |
| `assignee_id` | uuid FK users NULL | IN_REVIEW에서만 값 |
| `first_decider_id` | uuid FK users NULL | 최초 APPROVE·REJECT 때 기록, 이후 불변 |
| `decided_by`, `decided_at` | uuid, timestamptz | 마지막 결정 |
| `reason_code` | varchar(32) NULL | 정책 §5.1 코드. REJECTED면 필수 (CHECK) |
| `reviewer_note` | text NULL | 관리자 전용 메모, 500자. `reason_code='OTHER'`면 필수 (CHECK) |
| `appeal_count` | smallint | 0 또는 1 (CHECK) |
| `appealed_at` | timestamptz NULL | |
| `flags` | text[] NULL | 자동 표시 코드만 (`PII_PATTERN`, `DUPLICATE_SUSPECT`, `BANNED_TERM`). 탐지 원문은 저장하지 않음 |
| `report_count` | integer | 같은 열린 REPORT 건에 들어온 신고 수 |
| `due_at` | timestamptz | 접수 시 우선순위 기한으로 계산 (정책 §6) |
| `close_reason` | varchar(32) NULL | `WITHDRAWN`, `TARGET_DELETED`, `SUPERSEDED`. CLOSED면 필수 |
| `version` | integer | 낙관적 동시성. 전이마다 +1 |
| `created_at`, `updated_at` | timestamptz | |

인덱스 (PROPOSED):
- **열린 건 중복 방지:** 대상별 칸 + `trigger`로 부분 UNIQUE를 겁니다. 조건은 `WHERE status IN ('PENDING','IN_REVIEW','APPEALED')`입니다.
  - REJECTED는 이의제기 대기일 수 있지만 다른 계기의 새 건과 공존할 수 있으므로 조건에서 뺍니다.
- **큐 조회:** `(status, priority, due_at)`.

### 2.2 `career.moderation_case_events` (신규 — 이력, 추가만)

`event_id`, `case_id`, `from_status`, `to_status`, `event`(SUBMIT…CLOSE), `actor_user_id`(NULL=system), `reason_code`, `occurred_at`.

- 메모 원문은 넣지 않는다.
- 0001 `audit_events`에 결과·사유 칸이 없는 동안 결정 이력의 기준 기록이 된다.

### 2.3 `career.content_reports` (신규 — 신고 기능이 승인될 때만)

`report_id`, `case_id`, `reporter_id`, `report_reason_code`(정책 §5.1 코드), `consented_to_review`(bool, 본인 AI 결과 신고 시 열람 고지 동의), `created_at`.

- 같은 사용자가 같은 열린 건을 다시 신고하면 UNIQUE `(case_id, reporter_id)`로 막는다. 이때 신고 수는 늘리지 않는다.
- 신고자 신원은 관리자 상세 화면에서도 기본으로 숨긴다(PROPOSED).

## 3. 상태·전이

상태 모델 문서의 전이표(T01~T12)가 기준이다. 구현 규칙:

1. **한 트랜잭션 안에서 처리한다.** 순서: 건 행 `SELECT … FOR UPDATE` → 상태·version·가드 확인 → 갱신(`version+1`) → `moderation_case_events` 1행 → 감사 이벤트 → 콘텐츠 효과(공개·색인) → Commit.
2. **가드는 서버가 DB 값으로 판단한다:**
   - `not self`: `actor ≠ content_owner_id`, `actor ≠ submitted_by`
   - `not first_decider`: `actor ≠ first_decider_id`
   - `appeal_count`, `decided_at + 14일`
3. 요청 본문의 `version`이 현재 값과 다르면 409 `CONFLICT`를 반환하고 아무것도 바꾸지 않는다.
4. 콘텐츠 효과(공개 전환·색인)가 실패하면 상태 변경도 함께 롤백한다.

## 4. API 후보 (PROPOSED — T06 OpenAPI 재추가 필요)

FACT: v0.1 `GET·POST /admin/reviews`는 v0.2에서 삭제됐다. 아래는 새 이름의 제안이다. 경로 이름은 T06 담당 결정(**OPEN**).

| 메서드·경로 | 권한 | 전이 | 성공 |
|---|---|---|---|
| `GET /api/v1/admin/moderation-cases?status&content_type&priority&overdue&cursor` | `admin.content.review` | — | 200 목록 (cursor, 신고자 신원·메모 원문 제외) |
| `GET /api/v1/admin/moderation-cases/{case_id}` | `admin.content.review` | — | 200 상세 (+이력, 열람 감사) |
| `POST /api/v1/admin/moderation-cases/{case_id}/assignment` `{version, assignee_id?}` | `admin.content.review` | T02·T03·T09 | 200 |
| `DELETE /api/v1/admin/moderation-cases/{case_id}/assignment` `{version}` | 담당자 또는 `admin.content.review` | T04·T05 | 200 |
| `POST /api/v1/admin/moderation-cases/{case_id}/decision` `{version, decision: APPROVE\|REJECT, reason_code?, note?}` | 담당자 | T06·T07 | 200 |
| `POST /api/v1/admin/moderation-cases/{case_id}/temporary-hide` `{version, hidden: bool}` | `admin.content.review`, not self | (상태 변화 없음, 게시 후 건) | 200 |
| `GET /api/v1/me/moderation-cases` | 로그인 | — | 200 자기 콘텐츠 건 (상태·사유 코드·표준 문구만) |
| `POST /api/v1/me/moderation-cases/{case_id}/appeal` `{version, statement}` | 소유자 | T08 | 200 |
| `POST /api/v1/me/moderation-cases/{case_id}/withdrawal` `{version}` | 소유자 | T10·T12 | 200 |
| `POST /api/v1/content-reports` `{content_type, target_id, reason_code, consent}` | 로그인 | T01 (REPORT) | 201 새 건 / 200 기존 열린 건 |

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
| 사유 코드 없음·모름, OTHER 메모 없음, 메모 500자 초과, 검수 대상이 아닌 content_type, 신고 동의 누락 | 422 `VALIDATION_FAILED` |
| JSON 형식 오류 | 400 `MALFORMED_JSON` |
| DB 오류 (전체 롤백) | 503 `DEPENDENCY_UNAVAILABLE` |

## 5. 기존 테이블 재사용

| 기존 (FACT) | 재사용 | 필요한 변경 (PROPOSED, Migration) |
|---|---|---|
| `job_postings.status` draft·published·closed | 게시 전 대기 = `draft`, 승인 = `published` | **게시 중단에 `closed`를 쓸 수 없다**: T18 공고 API는 `published`·`closed`를 모두 노출한다(FACT, `backend/app/repositories/job_postings.py` `VISIBLE_STATUSES`). 그래서 `moderation_hold boolean` 같은 별도 표시와 조회 조건 추가가 필요하다. 형식은 **OPEN**. 기업 공고 등록자 컬럼은 T121 |
| `companies` | 대상 식별 | 노출 철회 표현 (OPEN) |
| `user_documents.visibility/status/owner_user_id` | 공용 자료 식별, 자기 검수 판정, 업로드 자동 검증 실패(`rejected`) | 색인 허용 여부를 검수 승인과 연결 (RAG 색인기 조건) |
| AI 결과 5개 테이블 | 신고 대상 식별 | 결과 숨김 표시 컬럼 (OPEN) |
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
| T08 이의제기, T10·T12 철회 | `content.review.appeal`, `content.review.withdraw` | `moderation_case` | 신규 코드 제안 |

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

- 전이표 12개 정상 경로와 허용하지 않는 전이 6종 (409 코드 구분)
- 자기 콘텐츠 담당·결정 403, 관리자 1명일 때 PENDING 유지(HOLD 표시)
- 재검토 단계 최초 결정자 403, 이의제기 2회째·14일 경과 409
- 동시 결정 2건 → 1건만 반영, 다른 1건 409 (실제 PostgreSQL, 행 잠금)
- 중복 검수 요청·중복 신고 → 기존 건 반환, 신고 수 1회만 증가
- 사유 코드 없음·OTHER 메모 없음 422, 감사 기록에 메모 원문 없음
- 감사 기록·콘텐츠 효과 실패 시 상태 변경 롤백
- 일반 사용자의 남의 건 404, 비로그인 401
- 기한 초과 시 상태 자동 변경 없음
