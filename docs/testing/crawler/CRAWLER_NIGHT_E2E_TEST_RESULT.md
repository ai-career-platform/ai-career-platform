# 야간 분산 크롤러 E2E 결과 (CRAWLER_NIGHT_04)

> 2026-11-12 · 판정: **PARTIAL**
> - E2E 하네스(#257) 구현 완료. 일회용 PostgreSQL 18 에서 7/7 PASS, 3회 연속, CI 포함
> - **Staging 실행은 NOT_EXECUTED**
>   - 최신 main 이 Staging 에 배포되지 않았습니다. Auto-CD 결함 F-07 로 HOLD 상태입니다(§1).
>   - 그래서 지시("정상 배포 전에 야간 실행 테스트를 시작하지 않는다")에 따라 Staging 에서는 실행하지 않았습니다.
> - 모든 데이터는 **합성**입니다. JobKorea HTTP 는 모의 응답으로만 처리했고 실제 요청은 0 건입니다. 실데이터 수집 결과가 아닙니다.

## 1. Staging 배포 상태 (STEP 01, 읽기 전용)

| 항목 | 결과 (2026-11-12 20:20 KST) |
|---|---|
| main | `8121bd1` (#255). #254 `4d8439b` 포함 |
| Staging `/api/version` | `b1e6ad7` (#253) — **최신 main 아님** |
| Auto-CD | 게시 run `43205545061`(8121bd1) success. 하지만 배포기가 매분 `HOLD: PUBLISH_NOT_SUCCESS` |
| 컨테이너 | backend·frontend·db healthy |
| 0012 | 적용됨(CRAWLER_NIGHT_03) |
| 야간 키워드 | 6/6 활성 |
| 03:00 Fixture | enabled, fixture, Asia/Seoul 03:00, 다음 2026-11-13 03:00 KST |
| Slack | configured=true |

**F-07 원인**
1. #254·#255 가 연달아 병합되었습니다.
2. 오래된 커밋 `4d8439b` 의 CI 가 더 늦게(11:01:53Z) 끝났습니다.
3. 그 CI 가 띄운 게시 run `43205558880` 은 workflow 의 `head_sha == github.sha` 조건에 따라 skipped 되었습니다. 이것은 정상입니다.
4. 그런데 배포기 `candidate()` 는 최신 run 1개(`per_page=1`)만 봅니다. 최신 run 이 skipped 라서 보류되었습니다.

조치
- **PR #256**: skipped run 만 건너뛰고, 실패·진행 중 run 은 계속 차단합니다. 테스트 45건 OK.
- 서버 `automation/deploy.py` 는 수동 관리 사본이므로, 병합 후 운영자 교체가 필요합니다.
- 교체 전이라도 다음 merge 의 게시 run 이 최신이 되면 배포가 재개됩니다.
- 배포 재실행·강제 재시작은 하지 않았습니다.

## 2. 실행 방법 (STEP 02)

| 우선순위 | 재사용 | 결과 |
|---|---|---|
| 1 | 기존 야간 PostgreSQL 통합 테스트(`local_night_integration`, 8건) | 개별 동작은 검증하지만 하룻밤 전체 흐름은 없음 |
| 2 | 기존 Fixture Worker(`dispatch`) | 03:00 공존 시험에 그대로 사용 |
| 3 | 기존 모의 HTTP(`_get` 대체) | 그대로 사용 |
| 4 | Staging 전용 진입점 | 없음 → **최소 추가: `crawler/tests/staging_night_e2e.py`(#257)**. 테스트 코드만 추가하고 운영 코드는 바꾸지 않음 |

하네스 원칙
- `CRAWLER_NIGHT_E2E=1` 일 때만 실행됩니다.
- 운영 DB 를 가리키면 시작하지 않습니다: `CRAWLER_DB_MODE=staging` 이거나 스케줄이 활성인 경우.
- 시계는 주입합니다(2031년 이후의 가상 밤). 서버 시계와 타이머는 바꾸지 않습니다.
- 상세 URL 은 **실제 T61 게이트**로 검사합니다(시험용 승인 기록에 해당 URL 만 넣음). 검색 페이지만 하네스에서 통과시킵니다. 현재 T61 범위로는 표현할 수 없기 때문이며, 운영 코드는 바꾸지 않았습니다.
- 결과 행은 격리 DB 에 그대로 남기고, JSON 요약을 씁니다.

**Staging 실행 절차** (배포 완료 후, 운영 DB 와 분리)

```bash
cd /home/kant/ai-career-staging-poc
IMG=$(docker compose --project-name ai-career-staging-poc images -q backend)   # 배포된 backend 이미지
# 1) 격리 PostgreSQL: 포트 공개 없음, 별도 네트워크, 일회용
docker run -d --name aicp-night-e2e-pg --network none -e POSTGRES_HOST_AUTH_METHOD=trust \
  -e POSTGRES_DB=ai_career_crawler_training postgres:18.1
docker exec aicp-night-e2e-pg sh -c 'until pg_isready -U postgres; do sleep 1; done'
docker exec aicp-night-e2e-pg psql -U postgres -c "CREATE ROLE crawler_student LOGIN" -c "CREATE ROLE crawler_staging LOGIN" \
  -c "ALTER DATABASE ai_career_crawler_training OWNER TO crawler_student"
# 2) 같은 이미지의 스키마·마이그레이션 0002~0012 적용
for f in local_training_schema.sql migrations/00{02,03,04,05,06,07,08,09,10,11,12}_*.sql; do
  docker run --rm --entrypoint sh "$IMG" -c "cat /app/crawler/storage/$f" |
    docker exec -i aicp-night-e2e-pg psql -U crawler_student -d ai_career_crawler_training -v ON_ERROR_STOP=1 -q -f -; done
# 3) 하네스: 격리 PG 의 네트워크 namespace 안에서만 실행(외부 네트워크 없음)
docker run --rm --network container:aicp-night-e2e-pg -e CRAWLER_DB_MODE=local -e CRAWLER_NIGHT_E2E=1 \
  -e CRAWLER_LOCAL_DATABASE_URL=postgresql://crawler_student@127.0.0.1/ai_career_crawler_training \
  -e CRAWLER_NIGHT_E2E_OUT=/tmp/e2e.json "$IMG" python -m unittest crawler.tests.staging_night_e2e -v
# 4) 증빙 조회 후 정리
docker exec aicp-night-e2e-pg psql -U postgres -d ai_career_crawler_training -c "SELECT night_date,keyword_id,attempt,outcome,error_code,inserted,updated,unchanged,failed FROM crawler_training.night_job_results ORDER BY 1,started_at"
docker rm -f aicp-night-e2e-pg
```

- `--network none` 인 격리 PG 의 네트워크를 공유합니다. 따라서 하네스는 **외부 네트워크에 접근할 수 없습니다**. 실제 HTTP 가 구조적으로 불가능합니다.
- 운영 `ai-career-staging-poc` 의 db·backend 컨테이너, 운영 크롤러 DB, 스케줄, 타이머는 건드리지 않습니다.

## 3. 야간 시나리오 결과 (로컬 일회용 PostgreSQL 18, 실행 ID `e2e-5fbb2245`)

**가상 밤 2031-04-05 의 poll trace** (5분 간격, 20:50 ~ 08:10)

| 가상 시각 | 결과 |
|---|---|
| 20:50, 20:55 | `IDLE/OUTSIDE_WINDOW` (21:00 이전 시작 없음) |
| 21:00 | AX `SUCCEEDED` |
| 21:05 ~ 21:55 | `IDLE/NOTHING_DUE` (한 시간에 한 키워드) |
| 22:00 / 23:00 / 00:00 / 01:00 / 02:00 | 데이터 분석 / 빅데이터 / AI 엔지니어 / 머신러닝 / 딥러닝 `SUCCEEDED` |
| 03:00 | daily Fixture `DAILY_SUCCEEDED`. 같은 lock 이므로 이 poll 에서 야간 단계는 실행하지 않음 |
| 03:05 ~ 07:45 | `IDLE/NOTHING_DUE` (재수집·추가 작업 없음) |
| 07:50, 07:55 | `IDLE/START_CUTOFF` |
| 08:00 | `SUMMARY_SENT` (1회) |
| 08:05, 08:10 | `IDLE/OUTSIDE_WINDOW` (종합 재전송 없음) |

- 자정 이후(00:00~02:00) 작업도 같은 `night_date=2031-04-05` 로 집계되었습니다.
- RUNNING 은 동시에 1건만 있었고, 시도는 모두 1회였습니다.
- 모의 HTTP 는 24회입니다(키워드당 robots + 목록 + 상세 2).

**키워드별 DB 결과** (`night_job_results`, 합성 공고)

| 밤 | 키워드 | 시도 | 결과 | 오류 코드 | 요청 | 조회 | 신규 | 수정 | 변경없음 | 실패 |
|---|---|---|---|---|---|---|---|---|---|---|
| 04-05 | AX | 1 | SUCCEEDED | - | 4 | 2 | 2 | 0 | 0 | 0 |
| 04-05 | 데이터 분석 | 1 | SUCCEEDED | - | 4 | 2 | 1 | 0 | 1 | 0 |
| 04-05 | 빅데이터 | 1 | SUCCEEDED | - | 4 | 2 | 2 | 0 | 0 | 0 |
| 04-05 | AI 엔지니어 | 1 | SUCCEEDED | - | 4 | 2 | 2 | 0 | 0 | 0 |
| 04-05 | 머신러닝 | 1 | SUCCEEDED | - | 4 | 2 | 2 | 0 | 0 | 0 |
| 04-05 | 딥러닝 | 1 | SUCCEEDED | - | 4 | 2 | 2 | 0 | 0 | 0 |
| 04-06 | AX | 1 | SUCCEEDED | - | 4 | 2 | 0 | 1 | 1 | 0 |
| 04-07 | AX | 1 | FAILED | ACCESS_FORBIDDEN | 3 | 0 | 0 | 0 | 0 | 0 |
| 04-08 | AX | 1 | FAILED | RATE_LIMITED | 3 | 0 | 0 | 0 | 0 | 0 |
| 04-09 | AX | 1·2·3 | FAILED | WORKER_TIMEOUT ×3 | 3 each | 0 | 0 | 0 | 0 | 0 |
| 04-10 | AX | 1 | FAILED | INVALID_CONTRACT (파싱) | 4 | 2 | 0 | 0 | 0 | 2 |
| 04-11 | AX | 1 | FAILED | INVALID_CONTRACT (DB 저장) | 4 | 2 | 0 | 0 | 0 | 2 |
| 04-12 | AX | 1 → 2 | FAILED → SUCCEEDED | HEARTBEAT_TIMEOUT → - | 0 / 4 | - / 2 | - / 2 | 0 | 0 | 0 |

- **F-08 (이번에 발견·수정, #257)**
  - 증상: 첫 pull 에서 실패하면 요청 수를 2 로 기록했습니다. 그래서 상세 첫 건에서 429 가 나면(실제 3회) 적게 기록되었습니다.
  - 수정: 첫 pull 실패 시 상한 3 으로 셉니다. 따라서 403(목록, 실제 2)과 timeout(실제 2)은 1 많게 기록됩니다.
  - 요청 수는 예산을 지키기 위한 값이라 적게 세지 않는 쪽을 택했습니다. E2E 가 "기록 ≥ 실제 모의 호출" 을 검증합니다.
- DB 의 `started_at` 은 실제 시계로 기록됩니다(운영과 같음). 가상 시각은 위 trace 로 검증했습니다.

## 4. 파싱·저장·중복·수정 (STEP 04)

| 항목 | 검증 |
|---|---|
| 실제 파서 | JobKorea 상세 HTML fixture(JSON-LD)를 `parse_jobkorea_html` 로 파싱하고 정규화 |
| 신규 INSERT | 첫 밤 신규 11 (`jobkorea_live`, 합성 ID) |
| 중복 INSERT 방지 | 키워드 간 같은 공고 → `unchanged` 1, 공고는 1행. 다음 밤 재수집 → 총 11행 유지 |
| 수정 UPDATE | 제목을 바꾼 공고 → `updated` 1 |
| 키워드 관계 | 같은 공고에 키워드 2개 연결(`keyword_posting_discoveries`) |
| 체크포인트 | 6 키워드 생성. 다음 밤 AX `last_success_at` 증가 |
| 실패 코드 | 고정 코드만 기록. DB 예외 문구(`secret`)는 결과·DB 에 나타나지 않음 |

## 5. 실패·복구 (STEP 05)

| 시나리오 | 결과 |
|---|---|
| 403 (목록) | FAILED `ACCESS_FORBIDDEN`. 요청 2회 후 중단, 그 밤 `NIGHT_HALTED` |
| 429 (상세) | FAILED `RATE_LIMITED`. 3번째 요청에서 중단, `NIGHT_HALTED` |
| Timeout | `WORKER_TIMEOUT` 3회 → 4번째 시작 없음(`NOTHING_DUE`) |
| 파싱 실패 | FAILED `INVALID_CONTRACT`, 실패 2 |
| DB 저장 실패 | FAILED, 실패 2, 신규 0, 예외 문구 미노출 |
| 중복 실행 | 디스패처 lock 점유 → `LOCKED`. 같은 시도 두 번째 시작 → 거부. RUNNING 중 → `JOB_RUNNING` |
| Worker 중단 | 방치된 RUNNING → 10분 뒤 `HEARTBEAT_TIMEOUT` → 시도 2 SUCCEEDED |
| 재시도 상한 | 3회(기존 T64 정책). 백오프 60·120초 자체는 단위 테스트(`test_night_crawl`)로 검증. E2E 에서는 실제 종료 시각과 가상 시계가 달라 백오프 대기를 관찰하지 못함 |

## 6. 테스트 목록

| 테스트 | 위치 | 결과 |
|---|---|---|
| E2E 7건 (`staging_night_e2e`) | 로컬 일회용 PG ×3(F-08 수정 전·후 각각) · CI | PASS |
| 하네스 뒤 회귀(T64 13 · 야간 통합 8 · crawler 단위 전체) | 같은 로컬 DB | PASS |
| 배포기 45건 (F-07 포함) | 로컬 · CI(#256) | PASS |
| Staging 격리 PG 실행 | Staging | **NOT_EXECUTED** (배포 HOLD) |
| 실제 Slack 채널 수신 | - | NOT_EXECUTED (모의 수신만) |

## 7. 남은 일

1. #256(F-07)·#257(E2E 하네스·F-08) 독립 리뷰·병합 → 게시 run 이 최신이 되어 배포 재개(또는 서버 deploy.py 교체)
2. Staging 에서 §2 절차로 격리 PG E2E 1회 → 이 문서 갱신
3. (선택) `[STAGING E2E TEST]` 실제 Slack 1건 → 채널 확인 후 VERIFIED
