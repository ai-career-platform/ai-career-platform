# T154 STEP02 — 체크포인트와 실패 재개 결정 (Fixture)

## 구현
- `0007_keyword_checkpoints.sql`: 크롤러 학습 DB 전용 신규 테이블 1개, 스키마 변경/자동 적용 금지.
- `KeywordCheckpointStore.read / mark_completed`: T151 `keyword_jobs.status='COMPLETED'` 및 `ended_at` 확인 후에만 성공 체크포인트를 원자적으로 기록. 이전 시점으로 되돌리지 않음. 기존 job과 FK 연결 유지.
- `select_incremental_candidates`: 호출자가 제공한 합성 공고 ID/관찰 시각을 기준으로 성공 체크포인트 이후 **3~7일 겹침 기간** 후보만 추려 내림차순 정렬·중복 제거. 신규/수정 정보 없는 실제 사이트를 추측하지 않음.
- `retry_fixture_decision`: 기존 T64의 bounded retry 정책 재사용. 403/429 등 중단 코드는 자동 재개하지 않음. 이 함수는 판단만 반환하고 Worker/Timer를 실행하지 않음.
- `plan_fixture_batches`는 기존 STEP01 그대로 유지; 위 후보 선별 결과를 넘겨 배치를 만들 수 있다.

## 주의 / 상태
- 실 PostgreSQL에 0007 **미적용**; Codex 격리 DB 통합 검증 필요.
- 실제 작업 Claim, 재시도 실행, 체크포인트 갱신 연결은 추후 Fixture E2E 단계.
- 실 외부 HTTP 0, Live HOLD, 스테이징 Scheduler enabled=false / mode=fixture, Timer disabled.
- T153 PR #103 수정 코드의 **실제 스테이징 RETEST 결과는 아직 미수신**. T153 완료로 기록하지 않는다.

## 테스트
`python -m unittest crawler.tests.test_t154_incremental_checkpoint -v`
`python -m unittest discover -s crawler/tests -v`
