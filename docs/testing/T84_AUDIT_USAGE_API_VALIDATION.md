# T84 — 감사 기록·AI 사용량 조회 API 구현 검증

> 판정: **PARTIAL** — 확정 계약 범위의 두 API를 실제 구현했고 일회용 PostgreSQL 18에서 통합 검증했습니다.
> PM 미승인 결정(D1~D5)은 코드·테스트로만 준비했고 운영 API에서는 켜지 않았습니다.
> 확인일 2026-11-10 · 기준 main `9320707` · 계약 준비 PR #185(OPEN, 미승인) · Staging 기준선 PR #178(OPEN)

## 1. 실제 구현 범위

| API | 상태 | 권한 |
|---|---|---|
| `GET /api/v1/admin/audit-events` (`listAuditEvents`) | 구현 — 확정 계약 그대로 | `admin` 역할 + Seed 권한 `admin.audit.read` |
| `GET /api/v1/admin/ai-usage` (`getAiUsage`) | 구현 — 확정 계약 그대로 + 비용 미확인 헤더 | `admin` 역할 (확정 계약 "관리자") |

두 API 모두 읽기 전용입니다. 운영 경로에서 쓰는 DB 작업은 SELECT뿐입니다.

## 2. 기존 계약 사용 범위

- 경로·`operationId`·파라미터(`from`·`to`·`actor_user_id`·`action_code`·`limit`·`cursor` / `from`·`to`·`group_by`)·응답 스키마(`AuditEventPage`, `AiUsageBucket[]`)는 `docs/api/openapi.yaml` 그대로입니다. FastAPI 생성 OpenAPI와 확정 계약의 일치를 테스트로 확인합니다.
- 공통 규칙 재사용: `Limit` 1~100, 서명 cursor(`ListCursor`, `JWT_SECRET` 파생 키), 오류 카탈로그, `X-Request-ID`, T15 `require_roles`·`require_permissions`, `get_db`의 DB 장애 503 변환.
- 0001 실제 컬럼만 SELECT합니다(`audit_events` 7개, `ai_usage_records` 중 `occurred_at`·`feature_code`·`provider_model`·토큰·비용). T83 제안 컬럼은 쓰지 않습니다.
- 확정 계약에서 벗어난 점 2가지 (T06 반영 필요):
  1. `listAuditEvents`의 잘못된 cursor는 400 `INVALID_CURSOR`. 확정 계약은 Cursor 파라미터 설명("변조 시 400")에만 있고 응답 목록에는 400이 없습니다.
  2. `getAiUsage` 응답 헤더 `X-AI-Cost-Status: unverified` 추가. D2 미승인 상태에서 비용 0을 "무료"로 단정하지 않도록 하는 표시입니다.

## 3. 미승인 계약 의존성 (PROPOSED — 운영 비활성)

`AdminQueryPolicy`가 정책을 한 곳에 모읍니다. 운영 라우터의 `get_admin_query_policy()`는 항상 `CONFIRMED_POLICY`(모든 제안 규칙 꺼짐)를 반환합니다. 환경변수로 바꿀 수 없고, 테스트(`test_operating_route_uses_only_the_confirmed_policy`)가 이를 고정합니다. 제안 동작은 테스트에서만 의존성 override로 켭니다.

| ID | 결정 | 승인 기록 | 구현 상태 |
|---|---|---|---|
| D1 | AI 사용량에 `admin.audit.read` 요구 | 없음 | `usage_requires_audit_read` — 테스트만 |
| D2 | 비용 NULL 허용 Migration | 없음 | Migration 없음. `usage_report_proposed()`(경계 시각 규칙) — 서비스 테스트만, HTTP 미연결 |
| D3 | 사용자 ID 마스킹 | 없음 | `mask_uuid()`·`to_view()`·`AuditEventView` — 직렬화 테스트만, HTTP 미연결 |
| D4 | 첫 페이지 감사 조회 기록, 실패 시 503 | 없음 | `record_reads` — 단위·PG 테스트만 |
| D5 | 최대 90일 | 없음 | `max_range_days=90` — 테스트만 |
| (제안) | 60회/분, `statement_timeout` 5초, 사용량 bucket 200개 | 기존 계약 없음 | 테스트만 |

승인 확인: PR #185 리뷰·댓글 0건, 저장소에 D1~D5 승인 기록 없음 → 모두 **미승인**으로 다룹니다.

## 4. 변경 파일

