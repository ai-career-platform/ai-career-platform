# 야간 키워드 분산 크롤러 설계 (CRAWLER_NIGHT_01)

> 2026-11-12 · 원칙: 기존 T64/T151/T154/T61/#250 구현을 재사용하고 최소한만 바꿉니다. 작게 나누는 목적은 부하 관리와 안정성이며, 접근 제한을 피하려는 것이 아닙니다.

## 1. 요구사항

- 매일 21:00 ~ 익일 08:00 KST 에 6개 키워드를 독립된 작업으로 순차·저속 수집합니다. 키워드: AX, 데이터 분석, 빅데이터, AI 엔지니어, 머신러닝, 딥러닝
- 승인된 실제 JobKorea 데이터만 수집합니다. 신규·변경 공고 위주로 저장합니다.
- 작업별 건수를 DB 에 기록하고, Slack 으로 작업별 결과와 야간 종합을 보냅니다.
- 03:00 Fixture 회귀 스케줄과 Staging 서비스는 그대로 둡니다.

## 2. 기존 구조 조사 (STEP 01 답변)

| 질문 | 답 |
|---|---|
| 1. 하루 1회 예약을 여러 작업으로 확장? | `schedules` 는 `source_id` UNIQUE(`jobkorea`) 라 두 번째 스케줄 행을 만들 수 없습니다. `runs` 도 이 스케줄에 묶여 있습니다. → 야간 작업은 `runs` 가 아니라 T151 `keyword_jobs` 로 관리합니다. |
| 2. 5분 디스패처 타이머 재사용? | 가능합니다. `dispatcher dispatch` 가 daily IDLE 일 때 같은 lock(0) 아래에서 야간 1단계를 실행합니다. 새 타이머·서비스는 없습니다. |
| 3. 키워드별 실행·결과 이력? | `search_keywords`(T151), `keyword_jobs`(상태 머신 PENDING→RUNNING→FETCHED→COMPLETED/FAILED), `keyword_posting_discoveries`, `keyword_checkpoints`(T154) 가 있습니다. **건수(조회/신규/수정/중복/실패)를 담을 곳이 없습니다.** → 0012 로 결과 테이블 추가 |
| 4. 기존 테이블 활용? | 그대로 씁니다: `create_job`(idempotency key), `transition`, `record_discovery`, `KeywordCheckpointStore.mark_completed`. 6개 키워드 중 DB 에 없는 것(AX·빅데이터·머신러닝·딥러닝)은 기존 키워드 관리(감사 기록 포함)로 등록해야 합니다. |
| 5. 목록·상세 처리? | #85 `fetch_pages(list_url=…, limit≤10)` 가 처리합니다. 순서: robots.txt → 검색 목록 1회 → 정규 상세 URL 최대 N건. 요청 간격은 최소 2초(robots crawl-delay 우선), timeout 15초. redirect·401·403·429·CAPTCHA·robots 거부면 즉시 중단, 재시도 없음. 파싱·정규화는 `import_pages` 와 `parse_jobkorea_html` 이 합니다. |
| 6. 신규·수정·중복 판정? | `PostgresPostingStore.upsert` 가 `(source_code, external_posting_id)` 로 판정합니다. 결과는 inserted / payload 비교 updated / unchanged. 한 배치 안의 같은 공고는 `import_pages` 가 duplicates 로 셉니다. |
| 7. Live 승인 조건? | `CRAWLER_LIVE_SCHEDULE_APPROVED=1`, 그리고 T61 `check_collection_permission` 이 ALLOWED 여야 합니다. ALLOWED 조건: 승인자·근거·유효기간, 허용 URL·목적·방법(WEB), 요청 상한, 보존기간, stop_on_block. **현재 T61 은 `/Recruit/GI_Read/<id>` 로 명시된 URL 만 허용하므로, 키워드 검색 URL(`/Search/?stext=…`)은 승인 기록이 있어도 OUT_OF_SCOPE 입니다.** 승인 상태도 HOLD 입니다. |
| 8. Slack 재사용? | #250 의 `webhook_config`/`send`(hooks.slack.com 만, 5초, 재시도 없음, URL 비노출)를 재사용하고 메시지 형식만 추가합니다. |

## 3. 야간 실행 설계

