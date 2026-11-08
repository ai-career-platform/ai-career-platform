# T154 STEP07 — Fixture 작업 payload 고정

기존 T154 STEP04는 T151 job ID만 저장했으므로 실패 후 재개할 때 어떤 공고 ID 목록이 배정됐는지 확인할 수 없었다. 신규 `0008_fixture_job_payloads.sql`은 각 T151 job ID별 합성 공고 ID 배열을 따로 저장한다.

- `FixturePayloadStore.register`: T151 keyword_jobs FK로 연결되는 job당 동일 payload만 허용. 다른 payload 재등록 시 명시적 충돌, 기존 값 변경하지 않음.
- `FixturePayloadStore.read`: 저장된 작업 ID·검색어·ID 목록·멱등 키 반환.
- `persist_fixture_keyword_jobs`: 기존 체크포인트·시간창·배치 생성 재사용. DB 작업 메타데이터 및 payload를 외부 트랜잭션으로 묶어 중간 오류 시 모두 롤백.
- 데이터는 합성 공고 ID만 저장. URL·HTML·비밀번호 등 저장하지 않음.
- 신규 migration 0008은 **수동 적용** 전용. 기존 0003~0007 재적용 금지. Runtime GRANT SELECT/INSERT만 부여(UPDATE 없음).
- 실제 Worker claim, 실패 재개 및 체크포인트 완료 전환은 이 단계에서 실행하지 않음. 스테이징·Timer·외부 HTTP 변경 없음.

## 검증

`python -m unittest crawler.tests.test_t154_fixture_payloads -v`
`python -m unittest discover -s crawler/tests -v`

추가 실제 격리 DB 검증: runtime 권한, 중복 job과 동일 payload, 다른 payload 거부, job/payload 전체 rollback, 다른 검색어 격리, 기존 데이터 보존.

T154 STEP06 사용자 제공 보고: 0007 스테이징 적용 및 runtime fixture 검증 PASS, 테스트 데이터 롤백, 기존 공고 7건·앱 51테이블 보존, 외부 HTTP 0, Scheduler false, Timer inactive. 실제 로컬 로그 원본은 미열람.

T153 STEP04 advisory-lock 스테이징 RETEST는 여전히 결과 미수신으로 별도 HOLD.
