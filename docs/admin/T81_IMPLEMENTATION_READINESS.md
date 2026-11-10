# T81 운영 콘텐츠 검수 — 구현 준비 계약 (STEP 18)

> 상태: **PROPOSED / 미승인 — 계약 갱신안.** 범위·정책·DB·API 어느 것도 승인되지 않았다. T81 실제 구현 착수는 **HOLD**.
> 기준 main `1f3465d` · 작성 2026-11-10 · 등급 표기는 [정책 §0](MODERATION_POLICY.md#0-읽는-법--근거-등급)과 같다 (`FACT` / `PROPOSED` / `OPEN`).
> 함께 읽기: [정책](MODERATION_POLICY.md) · [상태 모델](MODERATION_STATE_DIAGRAM.md) · [구현 계약](MODERATION_IMPLEMENTATION_CONTRACT.md) · OpenAPI 제안 조각 [`t81_openapi_proposal.yaml`](t81_openapi_proposal.yaml)
> **이 PR은 확정 계약 파일(`TRACEABILITY.md`, `openapi.yaml`, `DATA_DICTIONARY.md` 등)을 고치지 않는다.** 고치면 F-027이 승인된 것처럼 읽히기 때문이다. 대신 정확한 수정안을 이 문서에 두고, OpenAPI 조각은 `test_t81_contract_readiness.py`가 실제 `openapi.yaml`과 합쳐 기존 검사기로 검증한다.

## 1. 현재 상태 확인

| # | 항목 | 등급 | 내용 · 근거 |
|---|---|---|---|
| 1 | F-027 1차 제외 위치 | FACT | `docs/requirements/traceability/TRACEABILITY.md` 37행 "**제외**: 1차에 검수할 공개 콘텐츠 없음", `docs/requirements/overview/PROJECT_OVERVIEW.md` 41행, `docs/API_CONTRACT.md` 변경 이력 "`GET·POST /admin/reviews` 삭제", `database/FULL_DATABASE_MODEL.md` 241행(테이블 추가 안 함)·261행(`audit_events` 검수 연결 제거). `UI-027`은 요구사항 화면 목록에 없음. `docs/FULL_SCOPE_TRACEABILITY.md` 53행만 `GET /api/v1/admin/reviews`(구 경로)로 남아 있음 |
| 2 | T80 미확정 항목 | FACT | [정책 §10](MODERATION_POLICY.md#10-미확정-항목-pm담당자-결정-필요) 10건 + 트리거 사용 여부 + 이의제기 철회 규칙 → 이 문서 §9 결정표 |
| 3 | T81 Backend | FACT | 없음 — PR·브랜치·`backend/` 코드 없음. 작업지시서 [T81](../work-orders/remaining-30/T81.md) 산출물은 아직 `/api/v1/admin/reviews` 표기 |
| 4 | 검수 테이블 | FACT | 없음 (0001~0003). DDL은 [구현 계약 §2.2](MODERATION_IMPLEMENTATION_CONTRACT.md#22-ddl-스케치-proposed--migration-파일-아님) **스케치**(PostgreSQL 18 실행 검증 완료, Migration 아님) |
| 5 | OpenAPI 검수 경로 | FACT | 없음 (`openapi.yaml` operations 75, 검수 0). 이 문서 §5와 제안 조각 |
| 6 | 관리자 인증·권한 | FACT | 역할 `job_seeker`·`admin`, 권한 `admin.models.read`·`admin.audit.read`(Seed), 서버 의존성 `require_roles`·`require_permissions`(403)·`ensure_owner`(404) — `backend/app/dependencies/auth.py`. 매 요청 DB에서 세션·역할 재확인 |
| 7 | 오류 카탈로그 | FACT | `backend/app/core/errors.py`: `INVALID_CURSOR`(400), `MALFORMED_JSON`(400), `UNAUTHENTICATED`(401), `FORBIDDEN`(403), `NOT_FOUND`(404), `CONFLICT`·`APPROVAL_CLOSED`(409), `VALIDATION_FAILED`(422), `DEPENDENCY_UNAVAILABLE`(503) — 새 코드 불필요 |
| 8 | 감사 이벤트 | FACT | 0001 `audit_events(actor_user_id, action_code, resource_type, resource_id, request_id, occurred_at)` — 결과·사유 칸 없음. T83 계약에 `admin.content.review` 있음. Backend에서 `audit_events`에 쓰는 코드는 T73 `system.behavior.purge` 하나 |
| 9 | Migration 관리 | FACT | `database/migrate.py`(번호 순 forward-only, 체크섬, Staging 가드). 다음 번호 `0004`. Staging은 이력 기준선 없음 → PR #178 OPEN, 적용 HOLD |
| 10 | T82 Adapter 기대 | FACT | `frontend/src/api/moderationHttp.ts`(미연결) + 수기 타입 `frontend/src/api/moderation.ts` → §6 매핑 |

## 2. F-027 개발 범위 변경안 (PROPOSED — PM 승인 전)

### 2.1 범위 변경표

| 기능 | 제안 범위 | 이유 |
|---|---|---|
| 관리자 검수 큐 (필터·커서·기한 초과) | **이번 구현** | T82 화면이 이미 있음 |
| 검수 상세 + 처리 이력 | **이번 구현** | 같음 |
| 담당 시작 (본인 배정, 재검토 배정 포함) | **이번 구현** | T02·T09 |
| 승인·반려 (사유 코드, OTHER 설명) | **이번 구현** | T06·T07 |
| 서버 권한 검증 (자기 콘텐츠·담당자·최초 결정자), version 충돌, 중복 처리 방지 | **이번 구현** | 보안 경계 |
| 감사 기록 | **이번 구현** | 기존 `audit_events` 재사용 |
| 담당 변경(T03)·해제(T04·T05) | 후속 | T82에 화면 없음 |
| 이의제기 접수·철회 (사용자 `/me` 경로) | 후속 | 이의제기 규칙 미승인 |
| 신고 접수 (`content_reports`) | 후속 | 요구사항·법무(열람 고지) 미정 |
| 게시 중단 표시·임시 비공개 (자동 포함) | 후속 | 표시 형식·남용 위험 미정 |
| 기업 담당자 검수 요청 | 후속 (T121) | 역할 없음 |
| 처리 기한 자동화 (알림 등) | 후속 | 영업일 달력 미정 |
| 기존 실제 콘텐츠 일괄 검수 | 제외 | 실데이터 영향 |

이번 구현 범위의 검수 건은 **합성 Fixture와 서버 내부 생성 경로로만** 만들어진다(게시 전 검수 자동 생성은 수집·업로드 경로 변경이 필요해 후속).

### 2.2 T04 수정안 (적용하지 않음 — 승인 후 그대로 반영)

| 파일 | 현재 | 수정안 |
|---|---|---|
| `docs/requirements/traceability/TRACEABILITY.md` 37행 | `\| F-027 \| 운영 콘텐츠 검수 \| **제외**: 1차에 검수할 공개 콘텐츠 없음 \| — (T80~T82) \|` | `\| F-027 \| 운영 콘텐츠 검수 \| FR-ADM-007 (학습 범위, 축소: 큐·상세·배정·승인·반려·이력) \| T80~T82 \|` |
| 같은 파일 `## 2. 화면 목록` | `UI-027` 없음 | `\| UI-027 \| 관리자 검수 \| …` 행 추가 (형식은 기존 행을 따름) |
| `docs/requirements/functional/ADMIN.md` | FR-ADM-001~006 | `### FR-ADM-007 운영 콘텐츠 검수` 추가 — 사용자 스토리 "운영 관리자로서 공개될 콘텐츠를 승인·반려하고 이력을 남기고 싶다", 수용 기준: ① admin 권한만, ② 자기 콘텐츠 검수 불가, ③ 담당자만 결정, ④ 반려 사유 필수, ⑤ 동시 처리 시 한 건만 반영, ⑥ 모든 결정 감사 기록 |
| `docs/requirements/overview/PROJECT_OVERVIEW.md` 41행 | 제외 사유 | "학습 범위로 축소 포함 (FR-ADM-007), 신고·이의제기·자동 조치는 후속" |
| `docs/FULL_SCOPE_TRACEABILITY.md` 53행 | `GET /api/v1/admin/reviews` | `GET /api/v1/admin/moderation-cases`, 테이블 `moderation_cases`·`moderation_case_events` |
| `docs/work-orders/remaining-30/T81.md` §3 | `/api/v1/admin/reviews` | `/api/v1/admin/moderation-cases` (경로 이름 결정 후, §9-11) |

## 3. T05 데이터 모델 (PROPOSED)

설계 본문은 [구현 계약 §2](MODERATION_IMPLEMENTATION_CONTRACT.md#2-검수-건-데이터-구조-proposed)가 기준이며 여기서는 확인 결과만 둔다.

| # | 항목 | 정리 (구현 계약 위치) | 상태 |
|---|---|---|---|
| 1 | 기본키 | `case_id uuid` `gen_random_uuid()` | 확정 가능 |
| 2 | 대상 유형 | `target_type` 8종 = 대상 테이블 1:1 (§1) | 확정 가능 |
| 3 | 불변 스냅샷 | `target_type`·`target_id` NOT NULL, FK 아님, 변경 거부 (§2.1) | 확정 가능 |
| 4 | 대상별 FK | 8칸, NULL 허용, `ON DELETE SET NULL`. CHECK는 "최대 1칸 + 채워졌으면 유형 일치·`= target_id`" (§2.1) | 확정 가능 — SET NULL·CHECK 충돌 해소를 PG18에서 실행 검증 |
| 5 | 상태 | 6개 CHECK (상태 모델 §2) | 확정 가능 (CLOSED 정책은 §9) |
| 6 | 담당·결정자 | `assignee_id`(IN_REVIEW에서만, CHECK), `first_decider_id`(불변), `decided_by`·`decided_at` | 확정 가능 |
| 7 | 반려 사유 | `reason_code` 9종(REJECTED면 필수), `reviewer_note` 500자(OTHER면 필수), 응답·감사에 메모 없음 | 코드 목록은 §9-6 |
| 8 | 이의제기 횟수 | `appeal_count` 0/1, **접수(T08) 시 증가**, `APPEALED ⇒ 1` CHECK | 확정 가능 |
| 9 | version | 정수, 전이마다 +1, 요청 본문으로 비교 | 확정 가능 |
| 10 | 시각 | `created_at`·`updated_at`·`decided_at`·`appealed_at`·`due_at` (UTC) | 확정 가능 |
| 11 | 처리 이력 | `moderation_case_events` 추가만, FK `ON DELETE RESTRICT`, 메모 원문 없음 | 확정 가능 |
| 12 | 인덱스·UNIQUE | 열린 건 부분 UNIQUE `(target_type, target_id, review_trigger)`, 큐 `(status, priority, due_at)` + 정렬 안정용 `case_id` | 확정 가능 |
| 13 | FK 삭제 정책 | 대상·사용자 FK SET NULL, 이력 RESTRICT → **계정·문서 삭제를 막지 않음** | 확정 가능 |
| 14 | DB 트리거 | 아래 §3.1 비교 | **OPEN (§9-4)** |
| 15 | 감사 테이블 | 기존 `audit_events` 재사용 (§8) | 확정 가능 |

`FULL_DATABASE_MODEL.md`·`DATA_DICTIONARY.md` 수정안: 241행 "제외 0"을 "검수 2개 테이블 추가(F13 `moderation_cases`, F14 `moderation_case_events`)"로, 261행 `audit_events`에 "검수 결정·열람 감사(F-027) 재연결" 추가. `content_reports`는 신고 기능 승인 시 F15.

### 3.1 DB 트리거 방식 비교 (구현 계약 §2.1의 CASCADE 대응)

| 기준 | A. DB 트리거 | B. 서비스 계층 + 정리 작업 |
|---|---|---|
| 지금 존재하는 삭제 경로 | **FACT**: T50 문서 정리 작업(`backend/app/document_worker.py`)이 `user_documents` 행을 실제로 지우고, FK CASCADE로 `document_analyses`가 함께 지워진다 → `shared_document`·`document_analysis` 검수 대상이 **검수 서비스를 거치지 않고** 사라질 수 있다 | 같은 경로에서 문서 정리 작업이 검수 서비스를 불러야 함(모듈 결합). CASCADE로 지워지는 `document_analyses`는 정리 작업이 직접 알 수 없음 → 정기 정리 작업 필요 |
| 사용자 물리 삭제 | 아직 없음(T31은 비활성화만, D-06 미정). 생기면 자동 대응 | 생길 때마다 호출 추가 필요 |
| 열린 건이 대상 없이 남는 시간 | 0 (같은 트랜잭션) | 정리 작업 주기만큼 |
| 검증 근거 | T80에서 PG18 일회용 DB로 서비스·2단계 CASCADE 경로 실행 검증 (`docs/admin/moderation_sketch_scenario.sql`) | 새로 작성·검증 필요 |
| 저장소 관례 | 0001~0003에 트리거 없음 → 새 패턴 (Migration·리뷰 필요). T71·T83 mock은 함수·트리거 사용 | 기존 관례(T73 `behavior_data` 같은 명시적 작업)와 비슷 |
| 디버깅 | 숨은 동작 — 문서화·테스트 필수 | 코드에서 보임 |

**추천: A (DB 트리거)** — 이미 존재하는 문서 정리 CASCADE 경로를 결합 없이 막을 수 있고 실행 검증이 끝났다. 단 저장소 첫 트리거이므로 Migration 리뷰에서 명시 승인받는다. 승인되지 않으면 B로 하되, 문서 정리 작업에 검수 종료 호출을 넣고 "대상 없는 열린 건" 정리 작업(+ T73식 품질 검사)을 같이 만든다. **운영 방식으로 확정하지 않음.**

### 3.2 Migration 계획 (작성·실행 안 함)

- 파일 `database/migrations/0004_moderation_cases.sql` — 구현 계약 §2.2 스케치 기반, `-- Purpose:`·`-- Recovery:` 헤더, 트리거 결정 반영. `admin.content.review` 권한·`admin` 역할 연결은 Seed 갱신(또는 같은 Migration의 멱등 INSERT, §9-12에서 결정)
- 검증 순서: 일회용 PostgreSQL 18에서 `migrate.py lint/apply --target local/verify` → `moderation_sketch_scenario.sql` 수준의 삭제 시나리오 → pytest 통합
- **Staging 적용은 PR #178(이력 기준선) 해소 + 별도 승인 후.** 0002·0003도 아직 Staging 미적용이다

## 4. 감사·권한 모델 요약 (PROPOSED)

- 권한: 기존 `admin` 역할에 **권한 `admin.content.review`** 추가(새 역할 없음). 라우터는 `require_permissions("admin.content.review")`로 보호(FACT: 의존성 존재, 권한 코드는 아직 Seed에 없음)
- 서버 가드(서비스 계층, 행 잠금 안에서 DB 값으로): 자기 콘텐츠(`actor ∈ {content_owner_id, submitted_by}`) 403, 담당자 아님 403, 재검토 단계 최초 결정자 403, 결정·종료 409 `APPROVAL_CLOSED`, 상태·version 불일치 409 `CONFLICT`
- Frontend 버튼 비활성화는 UX일 뿐 — T82 `availableActions`는 보안 경계가 아니다

## 5. T06 OpenAPI 제안 — 8개 항목 정리

제안 조각: [`t81_openapi_proposal.yaml`](t81_openapi_proposal.yaml) (경로 4개, 스키마 10개). 기존 `Limit`·`Cursor`·응답 컴포넌트를 재사용한다.

| # | 항목 | 제안 (확정 가능 수준) | 남은 OPEN |
|---|---|---|---|
| 1 | 목록 응답 DTO | `ModerationCasePage {items: ModerationCaseSummary[], next_cursor}` — 항목 14필드: `case_id, target_type, target_id, target_summary(nullable, ≤200, 서버 생성 공개 요약), trigger, status, priority, assignee_id, due_at, overdue, flags[], report_count, version, created_at`. 신고자·메모·원문 없음 | `target_summary`를 AI 결과에 어떻게 만들지(유형 이름만 제안) |
| 2 | 상세 응답 DTO | 목록 14필드 + `content_owner_id, submitted_by, first_decider_id, decided_by, decided_at, reason_code, appeal_count, close_reason, events[]` (메모 없음) | — |
| 3 | 처리 이력 DTO | 상세에 **포함**(별도 경로 없음), `occurred_at` 오름차순. 필드 `event_id, event, from_status, to_status, actor_user_id(null=system), reason_code, occurred_at` — 기존 `AuditEvent`와 같은 `actor_user_id` 이름 | — |
| 4 | cursor | 기존 목록과 동일: `limit` 1~100 기본 20, 서버 HMAC 서명 불투명 문자열, **필터 값에 묶임**(바꾸면 400 `INVALID_CURSOR`), 정렬 `priority ASC, due_at ASC, case_id ASC` 고정, 마지막 페이지 `next_cursor: null` | — |
| 5 | `overdue` | 쿼리 `overdue=true\|false`(생략 시 전체), 응답 필드 `overdue`. 정의: 열린 상태 && `due_at < 서버 now()`(UTC). 자동 처리 없음 | 영업일 기반 기한 계산(§9-7) |
| 6 | 배정 | `POST …/assignment {version}` → 요청자 본인 배정(T02·T09), 200 갱신된 상세. **변경(T03)·해제(T04·T05)는 이번 범위 밖** — 후속 제안 형태: 변경 `{version, assignee_id}`, 해제 `POST …/assignment/release {version}`(DELETE 본문 회피) | 후속 범위 승인 |
| 7 | 오류 | 400 `INVALID_CURSOR`/`MALFORMED_JSON`, 401, 403 `FORBIDDEN`, 404, 409 `APPROVAL_CLOSED`(결정·종료)/`CONFLICT`(상태·version), 422 `VALIDATION_FAILED`(사유 누락·OTHER 설명 누락·APPROVE에 사유 전송·잘못된 필터) — 모두 기존 카탈로그 | — |
| 8 | 합성 Fixture | §7 표 — 9건(T82 Mock과 같은 시나리오), 고정 UUID, `@example.invalid`, 일회용 DB에서만 로드(DB 이름 가드) | Fixture 파일 위치·로더(T81 구현 시) |

이번 범위 경로 4개는 위 조각에 있다. 후속(담당 변경·해제, 이의제기, 철회, 임시 비공개, 신고, `/me` 조회)은 [구현 계약 §4](MODERATION_IMPLEMENTATION_CONTRACT.md#4-api-후보-proposed--t06-openapi-재추가-필요) 제안대로 두고 이번 조각에 넣지 않았다.

**검증:** `test_t81_contract_readiness.py`가 조각을 `openapi.yaml`과 합친 뒤 `docs/api/check_openapi.py`의 `validate_spec`·`check`를 실행한다. 이때 T04·T05 수정안(FR-ADM-007, UI-027, 두 테이블)만 검사기에 임시로 더한다 → **오류 0** (§11). 실제 `openapi.yaml`·`schema.gen.ts`는 그대로다.

## 6. T82 HTTP Adapter 호환성

| 대상 | T82 현재 (`frontend/src/api/moderation.ts`) | 제안 계약 | T82 조치 |
|---|---|---|---|
| 목록 경로·필터 | `GET /v1/admin/moderation-cases?status&target_type&priority` | 같음 + `overdue`, `limit`, `cursor` | 필터 유지. 커서 "더 보기" 추가, `overdue` 필터 선택 |
| 목록 항목 | 12필드 | 12필드 + `overdue`, `created_at` | 생성 타입으로 교체 (추가 필드 무시 가능) |
| 상세 | 같은 이름 9필드 + `events` | 같음 | 생성 타입으로 교체 |
| 이력 항목 | `actor_id` | **`actor_user_id`** | 필드 이름 1곳 변경 (`ModerationCasePage`의 이력 표시) |
| 담당 시작 | `POST …/assignment {version}` | 같음 | 없음 |
| 결정 | `POST …/decision {version, decision, reason_code?, note?}` | 같음 (APPROVE에 사유 보내면 422) | 없음 (화면이 APPROVE에 사유를 보내지 않음) |
| 오류 처리 | `moderationErrorMessage` 401·403·404·409 2종·422 | 같은 코드 + 400 `INVALID_CURSOR` | 400 문구 추가 (커서 만료 → 처음부터) |
| 서비스 선택 | Mock만 (`ModerationServiceProvider`) | — | 격리 통합 모드에서만 HTTP Adapter 선택 |

차이는 `actor_id → actor_user_id`, 추가 필드 2개, 페이지네이션·`overdue`뿐이다. 차이 목록은 테스트가 실제 TypeScript 타입과 제안 스키마를 비교해 고정한다.

## 7. 권한·상태 전이 ↔ API

| 전이 ([상태 모델 §3](MODERATION_STATE_DIAGRAM.md#3-전이표)) | 이번 API | 서버 판정 · 실패 응답 |
|---|---|---|
| T01 SUBMIT | 없음 — Fixture·서버 내부 생성 | 열린 건 중복이면 기존 건 반환 |
| T02 ASSIGN (PENDING) | `POST …/assignment` | 자기 콘텐츠 403, IN_REVIEW 409 `CONFLICT`, version 409, 결정·종료 409 `APPROVAL_CLOSED` |
| T03 REASSIGN | 후속 | — |
| T04 RELEASE | 후속 | — |
| T05 RELEASE_APPEAL | 후속 | — |
| T06 APPROVE | `POST …/decision` | 담당자 아님·자기 콘텐츠·재검토 최초 결정자 403, PENDING·APPEALED 409 `CONFLICT`, 결정·종료 409 `APPROVAL_CLOSED` |
| T07 REJECT | `POST …/decision` | T06과 같음 + 사유·OTHER 설명 422 |
| T08 APPEAL | 후속 (`/me`) | — (Fixture로만 APPEALED 건 생성) |
| T09 ASSIGN (APPEALED) | `POST …/assignment` | 최초 결정자·자기 콘텐츠 403 |
| T10 CLOSE (owner 철회) | 후속 (`/me`) | — |
| T11 CLOSE (system, 검수 중 대상 삭제) | 없음 — 삭제 경로(§3.1) | — |
| T12 CLOSE (system, 이의제기 중 대상 삭제) | 없음 — 삭제 경로(§3.1) | — |
| T13 WITHDRAW_APPEAL | 후속 (`/me`) | — |

공통: 미로그인 401, 권한 없음 403, 없는 건 404. 모든 쓰기는 대상 행 → 검수 건 행 순서로 잠근다([구현 계약 §3](MODERATION_IMPLEMENTATION_CONTRACT.md#3-상태전이)).

## 8. 감사 계약 (PROPOSED)

- 배정·승인·반려·상세 열람: `audit_events`에 `action_code='admin.content.review'`, `resource_type='moderation_case'`, `resource_id=case_id`, `actor_user_id`, `request_id`(요청 ID) — 상태 변경과 **같은 트랜잭션**, 실패 시 전체 롤백
- 이벤트 종류·사유 코드는 `moderation_case_events`가 담는다(0001 `audit_events`에 칸 없음, T83 확장은 T84)
- 메모 원문·콘텐츠 본문·신고자 정보는 어디에도 기록하지 않는다

## 9. PM 결정표

| # | 항목 | 현재 | 추천 결정 | 근거 | 구현 영향 | 미뤄도 되나 | T81 착수 전 필수 |
|---|---|---|---|---|---|---|---|
| 1 | F-027 범위 포함 | 1차 제외 (FACT) | §2.1 축소 범위로 포함 | T82 화면 완료, 학습 목적 | T04 수정안 반영 | 아니오 | **예** |
| 2 | T80 정책 승인 | 미승인 | 이번 범위 항목만 부분 승인 (§2.1) | 후속 항목과 분리 가능 | 정책 문서 등급 갱신 | 아니오 | **예** |
| 3 | 대상별 적용 범위 | 4종 제안 | 이번엔 Fixture 기반 8유형 모델만, 실제 생성 경로는 후속 | 실데이터·수집 경로 영향 없음 | 생성 API 없음 | 예 | 아니오 |
| 4 | DB 트리거 | OPEN | A 트리거 (§3.1) | 기존 CASCADE 경로 존재, 실행 검증 완료 | 0004 Migration 내용 | 아니오 | **예** |
| 5 | 이의제기 철회 규칙 | PROPOSED (T13) | 제안대로 두되 이번 범위 밖 | 사용자 경로가 후속 | 없음 | 예 | 아니오 |
| 6 | 반려 사유 코드 | 9종 + `FRAUD` OPEN | 9종 유지, `FRAUD`는 `HARMFUL`로 | 코드 추가는 나중에 쉬움(enum 확장) | enum·CHECK | 예 (기본안 사용) | 아니오 (기본안이면) |
| 7 | 처리 기한 | 영업일 가안 | 이번엔 달력 시간(24h·48h·72h)으로 `due_at` 계산, 자동 처리 없음 | 영업일 달력 미정 | `due_at` 계산 함수 | 예 | 아니오 |
| 8 | 공고 게시 중단 표시 | OPEN (`closed` 불가) | 이번 범위 밖 (승인·반려 결과를 공고에 반영하지 않음) | 게시 중단 기능이 후속 | 없음 | 예 | 아니오 |
| 9 | 관리자 부족 시 재검토 | HOLD 제안 | HOLD 유지 (우회 없음) | 권한 분리 원칙 | PENDING 유지 표시 | 예 | 아니오 |
| 10 | 검수 기록 보존 기간 | OPEN | T83 `security` 등급과 같게 (값은 T83에서) | 감사 계약과 일관 | 이번엔 삭제 작업 없음 | 예 | 아니오 |
| 11 | API 경로 이름 | `/admin/reviews`(T81 지시서) vs `/admin/moderation-cases`(T80) | `/admin/moderation-cases` | 리소스 이름 명확, T82 Adapter와 일치 | T81 지시서·FULL_SCOPE 수정 | 아니오 | **예** |
| 12 | 권한 코드 | `admin.content.review` 제안 | 승인, Seed 갱신 | 기존 `admin.*` 관례 | Seed·Migration | 아니오 | **예** |

개인정보·실데이터·운영 권한에 닿는 항목(신고 열람 고지, 실제 콘텐츠 반영, Staging 쓰기)은 추천만 하고 승인 처리하지 않았다.

## 10. T81 구현 순서 (승인 후)

| # | 단계 | 파일 후보 (기존 패턴) | 테스트 기준 | 완료 조건 |
|---|---|---|---|---|
| 1 | 일회용 PG 18 환경 | 기존 `pg_app` fixture (`backend/tests/test_profile_postgres.py`) 재사용 | `T16_ISOLATED_DB_TEST=YES`, loopback·DB 이름 가드 | fixture가 0001~0004 적용 |
| 2 | Migration | `database/migrations/0004_moderation_cases.sql` | `migrate.py lint/apply --target local/verify`, 삭제 시나리오 SQL | verify PASS, 삭제 시나리오 PASS |
| 3 | Model | `backend/app/models/moderation.py` (T72 `models/behavior.py` 방식) | import·매핑 | 컬럼 이름 = Migration |
| 4 | DTO | `backend/app/schemas/moderation.py` (`extra="forbid"`) | 422 경계 | 제안 조각 스키마와 일치 |
| 5 | Repository | `backend/app/repositories/moderation.py` (행 잠금: T31 `lock_user` 방식) | 커서·필터 SQL | 대상 → 건 잠금 순서 |
| 6 | Service·전이 | `backend/app/services/moderation.py` | 전이 T02·T06·T07·T09 표, 가드 | 상태 모델과 1:1 |
| 7 | Router | `backend/app/routers/admin_moderation.py`, `api_v1.py` 등록 | OpenAPI 경로·operationId | 제안 조각과 동일 |
| 8 | 인증·권한 | `require_permissions("admin.content.review")` + Seed | 401·403 | 권한 없는 admin 403 |
| 9 | 감사 | 서비스 안에서 `audit_events` INSERT (T73 패턴) | 감사 실패 시 롤백 | 결정·열람마다 1행 |
| 10 | pytest 단위 | `backend/tests/test_moderation.py` (메모리 저장소, T72 방식) | 정상·오류·경계 | 전이·오류 매트릭스 |
| 11 | PG 통합 | `backend/tests/test_moderation_postgres.py` | 동시 결정 1건만, version, 롤백, CASCADE 종료 | 로컬 PASS |
| 12 | OpenAPI·생성 타입 | 조각을 `openapi.yaml`에 병합, `check_openapi.py`, `npm run gen:api` | `check:api`, 추적 검사 | 예외 목록 변화 없음 |
| 13 | T82 Adapter 연결 | `ModerationServiceProvider`(격리 통합 모드만), §6 조치 | 계약 테스트 갱신 | Mock 모드 유지 |
| 14 | 로컬 브라우저 E2E | 기존 Playwright/headless 방식, 1280·375 | 실제 HTTP·DB 상태 확인 | T82 24항목 PASS |
| 15 | Staging | 승인 후 | 읽기 전용 → 쓰기 승인 시 합성 건만 | 기준선(#178)·쓰기 승인 |

## 11. 테스트 계획

- **Fixture 계약 (8번):**

| 건 | 상태 | 대상 | 목적 |
|---|---|---|---|
| F1 | PENDING, P1, 기한 지남, `PII_PATTERN` | job_posting | 배정·`overdue` |
| F2 | PENDING, 소유자 = 관리자 A | shared_document | 자기 콘텐츠 403 |
| F3 | IN_REVIEW, 담당 A | job_posting | 승인·반려 |
| F4 | IN_REVIEW, 담당 B | job_posting | 담당자 아님 403 |
| F5 | APPEALED, 최초 결정자 A | document_analysis | 재검토 최초 결정자 403 |
| F6 | APPEALED, 최초 결정자 B | company | 재검토 배정 |
| F7 | APPROVED | job_posting | 409 `APPROVAL_CLOSED` |
| F8 | REJECTED (HARMFUL) | retrieval_run | 사유·이력 |
| F9 | CLOSED (TARGET_DELETED) | job_posting(대상 삭제) | 종료 표시 |

  관리자 A·B·C(`admin` + `admin.content.review`), 권한 없는 admin D, 일반 사용자 U, 소유자 O — 모두 `@example.invalid`, 고정 UUID. 일회용 DB에서만 로드.
- **이번 PR 문서 검증:** §12
- **실제 API·PostgreSQL 통합:** **NOT_RUN** (구현 전)

## 12. 이번 PR 검증 결과

| 검증 (2026-11-10, Windows, Python 3.12) | 결과 |
|---|---|
| `python -B -m unittest docs/admin/test_moderation_state_model.py -v` (T80 기존) | 41건: 40 OK + 1 skip (opt-in PostgreSQL 스케치 실행 — 이번 미실행) |
| `python -B -m unittest docs/admin/test_t81_contract_readiness.py -v` (신규, pyyaml·jsonschema·openapi-spec-validator 필요) | **16 OK** — 병합 명세가 기존 검사기 오류 0, T04·T05 수정안 없이는 거부됨, T82 타입 차이 = §6 문서와 동일, enum·오류 코드·권한·Adapter 경로·전이 T01~T13 일치 |
| 같은 테스트, 의존성 없는 Python | 7 OK + 9 skip (OpenAPI 검사 부분만 skip) |
| 대조 실험 | 조각에 끊어진 `$ref` → 실패, 관리자 상세 경로의 401 제거 → "protected operation without 401"로 실패, 복원 후 PASS |
| `python docs/api/check_openapi.py`, `docs/api/test_check_openapi.py` | PASS (실제 `openapi.yaml` 변경 없음: operations 75), 9 OK |
| 실제 Backend·DB·Staging | 변경·실행 없음 (API·PostgreSQL 통합 **NOT_RUN**) |

## 13. Staging 적용 제한

- Staging DB는 Migration 이력 기준선이 없다(PR #178 OPEN). 0004는 그 해소와 별도 승인 전까지 적용하지 않는다
- Staging 프런트엔드(`:18080`)는 PoC 상태 페이지이며 T82 화면이 배포되지 않았다(PR #183 확인)
- 검수 기능의 운영·Staging 활성화는 정책 승인 후 별도 결정. 기존 사용자·공고 데이터는 건드리지 않는다

## 14. 미해결 의존성

1. PM 결정 §9의 필수 5건 (1·2·4·11·12)
2. T04·T05·T06 수정안 반영 PR (이 문서 §2.2·§3·§5 그대로)
3. T83·T84 감사 확장 (사유·결과 칸) — 이번엔 `moderation_case_events`로 대체
4. PR #178 Staging 기준선 → Staging 적용 전제
5. T82 소규모 변경 (§6)
