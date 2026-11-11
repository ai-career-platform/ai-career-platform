# 백그라운드 작업·이벤트 재처리 공통 계약 (T145)

> 상태: **PROPOSED**. 라이브러리와 시험만 추가했습니다. 실행기·Timer·운영 Worker는 켜지 않았습니다.
> - 코드
>   - `backend/app/services/background_jobs.py`: 상태 머신, 정책, 실행, 운영 명령
>   - `backend/app/repositories/background_jobs_pg.py`: PostgreSQL 저장소
> - 표: `database/proposed/T145_background_jobs.sql` (**정식 migration 아님**)
> - **T110(LLM 비동기)은 NOT_STARTED**입니다. `llm.*` 유형은 계약만 있고 enqueue를 거부합니다(`ContractOnly`).

## 1. 재사용한 기존 규칙

| 출처 | 가져온 규칙 | 일반화 |
|---|---|---|
| T64 `run_state.py` | 불변 레코드, 허용 전이표, 시각은 UTC aware만 | `Job.moved()` + `ALLOWED` |
| T64 `run_claims.py` | 같은 대상 중복 실행 거부 | `(kind, idempotency_key)` UNIQUE |
| T64 `offline_recovery.py` | 일시 오류만 재시도, 차단 신호는 즉시 중단 | `PERMANENT_CODES`(HTTP_403·CAPTCHA·robots 등) |
| T96 `notifications.py` | outbox, lease 5분, 지수 백오프, dedupe, 영구 실패 | lease + fencing token, `dead_letter` |
| T112 `request_id` | `[A-Za-z0-9._-]{8,64}` 안전 형식, 로그에 id만 | `correlation_id`. 요청 id를 이어 쓰고, 아니면 `job-` + 16 hex |

기존 모듈은 수정하지 않았습니다. 기존 모듈을 이 계약으로 옮기는 일은 후속 PR(승인 후)에서 합니다.

## 2. 상태와 전이

```
queued ─claim→ running ─성공→ succeeded
  │              ├─재시도 가능 오류, attempts < max → failed ─(next_attempt_at 도래) claim→ running
  │              ├─영구 오류 또는 attempts ≥ max → dead_letter ─(운영자 replay)→ queued
  │              ├─취소 요청 반영 → cancelled
  │              └─lease 만료 → (다른 Worker) running  [attempt+1, fencing token+1]
  └─cancel → cancelled                       failed ─cancel→ cancelled
```

- 종료 상태: succeeded, cancelled, dead_letter.
- dead_letter에서 나가는 길은 운영자 replay(`replay_dead_letter`)뿐입니다. 시도 횟수를 0으로 되돌리고, 이력에 행위자를 남깁니다.
- 이력은 append-only입니다(DB 트리거로 UPDATE·DELETE 거부). 각 항목에 남기는 값:
  - 시각, 이전·다음 상태, 사유
  - worker_id, correlation_id, attempt

## 3. 유형별 정책 (`KINDS`)

| kind | 최대 시도 | 백오프(기본→상한) | 지터 | lease | 실행 | 근거 |
|---|---|---|---|---|---|---|
| `crawler.fixture_fetch` | 3 | 30초 → 10분 | 20% | 10분 | 가능(합성 Fixture) | T64·T154 |
| `crawler.parse_raw` | 3 | 30초 → 10분 | 20% | 10분 | 가능 | T153 |
| `notification.deliver` | 5 | 1분 → 6시간 | 10% | 5분 | 가능(발송 공급자는 T96 기본 비활성) | T96 |
| `llm.document_analysis` | 3 | 1분 → 1시간 | 20% | 15분 | **거부(계약만)** | T110 NOT_STARTED |
| `llm.recommendation_explain` | 3 | 1분 → 1시간 | 20% | 15분 | **거부(계약만)** | T110 NOT_STARTED |

백오프 규칙
- 식: `min(cap, base·2^(n-1))`에 `[0, jitter)` 비율을 더하고, 다시 cap으로 자릅니다.
- 지터는 `sha256(job_id:attempt)`로 정합니다.
  - 같은 작업·같은 시도면 항상 같은 값이라 재현과 시험이 됩니다.
  - 작업마다 값이 달라 재시도 시각이 흩어집니다.

## 4. 핵심 보장

