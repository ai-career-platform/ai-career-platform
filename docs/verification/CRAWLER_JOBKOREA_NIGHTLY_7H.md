# JobKorea 야간 자동 수집·Slack 보고 (AI_CAREER_JOBKOREA_1000_AUTONOMOUS_7H, 2026-11-17)

판정 원칙: 실제로 실행한 것만 PASS. Fixture·Mock·단위 테스트 결과는 실제 수집 실적이 아닙니다.

이번 작업에서 한 외부 접촉:

| 대상 | 내용 |
|---|---|
| JobKorea | 요청 0. 대량 수집 허가가 없음 |
| GCP | 운영 쓰기 0. 08:11 읽기 전용 통계 확인 1회 예정 |
| Slack | TEST 메시지 1건 |

## 1. 구현 (브랜치 `feat/crawler-jobkorea-nightly`)

| 파일 | 내용 |
|---|---|
| `crawler/jobs/nightly.py` | 21:00–08:00 KST 야간 실행 관리. 기존 T61 harvest(`run_harvest`, `LiveSource`)를 덩어리(chunk) 단위로 반복 |
| `scripts/windows/nightly-jobkorea.ps1` | 작업 스케줄러가 실행하는 스크립트. `nightly-task.json` 의 모드 사용(기본 test), 중복 실행 차단 mutex, JSONL 로그. LIVE 야간 뒤 08:01 에 GCP 단계 실행 |
| `scripts/windows/register-nightly-task.ps1` | `AICP-JobKorea-Nightly` 등록·갱신·삭제. 기본은 비활성 |
| `scripts/windows/post-night-gcp.ps1` | 08:00 이후 공식 GCP Sync(dry-run → run → verify). 아래 조건이 모두 있어야 실행하고, 없으면 BLOCKED/NOT_RUN 과 사유를 기록 |
| `crawler/tests/test_nightly.py`, `crawler/tests/local_nightly_pg.py`, `run-crawler-tests.ps1` 의 `pg-nightly` 단계 | 테스트 |

**`nightly.py` 의 동작:**
- **덩어리 반복:** 신규 목표에 도달하거나, 08:00 이 되거나, 신규 공고가 더 없거나, 차단 신호(401/403/429/CAPTCHA/승인 만료)가 오면 멈춥니다.
- **08:00 이후 요청 없음:** 각 덩어리의 deadline 을 08:00 으로 둡니다. 기존 `LiveSource` 가 deadline 이후 요청을 거부합니다.
- **밤 전체 요청 상한:** `night_max_requests`. 승인의 `max_requests` 는 실행 1회 상한이라 밤 전체를 막지 못하므로 따로 둡니다.
- **NEW INSERT 집계:** `harvest_items.outcome='inserted'` 이고, LIVE 실행(HTTP > 0)이며, 실제 postings 행이 있는 것만 셉니다. Fixture, HTTP 0 실행, update, 창 밖, 행이 없는 원장은 제외합니다.
- **Slack 보고:** 시작, 1시간 진행(별도 스레드), 목표 달성, 종료, 비정상 종료, 미실행(차단), GCP 결과.
  - 같은 밤·같은 종류는 1회만 보냅니다(ledger 파일).
  - 측정하지 않은 값은 0 이 아니라 `NOT_RUN`·`UNVERIFIED` 로 표시합니다.
  - 기존 `crawler/notifications/slack.py` 를 재사용합니다: `SLACK_WEBHOOK_URL` → `SLACK_WEBHOOK_RUL` 순서, `hooks.slack.com` 만 허용, URL 비출력.
  - 일시 오류(5xx·네트워크)는 1회만 재시도합니다.
- **LIVE 실행 조건:** 유효한 T61 harvest 승인 파일과 `live_activated` 가 모두 있어야 합니다. 없으면 요청 전에 BLOCKED 입니다.
- **test 모드:** 외부 HTTP 0(egress guard), DB 쓰기 0.

**`post-night-gcp.ps1` 실행 조건:** `gcp_sync=true`, CA 파일, `career_sync` 비밀번호, LIVE run 이 모두 있어야 합니다.
- 일회성 cutover 플래그는 쓰지 않습니다. 첫 cutover 는 별도 승인된 수동 실행입니다.

**웹사이트 단계 (`nightly site-check`):** published 로 이관된 경우에만 실행합니다.
- 공개 API 목록에서 제목·회사가 같은 항목을 찾고, 그 상세 API 의 `source_url` 이 해당 공고의 `GI_Read/<id>` 와 같을 때만 "표시됨"으로 셉니다.
- draft 이관은 `NOT_RUN / DRAFT_NOT_PUBLIC` 입니다.
- 실측: 실제 사이트 API 를 읽기 전용으로 90항목 조회했고 모두 HTTP 200 이었습니다. 대상 공고가 없어 결과는 NOT_RUN 입니다.

## 2. 실측 결과

