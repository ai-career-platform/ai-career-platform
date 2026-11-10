# T84 — 감사 기록·AI 사용량 조회 API 계약 준비

> 상태: **PROPOSED / 미승인** — 계약 준비 문서입니다. 실제 API·DB·Migration 변경은 없습니다.
> T84 실제 API 구현 착수는 **HOLD** — 비용 컬럼 결정(D2), 마스킹·감사 조회 기록 방침(D3·D4), 기간 한도(D5) 승인이 필요합니다.
> 확인일 2026-11-10 · 기준 main `9320707` · 방식: T81 PR #184와 같음 (제안 조각 + 실제 계약에 메모리 병합 검증)
> 근거: [작업지시서 T84](../work-orders/remaining-30/T84.md), [T83 감사 계약](AUDIT_EVENT_CONTRACT.md) (DRAFT), [OpenAPI](../api/openapi.yaml) `listAuditEvents`·`getAiUsage`, [데이터 사전](../../database/DATA_DICTIONARY.md) F11·F12, `database/migrations/0001_initial_schema.sql`, [ADMIN 요구사항](../requirements/functional/ADMIN.md) FR-ADM-004·005

표기: **FACT** = 저장소·GitHub에서 확인한 사실 · **PROPOSED** = 이 문서의 제안(미승인) · **OPEN** = 결정 필요

## 0. 판정 요약

```text
T15_AUTH=FACT_DONE (PR #48 merged; require_roles / require_permissions 사용 가능)
T60_AI_USAGE_OPS=NOT_STARTED (작업지시서 상태 NOT_STARTED, ai_usage_records 기록 코드 없음)
T83_AUDIT_CONTRACT=DRAFT (PR #35 merged, "DRAFT / NOT APPROVED / NOT MIGRATED"; 후속 PR #129 OPEN)
OPENAPI_PATHS=EXIST (/admin/audit-events, /admin/ai-usage — T06 확정 계약)
DB_TABLES=EXIST_IN_0001 (audit_events 7컬럼, ai_usage_records 10컬럼)
CONTRACT_PROPOSAL=READY (이 문서 + t84_openapi_proposal.yaml)
T84_IMPLEMENTATION=HOLD
```

## 1. 선행조건 (FACT/PROPOSED/OPEN)

