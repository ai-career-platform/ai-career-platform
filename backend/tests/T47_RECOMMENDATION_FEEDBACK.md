# T47 추천 설명·피드백 API 작업 노트 (Redmine #1589)

- 상태: **PARTIAL** — 선행 T45(#156, d0d18e1)가 main에 머지되어 블로커는 해소. origin/main 병합 후 T45 실제 코드와 연결했고,
  메모리 저장소 테스트·로컬 일회용 PostgreSQL 16 E2E(T45 `POST /recommendation-runs`가 만든 실행 사용)까지 PASS.
  남은 사유: 병합된 브랜치의 **GitHub Backend CI 미실행**(push 전), Staging 검증 없음(승인 전 금지), 감사 공용 함수(T84) HOLD.
- 기능 추적: F-018 (FR-ANL-004), 화면 UI-017 · 작업 지시서 [T47](../../docs/work-orders/next-30/T47.md)
- 브랜치: `task/t47-recommendation-feedback-api` (처음 기준 `origin/main` 2cdd70c → `origin/main` d0d18e1 병합, rebase 없음)

## 1. 범위

| 포함 | 제외·HOLD |
|---|---|
| `POST /api/v1/recommendation-feedback` (operationId `createRecommendationFeedback`) | 추천 실행 생성·조회(`/recommendation-runs*`) — T45(머지됨) |
| 소유권 확인, 중복(멱등)·정정·취소 처리, 사용자별 이력 분리, 감사 기록 | Staging 검증 (승인 전 금지) |
| 최신 피드백 조회·현재 값 규칙을 T45 저장소가 그대로 쓰도록 연결 (`RecommendationItem.feedback`, `not_interested` 제외) | 화면(UI-017) 피드백 버튼 — Frontend 일감(T48) |
| 메모리 저장소(`tests/fakes.py`)와 PostgreSQL 저장소 구현 | DDL·Seed 변경 (없음. T09 `0001_initial_schema.sql` 테이블 그대로 사용) |

작업 지시서의 산출물 표기 `recommendations/{id}/feedback`은 API 계약 v0.2(§5 변경표)에서
`POST /recommendation-feedback`으로 바뀌었으므로 계약을 따랐습니다. 추적표(F-018)의 경로도 옛 표기입니다.

## 2. 계약 매핑

| 계약 | 구현 |
|---|---|
| `RecommendationFeedbackInput` (`additionalProperties: false`, 필수 `job_posting_id`·`feedback`) | `app/schemas/recommendation_feedback.py` — `extra="forbid"`. `recommendation_run_id`는 생략 가능, 명시적 `null`은 422 (계약 타입이 nullable 아님) |
| `feedback` enum `liked / not_interested / cleared` | `Literal` 로 제한. 대소문자·빈 값·숫자는 422 |
| `201 RecommendationFeedback {feedback_id, job_posting_id, feedback, created_at}` | 같은 4개 필드만 응답. user_id는 응답에 없음 |
| 401 / 404 / 422 (공통 오류 형식 `code·status·message`) | `UNAUTHENTICATED`·`TOKEN_EXPIRED` / `NOT_FOUND` / `VALIDATION_FAILED` (`ERROR_CATALOG` 그대로, 새 코드 없음) |
| API_CONTRACT §1.3 "다른 사람 리소스는 404" | 다른 사람 실행, 없는 실행, 내 추천에 없던 공고, 없는 공고 → 모두 같은 404 본문 |
| D07 `recommendation_feedback` "추가만, 공고별 최신 행이 현재 값" | `insert_feedback`만 있고 UPDATE·DELETE 없음. 최신 = `created_at DESC, feedback_id DESC` |
| D07 "`not_interested` 최신 공고는 다음 추천에서 제외" | T45 `SqlRecommendationRepository.load_inputs()`가 후보 공고 ID로 T47 `latest_feedback_records()` + `current_feedback_values()`를 호출해 최신 값이 `not_interested`인 공고만 뺀다 |
| T45 `RecommendationItem.feedback` (`liked / not_interested / null`) | T45 `SqlRecommendationRepository.get()`이 같은 두 함수를 항목 전체에 **한 번의 쿼리**로 호출 — 기록 없음·`cleared` → `null` (예전 T45는 항목마다 1쿼리) |
| F11 `audit_events` (T05 기본 컬럼) · [감사 계약](../../docs/security/AUDIT_EVENT_CONTRACT.md) | 새 이력 행을 넣을 때 같은 트랜잭션에서 `user.recommendation_feedback.create` / `recommendation_feedback` / `feedback_id` / `request_id` 기록 |

## 3. 결정 사항

- **소유권:** 피드백은 내 추천 실행(`recommendation_runs.user_id = 토큰 sub`)의 항목(`recommendation_items`)에 있던 공고에만 남깁니다.
  `recommendation_run_id`를 주면 그 실행 안에 공고가 있어야 합니다. 사용자 ID는 본문에서 받지 않습니다(`user_id`를 보내면 422).
- **중복:** 보낸 값이 현재(최신) 값과 같으면 새 행을 만들지 않고 최신 행을 그대로 201로 돌려줍니다(멱등). 감사 행도 만들지 않습니다.
  다른 추천 실행에서 같은 값을 눌러도 현재 상태가 같으므로 멱등입니다.
- **정정·취소:** 값을 바꾸거나 `cleared`를 보내면 새 행을 추가하고 최신 값이 이깁니다. 기록이 없을 때의 `cleared`도 1행을 남깁니다.
- **시각 순서:** 현재 값은 `created_at DESC`로 정하므로, 새 행의 `created_at`은 잠금 안에서 `max(앱 시계, 직전 행 + 1µs)`로 정합니다.
  앱 인스턴스끼리 시계가 어긋나거나 시계가 뒤로 가도 정정이 항상 현재 값이 됩니다(FR-ANL-004 수용 기준 2). 감사 `occurred_at`도 같은 값입니다.
- **동시성:** PostgreSQL 저장소는 `pg_advisory_xact_lock(hashtextextended('t47-feedback:<user>:<posting>', 0))`으로
  같은 사용자·공고 요청을 줄 세워 중복 판정이 경합하지 않게 합니다(트랜잭션 끝에 자동 해제, 테이블 잠금 없음).
- **감사:** F11에 이미 있는 컬럼만 씁니다. 피드백 값·공고 제목·이메일은 넣지 않습니다. T83 확장 컬럼(`result`, `retention_class` 등)과
  공용 감사 기록 함수는 T84 범위라, T84가 머지되면 `record_audit`를 그 함수로 바꿉니다.
- **문구 원칙:** 피드백은 내 추천 개선에만 쓰며 기업·채용 담당자에게 공유하지 않습니다(서비스 주석에 명시).
- **동의/삭제 정책:** 피드백은 내 추천 개선에만 쓰므로 별도 동의 항목을 두지 않습니다(외부 공유·학습 활용 없음).
  D07은 PERSONAL 등급이며 `users` 삭제 시 `ON DELETE CASCADE`로 함께 지워집니다. 감사 행은 남고 `actor_user_id`만 `ON DELETE SET NULL`로 비워집니다.
  API에서 사용자 데이터를 직접 지우는 코드는 없습니다(삭제는 회원 탈퇴 일감 범위). 이 동작은 PostgreSQL 선택 테스트로 확인합니다.

## 4. T45 연동 (origin/main d0d18e1 병합 후)

T45가 실제로 머지한 코드(`app/routers|services|repositories|schemas/recommendation_runs.py`, `tests/test_recommendation_runs*.py`,
`backend/docs/T45_RULE_BASED_API.md`)를 읽고 다음과 같이 맞췄습니다.

| 항목 | T45 머지 상태 | T47 조치 |
|---|---|---|
| 경로·DTO | `POST /recommendation-runs`, `GET /recommendation-runs/latest`, `GET /recommendation-runs/{id}`. `RecommendationItem.feedback` enum `liked/not_interested/null` | `openapi.yaml`과 같음(차이 없음). T47 계약 테스트가 yaml의 `RecommendationItem.feedback` enum을 계속 확인 |
| 테이블 정의 | T45 저장소 모듈 안에 `model_versions/runs/items/feedback` `table()` 정의. `feedback`에는 `recommendation_run_id` 컬럼 없음 | 두 모듈이 같은 정의를 쓰도록 `app/repositories/recommendation_tables.py`로 옮김(`feedback`에 `recommendation_run_id` 추가). T47의 중복 `recommendation_runs/items/feedback` 정의 삭제. T45 모듈은 `runs/items/model_versions` 이름을 그대로 노출(T45 PostgreSQL 테스트 import 유지) |
| 소유권 조회 | T45는 별도 조회 함수·메모리 저장소를 제공하지 않음 | `is_recommended_to()`는 공유 테이블로 `recommendation_items JOIN recommendation_runs`를 조회. 메모리 fake의 `add_run()`은 T45에 대체물이 없어 유지 |
| 최신 피드백 → `RecommendationItem.feedback` | T45가 자체로 항목마다 최신 피드백 1쿼리(같은 정렬 규칙) | T47 함수 호출로 교체(작고 안전한 변경, 동작 동일, 쿼리 N→1) |
| `not_interested` 제외 | T45가 자체로 사용자 피드백 전체를 읽어 제외(동작은 D07과 같음) | 후보 공고 ID로 T47 함수 호출로 교체(결과 동일, 읽는 범위는 후보로 한정) |

T45가 `openapi.yaml`과 다른 점은 찾지 못했습니다. T45 문서 §4대로 공고가 숨겨지거나 지워지면 GET에서 그 항목이 빠질 수 있는데,
이 경우 그 공고에 대한 피드백 POST는 여전히 201이 될 수 있습니다(소유권은 `recommendation_items` 기준, 공고 공개 여부는 보지 않음).
계약에 정한 바가 없어 그대로 두었습니다.

## 5. 제안 (계약 밖, 구현하지 않음)

- 추천 근거(설명) 조회는 계약상 `RecommendationItem.reason`(T45의 `GET /recommendation-runs/*`)로 제공됩니다. T47에서 별도 공개 API를 만들지 않았습니다.
- 내 피드백 이력 목록 API(예: `GET /me/recommendation-feedback`)가 필요하면 T06 계약 변경으로 먼저 제안합니다.

## 6. 파일

- `app/schemas/recommendation_feedback.py`, `app/repositories/recommendation_feedback.py`,
  `app/services/recommendation_feedback.py`, `app/routers/recommendation_feedback.py`, `app/routers/api_v1.py`(라우터 등록)
- `app/repositories/recommendation_tables.py`(T45·T47 공유 테이블 정의), `app/repositories/recommendation_runs.py`(T45, T47 함수 사용으로 변경)
- `tests/fakes.py`(`MemoryRecommendationFeedbackRepository`), `tests/test_t47_recommendation_feedback.py`,
  `tests/test_t47_recommendation_feedback_postgres.py`(선택 실행, `T47_TEST_DATABASE_URL`),
  `tests/test_t47_recommendation_feedback_t45_postgres.py`(선택 실행, T45 E2E와 같은 `T15_TEST_DATABASE_URL` — Backend CI에서 실행됨)

## 7. 테스트 명령

```bash
cd backend
python -m pytest -q tests/test_t47_recommendation_feedback.py   # T47 전용 (DB 불필요)
python -m pytest -q                                              # 전체
# 선택: 로컬 일회용 DB (Migration + Seed 적용, localhost만 허용). 모든 변경은 롤백됨
T47_TEST_DATABASE_URL=postgresql://USER@127.0.0.1:5432/career_dev python -m pytest -q tests/test_t47_recommendation_feedback_postgres.py
# 선택: T45 실제 실행과의 E2E. 지정 DB의 career 스키마를 지우고 T05 DDL + T10 Seed로 다시 만든다 (일회용 DB만)
T15_TEST_DATABASE_URL=postgresql://USER@127.0.0.1:5432/throwaway python -m pytest -q tests/test_t47_recommendation_feedback_t45_postgres.py
```

### 결과 — origin/main(d0d18e1) 병합 후 (2026-11-09, 워크트리 `.claude/worktrees/wf_82f459d5-986-1`)

- 전체 `python -m pytest -q` (DB 없음): **381 passed, 130 skipped**
- 전체 + 로컬 일회용 PostgreSQL 16 (`127.0.0.1:55447`, `T15_TEST_DATABASE_URL`·`T16_TEST_ADMIN_URL`=DB `t15`, `T47_TEST_DATABASE_URL`=DB `t47`): **395 passed, 116 skipped, 0 failed**
- T47 세 파일 (DB 없음): **43 passed, 5 skipped** (skipped = PostgreSQL 선택 테스트 4 + T45 E2E 1)
- T47 세 파일 + T45 두 파일 + 로컬 PostgreSQL 16: **64 passed**
  (T47 저장소 4건: Migration 0001·0002 + Seed 0001 적용 DB, 끝난 뒤 피드백·감사·`t47-*` 사용자 행 0건 / T45 E2E 1건: T05 DDL + T10 Seed)
- DB 없는 T45 연동 테스트 3건 추가: 공유 테이블·함수 동일성, `current_feedback_values` 규칙, 최신 피드백 SQL이 `DISTINCT ON` 1쿼리인지
- T45 E2E 1건 추가(`test_t47_recommendation_feedback_t45_postgres.py`): T45가 만든 실행으로 201, 다른 사용자·없는 실행 404,
  멱등, GET `items[].feedback` = liked / not_interested / null, 다음 실행에서 `not_interested`만 제외, `cleared` 뒤 다시 포함, 이력·감사 3행
- `ruff check --line-length 120` (T47 파일 + 공유 테이블 모듈): All checks passed. `ruff check --select F,E9` (T45 `recommendation_runs.py`, `api_v1.py`): All checks passed.
  저장소에 ruff 설정 파일이 없어 기본 규칙에서는 기존 파일과 같은 I001/C408이 남음(T45 원본 C408 1건 포함)
- `scripts/ci/*`: 새 main에도 없어 실행하지 못함
- Frontend (Node v24.22.2, 이 브랜치의 frontend 변경 없음 — main에서 온 변경만): `npm ci` 성공, `npm run lint` 통과,
  `npm test` Test Files 12 passed | 2 skipped, Tests 84 passed | 10 skipped, `npm run build` 성공

### 결과 — 병합 전 (참고, 기준 2cdd70c)

- 전체 `python -m pytest -q`: 271 passed, 85 skipped
- T47 두 파일 (DB 없음): 40 passed, 4 skipped (skipped 4건 = PostgreSQL 선택 테스트)
- T47 두 파일 + 로컬 일회용 PostgreSQL 16 (`127.0.0.1`, Migration 0001 + Seed 0001 적용, `verify_seed.sql` 통과): 44 passed. 끝난 뒤 피드백·감사·`t47-*` 사용자 행 0건(롤백 확인)

DB 없는 테스트가 다루는 경우: 정상 생성, `run_id` 생략, 중복(멱등), 정정, 취소, 기록 없는 취소, 다른 실행에서 이어지는 이력,
다른 사람 실행·추천 안 된 공고·없는 실행·없는 공고 404, 사용자별 이력 분리, 401(토큰 없음·위조·Basic·만료·로그아웃),
422(알 수 없는 필드·enum·uuid·null·빠진 필드·배열·문자열 본문), 400(깨진 JSON), 405, 실패 시 롤백, 감사 기록,
시계가 뒤로 가도 정정이 현재 값이 되는지, OpenAPI 생성 결과·`openapi.yaml` 계약 비교, PostgreSQL 방언 SQL 형태.

PostgreSQL 선택 테스트(4건): 소유권·중복·정정·감사, 다른 사람 실행·추천 안 된 공고 404, 사용자별 분리·`not_interested` 제외,
사용자 삭제 시 피드백 CASCADE 삭제와 감사 `actor_user_id` NULL (동의/삭제 정책).

## 8. PARTIAL 사유와 HOLD

| 항목 | 상태 | 해제 조건 |
|---|---|---|
| T45가 만든 추천 실행·항목과의 실제 DB 연동 (소유권 조회·이력 추가·감사 기록) | **PASS (로컬)** — 로컬 일회용 PostgreSQL 16에서 T45 E2E 1건 + 저장소 4건 | — |
| T45 `RecommendationItem.feedback` 채우기, `not_interested` 제외 | **PASS** — T45 저장소가 T47 함수 사용(E2E 확인) | — |
| 동의/삭제 정책 | 별도 동의 불필요(내 추천 개선에만 사용). 삭제는 `users` CASCADE, 로컬 DB 테스트 PASS | 회원 탈퇴 API는 해당 일감 |
| 병합된 브랜치의 GitHub Backend CI (`T15_TEST_DATABASE_URL`로 T45 E2E·T47×T45 E2E 실행) | **미실행** (push 전) | push 후 Backend tests 워크플로 통과 확인 → PASS 전환 |
| 감사 기록 공용 함수·T83 확장 컬럼 | HOLD | T84 |
| Staging 반영 | 하지 않음 (승인 전 금지) | PM 승인 |
