# Staging 수동 Fixture 실행 결과 (CRAWLER_SLACK_03)

> 판정: **수동 실행 PASS, DB 검증 PASS, Slack 전송 ACCEPTED(HTTP 200)**.
> - Slack 채널에서 실제 메시지를 직접 확인하는 일은 이 작업 환경에서 할 수 없어 **VERIFIED 가 아닙니다.** 채널 확인은 사용자 몫입니다.
> - 03:00 KST 예약 실행의 자동 알림은 아직 실행 전이라 NOT_VERIFIED 입니다.

## 1. 배포

| 항목 | 값 |
|---|---|
| PR | #250 병합 `2b19fd0a4b252e5272036f4039d56e924502d5a4` |
| 병합 리뷰 | 승인 리뷰 0건. 저장소 bypass 권한 계정으로 병합됨(이 작업이 병합한 것은 아님) |
| main CI | CI · Crawler MVP success |
| 게시 run | `43194768990` success |
| Staging 배포 | 09:51Z backend·frontend 재생성. `deploy-start` → `deploy-end`, deploy 서비스 Result=success |
| `/api/version` | `2b19fd0a…` (09:51:54Z 확인) |
| 컨테이너 | backend·db·frontend healthy |
| backend Slack 설정 | `slack-status` → `{"configured": true, "source": "SLACK_WEBHOOK_URL", "conflict": false}` (값 미출력) |

## 2. 실행 직전 상태 (새 기준, 2026-11-12 18:52:08 KST)

| 항목 | 값 |
|---|---|
| 스케줄 | `jobkorea-daily` enabled=true, mode=fixture, 대상 URL 0 |
| 다음 예약 / 마지막 실행 | 2026-11-13 03:00:00 KST / 11-08 15:59:17 |
| 타이머 | enabled / active, 직전 확인 IDLE |
| Live 승인 환경변수 | 미설정 |
| 실행 중 run | 0 |
| 공고 | 합계 35 = fixture 2 · imported 28 · live 5 |
| runs / run_events | 1 / 3 |

## 3. 실행 (정확히 1회)

```bash
docker compose --project-name ai-career-staging-poc exec -T backend python -m crawler.jobs.dispatcher manual-fixture
# 2026-11-12 18:52:55 KST 시작, exit=0
{"run_id": "061c7bae-0e2a-4dd7-8766-9c4a362b3711", "status": "SUCCEEDED", "worker_exit": 0, "manual": true, "slack": "SENT", "slack_http_status": 200}
```

- `next_run_at` 조작, 워커 직접 실행, 재실행은 하지 않았습니다.

## 4. DB 검증 (읽기 전용 조회)

| 항목 | 기대 | 실제 | 판정 |
|---|---|---|---|
| Run ID | - | `061c7bae-0e2a-4dd7-8766-9c4a362b3711` | - |
| 상태 / 모드 | SUCCEEDED / fixture | SUCCEEDED / fixture | PASS |
| 시작·종료(KST) | - | 18:52:55 / 18:52:55 | - |
| fetched / inserted / updated | 2 / 0 / 0 | 2 / 0 / 0 | PASS |
| duplicate·unchanged / failed | 2 / 0 | 2 / 0 | PASS |
| error_code / retry_at | 없음 | 없음 | PASS |
| 이벤트 | MANUAL_RUN → CLAIMED → WORKER_STARTED → SUCCEEDED → SLACK_NOTIFIED | 동일 5건(event_id 4~8) | PASS |
| 공고 | 35 (2/28/5), 저장 시각 불변 | 35 (2/28/5), 저장 시각 불변 | PASS |
| runs / run_events | 2 / 8 | 2 / 8 | PASS |
| 다음 예약 | 2026-11-13 03:00 KST | 2026-11-13 03:00:00 KST, last_run_at 11-08 그대로 | PASS |
| 실행 후 타이머 | IDLE, 추가 알림 없음 | 09:54:50Z IDLE, SLACK_* 이벤트 1건 유지 | PASS |

- `runs.trigger` 는 `scheduled` 로 저장됩니다. 0002 CHECK 제약 때문이며, 수동 실행 구분은 `MANUAL_RUN` 이벤트로 합니다(구현 문서 §4).
- 외부 HTTP: Fixture 워커는 HTTP 0. 외부 요청은 Slack Webhook 1회뿐입니다.

## 5. Slack

| 항목 | 결과 |
|---|---|
| 요청 | 1회 (`SLACK_NOTIFIED` 1건) |
| HTTP | 200 |
| 판정 | **ACCEPTED** (채널 직접 확인 전) |
| Secret | 명령 출력·backend 로그(10분)에 Webhook 0건 |

채널에 와야 하는 메시지(DB 값으로 생성):

```text
:white_check_mark: *AI Career Platform crawler SUCCEEDED* (Staging)
Trigger: MANUAL · Mode: FIXTURE
Run ID: `061c7bae-0e2a-4dd7-8766-9c4a362b3711`
Start: 2026-11-12 18:52:55 KST · End: 2026-11-12 18:52:55 KST
Fetched 2 · Inserted 0 · Updated 0 · Duplicate/unchanged 2 · Failed 0
```

채널에서 Run ID·건수·KST 시각이 위와 같으면 `SLACK_DELIVERY=VERIFIED` 로 바꿉니다.

## 6. 자동 실행

- 타이머: enabled / active. 5분마다 IDLE 입니다.
- 다음 예약: 2026-11-13 03:00 KST. 같은 디스패처 코드(#250)가 배포되어 있어 예약 실행도 같은 Slack 알림을 보냅니다.
- 예약 실행이 실제로 일어나기 전이라 **DAILY_SLACK_NOTIFICATION=NOT_VERIFIED** 입니다.
- Live 수집 HOLD: 승인 환경변수 미설정, 대상 URL 0.

## 7. 증빙

`evidence/slack03/` 에 실행 전·실행·실행 후 출력을 남겼습니다. 호스트 주소와 Webhook 은 들어 있지 않습니다.