| 항목 | 상태 | 근거 |
|---|---|---|
| T15 인증·인가 | **FACT** 완료 — Bearer 인증, 매 요청 DB에서 역할·권한 재조회, `require_roles`·`require_permissions`(403), CI pytest 게이트 | PR #48, #121, `backend/app/dependencies/auth.py` |
| T60 AI 사용량 운영 API | **FACT** 미착수 — 작업지시서 `NOT_STARTED / REVIEW_REQUIRED`, 관련 PR 없음 | `docs/work-orders/next-30/T60.md`, `gh pr list` |
| `ai_usage_records` 기록 코드 | **FACT** 없음 — T51 문서분석 Mock은 "숫자를 만들지 않기 위해" 일부러 기록하지 않음 | `backend/app/repositories/document_analyses.py`, `backend/docs/T51_DOCUMENT_ANALYSIS.md` |
| `audit_events` 기록 코드 | **FACT** 1곳 — T73 행동 데이터 purge(`system.behavior.purge`, 같은 트랜잭션) | `backend/app/behavior_data.py` |
| T83 감사 계약 | **FACT** 문서·mock 머지(PR #35), 상태 **DRAFT / NOT APPROVED / NOT MIGRATED**. 추가 컬럼 11개는 0001에 없음 | `docs/security/AUDIT_EVENT_CONTRACT.md` |
| T83 mock 계약 테스트 | **FACT** 이번에 로컬 일회용 PostgreSQL 18에서 35/35 PASS (§16) | `database/tests/test_audit_contract.sh` 공유 본문 |
| 권한 코드 | **FACT** `admin.audit.read`·`admin.models.read`만 Seed에 있고 둘 다 `admin` 역할에 부여 | `database/seeds/0001_initial_seed.sql` |
| Staging Migration 기준선 | **FACT** 없음 — PR #178 OPEN. 0002·0003 미적용 | PR #178 |
| 화면 UI-028 | **FACT** 추적표에 있음(운영 감사: FR-ADM-002·004·005). Frontend 구현 없음 (`schema.gen.ts` 생성 타입만) | `TRACEABILITY.md`, `frontend/src` |

## 2. 경로 불일치: 작업지시서 `/api/v1/admin/audit` ↔ 확정 계약 `/api/v1/admin/audit-events`

- **FACT**: T84 작업지시서 §3은 "`/api/v1/admin/audit` API"라고 쓰고, `auth.py` 주석 예시도 `/admin/audit`입니다. 그러나 확정 계약(T06 OpenAPI·`API_CONTRACT.md` §표)은 `GET /api/v1/admin/audit-events`(`listAuditEvents`)와 `GET /api/v1/admin/ai-usage`(`getAiUsage`)입니다.
- **PROPOSED**: 확정 계약의 경로를 그대로 씁니다. `/admin/audit` 별칭은 만들지 않습니다(경로가 둘이면 권한·감사 규칙도 두 번 맞춰야 함). 작업지시서의 표현은 "감사 API 묶음"을 가리키는 약칭으로 해석합니다.
- 테스트가 제안 조각에 새 경로가 없고 `operationId`가 그대로인지 확인합니다.

## 3. DB 모델 대조 (0001 SQL)

`audit_events` (F11) — **FACT** 0001에 7컬럼

| 컬럼 | 0001 정의 | 제안 API 사용 | 비고 |
|---|---|---|---|
| audit_event_id | uuid PK | 응답 · cursor 동률 기준 | |
| actor_user_id | uuid NULL, FK users SET NULL | 필터(정확히 일치) · 응답은 **마스킹** | 탈퇴 시 NULL |
| action_code | varchar(100) | 필터 · 응답 | 인덱스 `(action_code, occurred_at DESC)` |
| resource_type | varchar(80) | 필터(신규) · 응답 | 인덱스 없음 |
| resource_id | uuid NULL | 응답 (사용자 유형이면 마스킹) | |
| request_id | varchar(64) NULL | 필터(신규) · 응답 | FR-ADM-004 수용 기준 3, 인덱스 없음 |
| occurred_at | timestamptz | 기간 · 정렬 · cursor | 인덱스 `(occurred_at DESC)` |

T83이 제안한 `audit_seq, recorded_at, actor_type, result, reason_code, client_ip_hash, changed_fields, metadata, retention_class, retain_until, row_hash`는 **0001에 없으므로 조회 SQL·필터·응답에 쓰지 않습니다.** T83 §7의 `result` 필터와 `integrity` 표시는 Migration 이후 후속입니다(테스트로 고정).

`ai_usage_records` (F12) — **FACT** 0001에 10컬럼

| 컬럼 | 0001 정의 | 제안 API 사용 |
|---|---|---|
| usage_id | uuid PK | `request_count = count(*)` |
| user_id | uuid NULL, FK users SET NULL | **사용 안 함** (사용자별 분해 없음, 탈퇴자 포함 합계) |
| model_version_id | uuid NULL, FK RESTRICT | 사용 안 함 → `x-tables`에서 `model_versions` 제외 |
| provider_model | varchar(100) | `group_by=provider_model` |
| feature_code | varchar(40), CHECK 3값 | `group_by=feature_code` |
| input_tokens / output_tokens | integer NOT NULL DEFAULT 0 | 합계 |
| estimated_cost_usd | numeric(18,6) **NOT NULL DEFAULT 0** | 합계 — **D2 차단 요인** |
| latency_ms | integer NULL | 사용 안 함 (후속 후보) |
| occurred_at | timestamptz | 기간 · `group_by=day` |

**FACT (차단 요인)**: `estimated_cost_usd`가 `NOT NULL DEFAULT 0`이라 **"비용 미기록"과 "실제 0원"을 DB에서 구분할 수 없습니다.** 지시서의 "미기록 비용을 0으로 취급하지 않음"은 현재 스키마로는 지킬 수 없습니다(§10, D2).

## 4. 감사 목록 API 계약 — `GET /api/v1/admin/audit-events` (PROPOSED)

| 항목 | 규칙 |
|---|---|
| 권한 | `admin` 역할 **그리고** `admin.audit.read` (§6) |
| 필수 | `from`(포함)·`to`(제외), 시간대 표기 필수 date-time |
| 선택 필터 | `actor_user_id`(uuid, 정확히 일치), `action_code`(정확히 일치, 점 표기 형식), `resource_type`, `request_id` — 모두 AND |
| 페이지 | 공통 `limit`(1~100, 기본 20)·`cursor`(최대 500자) |
| 정렬 | `occurred_at DESC, audit_event_id DESC` 고정 (변경 파라미터 없음) |
| 응답 | `AuditEventViewPage {items[], next_cursor}` — 항목은 0001 컬럼만, 행위자는 마스킹 |
| 빈 결과 | 200 `items: []`, `next_cursor: null` (화면은 "결과 없음") |
| 오류 | 400 `INVALID_CURSOR`, 401 `UNAUTHENTICATED` / 401 `TOKEN_EXPIRED`, 403 `FORBIDDEN`, 422 `VALIDATION_FAILED`, 429 `RATE_LIMITED`, 503 `DEPENDENCY_UNAVAILABLE` |

422 조건: `from`·`to` 누락, 시간대 없는 값, `from >= to`, 기간 90일 초과, 형식 위반(`action_code` 점 표기, `request_id` `[A-Za-z0-9._:-]{1,64}`), `limit` 범위 밖. 수정·삭제 경로는 만들지 않습니다(FR-ADM-004 수용 기준 1).

## 5. AI 사용량 집계 API 계약 — `GET /api/v1/admin/ai-usage` (PROPOSED)

| 항목 | 규칙 |
|---|---|
| 권한 | §4와 같음 |
| 기간 | `from`·`to` 날짜, **양쪽 포함**, Asia/Seoul 기준 — `occurred_at >= from 00:00 KST AND occurred_at < (to + 1일) 00:00 KST`. 최대 90일 |
| 묶음 | `group_by` = `day`(KST 날짜) / `feature_code` / `provider_model` (기존 그대로) |
| 응답 | `AiUsageReport {from, to, timezone, group_by, currency: USD, cost_is_estimate: true, buckets[], totals}` |
| bucket | `key, request_count(≥1), input_tokens, output_tokens, estimated_cost_usd(number\|null), unpriced_request_count` |
| 빈 결과 | `buckets: []`, `totals` 0·`estimated_cost_usd: null` — 기록 없는 날을 0으로 채우지 않음 |
| 사용자 | 사용자별 분해·필터 없음. `user_id` NULL(탈퇴) 행도 합계 포함 (FR-ADM-005 수용 기준 3) |
| 상한 | bucket 200개 초과면 422 `VALIDATION_FAILED` (기간을 줄이도록 안내) |
| 오류 | 401·403·422·429 (페이지 없음 → 400 없음) |

배열만 돌려주던 기존 응답을 객체로 감싸는 이유: FR-ADM-005 수용 기준 1("추정치로 표시")과 예외 처리("데이터 없음 안내"), 날짜 묶음의 시간대를 응답에 명시해야 화면이 숫자를 잘못 해석하지 않습니다.

## 6. 권한 (PROPOSED, 재사용)

- 두 API 모두 `Depends(require_roles("admin"))` + `Depends(require_permissions("admin.audit.read"))`. **신규 권한 코드·Seed 변경 없음.**
- `admin.audit.read`는 Seed에서 `admin`에만 부여되어 있어 역할 검사는 중복이지만, `API_CONTRACT.md`의 "/admin은 admin 역할 없으면 403" 규칙과 권한 회수 시 즉시 차단(T15: 매 요청 DB 재조회)을 함께 보장합니다.
- AI 사용량에 `admin.audit.read`를 쓰는 근거: 두 API가 같은 화면 UI-028(운영 감사)에 있고, 지금 Seed만으로 동작합니다. 대안(OPEN D1): `admin.models.read`(T60 영역) 또는 신규 `admin.ai_usage.read`(Seed 변경 필요).
- 저장 데이터 접근권한보다 넓히지 않음(작업지시서 §5): 응답은 0001 컬럼의 부분집합이고, 원문 사용자 ID를 돌려주지 않으며, 사용량은 사용자 단위로 내려가지 않습니다.

## 7. 마스킹 규칙 (PROPOSED, D3)

| 값 | 응답 | 규칙 |
|---|---|---|
| `actor_user_id` | `actor_user_id_masked` | 항상 마스킹: UUID 앞 8자리 + 끝 4자리, 나머지 `*` (모양·길이 36자 유지). NULL은 null |
| `resource_id` | `resource_id` + `resource_id_masked` | `resource_type`이 사용자 식별 유형(현재 `user`)이면 같은 방식으로 마스킹, 아니면 원래 UUID |
| `request_id` | 그대로 | 개인정보 아님, 오류 화면 요청 번호로 찾기에 필요 |
| 이메일·이름·IP·메타데이터 | 응답 없음 | 0001에 컬럼이 없고, T83 금지 규칙과 같음 |

- 마스킹은 서버 직렬화 단계에서 합니다. 마스킹 값은 검색 조건으로 받지 않습니다(필터는 원래 UUID만 — 사용자 관리 화면 등에서 이미 아는 관리자만 입력 가능).
- 한계: 노출되는 48비트로 사용자 목록과 대조할 수 있으므로 **익명화가 아니라 화면 노출 최소화**입니다. 원문 열람(별도 권한) 필요 여부는 OPEN D3.
- 서버 로그(`log_detail`)에도 필터 값의 사용자 ID를 남기지 않습니다.

## 8. 기간 제한·대량 조회 보호 (PROPOSED, D5)

| 보호 | 값 | 근거 |
|---|---|---|
| 최대 기간 | 90일 (두 API) | T83 §7 "최대 90일" 제안을 따름 — **PROPOSED** |
| 페이지 크기 | 최대 100 | 공통 `Limit` |
| 요청 한도 | 관리자 1명당 60회/분 → 429 `RATE_LIMITED` + `Retry-After` | 기존 `AttemptLimiter`(프로세스 메모리, 다중 인스턴스 전 교체 필요) |
| 쿼리 시간 | `SET LOCAL statement_timeout = '5s'`, 초과 시 503 `DEPENDENCY_UNAVAILABLE` | 인덱스 없는 필터(`resource_type`, `request_id`) 대비 |
| 내보내기 | 없음 (CSV·전체 다운로드 미제공) | 범위 밖 |

## 9. Cursor 규칙 (PROPOSED)

- 기존 서명 cursor `ListCursor`(`backend/app/services/job_postings.py`, HMAC-SHA256, `JWT_SECRET`에서 용도별 파생)를 재사용합니다. 새 비밀값·의존성 없음.
- kind = `admin-audit-events`, params = 정규화한 검색 조건(`from`·`to`는 UTC ISO 8601, 선택 필터는 없으면 제외). `limit`은 params에 넣지 않아 페이지 크기만 바꿔도 이어집니다.
- 위치 = `(occurred_at, audit_event_id)`. `sort_key`에 `occurred_at`을 **마이크로초까지** UTC ISO 문자열로, `last_id`에 `audit_event_id`를 넣습니다. 정밀도를 줄이면 같은 초의 행이 누락됩니다.
- SQL: `WHERE occurred_at >= :from AND occurred_at < :to [AND 필터] AND (occurred_at, audit_event_id) < (:t, :id) ORDER BY occurred_at DESC, audit_event_id DESC LIMIT :limit + 1` — `limit + 1`번째 행이 있을 때만 `next_cursor`를 만듭니다.
- 변조·다른 조건·다른 버전이면 400 `INVALID_CURSOR`.
- **기록 유실 분석**: 순회 시점에 있던 행은 동률 기준 덕분에 중복·누락이 없습니다. 다만 `occurred_at`은 트랜잭션 시작 시각(`now()`)이라, 긴 트랜잭션이 늦게 커밋하면 이미 지나간 위치에 행이 생길 수 있습니다. 같은 cursor 순회에서는 안 보이고 새 조회에서는 보입니다. T83의 `recorded_at`·`audit_seq`가 Migration되면 해결됩니다. 그 전에는 화면이 조회 시작 시각을 `to`로 고정하고 "새로 조회"를 제공합니다(OPEN D5).
- 인덱스: `(occurred_at DESC)`로 충분합니다. `(occurred_at DESC, audit_event_id DESC)` 복합 인덱스와 `request_id` 인덱스는 성능 후보이며 Migration이 필요하므로 이번에 만들지 않습니다(D6).

## 10. 비용 집계 규칙 (PROPOSED, D2)

1. 비용은 **추정치**: 응답 `cost_is_estimate: true` 고정, 화면은 "추정 비용(USD)"으로 표시합니다. 청구 금액과 대조하지 않습니다.
2. **미기록 비용은 0으로 더하지 않음**: 비용을 아는 행만 더하고, 모르는 행은 `unpriced_request_count`로 셉니다. 아는 행이 하나도 없으면 `estimated_cost_usd: null`.
3. 현재 0001은 `estimated_cost_usd numeric(18,6) NOT NULL DEFAULT 0`이라 2를 판별할 수 없습니다. 결정 필요(D2):
   - **D2-A (권장)**: T05·T09에서 `NULL` 허용·기본값 제거로 바꾸고, 기록 함수(T60)는 단가가 없으면 NULL을 저장. Migration은 별도 승인 후.
   - D2-B: 컬럼은 두고 "승인된 단가표로 계산한 경우에만 행을 쓴다"는 기록 규칙. 단가를 모르는 호출의 토큰까지 빠지므로 권장하지 않음.
   - D2가 정해지기 전에 구현해야 한다면 비용 칸은 항상 `null`, `unpriced_request_count = request_count`로 돌려줍니다(0원을 표시하지 않음).
4. 합은 SQL `sum(numeric)` 후 소수 6자리로 반올림해 JSON number로 냅니다. 금액이 커져 정밀도가 문제가 되면 문자열 표기로 바꾸는 것을 D8로 남깁니다.
5. 실제 사용량 데이터가 없으면(현재 기록 코드 없음) 빈 결과를 돌려줍니다. 시험·Staging에 임의 사용량을 만들지 않습니다.

## 11. 감사 조회 자체의 감사 (PROPOSED, D4)

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A | 기록하지 않음 (T83 §3 "GET은 원칙적으로 기록 안 함") | 단순, 소음 없음 | 내부자가 감사 기록을 훑어본 사실이 남지 않음 |
| **B (권장)** | **첫 페이지(cursor 없음) 조회 1회마다 `admin.audit.view` 1행** | T83 §7 제안 충족, 다음 페이지 넘김은 같은 조회로 봄 | 조회가 많으면 감사 행이 늘어남 → 한도(§8)로 제한 |
| C | 모든 페이지마다 1행 | 가장 자세함 | 조회할수록 목록 자체가 불어남(자기 증폭) |

안 B의 행 내용(0001 컬럼만): `actor_user_id` = 조회한 관리자, `action_code` = `admin.audit.view`, `resource_type` = `audit_events`, `resource_id` = NULL, `request_id` = 현재 요청 ID. **검색 조건 값은 저장하지 않습니다**(0001에 `metadata`가 없고, 조건에 다른 사람의 사용자 ID가 들어갈 수 있음). T83 `metadata`가 Migration되면 조건의 *이름*만 남기는 안을 검토합니다.

- 실패 처리: 감사 INSERT가 실패하면 결과를 돌려주지 않고 503 `DEPENDENCY_UNAVAILABLE`(fail-closed). T73 purge와 같은 "작업과 감사는 함께" 원칙.
- DB 계정: 데이터 사전 F11 기준 앱 계정은 `INSERT`·`SELECT`라 한 세션으로 가능합니다. T83의 조회 전용 계정 분리가 Migration되면 쓰기는 앱 계정, 읽기는 조회 계정으로 나눕니다.
- AI 사용량 조회는 기록하지 않습니다. 개인을 알 수 없는 집계이기 때문입니다(T83 §3 원칙).

## 12. 확정 계약과의 차이 (T06 반영 대상)

| 대상 | 확정(openapi.yaml) | 제안 | 근거 |
|---|---|---|---|
| audit 필터 | from·to·actor_user_id·action_code | + `resource_type`, `request_id` | FR-ADM-004 수용 기준 3, T83 §7. 0001 컬럼 |
| audit 응답 코드 | 200·401·403·422 | + `400` BadCursor, `429` TooManyRequests, `503` ServiceUnavailable | Cursor 파라미터가 이미 있는데 400이 빠져 있음, §8·§11 |
| audit 항목 | `AuditEvent` (원문 `actor_user_id`) | `AuditEventView` — `actor_user_id_masked`, `resource_id_masked` | T84 작업지시서 "사용자 ID 마스킹" |
| audit 페이지 | `AuditEventPage` | `AuditEventViewPage` (items 최대 100) | 같은 구조 |
| usage 응답 | `AiUsageBucket[]` (배열) | `AiUsageReport` 객체 + `AiUsageAmounts` 합계 | FR-ADM-005 수용 기준 1, 시간대 명시 |
| usage 비용 | number, 최소 0 | number\|null + `unpriced_request_count` | §10, D2 |
| usage 응답 코드 | 200·401·403·422 | + `429` | §8 |
| usage x-tables | ai_usage_records, model_versions | ai_usage_records | 조회에서 `model_versions`를 쓰지 않음 |
| 공통 | 없음 | `MaskedUuid` 스키마 | §7 |

- 영향: Frontend는 생성 타입(`schema.gen.ts`)만 있고 사용하는 화면·호출이 없습니다. Backend 구현도 없습니다. 반영 시 `openapi.yaml` 수정 → `npm run gen:api` → `check:api`가 필요합니다(T06).
- 바꾸지 않는 것: 경로, `operationId`, `from`·`to` 필수, `group_by` 값, `admin` 태그, 공통 `Limit`·`Cursor`.

## 13. PM·담당자 결정 필요 (OPEN)

| ID | 결정 | 권장 |
|---|---|---|
| D1 | AI 사용량 권한 코드 | `admin.audit.read` 재사용 |
| D2 | `estimated_cost_usd` NULL 허용 (T05·T09 Migration) | D2-A |
| D3 | 마스킹 범위(`user` 외 유형), 원문 열람 권한 필요 여부 | 목록 = `user`, 원문 열람 없음 |
| D4 | 감사 조회 기록 방식·실패 처리 | 안 B + fail-closed |
| D5 | 기간 한도 90일, 시간대 Asia/Seoul, 지연 커밋 처리 | 90일 / KST / 화면이 `to` 고정 |
| D6 | 복합·`request_id` 인덱스 Migration | 데이터량 확인 후 |
| D7 | `action_code` 접두어 검색 | 이번 미지원 |
| D8 | 비용 금액 표기(number ↔ 문자열) | number 유지 |
| D9 | T83 계약 승인과 추가 컬럼 Migration 시점 | T83 소관 |

## 14. 구현 계획 (승인 후, 18단계)

| 단계 | 작업 | 산출물 | 완료 기준 |
|---|---|---|---|
| 1 | D1~D5 PM 결정 기록 | 이 문서 갱신 | 결정 ID별 승인자·일자 |
| 2 | T06: 제안 조각을 `openapi.yaml`에 반영 | OpenAPI PR | `check_openapi.py` 오류 0 |
| 3 | `npm run gen:api` | `schema.gen.ts` | `check:api` CI PASS |
| 4 | (D2-A 승인 시) T05·T09 데이터 사전·Migration | 0004 이후 파일 | 일회용 DB Migration 테스트 PASS |
| 5 | 감사 조회 저장소 | `backend/app/repositories/admin_audit.py` | 0001 컬럼만 SELECT |
| 6 | AI 사용량 저장소 | `backend/app/repositories/admin_ai_usage.py` | `group_by` 3종 SQL, KST 날짜 |
| 7 | 마스킹 함수 | `backend/app/services/masking.py` | §7 형식·NULL 처리 단위 테스트 |
| 8 | 기간·필터 검증 | 서비스 계층 | §4 422 조건 전부 |
| 9 | Cursor | `ListCursor` 재사용 (kind `admin-audit-events`) | 변조·조건 변경 400 |
| 10 | 감사 조회 기록 | 같은 트랜잭션 INSERT `admin.audit.view` | 실패 시 503, 결과 미반환 |
| 11 | 라우터 | `backend/app/routers/admin_audit.py` | `require_roles` + `require_permissions` |
| 12 | 요청 한도·쿼리 시간 | `AttemptLimiter` 키 `admin-read:{user_id}`, `statement_timeout` | 429·503 |
| 13 | 단위 테스트 | `backend/tests/test_admin_audit.py` | §15 A·U 항목 |
| 14 | PostgreSQL 통합 테스트 | `backend/tests/test_admin_audit_postgres.py` (일회용 DB) | 페이지 누락·중복 0, 동률 시각 |
| 15 | OpenAPI 응답 대조 | 응답을 생성 스키마로 검증 | 추가 필드 0 |
| 16 | CI | 기존 backend pytest 게이트 | PASS |
| 17 | UI-028 연동 (별도 일감) | Frontend | 추정치·마스킹 표시 |
| 18 | Staging | Migration 기준선(#178) 해소 + 별도 승인 후 읽기 확인 | 합성 데이터 생성 없음 |

## 15. 테스트 계약 (구현 시 작성할 pytest)

감사 목록 (A):
- A01 관리자 + `admin.audit.read` → 200, 최신 순, 원문 `actor_user_id` 키 없음
- A02 토큰 없음 401 `UNAUTHENTICATED`, 만료 401 `TOKEN_EXPIRED`
- A03 일반 사용자 403, `admin` 역할이지만 권한 회수 → 다음 요청 403
- A04 `from`·`to` 누락 / 시간대 없음 / `from >= to` / 91일 → 422
- A05 같은 `occurred_at` 행 250건을 limit 100으로 순회 → 250건, 중복 0, 누락 0
- A06 cursor 1바이트 변조 / 다른 필터로 재사용 / 다른 kind cursor → 400
- A07 필터 4종 각각·조합 일치, 다른 사람 행 섞이지 않음
- A08 `resource_type = user` 행만 `resource_id` 마스킹, 탈퇴 익명화 행은 null
- A09 첫 페이지 조회마다 `admin.audit.view` 1행, 다음 페이지는 0행, 조건 값 미저장
- A10 감사 INSERT 실패 주입 → 503, 결과 미반환
- A11 61번째 요청 429 + `Retry-After`
- A12 응답·로그에 이메일·토큰·비밀번호 형식 문자열 없음
- A13 UPDATE·DELETE 경로 없음 (405/404)

AI 사용량 (U):
- U01 기록 0건 → `buckets: []`, `estimated_cost_usd: null`
- U02 KST 자정 경계(UTC 15:00 전후) 행이 올바른 날짜로 묶임, `to` 당일 포함
- U03 `group_by` 3종 합계 = 전체 합계
- U04 `user_id` NULL 행 포함
- U05 (D2-A 후) 비용 NULL 행은 합에서 제외, `unpriced_request_count` 증가, 0원 행과 구분
- U06 91일·`to < from` → 422, 권한·인증 경계는 A02·A03과 같음
- U07 조회 시 `audit_events` 행 증가 0

테스트 데이터: 일회용 DB에서만, `@example.invalid` 계정과 고정 UUID. 실제 사용량·비용 숫자는 테스트 입력값으로만 쓰고 운영·Staging에 넣지 않습니다.

## 16. 이번 PR 검증 결과

| 검증 | 결과 |
|---|---|
| `python -B -m unittest docs/security/test_t84_contract_readiness.py -v` — 제안 조각을 실제 `openapi.yaml`에 병합 후 검사기, 깨진 변형 거부, 확정 계약과의 차이, 0001 컬럼·인덱스·CHECK 대조, T83 미적용 컬럼 미사용, 마스킹 패턴, Seed 권한, 오류 코드, 구현·Migration 부재, 18단계 | PR 본문 기록 |
| T83 mock 계약 (`test_audit_contract.sh`의 공유 본문을 로컬 일회용 PostgreSQL 18.1 클러스터에서 실행, Docker 없음) | 35/35 PASS — CI의 Docker 실행과 별개 |
| `docs/api/check_openapi.py` (실제 계약, 변경 없음) | PR 본문 기록 |
| 실제 API·PostgreSQL 통합 (§15) | **NOT_RUN** — 구현 전 |

## 17. Staging 적용 제한

- Staging DB 스키마·데이터를 바꾸지 않았고 연결도 하지 않았습니다. Migration 기준선 PR #178이 해소되기 전에는 D2 Migration도 적용하지 않습니다.
- 실제 감사 행 수정·삭제, purge 실행, AI 사용량·비용 기록·수정 — 모두 하지 않았습니다.
- Staging 확인은 구현·승인 후 읽기 전용으로만 하며, 확인용 감사 행·사용량 행을 만들지 않습니다.
