# 학습용 야간 크롤러 최종 검증 (CRAWLER_NIGHT_12)

> 2026-11-12 22:55 KST · Staging `e92b34d` · 학습용 PoC.
> 판정: 크롤러 기능·Staging 실행 경로·PostgreSQL·Slack 경로 **검증 완료**. 실제 JobKorea 수집은 **BLOCKED**(실제 요청 0 건).

## 1. 구현 완료 범위

| 기능 | 위치 | 근거 |
|---|---|---|
| 21:00~08:00 KST, 한 시간에 키워드 하나, 07:45 이후 시작 금지, 08:00 종합 | `crawler/jobs/night_crawl.py` | E2E trace |
| 5분 Dispatcher 안의 야간 단계, 03:00 Fixture 와 같은 advisory lock | `crawler/jobs/dispatcher.py` | E2E `DAILY_SUCCEEDED`, `LOCKED` |
| 검색 → 상세 ≤5 → 파싱 → 정규화 → `upsert`(insert/update/unchanged) | `import_jobkorea_html.py`, `PostgresPostingStore` | E2E 2·5번 |
| 키워드 관계·체크포인트·작업 이력 | `keyword_jobs`, `keyword_posting_discoveries`, `keyword_checkpoints`, `night_job_results` (마이그레이션 0012) | 격리 DB 조회 |
| T61 게이트: 검색 URL, 발견 상세 URL, 요청 상한 사전 검사 | `crawler/policy/source_approval_gate.py` (#261) | 이미지 내부 probe, CI |
| 403·429·CAPTCHA 중단, 리다이렉트 미추적, Timeout 재시도 ≤3, 비정상 URL 차단 | `_get`/`_fetch_allowed`, `offline_recovery` | E2E 3·4번, `test_live_http` |
| 단일 실행·중단 복구 | 단일 RUNNING 인덱스, `recover_stale` | E2E 6번 |
| Slack 작업별·종합 알림, DB 기준 중복 방지 | `crawler/notifications/slack.py` | E2E 7번, 4절 |

## 2. E2E Evidence (Staging 호스트, 배포 이미지)

`crawler/tests/staging_night_e2e.py` 를 #258 절차 그대로 실행했습니다. 일회용 `postgres:18.1` 를 `--network none` 으로 띄우고, 실제 배포 backend 이미지를 사용했습니다.

| 회차 | 이미지 | T61 경로 | 결과 |
|---|---|---|---|
| CRAWLER_NIGHT_07 `e2e-5abde009` | `d5dd380` (`sha256:6109a92b…`) | 검색 URL 은 테스트 패치로 통과 | 7/7 |
| **CRAWLER_NIGHT_12 `e2e-97df6e16`** | **`e92b34d` (`sha256:77435f81…`)** | **실제 `live_gate` 와 실제 게이트**(테스트 전용 메모리 승인: 검색 URL 6개, `max_discovered_details=5`) | **7/7** |

`e2e-97df6e16` 의 격리 DB:
- `night_job_results` 16행, `night_summaries` 1행
- `keyword_checkpoints` 6, `keyword_posting_discoveries` 14
- postings `jobkorea_live` 13(합성), runs 1(Fixture SUCCEEDED)
- 모의 HTTP 24회(하룻밤 6키워드)
- 다음 날 같은 공고: inserted 0, updated 1, unchanged 1
- 403 중단 전 2회, 429 중단 전 3회
- 실행 후 컨테이너는 삭제했습니다(잔여 0)

이 결과는 **합성 데이터와 모의 HTTP** 입니다. 실제 수집 결과가 아닙니다.

CI(`crawler-mvp`, run 43225852924)에서도 같은 E2E 7/7, `local_night_integration` 8/8 이 통과했습니다. 후자는 실제 게이트로 AX 검색 → 발견 상세 2건 → INSERT → 키워드 관계 → 체크포인트를 실행합니다.

## 3. Staging 배포 상태

| 항목 | 값 |
|---|---|
| main / Staging | `e92b34d` / `e92b34d` (Publish run 43228344848 → Auto-CD deploy-end PASS 13:37:21Z) |
| 이미지 내용 | `/app` 안 T61·importer·scheduler·night_crawl 파일 해시가 git `e92b34d` 와 일치 |
| 컨테이너 | backend·frontend·db healthy (db PostgreSQL 18.1) |
| Dispatcher | 5분 주기, `IDLE` / `night=DISABLED` / `external_requests=0` |
| Auto-CD | 1분 주기, F-07 서버 반영 완료([결과](CRAWLER_NIGHT_12_AUTO_CD_F07_RESULT.md)) |

## 4. PostgreSQL 검증

운영 DB 는 읽기 전용으로만 조회했습니다. E2E 전후 비교 결과 `OPS_DB_UNCHANGED` 입니다.

| 항목 | 값 |
|---|---|
| postings | fixture `jobkorea` 2 · `jobkorea_imported` 28 · `jobkorea_live` 5 (= 35, 기존 그대로) |
| runs / run_events | 2 / 8 |
| night_job_results | 0 |
| keyword_jobs / keyword_checkpoints | 14 / 2 |
| 야간 키워드 | 6개 enabled |
| 마이그레이션 0012 | 적용됨 (`night_job_results`, `night_summaries`) |
| 03:00 Fixture | enabled / fixture / 03:00, next_run 2026-11-13 03:00 KST |

## 5. Slack

| 경로 | 판정 | 근거 |
|---|---|---|
| Fixture 실행 알림 (#250 `notify_run`) | **VERIFIED** | 수동 Fixture run `061c7bae…` 알림 HTTP 200. 채널 수신은 PM 이 확인 |
| 야간 작업·종합 메시지 생성 (`notify_night`) | MOCK_VERIFIED | E2E 7번: 라벨, 건수와 DB 일치, 중복 0 |
| 야간 종합 형식의 실제 Webhook 전송 | **ACCEPTED (HTTP 200)** | 2026-11-12 22:54 KST, backend 컨테이너에서 기존 `notify_night('summary')` 를 1회 호출. 메시지 앞에 `[STAGING TEST] CRAWLER_NIGHT_12 Slack path check - synthetic summary, no collection ran` 표시. 실제 작업 0 건, 미처리 키워드 6개로 표시됨. **채널 수신은 확인하지 않음** |

## 6. 실제 Live 수집

**BLOCKED.** 실제 JobKorea 요청 0 건, 승인 기록 0 건입니다.
- 환경변수: `CRAWLER_NIGHT_ENABLED`·`CRAWLER_LIVE_SCHEDULE_APPROVED`·`CRAWLER_NIGHT_POLICY_FILE` UNSET
- T61 HOLD
- robots.txt 는 현재 User-Agent 에 `/Search/`·`GI_Read` 를 허용합니다(NIGHT_10)
- 회원 약관 제18조④·제19조④ 는 사전동의 없는 복제·제공을 제한하며, 비회원 적용 범위는 미확정입니다(NIGHT_11, `T61_STEP06`)

코드는 준비되어 있습니다. 승인 기록과 서버 설정만 있으면 새 코드 없이 1회 실행할 수 있습니다(NIGHT_11 보고).

## 7. 완료·미완료

| 항목 | 상태 |
|---|---|
| 야간 크롤러 코드, T61 게이트, Staging E2E, PostgreSQL 경로 | 완료 |
| Slack: Fixture VERIFIED, 야간 MOCK_VERIFIED + 실제 Webhook ACCEPTED | 완료(야간 채널 수신은 미확인) |
| Auto-CD F-07 서버 반영 | 완료 |
| 실제 JobKorea 수집 | **미완료(BLOCKED)** |
| 03:00 Fixture 첫 예약 실행(2026-11-13) | 실행 후 확인 필요 |
