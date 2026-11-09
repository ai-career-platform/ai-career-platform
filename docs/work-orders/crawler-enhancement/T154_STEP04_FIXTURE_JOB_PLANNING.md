# T154 STEP04 — 합성 배치 계획과 T151 작업 메타데이터 연결

## 입력 및 순서
1. `in_fixture_window`로 KST 21:00~08:00 검증. 범위 밖에서는 DB 조회조차 수행하지 않음.
2. 합성 Candidate 입력을 검증하고 `keyword_checkpoints`의 마지막 성공 시각 조회.
3. 기존 3~7일 overlap 함수로 후보 추림, 최대 10건 단위 분할 및 야간/검색어/slot 멱등 키 생성.
4. T151 `KeywordStore.create_job`로 **PENDING 작업 메타데이터만** 생성. 기존 동일 키 요청은 기존 job_id 반환.
5. 한 호출의 작업 생성 도중 실패하면 outer DB transaction을 rollback.

## 현재 의도적 제약
- **Worker 실행/claim 없음**. T64 Dispatcher·Scheduler, Timer 설정·run_events는 변경하지 않음.
- `keyword_jobs`에는 공고 ID 목록이 아니라 idempotency key만 저장된다. 따라서 이 단계만으로 실제 작업 payload 재개가 가능하다고 주장하지 않음. 이후 Fixture Worker 연결 시 payload 영속화가 필요.
- 날짜/검색어/slot 기반 키이므로 같은 날 slot 수가 같아도 후보 ID 목록이 바뀔 수 있다. 기존 작업의 payload를 바꾸지 않으며 기존 job을 재사용. 완전한 데이터 재현성은 payload 계약을 추가한 후 검증.
- T153 스테이징 E2E RETEST 결과 미수신. 데이터 흐름 전체 PASS 판정 금지.
- `0007`은 사용자 제공 T154 STEP03 격리 PostgreSQL 검증 175/175 PASS. 실제 스테이징 적용은 아직 하지 않았음.
- HTTP 요청·Worker 실행·타이머 활성화·스테이징 DB 변경 없음.

## 검증
`python -m unittest crawler.tests.test_t154_fixture_jobs -v`
`python -m unittest discover -s crawler/tests -v`
