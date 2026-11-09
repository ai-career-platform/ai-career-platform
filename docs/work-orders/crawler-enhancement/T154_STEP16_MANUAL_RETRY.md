# T154 STEP16 — Explicit Fixture Retry Orchestration

T154 STEP11 스테이징 Fixture Worker PASS, STEP13 동시 잠금 214/214 PASS (사용자 제공). **STEP15 실제 0009 격리 PostgreSQL 검증 결과는 아직 받지 못했으므로 HOLD.**

`execute_manual_fixture_attempt`는 서로 다른 연결 `attempt_connection`과 `worker_connection`을 인자로 받는다. 순서는 예약(별도 commit) → 기존 `process_fixture_job` 1회 명시적 실행 → 성공 시 별도 commit의 `record_success`, 실패 시 (Worker rollback 이후) 명시적으로 분류된 오류만 `record_failure`다. 자동 재호출/스케줄 연동은 없다.

- 예약 불가(이미 IN_PROGRESS, STOPPED, 3회 초과, 비활성)는 Worker 호출 없이 거부.
- 403/429/INVALID_CONTRACT 등의 비재시도 코드는 기존 T64 판정으로 STOPPED.
- 작업 처리 중 미분류 예외는 attempt IN_PROGRESS로 남겨 수동 검토. 원래 예외를 다시 전달.
- Worker 성공 후 시도 레저 갱신이 실패하면 `AttemptFinalizationRequired`로 보고. 이미 저장된 공고나 체크포인트를 임의로 되돌리지 않는다.
- 연결이 물리적으로 다르기만 하면 충분하지 않다. 동일 **격리 전용 DB**로 연결되고, 예약 연결은 변경사항 commit을 마쳤어야 한다. 진행 중 외부 transaction 금지.
- 시도 예약과 Worker Claim 사이 짧은 창이 있다. 명시적 단일 실행 흐름만 제공하고 프로세스 중단 자동 복구는 하지 않는다.
- Worker 실패 증거가 없는 오류 분류를 강제하지 않는다. 오류 코드는 호출자가 검증 가능한 맥락으로 전달해야 하며, 오류 코드 자동 추론은 하지 않는다.

## 검증
- GitHub CI smoke/offline test.
- STEP15 (0009 직접 검증) PASS 이후 격리 PostgreSQL에서 실제 두 연결로 STEP16 E2E 별도 수행.
- 원본 코드 변경이나 Migration 실행 없이 추가된 파일만; 0009 스테이징 미적용 상태 유지.
- Scheduler disabled, Timer inactive, Dispatcher 없음, Live HTTP HOLD.
