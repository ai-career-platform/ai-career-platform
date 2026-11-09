# T47 추천 설명·피드백 API 작업 노트 (Redmine #1589)

- 상태: **PARTIAL** — 계약(OpenAPI) 기준 구현과 메모리 저장소 테스트는 PASS. 로컬 일회용 PostgreSQL 16 선택 테스트(추천 실행·항목은 테스트가 직접 넣음)도 PASS.
  선행 T45(추천 실행 API)가 머지되지 않아 T45가 만든 실제 추천 데이터와의 연동 검증은 **HOLD**
- 기능 추적: F-018 (FR-ANL-004), 화면 UI-017 · 작업 지시서 [T47](../../docs/work-orders/next-30/T47.md)
- 브랜치: `task/t47-recommendation-feedback-api` (기준 `origin/main` 2cdd70c)

## 1. 범위

| 포함 | 제외·HOLD |
|---|---|
| `POST /api/v1/recommendation-feedback` (operationId `createRecommendationFeedback`) | 추천 실행 생성·조회(`/recommendation-runs*`) — T45 |
| 소유권 확인, 중복(멱등)·정정·취소 처리, 사용자별 이력 분리, 감사 기록 | 실제 PostgreSQL 연동 검증 (T45 머지 후) |
| T45용 서비스 함수: 공고별 최신 피드백, `not_interested` 제외 목록 | 화면(UI-017) 피드백 버튼 — Frontend 일감 |
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
| D07 "`not_interested` 최신 공고는 다음 추천에서 제외" | `RecommendationFeedbackService.not_interested_ids()` (T45가 호출) |
| T45 `RecommendationItem.feedback` (`liked / not_interested / null`) | `RecommendationFeedbackService.current_feedback()` — 기록 없음·`cleared` → `None` |
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

## 4. 제안 (계약 밖, 구현하지 않음)

- 추천 근거(설명) 조회는 계약상 `RecommendationItem.reason`(T45의 `GET /recommendation-runs/*`)로 제공됩니다. T47에서 별도 공개 API를 만들지 않았습니다.
- 내 피드백 이력 목록 API(예: `GET /me/recommendation-feedback`)가 필요하면 T06 계약 변경으로 먼저 제안합니다.

## 5. 파일

- `app/schemas/recommendation_feedback.py`, `app/repositories/recommendation_feedback.py`,
  `app/services/recommendation_feedback.py`, `app/routers/recommendation_feedback.py`, `app/routers/api_v1.py`(라우터 등록)
- `tests/fakes.py`(`MemoryRecommendationFeedbackRepository`), `tests/test_t47_recommendation_feedback.py`,
  `tests/test_t47_recommendation_feedback_postgres.py`(선택 실행)

## 6. 테스트 명령

```bash
cd backend
python -m pytest -q tests/test_t47_recommendation_feedback.py   # T47 전용 (DB 불필요)
python -m pytest -q                                              # 전체
# 선택: 로컬 일회용 DB (Migration + Seed 적용, localhost만 허용). 모든 변경은 롤백됨
T47_TEST_DATABASE_URL=postgresql://USER@127.0.0.1:5432/career_dev python -m pytest -q tests/test_t47_recommendation_feedback_postgres.py
```

결과 (2026-11-09, 워크트리 `.claude/worktrees/wf_b056e09a-0b8-1`, 커밋 전 기준):

- 전체 `python -m pytest -q`: 271 passed, 85 skipped
- T47 두 파일 (DB 없음): 40 passed, 4 skipped (skipped 4건 = PostgreSQL 선택 테스트)
- T47 두 파일 + 로컬 일회용 PostgreSQL 16 (`127.0.0.1`, Migration 0001 + Seed 0001 적용, `verify_seed.sql` 통과): 44 passed. 끝난 뒤 피드백·감사·`t47-*` 사용자 행 0건(롤백 확인)

DB 없는 테스트가 다루는 경우: 정상 생성, `run_id` 생략, 중복(멱등), 정정, 취소, 기록 없는 취소, 다른 실행에서 이어지는 이력,
다른 사람 실행·추천 안 된 공고·없는 실행·없는 공고 404, 사용자별 이력 분리, 401(토큰 없음·위조·Basic·만료·로그아웃),
422(알 수 없는 필드·enum·uuid·null·빠진 필드·배열·문자열 본문), 400(깨진 JSON), 405, 실패 시 롤백, 감사 기록,
시계가 뒤로 가도 정정이 현재 값이 되는지, OpenAPI 생성 결과·`openapi.yaml` 계약 비교, PostgreSQL 방언 SQL 형태.

PostgreSQL 선택 테스트(4건): 소유권·중복·정정·감사, 다른 사람 실행·추천 안 된 공고 404, 사용자별 분리·`not_interested` 제외,
사용자 삭제 시 피드백 CASCADE 삭제와 감사 `actor_user_id` NULL (동의/삭제 정책).

## 7. PARTIAL 사유와 HOLD

| 항목 | 상태 | 해제 조건 |
|---|---|---|
| T45가 만든 추천 실행·항목과의 실제 DB 연동 (소유권 조회·이력 추가·감사 기록) | HOLD (로컬 일회용 DB에서 테스트가 직접 넣은 실행·항목으로는 4건 PASS) | T45 머지 후 T45 데이터로 `*_postgres.py` 다시 실행 |
| 동의/삭제 정책 | 별도 동의 불필요(내 추천 개선에만 사용). 삭제는 `users` CASCADE, 로컬 DB 테스트 PASS. T45 데이터 기준 재확인은 HOLD | T45 머지 후 재실행, 회원 탈퇴 API는 해당 일감 |
| T45 `RecommendationItem.feedback` 채우기, `not_interested` 제외 | HOLD (서비스 함수만 제공) | T45가 `current_feedback()`·`not_interested_ids()` 호출 |
| 감사 기록 공용 함수·T83 확장 컬럼 | HOLD | T84 |
| Staging 반영 | 하지 않음 (승인 전 금지) | PM 승인 |