| 항목 | 규칙 | 시험 |
|---|---|---|
| 멱등성 | 같은 `(kind, idempotency_key)`면 기존 작업을 돌려줍니다. 완료 뒤 재전송해도 다시 실행하지 않습니다. | `test_duplicate_message_runs_handler_once` |
| 재시도 한도 | 시도 횟수가 `max_attempts`에 이르면 `dead_letter`(사유 attempts_exhausted)이고, 자동 재시도는 없습니다. | `test_retry_backoff_then_dead_letter` |
| 차단·영구 오류 | `PermanentJobError` 또는 `PERMANENT_CODES`면 1회 만에 dead_letter입니다. 403·429·CAPTCHA·robots에서 즉시 멈춥니다. | `test_blocking_and_permanent_errors_stop_immediately` |
| 알 수 없는 예외 | 재시도합니다. `last_error`에는 예외 **형식 이름만** 남기고, 메시지(토큰·주소 포함 가능)는 저장하지 않습니다. | `test_unknown_exception_is_retryable_without_leaking_message` |
| 취소 | queued·failed는 즉시 cancelled입니다. running은 표시만 하고, handler가 `ctx.cancel_requested()`로 확인합니다. 실패로 끝나면 cancelled, 이미 성공했으면 succeeded(사유 기록)입니다. | `test_cancel_queued_running_and_terminal` |
| 중복 Worker | claim은 `FOR UPDATE SKIP LOCKED`로 원자적입니다. Worker 4개가 동시에 claim해도 24개 작업이 각각 한 번씩만 배정됩니다. | `test_competing_workers_claim_each_job_once`(메모리·PG). 잠금을 제거하면 실패하는 것을 변이 시험으로 확인했습니다. |
| lease 만료 회수 | lease가 지난 running은 다른 Worker가 회수합니다(attempt+1). 시도를 다 썼으면 dead_letter입니다. | `test_lease_expiry_reclaim_and_fencing`, `test_lease_reclaim_after_last_attempt_goes_to_dead_letter` |
| fencing | 저장은 `lease_token`이 같을 때만 됩니다. lease를 잃은 옛 Worker의 늦은 완료 보고는 거부되며(`LeaseLost`), 새 Worker의 상태를 덮어쓰지 않습니다. | `test_runner_reports_lease_lost_instead_of_overwriting` |
| 상태 이력 | 모든 전이를 남기고, PG에서는 수정·삭제를 거부합니다. | `test_pg_history_is_append_only` |
| correlation id | 요청의 `X-Request-ID`를 이어 쓰고, handler 안에서 `current_correlation_id()`로 읽습니다. 로그에는 id만 남기고 payload는 남기지 않습니다. 실행이 끝나면 초기화합니다. | `test_success_path_records_history_and_correlation`, `test_correlation_id_follows_t112_request_id_rules` |
| payload | `payload_ref`는 128자 이하의 참조 문자열만 받습니다. 원문·개인정보·토큰은 넣을 수 없습니다(형식 검사). | `test_contract_only_and_input_validation` |

### handler 작성 규칙
1. **at-least-once**입니다. lease 만료 뒤 같은 작업이 다시 실행될 수 있으므로 부작용은 멱등이어야 합니다.
   - 예: T63 UPSERT, T96 dedupe_key, T153 lineage UNIQUE
2. 차단 신호(403·429·CAPTCHA·robots)는 `RetryableJobError("HTTP_403")`처럼 코드로 올립니다. 그러면 자동으로 영구 처리됩니다.
3. 오래 걸리는 작업은 중간에 `ctx.cancel_requested()`를 확인합니다.

## 5. 결정 필요 (PM·DevOps)
1. `T145_background_jobs.sql`을 정식 migration으로 만들지 여부와 시점(T115 게이트 적용)
2. 기존 T64 실행 기록·T96 outbox를 이 표로 합칠지, 계약만 맞출지
3. dead_letter 보존 기간과 정리 방법
   - 이력 append-only 트리거가 있어 작업 삭제(CASCADE)가 막힙니다.
   - 보존 정책을 정한 뒤 별도 정리 역할이 필요합니다.
4. replay 권한(운영 관리자만)과 감사 이벤트(T83) 연결
5. LLM 작업(T110) 착수 시 비용 한도(T119)와 함께 정책값 확정

## 6. 재현

```bash
cd backend
python -m pytest -q tests/test_t145_background_jobs.py                     # 메모리 저장소
T145_ADMIN_URL=postgresql://<admin>@127.0.0.1:<port>/postgres \
  python -m pytest -q tests/test_t145_background_jobs.py                   # + 일회용 PG(DB 생성 후 삭제)
```
