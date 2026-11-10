# T84 — 감사 기록·AI 사용량 조회 API 구현 검증

> 판정: **PARTIAL** — 확정 계약 범위의 두 API를 실제 구현했고 일회용 PostgreSQL 18에서 통합 검증했습니다.
> PM 미승인 결정(D1~D5)은 코드·테스트로만 준비했고 운영 API에서는 켜지 않았습니다.
> 최종 갱신 2026-11-10 (STEP 05 계약·API 정합성 보완) · 기준 main `9320707`
> 계약 PR #185(OPEN, 미승인) · 구현 PR #186(Draft) · Staging 기준선 PR #178(OPEN)

## 1. 변경 이유 (STEP 05)

첫 구현(`db52a46`) 뒤 검토에서 다음을 보완했습니다. 기존 API 코드는 바꾸지 않았고, 테스트와 문서만 추가했습니다.

| 항목 | 이전 | 보완 |
|---|---|---|
| Cursor 보장 범위 | "중복·누락 없음"이라고만 씀 | 고정 데이터(조건 A)와 동시 변경(조건 B-1~B-5)을 나누고, 스냅샷 격리가 없음을 명시하고 PG로 재현 |
| Cursor 테스트 | limit 100, 같은 시각 | limit 1·20·100, 마이크로초 간격, 다른 API cursor, 다른 키 서명, 크기 제한 |
| 비용 | 저장 합 + 미확인 헤더 | 확정 응답과 미래 제안 응답 구분(#185 §10.7), Decimal 정확도 테스트 |
| OpenAPI 차이 | 보고서에만 기록 | 차이 2건을 테스트로 고정(`test_known_contract_deviations_are_exactly_two`), 제안 계약에 헤더 추가(#185) |
| 개인정보 | 응답 키 검사 | 만료 토큰, 응답 내 토큰·쿠키·이메일·IP 없음, 서버 로그·SQL 오류 로그에 필터 사용자 ID 없음 |
| 데이터 보호 | 행 수 비교 | 두 표 전체 md5 지문이 요청 전후 같음 |
| 발견 | — | 운영 접근 로그(uvicorn·Nginx)가 쿼리 문자열의 `actor_user_id`를 남길 수 있음 (§8) |

## 2. 계약 보완 내역 (PR #185, 문서만)

| 커밋 | 내용 |
|---|---|
| `dd971c2` | D2 과거 0원 해석 제한(무료로 단정 금지·일괄 NULL 금지·Migration 별도 승인·경계 시각). D4 처리 순서 6단계와 자기 조회 제외 |
| `6496b5b` | Cursor 보장 범위 표(A·B-1~B-5, 스냅샷 격리 없음, 완화책). 확정·미래 비용 응답 구분. 제안 OpenAPI에 `X-AI-Cost-Status` 헤더. D 결정과 무관한 최소 T06 변경(400·헤더)을 분리. 상태 문구를 PR #186과 맞춤. 계약 테스트 22건 |

## 3. D1~D5 승인 상태

PR #185·#186의 리뷰·승인 0건이고 저장소에 승인 기록이 없습니다 → 모두 **NOT_APPROVED**.

| ID | 권고안 | 상태 | 이 PR의 처리 |
|---|---|---|---|
| D1 | 사용량에 `admin.audit.read` | NOT_APPROVED | `PROPOSED_POLICY.usage_requires_audit_read` — 테스트만 |
| D2 | 비용 NULL 허용 Migration | NOT_APPROVED | Migration 없음. `usage_report_proposed()` — 서비스 테스트만 |
| D3 | 앞 8·끝 4자리 마스킹 | NOT_APPROVED | `mask_uuid()`·`AuditEventView` — 직렬화 테스트만 |
| D4 | 첫 페이지 1건 기록, 실패 시 503 | NOT_APPROVED | `record_reads` — 단위·PG 테스트만 |
| D5 | 최대 90일 | NOT_APPROVED | `max_range_days=90` — 테스트만 |

```text
CONFIRMED_POLICY → 운영 API (get_admin_query_policy 가 항상 반환, 환경변수로 변경 불가 — 테스트로 고정)
PROPOSED_POLICY  → 격리 테스트 전용 (dependency override)
```

## 4. 확정 API와 Proposed API 구분

| 구분 | 감사 목록 | AI 사용량 |
|---|---|---|
| 확정 (운영) | `AuditEventPage`, 원래 UUID, 필터 4종, 200·401·403·422 + **400** | `AiUsageBucket[]`, 저장 비용 합, 200·401·403·422 + **헤더** |
| Proposed (미연결) | `AuditEventViewPage`(마스킹), `resource_type`·`request_id` 필터, 429·503 | `AiUsageReport`(NULL 비용, `unpriced_request_count`, `currency: USD`), 429 |

확정 OpenAPI와 다른 점 2건 (T06 반영 후보, 테스트로 고정):
1. `listAuditEvents`의 잘못된 cursor → 400 `INVALID_CURSOR`. Cursor 파라미터 설명("변조 시 400")에는 있지만 응답 목록에는 없습니다.
2. `getAiUsage` 200에 `X-AI-Cost-Status: unverified` 헤더.

그 밖에 operationId, 파라미터 이름·필수 여부, 응답 스키마는 FastAPI 생성 OpenAPI와 확정 계약이 같습니다(테스트).

## 5. Cursor 페이지네이션 검증

정렬 `ORDER BY occurred_at DESC, audit_event_id DESC`, 서명 cursor(`ListCursor`, kind `admin-audit-events`, 위치 + 첫 페이지 `as_of`).

| # | 항목 | 단위 | PG |
|---|---|---|---|
| 1 | 같은 시각 250건 순회 | PASS | PASS |
| 2 | limit 1 / 20 / 100 | PASS (40·250·250건) | PASS (1·20, 마이크로초 간격 30건) |
| 3·4 | 페이지 사이 중복·누락 0 | PASS | PASS |
| 5 | 서명 변조 4종, 다른 키 서명 | PASS (400) | PASS (400) |
| 6 | 필터·기간 변경 후 재사용 | PASS (400) | PASS (400) |
| 7 | 다른 API(`bookmarks`) cursor | PASS (400) | — |
| 8 | 501자 cursor | PASS (422) | — |
| 9 | 마이크로초 정밀도 | PASS | PASS |
| 10 | 첫 페이지 상한 고정 | PASS | PASS |
| 11 | 순회 중 새 INSERT (`as_of` 이후 시각) | PASS — 나타나지 않음 | PASS |
| 12 | 늦게 커밋된 과거 시각 행 | — | 한계 재현 (§6) |
| 13 | 순회 중 삭제·수정 | — | 한계 재현 (§6) |

**조건 A (고정 데이터)**: 중복 0, 누락 0 — 위 1~4, 9에서 PASS.

## 6. 동시 변경과 늦은 커밋의 한계 (조건 B)

페이지마다 별도 요청·별도 트랜잭션이므로 순회 전체의 **스냅샷 격리는 없습니다.** 아래는 실제 PostgreSQL에서 재현한 동작이며, 테스트는 "한계가 문서대로 나타나는지"를 확인합니다(기능 PASS가 아님).

| 경우 | 실제 동작 | 테스트 |
|---|---|---|
| B-1 `occurred_at >= as_of` 새 행 | 순회에 안 나타남 | `test_pg_rows_newer_than_the_first_page_never_join_the_walk` |
| B-2 늦은 커밋, 과거 시각, 지난 구간 | 그 순회에서 **누락**, 새 조회에서 보임 | `test_pg_condition_b2_…` |
| B-3 늦은 커밋, 남은 구간 | 다음 페이지에 **나타남** | `test_pg_condition_b3_…` |
| B-4 순회 중 삭제 | 남은 구간에서 사라짐, 중복 없음 | `test_pg_condition_b4_…` |
| B-5 순회 중 `occurred_at` 수정(소유자) | **중복** 가능. 앱 계정에는 UPDATE·DELETE·TRUNCATE 권한 없음 | `test_pg_condition_b5_…` |

Migration 없는 완화책 (#185 §9):
1. 화면 안내와 "새로 조회" 버튼
2. 정밀 조사용 조회는 `to`를 충분히 이전으로 지정
3. 서버 상한 `min(to, as_of − 지연 여유)` — PROPOSED, 값 미정

완전한 해결은 T83 `recorded_at`·`audit_seq` Migration과 수정 금지 트리거 이후입니다.

## 7. 비용 미기록 처리

- 0001: `estimated_cost_usd numeric(18,6) NOT NULL DEFAULT 0` → "미기록"과 "0원"을 구분할 수 없습니다. Migration은 하지 않았습니다.
- 확정 응답:
  - 저장된 추정값의 합을 그대로 돌려주고, `X-AI-Cost-Status: unverified`를 붙입니다(빈 결과에도).
  - SQL `sum(numeric)` 후 Decimal로 소수 6자리 반올림합니다. `0.1 + 0.2 + 0.000001` = `0.300001`(단위·PG).
  - NULL 비용 행이 있으면 0으로 바꾸지 않고 500으로 실패합니다.
  - 통화 USD는 필드 이름으로만 표시합니다(확정 스키마에 통화 필드 없음).
- Proposed: 경계 시각 이전 행과 NULL 행은 `unpriced_request_count`로 셉니다. 비용은 기록된 값만 합하고, 없으면 `null`입니다(일회용 DB에서만 `ALTER`로 D2-A를 흉내 내어 검증).
- 일·기능·모델 합계 일치와 탈퇴 사용자(NULL `user_id`) 포함은 PASS입니다. 사용자 ID는 응답에 없습니다.
- 현재 `ai_usage_records`를 쓰는 코드가 없습니다(T60 미착수). 실제 결과는 빈 배열입니다.

## 8. 개인정보 노출 검증

| 항목 | 결과 |
|---|---|
| 응답 키 = 확정 7개, 사용자 표와 JOIN 없음 | PASS |
| 비밀번호·Access Token·Refresh Token(쿠키 포함)·이메일·이름·IP 형식 문자열 미노출 | PASS (단위) |
| 개인 문서 원문 | 해당 컬럼 없음 (0001 `audit_events`·`ai_usage_records`) |
| SQL 오류 응답·서버 로그에 필터 사용자 ID 없음 (`hide_parameters=True`) | PASS (PG) |
| 서버 애플리케이션 로그(`app.*`, 200·400·503 경로)에 필터 사용자 ID 없음 | PASS (단위) |
| 만료 토큰 401 `TOKEN_EXPIRED` (두 API) | PASS |
| D3 마스킹 | Proposed 직렬화 테스트만 |

**발견 (배포 설정, 이번 범위 밖)**: 운영 이미지는 `uvicorn`을 기본 설정으로 실행합니다(`poc/staging/backend/Dockerfile*`). 기본 접근 로그는 요청 줄 전체를 남기므로, 쿼리 문자열의 `actor_user_id`도 그대로 기록됩니다. Nginx 접근 로그도 같습니다. 테스트 클라이언트 로그(`httpx`)에서 같은 현상을 확인했습니다. 선택지(승인 필요):
- (a) 접근 로그에서 쿼리 문자열을 지우는 로그 필터
- (b) `--no-access-log` + 앱 자체 요청 로그
- (c) 필터를 POST 본문으로 옮기는 계약 변경

운영 설정은 바꾸지 않았습니다.

## 9. 일회용 PostgreSQL 테스트

- 환경: 로컬 PostgreSQL 18 일회용 클러스터(스크래치 디렉터리, 127.0.0.1 전용 포트, DB `t16_profile_test`). 테스트 후 삭제했습니다.
- 데이터: 0001 Migration + 0001 Seed를 그대로 쓰고, 합성 사용자 2명(`@example.invalid`), 합성 감사·사용량 행만 넣었습니다.
- 런타임 역할(SUPERUSER 아님): 인증 7개 표(`users`, `user_profiles`, `auth_sessions`, `user_roles`, `roles`, `role_permissions`, `permissions`) SELECT, `audit_events` SELECT·INSERT, `ai_usage_records` SELECT. `user_profiles`는 인증 경로의 User ORM JOIN 때문에 필요합니다.
- 고정 장치(DDL·합성 행·조건 B 재현용 동시 쓰기)는 T16 패턴의 테스트 관리 연결이 맡습니다. 이 연결은 CI 서비스 컨테이너의 사용자이고, 앱 경로에서는 쓰지 않습니다.
- 결과: `tests/test_t84_admin_audit_postgres.py` **23 passed**.
- 신규 9건: 마이크로초 순회 ×2, B-2·B-3·B-4·B-5, 기존 데이터 지문 불변, SQL 오류 로그 파라미터 숨김, 비용 Decimal 합.

## 10. 기존 회귀 테스트 (로컬, Windows)

| 범위 | 결과 |
|---|---|
| `tests/test_t84_admin_audit.py` | **68 passed** (기존 57 + 신규 11) |
| `tests/test_t84_admin_audit_postgres.py` | **23 passed** (기존 14 + 신규 9) |
| 전체 Backend (일회용 PG, CI와 같은 환경변수) | 794 passed, 53 skipped, **1 failed + 19 errors** |
| 위 실패·오류 | 모두 `tests/test_documents.py` — `DOCUMENT_STORAGE_ROOT must have mode 0700`(POSIX 권한 검사, Windows에서 성립 안 함). T84와 무관하며 PASS로 처리하지 않음. Linux CI 결과로 판정(§11) |
| T83 감사 계약 35항목 (같은 클러스터, 공유 본문) | 35/35 PASS |
| T84 계약 문서 테스트 (PR #185) | 22 OK |
| `docs/api/check_openapi.py` | PASS (확정 계약 변경 없음) |
| Frontend 생성 타입 `check:api` | NOT_RUN — 확정 `openapi.yaml`을 바꾸지 않아 대상 아님 |

## 11. CI 결과

PR 본문의 최신 HEAD 결과를 따릅니다. 로컬 결과로 CI를 대신하지 않습니다. `backend-tests.yml`(postgres:18.1)은 같은 T16 가드로 T84 PG 테스트를 실행합니다.

## 12. Staging 미변경

Staging DB 연결·스키마·데이터 변경, Migration 작성·실행, 실제 감사 행 수정·삭제·purge, 실제 AI 사용량·비용 기록, 운영·배포 설정 변경 — 모두 없습니다.

## 13. 남은 차단 요인

1. PM 결정 D1~D5 (PR #185)
2. T06: 최소 변경(400 BadCursor, `X-AI-Cost-Status`)과 D 결정에 따른 스키마를 `openapi.yaml`에 반영 → `gen:api`
3. 접근 로그의 쿼리 문자열(§8 발견) 처리 방식 결정
4. T60 사용량 기록 코드
5. T83 `recorded_at`·`audit_seq`·수정 금지 트리거 Migration (조건 B 한계 해소), 조회 전용 DB 계정
6. Staging 기준선 PR #178, Staging 적용 승인
7. 독립 리뷰(Crasnec)
