# Staging 수동 Fixture 실행 결과 (CRAWLER_SLACK_01)

> 판정: **미실행(BLOCKED)**. 수동 실행 명령(`manual-fixture`)은 이 PR 의 신규 코드라서, 병합·Auto-CD 배포 전에는 Staging 에서 실행할 수 없습니다.
> Staging DB 의 `next_run_at` 을 과거로 바꾸거나 워커를 직접 실행하는 우회는 하지 않았습니다.

## 1. 실행 상태

| 항목 | 값 |
|---|---|
| 실행 일시 | - (미실행) |
| Run ID | - |
| 모드 | fixture (예정) |
| 상태 | NOT_EXECUTED |
| 조회 / 신규 / 업데이트 / 중복 / 실패 | - |
| Slack 전송 | NOT_SENT |
| Slack 수신 확인 | NOT_VERIFIED |

## 2. 실행 전 기준값 (2026-11-12 18:33 KST, 읽기 전용 조회)

| 항목 | 값 |
|---|---|
| 공고 합계 | 35 |
| Fixture(`jobkorea`) | 2 |
| Imported(`jobkorea_imported`) | 28 |
| Live(`jobkorea_live`) | 5 |
| runs / 실행 중 | 1 / 0 |
| run_events | 3 |
| 마지막 실행 / 성공 | 2026-11-08 15:59:17 KST / 같음 |
| 스케줄 | enabled=true, fixture, 다음 2026-11-13 03:00 KST |
| 타이머 | enabled / active, 최근 30분 IDLE 5회 |

## 3. 실행 후 기대값 (실행 시 이 표와 비교)

| 항목 | 기대 |
|---|---|
| 상태 | SUCCEEDED, mode=fixture, 이벤트 `MANUAL_RUN` → `CLAIMED` → `WORKER_STARTED` → `SUCCEEDED` → `SLACK_NOTIFIED` |
| 건수 | fetched 2, inserted 0, duplicate 2, failed 0 (기존 합성 2건 멱등 처리) |
| 공고 | 합계 35 그대로, Live 5·Imported 28 불변 |
| runs / run_events | 2 / 3 + 5 |
| 다음 예약 | 2026-11-13 03:00 KST 그대로 |
| 외부 HTTP | Slack 1회만. JobKorea 0 |

## 4. 실행 절차 (병합·배포·서버 Webhook 설정 후, 정확히 1회)

```bash
cd /home/kant/ai-career-staging-poc
P="docker compose --project-name ai-career-staging-poc"
curl -s http://127.0.0.1:18080/api/version                       # 병합 SHA 확인
$P exec -T backend python -m crawler.jobs.dispatcher slack-status  # {"configured": true, ...}
$P exec -T backend python -m crawler.jobs.dispatcher manual-fixture
#   기대: {"run_id": "...", "status": "SUCCEEDED", "manual": true, "slack": "SENT", "slack_http_status": 200}
```

- `LOCKED`(타이머 dispatch 와 겹침) 또는 `REFUSED` 이면 워커가 실행되지 않은 것이므로 원인을 확인한 뒤 한 번 더 시도할 수 있습니다.
- `SUCCEEDED` 외 결과면 재실행하지 않고 보고합니다.
- 검증: 기존 `daily_crawler_host_readonly_check.sh`(v2)로 §3 비교, Slack 채널에서 Run ID·건수·KST 시각 대조.