| 파일 | 내용 |
|---|---|
| `backend/app/routers/admin_audit.py` | 신규: 두 라우트, 정책 의존성 |
| `backend/app/services/admin_audit.py` | 신규: 검증·cursor·처리 순서·마스킹·집계·정책 |
| `backend/app/repositories/admin_audit.py` | 신규: 바인딩 파라미터 SQL, 고정 묶음 식 |
| `backend/app/schemas/admin_audit.py` | 신규: 확정 응답 모델 + PROPOSED 모델(미연결) |
| `backend/app/routers/api_v1.py` | 라우터 등록 1줄 |
| `backend/tests/fakes_admin_audit.py` | 신규: 메모리 저장소 |
| `backend/tests/test_t84_admin_audit.py` | 신규: 단위·HTTP 57건 |
| `backend/tests/test_t84_admin_audit_postgres.py` | 신규: 실제 PostgreSQL 14건 |
| `docs/testing/T84_AUDIT_USAGE_API_VALIDATION.md` | 이 문서 |

`docs/api/openapi.yaml`, 데이터 사전, Migration, Seed, Frontend, CI 설정은 바꾸지 않았습니다.

## 5. 감사 조회 API

처리 순서 (readiness §11, 한 트랜잭션):

1. 권한: 라우터 의존성. 401은 입력 검증보다 먼저 나옵니다.
2. 검증 → 422: `from`·`to` 누락, UTC 오프셋 없음(RFC 3339), `from >= to`, `limit` 범위 밖, 형식 오류.
3. 범위 확정: 첫 페이지에서 `as_of = now()`를 읽고 상한을 `min(to, as_of)`로 고정해 cursor에 서명합니다.
4. ~5. (PROPOSED D4) `admin.audit.view` INSERT. 실패하면 503이고 결과를 반환하지 않습니다.
6. SELECT (`ORDER BY occurred_at DESC, audit_event_id DESC LIMIT n+1`, 자기 조회 행 제외) → 응답.

- SQL은 모두 바인딩 파라미터입니다. 문자열로 붙이는 것은 고정 컬럼 목록과 `group_by` 표의 식뿐입니다.
- DB 장애(`OperationalError`, statement timeout 포함)는 503 `DEPENDENCY_UNAVAILABLE`입니다. 권한 누락 같은 설정 오류는 500 `INTERNAL_ERROR`이며 응답에 내부 정보를 담지 않습니다.
- 로그(`log_detail`)에 필터 값·사용자 ID를 남기지 않습니다.

## 6. AI 사용량 API

- 기간: `from`·`to` 날짜, 양쪽 포함, KST(UTC+9 고정, 일광절약시간 없음) → `[from 00:00 KST, to+1 00:00 KST)`. `from > to`는 422.
- 묶음: `day`(KST 날짜) / `feature_code` / `provider_model`. 사용자별 분해는 없고, `user_id` NULL(탈퇴) 행도 합계에 들어갑니다.
- 빈 데이터: `[]`. 0으로 채운 날을 만들지 않습니다.
- 토큰·요청 수: 실제 DB `count(*)`·`sum`.

## 7. 사용자 ID 마스킹

- 현재 HTTP 응답: 확정 계약대로 `actor_user_id`·`resource_id` 원래 UUID. **D3 미승인이라 응답 모델을 바꾸지 않았습니다.**
- 비노출 보장(HTTP 테스트): 응답 키는 확정 7개뿐이고, 이메일·이름·토큰·IP·문서 원문이 없습니다. 0001 `audit_events`에 그런 컬럼이 없고, 사용자 표와 JOIN하지 않습니다.
- PROPOSED 마스킹(직렬화 테스트): 앞 8자리와 끝 4자리만 남기며 36자 모양을 유지합니다. `resource_type = user`이면 `resource_id`도 마스킹합니다. 마스킹 값을 다시 원문 필드에 넣으면 거부합니다. **마스킹 값은 익명정보가 아닙니다**(코드 주석에도 표시).

## 8. Cursor 및 기간 처리

- `ListCursor` 재사용(kind `admin-audit-events`). 검색 조건(정규화한 UTC `from`·`to`, 필터)에 묶이고 `limit`에는 묶이지 않습니다.
- 위치 `(occurred_at, audit_event_id)`. `occurred_at`은 마이크로초까지 쓰고, 상한 `as_of`를 함께 서명합니다.
- 같은 시각 250건을 100건씩 순회하면 250건, 중복 0, 누락 0입니다. 순서는 PostgreSQL uuid 바이트 순서와 일치합니다(PG 테스트).
- 순회 중 새로 생긴 행(`as_of` 이후)은 그 순회에 끼어들지 않습니다(단위·PG 테스트).
- **알려진 한계**: 다른 트랜잭션이 *과거 시각*(`occurred_at` = 그 트랜잭션 시작 시각)으로 늦게 커밋한 행은 진행 중인 순회에서 빠질 수 있습니다. 새로 조회하면 보입니다. T83 `recorded_at`·`audit_seq` Migration 후 해결합니다.
- 기간 상한: 확정 계약에 없음 → 운영은 제한 없음(`limit` ≤ 100으로 페이지당 비용 제한). 90일은 PROPOSED D5.

