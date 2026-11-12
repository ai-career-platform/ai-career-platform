# 야간 크롤러 Slack·안전성 결과 (CRAWLER_NIGHT_04)

> 2026-11-12 · Slack 판정: **MOCK_VERIFIED**. 응답을 가로채는 sender 로 실제 메시지 생성·전송 경로를 확인했습니다. 실제 채널 전송과 수신은 하지 않았습니다.
> 안전성: Staging 운영 데이터·스케줄·타이머·환경변수 변화 없음. 실제 JobKorea 요청 0 건.

## 1. 개별 작업 알림

- 경로: `run_night_step` → DB 결과 기록 → `slack_notified_at` 선점 → `notify_night('job')` → #250 `send` 형식
- E2E 에서 작업 15건(성공·실패 포함, 중단 정리분 제외)에 대해 각 1건 생성. 모든 메시지 앞에 `[STAGING E2E TEST] run=e2e-5fbb2245`
- 예시(합성)

```text
[STAGING E2E TEST] run=e2e-5fbb2245
:white_check_mark: *AI Career Platform night crawl SUCCEEDED* (Staging)
Keyword: AX · Mode: LIVE · Attempt 1
Job ID: `c913f94e-63fd-4766-a645-b3c12c688348`
Start: 2026-11-12 20:22:56 KST · End: 2026-11-12 20:22:56 KST
Requests 4 · Fetched 2 · Inserted 2 · Updated 0 · Duplicate/unchanged 0 · Failed 0
```

- 포함 항목: 키워드, Job ID, 상태, 시도, 시작·종료 KST, 요청·조회·신규·수정·중복(변경없음)·실패, 오류 코드(실패 시)
- `Mode: LIVE` 는 저장 모드(`jobkorea_live`) 표기입니다. E2E 는 모의 HTTP 이므로 라벨로 구분했습니다.

## 2. 야간 종합 알림

- 가상 08:00 첫 poll 에서 1회 생성. 08:05·08:10 에는 재생성 없음(`night_summaries` PK)

```text
[STAGING E2E TEST] run=e2e-5fbb2245
:crescent_moon: *AI Career Platform night crawl summary* (Staging) · 2031-04-05 21:00 → 08:00 KST
Jobs 6 · Succeeded 6 · Partial 0 · Failed 0
Requests 24 · Inserted 11 · Updated 0 · Duplicate/unchanged 1 · Failed items 0
Unprocessed keywords: none
```

## 3. 전송·수신 판정

| 항목 | 결과 |
|---|---|
| HTTP 응답 | 모의 sender 200 |
| 실제 Slack 채널 | 전송 안 함 |
| 판정 | `SLACK_DELIVERY=MOCK_VERIFIED` |
| 중복 방지 | (종류, 밤, Job ID) 키 중복 0. 작업 알림은 `slack_notified_at`, 종합은 `night_summaries` 로 DB 에서 1회 보장 |
| 비밀값 | 메시지·증빙에 Webhook 없음(가짜 URL 문자열도 미노출 확인) |

- 실제 채널 검증이 필요하면, Staging 배포 후 격리 E2E 결과로 `[STAGING E2E TEST]` 메시지 1건을 보내 채널에서 확인합니다. 그 뒤 `VERIFIED` 로 갱신합니다.

## 4. 기존 데이터·스케줄·타이머 보존 (Staging, 읽기 전용, 20:20 KST)

이번 작업에서 Staging 에 대한 쓰기는 0 건입니다. 아래 값은 CRAWLER_NIGHT_03 종료 시점(19:55)과 같습니다.

| 항목 | 값 |
|---|---|
| 공고 | 35 (fixture 2 · imported 28 · live 5) |
| runs / run_events | 2 / 8 |
| keyword_jobs / night_job_results | 14 / 0 |
| 03:00 Fixture | enabled, fixture, Asia/Seoul 03:00, 다음 2026-11-13 03:00 KST |
| 디스패처 타이머 | enabled/active. 최근 poll `IDLE`, `external_requests: 0`, `night: DISABLED` |
| Auto-CD 타이머 | enabled/active. F-07 로 `HOLD: PUBLISH_NOT_SUCCESS` (§E2E 결과 §1) |
| `CRAWLER_NIGHT_ENABLED` / `CRAWLER_LIVE_SCHEDULE_APPROVED` | 미설정 / 미설정 |
| Slack 설정 | configured=true, 충돌 없음 |
| 컨테이너 | backend·frontend·db healthy |
| Live HTTP | 0 |

증빙: `evidence/night04/n04_base_out.txt`, `n04_deploy_out.txt`, `e2e_local_run.json`(호스트 주소·비밀값 없음)