| 항목 | 결과 | 증거 |
|---|---|---|
| 테스트 전체 (새 일회용 클러스터 5436) | 18단계 실패 0.<br>crawler 576 실행 / 571 PASS / 5 SKIP, backend 21/21.<br>PostgreSQL 102 실행 / 101 PASS / 1 SKIP (`pg-nightly` 3/3 포함). 외부 연결 0 | `C:\dev\crawler-data-int4\logs\tests-20261117-012842` |
| Fixture 1,050건 야간 (일회용 DB) | 400건씩 3덩어리로 1,050건 모두 1회씩 INSERT.<br>두 번째 밤은 0건. LIVE 집계는 +0 | `local_nightly_pg.test_1` |
| 작업 등록 | `AICP-JobKorea-Nightly` 1개.<br>매일 21:00, 11시간 15분 제한, IgnoreNew, StartWhenAvailable, Interactive(TEST).<br>재등록해도 중복 없음. 상태 **Disabled** | `Get-ScheduledTask` |
| 작업 스케줄러 수동 실행 (test 모드) | `LastTaskResult=0`. 로그: TEST·interactive, 외부 요청 0, DB 쓰기 0.<br>창 2026-11-16 21:00–2026-11-17 08:00 을 정확히 계산. 24시간 LIVE 신규 5(승인 B 실측분). 이후 다시 Disabled | `C:\dev\crawler-data\logs\scheduler\nightly-20261117.jsonl` |
| 중복 실행 차단 | 다른 프로세스가 실행 중이면 `SKIPPED / ALREADY_RUNNING` | 같은 로그 |
| main DB 무변경 (test 모드) | runs/items/postings 1/5/47 → 1/5/47 | |
| Slack TEST 발송 | **SENT, HTTP 200**. ledger 와 로그에 URL 없음 | `C:\dev\crawler-data\scheduler\nightly-slack-*.json` |
| GCP 단계 | 지난 밤: `NOT_RUN / NO_LIVE_RUNS`, GCP 쓰기 0.<br>진행 중인 밤: `NOT_RUN / NIGHT_WINDOW_NOT_ENDED` | `C:\dev\crawler-data\logs\gcp-sync\post-night-*.json` |

**테스트로 찾아 고친 결함:**
- harvest 결과의 신규 키가 `new` 인데 `new_found` 로 읽어, 첫 덩어리 뒤 "공급 없음"으로 끝났습니다.
- 다음 덩어리가 2페이지 연속 기존 공고만 보면 키워드를 끝냈습니다. 이제 `known_page_stop = pages` 입니다.
- 테스트가 LIVE 행을 남겨 다른 테스트를 깨뜨렸습니다. 이제 트랜잭션을 롤백합니다.

## 3. 실행되지 않은 것

| 항목 | 상태 | 이유 |
|---|---|---|
| 실제 신규 1,000건 | 0 / 1,000 | JobKorea 대량 수집·저장 허가 없음 (PM 결정: 미승인) |
| 21:00 자동 시작, 08:00 종료 실측 | 미검증 | 작업이 비활성. 7시간 창에 21:00 이 없음. 경계 처리는 단위 테스트로만 검증 |
| GCP 운영 이관 | BLOCKED | CA 파일, `career_sync` 비밀번호, 승인 C 없음 |
| 웹사이트 실공고 표시 | 0건 | 이관 공고 없음. 권한 미확인 공고는 draft 정책 |
| Slack 시작·진행·종료 실발송 | 미실행 | 실제 야간 실행이 없음. 형식과 1회 발송은 단위 테스트로만 검증 |
| 로그오프·재부팅 후 실행 | 미검증 | Interactive 등록. 무인 실행(S4U)은 관리자 셸 필요 |

## 4. 활성화 절차 (PM 승인 후)

1. JobKorea 수집·저장 허가를 확보하고, 그 범위 이하로 T61 harvest 승인 파일을 작성합니다. 파일 위치는 비공개 경로입니다.
2. `C:\dev\crawler-data\scheduler\nightly-task.json` 을 수정합니다:
   ```json
   {"mode":"live","live_activated":true,"policy_file":"<승인 파일>","slack":true,"gcp_sync":false}
   ```
   필요하면 `night_config` 를 지정합니다: `night_max_requests`·`pages`·`chunk_new` 등, 승인 범위 이하.
3. `.\scripts\windows\register-nightly-task.ps1 -Enable`
4. GCP 를 자동 이관하려면, 첫 cutover 를 승인된 수동 실행으로 끝낸 뒤 `"gcp_sync": true` 로 바꿉니다. 그 전에 CA 와 `career_sync` 비밀번호도 있어야 합니다.
5. 다음 날 확인:
   - `Get-ScheduledTaskInfo AICP-JobKorea-Nightly` (LastRunTime·LastTaskResult)
   - `nightly-YYYYMMDD.jsonl`
   - `python -m crawler.jobs.nightly count --hours 24`
   - Slack 메시지