## 9. 비용 NULL 문제

- 0001: `estimated_cost_usd numeric(18,6) NOT NULL DEFAULT 0` → "미기록"과 "0원"을 구분할 수 없습니다. Migration은 하지 않았습니다.
- 확정 응답(`AiUsageBucket.estimated_cost_usd` number 필수):
  - 저장된 추정값의 합을 그대로 돌려줍니다(새 값을 만들지 않음).
  - 응답 헤더 `X-AI-Cost-Status: unverified`로 미확인임을 표시합니다.
  - NULL 비용 행이 생기면(D2 이후) 0으로 바꾸지 않고 500으로 실패합니다. 계약 교체가 필요하다는 신호입니다.
- PROPOSED 응답(`AiUsageReport`):
  - 경계 시각 이전 행과 NULL 행은 `unpriced_request_count`로 세고 비용 합에서 뺍니다.
  - 경계 시각이 없으면(D2 전) 비용은 전부 `null`입니다.
  - PG 테스트는 일회용 DB에서만 `ALTER ... DROP NOT NULL`로 D2-A를 흉내 내어 0원과 NULL을 구분하는지 확인합니다(실제 Migration 아님).
- 현재 `ai_usage_records`를 쓰는 코드가 없습니다(T60 미착수). 실제 사용량이 없으면 빈 결과입니다. 운영·Staging에 사용량 행을 만들지 않았습니다.

## 10. 단위 테스트 (`tests/test_t84_admin_audit.py`, 메모리 저장소 + 실제 T15 인증 흐름)

| 지시서 번호 | 테스트 | 결과 |
|---|---|---|
| 1 | 관리자 정상 조회, 확정 스키마 검증, 쓰기 0 | PASS |
| 2 | 비로그인 401 (검증보다 먼저) | PASS |
| 3 | 일반 사용자 403 (두 API) | PASS |
| 4 | 권한 없는 admin 403, 역할 회수 다음 요청 403 | PASS |
| 5 | 잘못된 기간·필터 9종 422, 긴 기간 확정 200 / 제안 422 | PASS (D5는 PROPOSED) |
| 6 | 같은 시각 251건 3페이지 무중복·무누락, 순회 중 새 행 미개입 | PASS |
| 7 | cursor 변조 4종 400, 다른 조건 재사용 400 | PASS |
| 8 | 필터 조합 | PASS |
| 9 | 응답 키 7개·개인정보 없음, 마스킹 직렬화 | PASS (마스킹은 PROPOSED) |
| 10 | 빈 데이터 | PASS |
| 11 | DB 오류 503, 내부 정보 미노출 | PASS |
| 12 | 반열림 범위·`as_of` 상한 | PASS |
| D4 | 첫 페이지 1건 기록·자기 행 제외·다음 페이지 0건·조건 값 미저장·실패 3종 fail-closed·확정 정책에서 꺼짐 | PASS (PROPOSED) |
| 제한 | 61번째 429 + `Retry-After`, timeout 설정 / 확정 정책은 새 제한 없음 | PASS (PROPOSED) |
| 13 | 빈 사용량 `[]` + 미확인 헤더 | PASS |
| 14~16 | 일·기능·모델 집계 | PASS |
| 17~18 | 입력·출력 토큰 합 | PASS |
| 19 | 확정: 저장 합 + 미확인 헤더 / 제안: D2 전 비용 전부 null | PASS |
| 20 | 0원·NULL·경계 이전 0원 구분 / 확정 계약은 NULL을 0으로 바꾸지 않음 | PASS (D2는 PROPOSED) |
| 21 | KST 자정 경계(UTC 14:59:59.999999 / 15:00), `to` 포함 | PASS |
| 22 | 기간 오류 422, 90일 제안 | PASS |
| 23 | 사용량 권한: 확정 admin 역할 / 제안 D1 403 | PASS |
| 24 | 세 묶음 합계 일치 | PASS |
| 계약 | FastAPI 생성 operation ↔ 확정 OpenAPI 파라미터·응답·operationId, `/admin/audit` 별칭 없음 | PASS |

명령: `cd backend; APP_ENV=test python -m pytest -q tests/test_t84_admin_audit.py` → **57 passed**

## 11. PostgreSQL 통합 테스트 (`tests/test_t84_admin_audit_postgres.py`)

환경: 로컬 일회용 PostgreSQL 18 클러스터(스크래치 디렉터리, 127.0.0.1 전용 포트, trust 인증, DB `t16_profile_test`). 테스트 후 클러스터를 삭제했습니다. 0001 Migration과 0001 Seed를 그대로 적용하고, 합성 사용자 2명(`@example.invalid`)·합성 감사 행·합성 사용량 행만 넣었습니다.

