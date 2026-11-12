# 야간 키워드 분산 크롤러 구현 결과 (CRAWLER_NIGHT_01)

> 2026-11-12 · 판정: **PARTIAL** (CRAWLER_NIGHT_02 갱신)
> - IMPLEMENTED=YES · TESTED=YES(로컬·CI) · STAGING_DEPLOYED=NO · LIVE_VERIFIED=NO(BLOCKED)
> - 끝난 것: 구현, 로컬 단위·PostgreSQL 통합·전체 회귀 PASS
> - BLOCKED: Live 수집. T61 출처 승인이 HOLD 이고, 키워드 검색 URL 이 T61 범위 밖입니다.
> - NOT_EXECUTED: Staging 배포·Live 시험·야간 자동 실행 관찰
> - Fixture 결과를 실데이터 수집 결과로 보고하지 않습니다.

## 1. 변경 파일

| 파일 | 내용 |
|---|---|
| `crawler/jobs/night_crawl.py`(신규) | 창·페이싱·재시도 판단(`plan_next`), T61 게이트(`live_gate`), 작업 실행(`run_job`), poll 진입점(`run_night_step`), 종합 알림 |
| `crawler/storage/migrations/0012_night_keyword_results.sql`(신규) | `night_job_results`, `night_summaries`, `crawler_staging` 권한. Staging 미적용 |
| `crawler/jobs/dispatcher.py` | `dispatch` 가 IDLE 이면 같은 lock(0) 아래에서 `night_step` 실행. 기본은 `DISABLED` |
| `crawler/notifications/slack.py` | 야간 작업·종합 메시지, `notify_night` |
| `poc/staging/automation/compose.release.yaml` | `CRAWLER_NIGHT_ENABLED`(기본 0) 전달 |
| `.github/workflows/crawler-mvp.yml` | 0012 적용, `local_night_integration` 실행 |
| `crawler/tests/test_night_crawl.py`(신규) | 단위 16건 |
| `crawler/tests/local_night_integration.py`(신규) | PostgreSQL 통합 6건 |

재사용(변경 없음)
- `night_slot`, `fetch_pages`, `import_pages`, `PostgresPostingStore.upsert`
- `KeywordStore.create_job/transition/record_discovery`, `KeywordCheckpointStore`
- `retry_at`, `RETRYABLE_CODES/STOP_CODES`, `failure_code`, `check_collection_permission`, #250 Slack 전송

## 2. 구현 중 발견·수정

- **체크포인트 시계 경합**
  - 증상: 작업 `ended_at` 은 DB 시계, 체크포인트 완료 시각은 Python 시계였습니다. Python 이 DB 보다 몇 µs 늦으면 `mark_completed` 가 조용히 거부했습니다(통합 테스트에서 재현).
  - 수정: 작업의 DB `ended_at` 을 완료 시각으로 씁니다.
- **게이트 우회 경로 보완(CRAWLER_NIGHT_02)**: #85 `import_jobkorea_html` 의 Live HTTP 는 T61 게이트를 거치지 않았습니다(CRAWLER_LIVE_TEST_01 §5). 아래 §2.1 로 막았습니다.

### 2.1 Live HTTP 단일 게이트 (CRAWLER_NIGHT_02)

- 모든 Live HTTP 는 `fetch_pages()` 한 곳을 지납니다. 여기서 T61 `check_collection_permission` 을 호출합니다.
  - 검사 대상: 목록 URL·명시 URL 은 요청 전에, **목록에서 찾은 상세 URL 도 각각 요청 전에**
  - 승인 기록과 목적이 없거나 맞지 않으면 `FetchBlocked('UNAPPROVED_SOURCE')`. HTTP 0 건
  - robots.txt 는 준수용 요청으로 예산(`requested_calls`)에만 포함합니다.
- 호출자별 승인 전달
  - CLI: `--policy-file`(서버 private 승인 JSON). 목적 `manual_collection`. 없으면 STOPPED·exit 2·HTTP 0
  - T64 스케줄 워커: 스케줄의 승인 기록(`schedule_approval`). 목적 `scheduled_collection`
  - 야간 실행기: `CRAWLER_NIGHT_POLICY_FILE`. 목적 `night_keyword_collection`
- 실패 코드: `failure_code` 가 `UNAPPROVED_SOURCE` 를 그대로 돌려줍니다. STOP 코드이므로 재시도 없이 그 밤을 중단합니다.
- 영향 없음: `--html` 가져오기, `--list-html`, 합성 Fixture 경로(HTTP 없음)
- 현재 T61 정책상 검색 URL 은 항상 범위 밖입니다. 따라서 `--list-url` Live 와 야간 키워드 Live 는 BLOCKED 입니다.

## 3. 테스트 (로컬, 2026-11-12)