- **창**: T154 `night_slot()` 을 씁니다. 21:00:00 ~ 07:59:59 KST, 21:00~23:59 는 당일, 00:00~07:59 는 전날 밤입니다. **07:45 이후에는 새 작업을 시작하지 않습니다.**
- **페이싱**: 키워드 i(0~5)는 21:00 + i 시간부터 시작할 수 있습니다.
  - 21시 AX, 22시 데이터 분석, 23시 빅데이터, 00시 AI 엔지니어, 01시 머신러닝, 02시 딥러닝
  - 정해진 시간을 놓친 키워드는 다음 poll 부터 순서대로 따라잡습니다. 한 poll(5분)에 1작업만 실행합니다.
- **작업 크기**: 키워드당 검색 목록 1페이지와 상세 최대 5건입니다. 요청은 robots 포함 최대 7건, 작업 마감은 150초(서비스 TimeoutStartSec=180 미만)입니다. 한 밤 최대 요청 = 6 × 7 + 재시도분입니다.
- **03:00~07:45**: 성공한 키워드는 다시 수집하지 않습니다. 실패한 키워드만 아래 재시도 규칙으로 다시 시도합니다(무한 반복 없음).
- **재시도**: 기존 T64 정책을 그대로 씁니다. `TEMPORARY_IO`/`WORKER_TIMEOUT`/`HEARTBEAT_TIMEOUT` 만 재시도하고, 백오프 60·120초, 최대 3회입니다. `WORKER_CRASH` 등 그 밖의 코드는 재시도하지 않습니다.
- **밤 전체 중단**: `RATE_LIMITED`·`ACCESS_FORBIDDEN`·`INVALID_CONTRACT`·`UNAPPROVED_SOURCE` 가 나오면 그 밤의 나머지 작업을 모두 시작하지 않습니다(차단 존중).

## 4. 키워드 작업 모델

| 테이블 | 역할 |
|---|---|
| `keyword_jobs`(기존) | 생명주기. idempotency key `night:<날짜>:<keyword_id>:<시도>` |
| `night_job_results`(0012 신규) | 시도별 결과: RUNNING/SUCCEEDED/PARTIAL/FAILED, 요청 수, 조회/신규/수정/변경없음/중복/실패, 오류 코드, 시작·종료, Slack 통지 시각. `UNIQUE(night_date, keyword_id, attempt)`. RUNNING 은 전역 1행만(부분 unique index) |
| `night_summaries`(0012 신규) | 밤별 종합 알림 1회 보장 (PK night_date) |
| `keyword_posting_discoveries`(기존) | 키워드 ↔ 공고 관계. 같은 공고가 여러 키워드에서 보이면 각각 연결 |
| `keyword_checkpoints`(기존) | 키워드별 마지막 성공 시각 |
| `postings`(기존) | `source_code='jobkorea_live'`. Fixture(`jobkorea`)·imported 와 구분. 삭제 없음 |

상태 매핑
- SUCCEEDED·PARTIAL → `keyword_jobs` COMPLETED, 체크포인트 갱신
- FAILED → `keyword_jobs` FAILED
- 게이트 BLOCKED·창 밖 → 아무 행도 만들지 않습니다(SKIPPED/BLOCKED 는 poll 결과 JSON 으로만 남김)

## 5. 동시 실행 제어

- 디스패처 lock(0) 하나로 03:00 Fixture dispatch, `manual-fixture`, 야간 단계를 직렬화합니다. 야간 단계는 daily dispatch 가 끝나 IDLE 일 때만 실행됩니다.
- DB 에서도 `night_job_results_one_running` 으로 RUNNING 을 1개로 제한하고, 같은 시도의 중복 시작을 막습니다(PK·UNIQUE·idempotency key).
- 배포·kill 로 중간에 끊겼으면 RUNNING 이 10분 넘게 남습니다. 다음 poll 에서 `HEARTBEAT_TIMEOUT` FAILED 로 정리하고, 재시도 규칙에 따라 다시 시도합니다.
- 야간 단계의 예외는 디스패처로 전파되지 않습니다(`{"night":"ERROR"}`). daily 결과와 종료 코드는 바뀌지 않습니다.

## 6. Live 수집 제한 (fail-closed)