최소 권한 런타임 역할: 인증 7개 표 SELECT, `audit_events` SELECT·INSERT, `ai_usage_records` SELECT. UPDATE·DELETE·SUPERUSER가 없음을 확인합니다.
- 발견: 인증 경로가 `user_profiles`도 읽습니다(User ORM LEFT JOIN). 최소 권한 시험에서 드러났습니다.

| 테스트 | 결과 |
|---|---|
| 최소 권한 역할 확인 (`current_user`, 권한 목록) | PASS |
| FastAPI → PG 실제 SELECT, 확정 스키마, 개인정보 없음, 쓰기 0 | PASS |
| 401 / 일반 사용자 403 / 권한 삭제 403 (사용량은 확정상 200) / 역할 회수 403 | PASS |
| 같은 시각 250건 순회 + 필터 조합 | PASS |
| cursor 변조·조건 변경 400, 422 | PASS |
| 첫 페이지 이후 새 행 미개입 | PASS |
| (PROPOSED D4) 기록 커밋·자기 행 제외·1회만·조건 값 미저장 | PASS |
| (PROPOSED D4) INSERT 권한 회수 시 확정 200 / 제안 503·행 증가 0 | PASS |
| (PROPOSED) `statement_timeout` + 테이블 잠금 → 503 | PASS |
| SELECT 권한 회수 → 500, 내부 정보 미노출 | PASS |
| 사용량 빈 결과 + 헤더 | PASS |
| 사용량 SQL 집계, KST 경계, 탈퇴 사용자 포함, 사용자 ID 미노출, 422 | PASS |
| (PROPOSED D2, 일회용 DB에서만 ALTER) 0원·NULL·경계 이전 구분, 확정 응답 NULL → 500 | PASS |
| `ai_usage_records` 쓰기 권한 없음 | PASS |

명령:

```bash
T16_ISOLATED_DB_TEST=YES T16_TEST_ADMIN_URL=postgresql://USER@127.0.0.1:PORT/t16_profile_test \
  APP_ENV=test python -m pytest -q tests/test_t84_admin_audit_postgres.py
```

결과: **14 passed**. CI `backend-tests.yml`(postgres:18.1 서비스, 같은 T16 가드)에서도 실행됩니다.

## 12. CI 결과

PR 본문과 GitHub Checks를 따릅니다. 로컬 결과를 CI 결과로 대신하지 않습니다.

## 13. Backend 회귀 (로컬, Windows)

| 범위 | 결과 |
|---|---|
| 전체 `python -m pytest -q` (일회용 PG 18, CI와 같은 환경변수) | 772 passed, 53 skipped, **1 failed + 19 errors** |
| 실패·오류 원인 | 모두 `tests/test_documents.py`: `DOCUMENT_STORAGE_ROOT must have mode 0700` — POSIX 디렉터리 권한 검사가 Windows에서 성립하지 않음. T84 변경과 무관하며 Linux CI에서 판정 |
| T83 감사 계약 35항목 (`test_audit_contract.sh` 공유 본문, 같은 일회용 클러스터) | 35/35 PASS |
| `docs/api/check_openapi.py` | PASS (계약 변경 없음) |
| T84 계약 문서 테스트 (PR #185 브랜치) | 19 OK |
| 생성 타입 `check:api` | NOT_RUN — `openapi.yaml`·`schema.gen.ts`를 바꾸지 않음 |

## 14. Staging 미변경

Staging DB 연결·스키마·데이터 변경 없음. Migration 작성·실행 없음. 실제 감사 행 수정·삭제·purge 없음. 실제 AI 사용량·비용 기록·수정 없음. 운영 자동배포 설정 변경 없음.
배포 후에도 운영 경로는 읽기 전용이며 확정 정책만 사용합니다. Staging DB 기준선(PR #178)이 미해결이라, Staging 확인은 별도 승인 후 읽기로만 합니다.

## 15. 남은 차단 요인

1. PM 결정 D1~D5 (PR #185) — 특히 D2(비용 NULL 허용 Migration)와 D3(마스킹)
2. T06: 승인된 제안을 `openapi.yaml`에 반영 (400 BadCursor, 비용 헤더 또는 `AiUsageReport`, 마스킹 스키마) → `gen:api`
3. T60: `ai_usage_records` 기록 코드 — 그 전에는 실제 사용량이 없음
4. T83: `recorded_at`·`audit_seq` Migration (지연 커밋 한계 해소), 조회 전용 DB 계정 분리
5. Staging 기준선 PR #178, Staging 적용 승인
6. 독립 리뷰(Crasnec)
