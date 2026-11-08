# T154 STEP14 — Durable Fixture Attempt Budget (manual-only)

기존 T154 STEP13 사용자 보고: 격리 PostgreSQL 동시성 214/214 PASS, NOWAIT 55P03 약 15ms, 수동 롤백 후 재호출 가능. 반복 검증하지 않음.

## 기능
- 수동 Migration `0009_fixture_job_attempts.sql`: T151 Job FK로 검색 가능한 독립 시도 상태 테이블 생성. `IN_PROGRESS/RETRYABLE/STOPPED/COMPLETED`, 최대 3회. 원본 데이터·기존 컬럼 변경 없음.
- `DurableFixtureAttemptStore.reserve`: 이미 `PENDING`이고 immutable payload가 있는 작업만 1회 예약. PostgreSQL의 ON CONFLICT 조건부 UPDATE로 **중복 예약 차단**, `RETRYABLE` 상태 및 남은 횟수에서만 다음 시도 허용.
- `record_failure`: 기존 T64 `retry_decision` 사용. 일시적 I/O 오류는 3회 한도까지 수동 재예약 가능. 403/429/비허용 오류 즉시 STOPPED. 작업 상태가 PENDING으로 롤백된 경우에만 실패를 기록할 수 있다.
- `record_success`: 실제 Job이 COMPLETED일 때만 성공 표기.
- `IN_PROGRESS` 중 단절은 자동 재예약 금지. 운영자가 기존 실행·DB 상태 확인 후 별도 복구 설계 필요.

## 매우 중요한 트랜잭션 분리
Attempt 기록은 Worker와 **다른 DB 연결**에서 별도 commit해야 한다. 그렇지 않으면 Worker 파싱/UPSERT 실패 시 예약 내역도 롤백되어 최대 횟수 제한이 무력화된다. 또한 완료된 worker 실행과 record_success 사이에 중단이 발생하면 IN_PROGRESS로 남을 수 있으므로 수동 검사가 필요하다. 이 단계에서는 안전한 미완료 표시를 택하고 자동 복구하지 않는다.

## 범위/검증
- 실제 Worker 자동 호출/스케줄/Timer 연동은 **미구현**. 별도 호출자 통합은 후속 작업.
- Migration 0009 아직 DB 미적용, 격리 PostgreSQL 적용 전.
- CI static/offline tests 후 격리 PostgreSQL에서 runtime 권한·중복 예약 동시성·실제 commit 경계·실패 rollback·3회 한도·STOPPED 검증.
- 기존 0003~0008 migration 재적용 금지. 외부 HTTP 0, Scheduler false/fixture, Timer disabled, Live HOLD.