| 범위 | 결과 |
|---|---|
| `test_night_crawl` 단위 | **16/16 PASS** — 20:59/21:00/23:59/00:00/07:59/08:00 경계, 07:45 시작 마감, 시간당 1키워드·지연 따라잡기, RUNNING 중복 방지, 차단 코드로 밤 중단, 백오프 재시도·3회 상한·비재시도 코드, 게이트 단계별 차단(플래그·정책 파일·**완전한 승인 기록이 있어도 검색 URL OUT_OF_SCOPE**), 요청 수 집계·마감, 디스패처 lock·예외 격리, Slack 작업·종합 문구 |
| `test_live_http` 게이트 추가분 | 6건 PASS — 승인 없음·목적 없음·다른 URL·비활성 승인 → 요청 0 / 검색 URL 범위 밖 / **목록에서 찾은 미승인 상세는 요청 안 함(robots+목록 2건에서 중단)** / 승인 URL 정상 수집 / CLI `--policy-file` 없으면 exit 2·요청 0 / 승인 파일 로더 |
| 기존 Live HTTP 테스트 | test_live_http·test_html_import·local_html_pg_integration 은 시험용 승인 기록(해당 URL만 허용)을 넘기도록 수정, 모두 PASS. 목록 동작 시험 2건은 게이트만 대체(게이트는 별도 시험) |
| `local_night_integration`(PostgreSQL 18, 일회용) | **8/8 PASS**, 3회 반복 PASS. 추가 2건(실제 `fetch_pages` + **모의 HTTP 응답**): robots → 검색 목록 → 상세 2건 → 파싱 → 신규 2 → 키워드 연결 2 → Slack 1회, 요청 4건 / 상세에서 429 → FAILED `RATE_LIMITED`, 요청 3건에서 중단 / 승인에 없는 상세 → FAILED `UNAPPROVED_SOURCE`, 요청 2건에서 중단. 기존 6건: 실제 파서·upsert 사용, 게이트만 ALLOWED 로 patch, 네트워크 0 — ① AX 신규 2 → COMPLETED·체크포인트·Slack 1회 ② 같은 시간 재poll 시 작업 없음 ③ 데이터 분석: 변경없음 1·수정 1, 공고 1건이 두 키워드에 연결, 공고 총 2건 ④ 08:05 종합 1회만 ⑤ 03:00 Fixture 스케줄 불변 ⑥ 429 → FAILED `RATE_LIMITED`, 그 밤 중단 ⑦ 상세 1건 파싱 실패 → PARTIAL ⑧ 게이트 BLOCKED·비활성 → DB 쓰기 0, HTTP 0 ⑨ RUNNING 방치 → `HEARTBEAT_TIMEOUT` 정리 후 2회차 성공 ⑩ 디스패처 lock 점유 시 LOCKED |
| 전체 회귀 | `crawler/tests` 단위 전체 OK(5 skip) · `local_t64_integration` 13/13(0002 만 / 0002~0012 모두) · T154·T155·T152 PostgreSQL 27건 OK(1 skip) |
| 권한 | 0002~0012 적용 DB 에서 `crawler_staging` 이 야간 경로에 필요한 15개 권한 모두 보유 |

- 로컬 Windows 에서는 `PYTHONUTF8=1`, `PGCLIENTENCODING=UTF8` 이 필요합니다(기존 테스트·0003 한글 시드). CI(Linux)는 그대로입니다.

## 4. Staging·Live·자동 실행

| 항목 | 상태 |
|---|---|
| Staging 배포 | NOT_EXECUTED. 이 PR 은 독립 승인 리뷰 후 병합 |
| 배포 후 영향 | `CRAWLER_NIGHT_ENABLED` 기본 0 이므로 기존 동작과 같음. 0012 미적용 상태에서 켜도 `MIGRATION_REQUIRED` 로 멈춤 |
| Live 시험 | **BLOCKED** — T61 출처 승인 HOLD, 검색 URL 이 T61 범위 밖, Live 플래그·정책 파일 없음. JobKorea 요청 0 |
| 야간 자동 실행 | NOT_VERIFIED (Live 차단 상태에서는 실행할 작업이 없음) |
| Slack | 단위·통합 테스트만(전송 함수 대체). 실제 전송 없음 |

## 5. 운영 반영 순서 (승인 필요 항목 표시)

1. 이 PR 리뷰·병합 → Auto-CD (동작 변화 없음)
2. **[DB 승인]** Staging 크롤러 DB 에 0012 적용(백업 후)
3. **[키워드 승인]** 기존 키워드 관리로 AX·빅데이터·머신러닝·딥러닝 등록(감사 기록)
4. **[PM/T61 결정]** JobKorea 출처 승인, 키워드 검색 페이지 범위를 T61 정책에 넣을지 결정. evaluator 확장은 별도 PR
5. **[서버 설정]** 서버 private 승인 파일과 컨테이너 마운트(`CRAWLER_NIGHT_POLICY_FILE`), overlay 전달 줄 추가
   - 대상 변수: `CRAWLER_NIGHT_ENABLED`, `CRAWLER_LIVE_SCHEDULE_APPROVED`, `CRAWLER_NIGHT_POLICY_FILE`
   - 서버 overlay 는 수동 관리 사본입니다.
6. 제한 Live 1회 → 첫 야간 관찰(21:00~08:00) → 종합 Slack 확인

## 6. 미완료·후속

- T61 검색 범위 정책 결정과 evaluator 확장(별도 PR)
- 정책 파일 컨테이너 마운트 방식 확정
- `import_jobkorea_html` Live 옵션에 같은 게이트 적용
- `recover()` 류 사후 실패에 대한 알림(현재 작업 알림은 정상 종료 경로만)
