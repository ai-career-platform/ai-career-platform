# T82 — 실제 Backend API 연동 검증

> **2026-11-10 재확인 (main `1f3465d`, PR #182 병합 후): 판정 변화 없음 — BLOCKED / HOLD.** 아래 §10 참고.
> 판정: **NOT_READY / HOLD** — 실제 API 연동을 하지 않았습니다. 선행 T81 API·OpenAPI 계약·정책 승인·F-027 범위가 없습니다.
> 이 문서의 테스트는 **가짜 fetch를 쓰는 Frontend 계약 테스트**입니다. 실제 API·PostgreSQL 통합 테스트는 실행하지 않았습니다(NOT_RUN).
> 확인일 2026-11-10 · 기준 main `1fe3025` · T82 PR #182 (`task/t82-admin-moderation-ui`)

## 1. 선행조건 확인 (GitHub·main 실제 상태)

| 항목 | 확인 결과 | 근거 |
|---|---|---|
| T82 UI | PR #182 **OPEN**, 리뷰 0건, Mock 기반 구현 | `gh pr view 182` |
| T81 Backend | **없음** — PR·브랜치 없음, `backend/`에 moderation 코드 없음 | `gh pr list`, `git grep moderation origin/main -- backend` |
| OpenAPI 계약 | **없음** — `docs/api/openapi.yaml`에 검수 경로·스키마 없음. v0.1 `/admin/reviews`는 v0.2에서 삭제 | `git grep`, `docs/API_CONTRACT.md` 변경 이력 |
| 생성 타입 | **없음** — `schema.gen.ts`에 검수 타입 없음 | 같음 |
| 데이터 계약 (T05) | **없음** — 데이터 사전·Migration에 `moderation_cases` 없음. T80 계약의 DDL은 제안 스케치 | `database/` |
| 정책 (T80) | **PM 승인 미완료** — 문서 상태 "DRAFT / REVIEW_REQUIRED", "정책 승인: 미완료" | `docs/admin/MODERATION_POLICY.md` |
| F-027 범위 (T04) | **1차 제외** — "1차에 검수할 공개 콘텐츠 없음" | `docs/requirements/traceability/TRACEABILITY.md` |
| 인증·권한 통합 | 기존 `HttpClient`(Bearer·CSRF·401 처리)와 `RequireAuth({ roles })`는 재사용 가능. 검수 권한 `admin.content.review`는 제안 코드로 아직 없음 | `frontend/src/api/http.ts`, Seed |

```text
T82_UI=MOCK_IMPLEMENTED (PR #182 OPEN, not merged)
T81_BACKEND=NOT_IMPLEMENTED
OPENAPI_CONTRACT=NONE
DATABASE_CONTRACT=NONE (T80 proposed sketch only)
POLICY_APPROVAL=NOT_APPROVED
F027_SCOPE_APPROVAL=EXCLUDED_FROM_PHASE_1
REAL_API_READY=NO
```

→ 지시서의 필수 분기에 따라 **실제 API 연동·실제 Adapter 선택·Backend/DB/OpenAPI 구현을 하지 않았습니다.** Mock UI는 그대로 유지합니다.

## 2. 실제 연결한 API

없습니다. `createHttpModerationService`는 만들어져 있지만 `ModerationServiceProvider`가 고르지 않습니다(테스트로 고정).

## 3. HTTP Adapter ↔ 계약 비교

비교 기준은 OpenAPI가 아니라 **T80 구현 계약 §4의 제안**입니다(유일한 문서). T81 OpenAPI가 나오면 그것이 우선입니다.

| 항목 | T80 §4 제안 | 현재 Adapter / 화면 | 판정 |
|---|---|---|---|
| 목록 경로·메서드 | `GET /api/v1/admin/moderation-cases` | 같음 | 일치 |
| 상태·유형·우선순위 필터 | `status`, `target_type`, `priority` | 같은 이름의 쿼리, 비어 있으면 생략 | 일치 |
| 기한 초과 필터 | `overdue` | 없음 (화면은 목록에서 글자로만 표시) | **미지원** |
| 페이지네이션 | `cursor` | 없음 (응답 `next_cursor` 무시, Mock은 항상 null) | **미지원** |
| 상세 | `GET …/{case_id}` (+이력) | 같음, id는 경로 인코딩 | 일치 |
| 담당 시작 | `POST …/assignment {version, assignee_id?}` | `{version}`만 (본인 배정) | 일치 (선택 필드 미사용) |
| 담당 해제 | `DELETE …/assignment {version}` | 없음 | **미지원** (화면 범위 밖) |
| 승인·반려 | `POST …/decision {version, decision, reason_code?, note?}` | 같음 | 일치 |
| 임시 비공개·이의제기·철회·신고 | 각 제안 경로 | 없음 | 의도적 제외 (정책 미승인) |
| 오류 형식 | 기존 카탈로그 `{code, status, message}` | `ApiError(status, code)` → 화면 문구, 409 2종 구분 | 일치 |
| version 충돌 | 409 `CONFLICT` | 본문 `version` 전송, 409 시 재조회 안내 | 일치 |
| 인증 | Bearer | 기존 `HttpClient`가 메모리 토큰을 `Authorization`에 첨부, 비GET은 CSRF 헤더 | 일치 |
| 응답 필드 | 계약에 응답 스키마 **정의 없음** | Frontend 가정: `target_summary`, `events[]`(`actor_id`, `event`), `trigger`, `flags`, `report_count` 등 | **미확정 — T81 OpenAPI와 대조 필요** |

T81 연결 전에 해결해야 할 계약 공백:
1. 응답 DTO (특히 목록에 보여 줄 대상 요약 `target_summary` 존재 여부, 이력 필드 이름, `trigger`/`review_trigger`)
2. 커서 페이지네이션과 `overdue` 필터를 화면에 넣을지
3. 다른 관리자 표시 이름 (현재 ID 표시)
4. `admin.content.review` 권한 확정과 화면 가드 조건

## 4. 추가한 독립 계약 테스트 (Frontend 전용, 가짜 fetch)

`frontend/src/api/moderationHttp.contract.test.ts` — 14건, 실제 `createHttpClient` 사용

| 검증 | 결과 |
|---|---|
| 목록: 주어진 필터만 쿼리로, Bearer 첨부, GET에는 CSRF 헤더 없음 | PASS |
| 상세: case id 경로 인코딩 (`/`·공백) | PASS |
| 담당 시작: `POST`, 본문 `{version}`만 (클라이언트가 사용자 ID를 보내지 않음), CSRF·JSON 헤더 | PASS |
| 승인·반려: 본문 `{version, decision[, reason_code, note]}`, `user_id` 없음 | PASS |
| 읽기 요청에 AbortSignal 전달 (useQuery 의 오래된 응답 무시와 연결) | PASS |
| 서버 오류 6종 → `ApiError(status, code)` → 화면 문구·재조회 여부 | PASS |
| 401 → 기존 `onUnauthorized` 세션 처리 호출 | PASS |
| Provider는 Mock만 생성하고 HTTP Adapter를 import하지 않음 | PASS |
| 기능 플래그는 여전히 Mock 모드 필수 | PASS |

**이 PASS는 실제 API 연동 PASS가 아닙니다.** 서버가 실제로 같은 경로·필드·오류를 쓰는지는 T81 이후에만 확인할 수 있습니다.

## 5. 실행하지 않은 테스트 (NOT_RUN)

지시서 STEP 06의 실제 API 통합 테스트 24개 항목(관리자 로그인 → 목록·필터·상세·배정·승인·반려·사유 저장·이력, 401·403·자기 콘텐츠·다른 담당자·최초 결정자·비공개 데이터, 404·409·version·연속 클릭 실제 변경 1건·422·서버 오류·재조회)은 **모두 NOT_RUN**입니다. 같은 시나리오는 Mock 수준에서 PR #182의 56건 테스트로만 확인돼 있습니다(Mock PASS ≠ 실제 PASS).

PostgreSQL 통합 테스트: **NOT_RUN** (검수 테이블·API 없음, 일회용 DB도 만들지 않음).

## 6. Mock 회귀와 Frontend 검증 (로컬)

PR 본문과 아래 명령 결과를 따릅니다.

```powershell
Set-Location frontend
npm ci; npm run typecheck; npm run lint; npm test; npm run build
npm run check:api   # Windows 로컬은 CRLF 차이만 — OpenAPI·schema.gen.ts 변경 없음, CI(Linux)에서 판정
```

## 7. 정책 승인 상태

T80 정책·상태 모델·권한·이의제기 규칙, DB 트리거 사용, F-027 범위 포함 — **모두 미승인**. 이 문서와 테스트는 어떤 정책도 승인된 것으로 다루지 않습니다.

## 8. 변경 파일 (이번 단계)

| 파일 | 내용 |
|---|---|
| `frontend/src/api/moderationHttp.contract.test.ts` | 신규: HTTP Adapter 독립 계약 테스트 14건 |
| `docs/testing/T82_REAL_API_INTEGRATION_VALIDATION.md` | 신규: 이 문서 |

화면·Adapter·Mock·라우팅·인증 코드는 바꾸지 않았습니다. Backend·DB·Migration·OpenAPI·Staging·운영 변경 없음.

## 9. 실연동을 위한 후속 순서

1. PM: T80 정책 승인, F-027을 실제 개발 범위에 포함할지 결정 (T04 갱신)
2. T05·T08: 검수 테이블 데이터 사전·Migration (T80 §2.2 스케치 기반, Staging Migration 기준선 HOLD #178 해소 후 적용)
3. T06: OpenAPI에 검수 경로·DTO 추가 → `npm run gen:api`
4. T81: Backend 구현 + 일회용 PostgreSQL 통합 테스트
5. T82: 생성 타입으로 교체 → §3 공백 해소 → `ModerationServiceProvider`에서 HTTP Adapter 선택(격리 통합 모드 한정) → STEP 06 실제 통합 테스트
6. 운영 활성화는 정책·기능 승인 후 별도 결정

## 10. 재확인 — PR #182 병합 후 (2026-11-10, main `1f3465d`)

### 10.1 선행조건 (실제 코드·GitHub 기준)

| 항목 | 결과 | 판정 |
|---|---|---|
| T82 UI | PR #182 **MERGED** (`1f3465d`). Mock Adapter만 연결, 기능 플래그는 Mock 모드 전용 | PASS (Mock) |
| T81 Backend | PR·브랜치 없음. `backend/`·`database/`·`docs/api/openapi.yaml`·`schema.gen.ts`에 moderation 없음 | HOLD |
| 승인된 API 계약 | 없음 — T80 구현 계약 §4는 **PROPOSED** | HOLD |
| T04 범위 (F-027) | "**제외**: 1차에 검수할 공개 콘텐츠 없음" 그대로 | HOLD |
| T80 정책 | "정책 승인: 미완료" 그대로 (#181 병합 ≠ 정책 승인) | HOLD |
| T05·T06 계약 갱신 | 없음 | HOLD |
| Staging Migration 기준선 | PR #178 **OPEN**, Staging에 이력 테이블 없음 | HOLD |
| 스테이징 쓰기 승인 | 없음 | HOLD |

→ 지시서 **경로 B** (T81 미구현). 승인된 구현 계약이 없으므로 **실제 연동 코드를 확정하지 않고 BLOCKED**로 둡니다. T81 API·Migration은 작성하지 않았습니다.

### 10.2 Staging 읽기 전용 점검 (접속 정보 비공개)

| 항목 | 방법 | 결과 |
|---|---|---|
| STAGING_CONNECTION | `.env` 기존 접속으로 `default_transaction_read_only=on` 세션 | PASS — `ai_career_poc`, PostgreSQL 18.1, 세션 read-only on |
| STAGING_SCHEMA | `pg_tables`·`pg_proc` 조회 | `career` 테이블 51개, **검수 테이블·함수 0개**, Migration 이력 테이블 없음 → 검수 스키마 **NOT_PRESENT** |
| STAGING_READ_ONLY | 위 SELECT만 실행 | PASS (변경 없음) |
| STAGING_API | 배포 API에 인증 없는 GET | `/api/version` 200 — 배포 버전 **`1f3465d`**(최신 main), `/api/v1/admin/moderation-cases` **404**, `/api/v1/admin/reviews` 404, `/api/openapi.json` 경로 50개 중 검수 경로 0개 → **NOT_DEPLOYED** |
| Staging 프런트엔드 | headless Chrome으로 `:18080` 열기 | `:18080`은 React 앱이 아니라 **PoC 상태 페이지**(`poc/staging/frontend/index.html`, `status.js`)를 제공. 검수 메뉴·Mock 안내 0, 검수 API 요청 0 → T82 UI는 Staging에 노출되지 않음 |
| STAGING_WRITE_E2E | — | **NOT_RUN** (정책·계약·Migration·쓰기 승인 없음) |
| STAGING_DATA_INTEGRITY | — | 변경 없음 (쓰기 0건) |

### 10.3 T81 구현자에게 넘기는 T82 연결 체크리스트

T82는 아래가 갖춰지면 **화면 수정 없이** Adapter·타입만 바꿔 연결할 수 있습니다. 각 항목은 T81 OpenAPI로 확정돼야 하며, 지금 값은 T80 제안입니다.

| # | T81이 확정해 줄 것 | T82 쪽 영향 (현재 가정 위치) |
|---|---|---|
| 1 | 목록 `GET` 경로·쿼리 `status`·`target_type`·`priority`(+`overdue`·`cursor` 여부) | `api/moderationHttp.ts` `list`, 계약 테스트 |
| 2 | 목록 항목 DTO — 대상 요약 문자열 제공 여부(현재 `target_summary` 가정), `assignee_id`, `due_at`, `flags`, `report_count`, `version` | `api/moderation.ts` `ModerationCaseSummary` |
| 3 | 상세 DTO — `content_owner_id`·`submitted_by`·`first_decider_id`·`appeal_count`·`reason_code`·`close_reason`, 이력 배열 이름·필드(현재 `events[]`·`actor_id`·`event`) | `ModerationCaseDetail`, `ModerationCaseEvent` |
| 4 | 담당 시작 `POST …/assignment {version}` 응답 = 갱신된 상세 | `assign` |
| 5 | 결정 `POST …/decision {version, decision, reason_code?, note?}` 응답 = 갱신된 상세, `note`는 응답에 미포함 | `decide` |
| 6 | 오류: 401·403 `FORBIDDEN`·404·409 `APPROVAL_CLOSED`/`CONFLICT`·422 `VALIDATION_FAILED` (기존 카탈로그) | `moderationErrorMessage` |
| 7 | 권한 코드(`admin.content.review` 등)와 서버 측 가드 (자기 콘텐츠·담당자·최초 결정자·version) | `RequireAuth`·메뉴 조건, `availableActions`(UX 전용) |
| 8 | 통합 테스트용 합성 데이터 생성 방법 (일회용 DB 픽스처) | 실제 통합 테스트 24항목 실행 전제 |

연결 단계 (T81 병합 후): `npm run gen:api` → 수기 타입을 생성 타입으로 교체 → `ModerationServiceProvider`에서 **격리 통합 모드에서만** `createHttpModerationService` 선택 (Mock 모드·운영 빌드는 그대로) → 일회용 PostgreSQL + 로컬 FastAPI로 §5의 24항목 실행 → Staging은 쓰기 승인 후.

### 10.4 이번 단계 테스트

코드 변경 없음(문서만). Frontend·Backend 코드는 main과 같으므로 회귀 결과는 PR #182 시점(Frontend 302 passed / 22 skipped)과 이 PR의 CI로 확인합니다. 로컬 FastAPI·일회용 PostgreSQL 통합 테스트와 브라우저 실 API E2E는 **NOT_RUN**(연결할 API 없음).
