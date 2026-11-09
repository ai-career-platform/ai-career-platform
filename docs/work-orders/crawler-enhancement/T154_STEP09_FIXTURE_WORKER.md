# T154 STEP09 — Explicit Fixture Job Processor

## 범위
- `process_fixture_job(connection, files, job_id)` 수동 함수 호출 **전용**. 실제 Dispatcher/Timer/자동 Scheduler/HTTP 호출 없음.
- T151 job PENDING 상태를 확인하고, T154 immutable payload read 후 해당 job_id와 검색어 ID에 매핑된 T152 합성 detail Raw를 모두 조회한다.
- Payload 내 synthetic 공고 ID와 Raw URL ID는 정확히 1:1 대응해야 한다. 누락/중복/예상 밖 Raw는 **상태 전환 전** 실패.
- 한 트랜잭션 안에서 PENDING → RUNNING → FETCHED → COMPLETED, T153 RawParseLedger 처리, T154 성공 checkpoint 갱신. Invalid/예외는 DB 전체 rollback.
- COMPLETED job은 즉시 반환(새 원본 INSERT 0). RUNNING·FAILED 등의 재실행은 거부. 실패 작업 자동 재개 및 claim/heartbeat 연동은 아직 미구현.
- PostgreSQL 경로 실검증은 **별도 진행**. CI는 오프라인 단위 테스트만 수행.
- 신규 migration 없음. `0008`은 STEP08 격리 DB 200/200 PASS이나 **스테이징 적용 전**.
- T153 PR #103 Advisory Lock 이후 runtime E2E RETEST는 사용자 결과가 없어 완료라고 단정하지 않음.

주의: Raw 파일은 트랜잭션 롤백의 대상이 아니다. 처리 함수는 읽기만 수행하며 새 파일 생성/삭제 없음.