1. `CRAWLER_NIGHT_ENABLED=1` 이 아니면 아무것도 하지 않습니다. 기본값 0 입니다.
2. 마이그레이션 0012 가 없으면 `BLOCKED: MIGRATION_REQUIRED` 입니다.
3. 아래가 모두 필요합니다. 어느 하나라도 없으면 `BLOCKED` 이고, **DB 쓰기와 HTTP 는 0건**입니다.
   - `CRAWLER_LIVE_SCHEDULE_APPROVED=1`
   - 서버 private 승인 파일 `CRAWLER_NIGHT_POLICY_FILE`
   - 그 승인 기록에 대한 T61 판정 ALLOWED(목적 `night_keyword_collection`, 요청 상한 ≥ 7)
4. robots 준수, 2초 이상 간격, 차단 시 즉시 중단은 #85 코드를 그대로 씁니다. 프록시·IP 변경·세션 교체는 없습니다.
4-1. `fetch_pages()` 가 요청 전에 모든 URL(검색 목록과 거기서 찾은 상세 각각)을 같은 승인 기록으로 다시 검사합니다. CLI·T64 스케줄·야간 실행기 모두 이 한 곳을 지나므로 게이트를 우회하는 Live 경로가 없습니다(CRAWLER_NIGHT_02).
5. **현재 판정**: T61 승인 HOLD, 그리고 검색 URL 은 T61 범위 밖입니다. 따라서 `LIVE_COLLECTION=BLOCKED`.
   - 해제하려면 PM/T61 이 두 가지를 결정해야 합니다: ① 출처 승인 ② 키워드 검색 페이지를 승인 범위에 넣는 정책(evaluator 확장 포함)
   - 이 PR 은 evaluator 를 바꾸지 않습니다.

## 7. Fixture 분리

| 항목 | 03:00 Fixture | 야간 Live |
|---|---|---|
| 스케줄 | `schedules.jobkorea-daily`(그대로) | 없음(창 + 키워드 페이싱) |
| 이력 | `runs`/`run_events` | `keyword_jobs`/`night_job_results` |
| 데이터 | `source_code='jobkorea'` | `source_code='jobkorea_live'` |
| 실행 | 워커 서브프로세스 | 디스패처 프로세스 안, 150초 마감 |

- 03:00 에는 daily 가 먼저 lock 과 실행권을 가져갑니다. 야간 단계는 daily 가 IDLE 일 때만 돌아가므로 같은 poll 에서 겹치지 않습니다.
- 야간 코드는 `schedules` 를 읽지도 쓰지도 않습니다. 통합 테스트로 확인했습니다.

## 8. Slack

- 작업별: 키워드, Job ID, 모드, 시도, 시작·종료 KST, 요청·조회·신규·수정·중복·실패, 오류 코드. 중복 방지는 `slack_notified_at` 을 먼저 기록하는 방식입니다(실패 시에도 재전송 안 함).
- 종합: 08:00~11:59 KST 첫 poll 에 그 밤 결과가 있으면 1회 보냅니다(`night_summaries` PK). 내용: 작업 수, 성공·부분·실패, 요청·신규·수정·중복·실패 건수 합계, 미처리 키워드, 오류 코드.
- Slack 실패는 작업 상태를 바꾸지 않습니다.

## 9. 장애·복구

| 상황 | 동작 |
|---|---|
| 일시 오류(네트워크·5xx·timeout) | FAILED, 같은 밤 안에서 최대 3회까지 백오프 재시도 |
| 차단(403/429/robots/CAPTCHA/redirect) | FAILED, 그 밤 중단. 다음 밤에 다시 판단 |
| 파싱 실패 일부 | PARTIAL(성공분 저장, 체크포인트 갱신) |
| 전부 파싱 실패 | FAILED `INVALID_CONTRACT` → 사이트 구조 변경 의심으로 그 밤 중단 |
| 프로세스 중단(배포 등) | 10분 뒤 `HEARTBEAT_TIMEOUT` 으로 정리 후 재시도 |
| 0012 미적용 | BLOCKED, 기존 기능 영향 없음 |
| 롤백 | `CRAWLER_NIGHT_ENABLED=0` 이면 즉시 정지. 코드 revert 해도 0012 테이블은 이력으로 남깁니다(삭제는 별도 결정) |
