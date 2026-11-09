# T154 STEP12 — Fixture Job 중복 Claim 차단

T154 STEP11 스테이징 Fixture Worker 사용자 제공 결과 PASS, 테스트 행 롤백, 기존 공고 7건 및 앱 51 테이블 보존.

`process_fixture_job`의 기존 `keyword_jobs FOR UPDATE` 잠금을 `FOR UPDATE NOWAIT`로 변경한다. 이미 동일 job을 다른 트랜잭션에서 처리 중이면 대기하여 시간 초과가 발생하기보다 PostgreSQL `lock_not_available` 오류로 즉시 거부한다. 실제 처리 트랜잭션, T151 상태 전이, T153 파싱 및 체크포인트 갱신은 변경하지 않는다.

**실패 후 재개와 구별:** 본 변경은 중복 동시 Claim을 차단하는 안전장치다. 실패 시 기존 worker 트랜잭션이 전체 롤백되어 `PENDING` 상태로 남는 경우 **수동 재호출**은 가능하지만, 지속적 시도 횟수 기록·재시도 예약·재개 서비스는 구현하지 않았다. 이 기능을 완료했다고 주장하지 않는다.

## 검증
- CI: offline-tests, CI Smoke Test.
- 격리 PostgreSQL 별도 검증: 두 연결이 같은 job을 동시 처리할 때 한쪽만 lock을 획득하고 나머지 즉시 `55P03` (lock_not_available), 결과 공고 및 체크포인트 1회 저장, 실패/중단 시 rollback.
- 스테이징 DB는 현재 변경하지 않는다. 스케줄 enabled=false, Timer disabled, HTTP 0, Live HOLD.
