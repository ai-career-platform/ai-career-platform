# 크롤러 실행 결과 Slack 알림 · 수동 Fixture 실행 (CRAWLER_SLACK_01)

> 2026-11-12 · 대상: Staging 데일리 크롤러(T64 디스패처)
> 원칙: 기존 T64 디스패처·워커·잠금·systemd 타이머 재사용. 새 스케줄러·타이머·테이블·Migration 없음. Live 수집은 HOLD.

## 1. 변경 코드

| 파일 | 변경 |
|---|---|
| `crawler/notifications/slack.py` (신규) | Webhook 설정 해석, 메시지 생성, 1회 전송, `run_events` 기반 중복 방지. 표준 라이브러리만 사용 |
| `crawler/jobs/dispatcher.py` | `dispatch()` 가 최종 run 행을 DB 에서 다시 읽은 **뒤** 알림 1회. `manual=True` 경로. CLI `manual-fixture`, `slack-status` |
| `crawler/jobs/scheduler.py` | `claim_manual()`(수동 Fixture 1건 claim), `is_manual()`. 수동 run 은 FAILED 여도 자동 재시도(`retry_at`) 안 함 |
| `poc/staging/automation/compose.release.yaml` | backend 에 `SLACK_WEBHOOK_URL`, `SLACK_WEBHOOK_RUL` 전달(값 없음, 기본 빈 값) |
| `crawler/tests/test_slack_notification.py` (신규) | 단위 15건 |
| `crawler/tests/local_t64_integration.py` | 실제 PostgreSQL 통합 4건 추가(CI `Crawler MVP` 에서 실행) |

## 2. 환경변수

| 이름 | 우선순위 | 비고 |
|---|---|---|
| `SLACK_WEBHOOK_URL` | 1 | 표준 이름 |
| `SLACK_WEBHOOK_RUL` | 2 | 기존 사용자 설정 표기. 그대로 인식 |

- 둘 다 있고 값이 다르면 `SLACK_WEBHOOK_URL` 을 쓰고, `slack-status` 에 `"conflict": true` 로 표시합니다(값은 표시하지 않음).
- `https://hooks.slack.com/services/...` 만 허용합니다. 다른 호스트·http·포트·계정 포함 URL 은 `INVALID_WEBHOOK` 으로 알림 비활성.
- 비어 있으면 알림 비활성(`DISABLED`, `NOT_CONFIGURED`). 크롤러 실행에는 영향 없음.
- 설정 확인(값 미출력): `docker compose --project-name ai-career-staging-poc exec -T backend python -m crawler.jobs.dispatcher slack-status`

**Staging 전달 경로** — 로컬 PC `.env` 는 서버로 전달되지 않습니다.
1. 서버 private `/home/kant/ai-career-staging-poc/.env`(mode 600)에 `SLACK_WEBHOOK_URL=...` 추가
2. 서버 overlay `automation/compose.release.yaml` 에 위 2줄 추가 — **서버 overlay 는 저장소에서 자동 동기화되지 않는** 수동 관리 사본입니다(현재 저장소와 이미 다름)
3. 다음 Auto-CD 배포가 backend 를 새 이미지로 재생성할 때 반영

Webhook 은 저장소·Docker 이미지·GitHub Actions 로그에 들어가지 않습니다.

## 3. Slack 메시지 형식

값은 모두 DB 의 `crawler_training.runs` 최종 행에서 읽습니다.

```text
:white_check_mark: *AI Career Platform crawler SUCCEEDED* (Staging)
Trigger: MANUAL · Mode: FIXTURE
Run ID: `<uuid>`
Start: 2026-11-12 18:40:00 KST · End: 2026-11-12 18:40:01 KST
Fetched 2 · Inserted 0 · Updated 0 · Duplicate/unchanged 2 · Failed 0
```

- PARTIAL: `:warning:` 와 "Warning: partial result" 줄 추가
- FAILED: `:x:` 와 `Error code: \`WORKER_TIMEOUT\`` 처럼 DB 의 안전한 오류 코드만. 코드 형식(`^[A-Z][A-Z0-9_]*$`)이 아니면 `UNKNOWN`
- `Duplicate/unchanged` 는 기존 `runs.duplicate_count`(= unchanged + duplicates) 그대로입니다.

## 4. 실행·알림 구조

```text
systemd timer(5분, 기존) ─▶ dispatcher dispatch ─┐
운영자 1회 ─▶ dispatcher manual-fixture ─────────┤  기존 lock(0) · 소스 lock(1) · 단일 RUNNING 규칙
                                                 ▼
                       claim() / claim_manual() → scheduled_worker(기존 fixture) → finish()(DB 기록)
                                                 ▼
                       store.read('run') 최종 행 → notify_run() → Slack 1회 POST(5초, 재시도 없음)
                                                 ▼
                       run_events: SLACK_NOTIFIED(INFO) 또는 SLACK_NOTIFY_FAILED(WARNING)
```

- **중복 방지**: 기존 `run_events` 를 이력으로 재사용. 같은 run 에 위 이벤트가 있으면 다시 보내지 않습니다(실패도 1회로 끝).
- **알림 실패 정책**: 2xx 가 아니면 `SLACK_NOTIFY_FAILED` 만 기록. run 상태·종료 코드는 바뀌지 않습니다. 예외 문구(URL 포함 가능)는 출력하지 않고 `NETWORK_ERROR`/`HTTP_ERROR` 코드만 남깁니다. 리다이렉트는 따라가지 않습니다.
- **수동 실행**(`manual-fixture`)
  - mode=fixture·enabled 스케줄에서만 1건. live 는 `MANUAL_FIXTURE_ONLY` 로 거부, 실행 중이면 `ALREADY_RUNNING`.
  - `next_run_at`·`last_run_at` 을 바꾸지 않으므로 03:00 KST 예약이 그대로입니다.
  - FAILED 여도 자동 재시도하지 않습니다.
  - **trigger 표기**: `runs.trigger` 는 0002 CHECK 로 `scheduled`/`retry` 만 허용합니다. Migration 없이 가는 최소 대안으로, 수동 run 은 `trigger=scheduled`·`scheduled_for=요청 시각` 으로 저장하고 첫 이벤트 `MANUAL_RUN` 으로 구분합니다. Slack 은 이 이벤트로 `MANUAL` 을 표시합니다.
  - 후속 제안(미적용): `runs.trigger` CHECK 에 `'manual'` 추가 Migration. Staging 적용에는 별도 DB 승인이 필요합니다.
- **알림 대상 밖**: 다음 dispatch 의 `recover()` 가 기록하는 `HEARTBEAT_TIMEOUT` 실패는 알림하지 않습니다(디스패처가 죽은 경우). 필요하면 후속 작업으로 다룹니다.
- **외부 연결**: 새 egress 는 `hooks.slack.com` 1곳. Fixture 워커는 HTTP 를 하지 않습니다. Staging backend 컨테이너에서 `https://hooks.slack.com/` 접속 가능 확인(2026-11-12, GET 만).

## 5. 테스트 결과 (로컬)

| 범위 | 결과 |
|---|---|
| `crawler.tests.test_slack_notification` | 15/15 PASS — 우선순위·RUL 대체·충돌, 빈 값 비활성, 비 Slack URL 거부, Secret 미노출, 메시지(KST·건수·오류 코드), 2xx·404·500·네트워크 오류, 중복 방지, 실패 1회 기록, 예외 무해화, dispatch 연결(IDLE/REFUSED 미알림) |
| `crawler/tests` 전체 단위 | 432 실행, OK(5 skip). Windows 는 `PYTHONUTF8=1` 필요(기존 `test_t155_read_models` 의 cp949 읽기 문제, 이번 변경과 무관) |
| `crawler.tests.local_t64_integration`(PostgreSQL 18, 일회용) | 13/13 PASS. 신규 4건: 수동 1회 SUCCEEDED·HTTP 0·슬롯 불변·직후 dispatch IDLE / live·비활성·동시 실행 거부 / 수동 실패 재시도 없음 / Slack 중복 방지(실제 run_events) |
| 예약 실행 회귀 | 기존 통합 9건 그대로 PASS(fixture 성공·멱등, 동시 claim, 잠금, 타임아웃 재시도, 하트비트 복구) |

## 6. 배포 상태

- 코드: #250 병합 `2b19fd0`. Auto-CD 로 2026-11-12 09:51Z Staging 반영(게시 run `43194768990`). backend `slack-status` configured=true.
- 수동 1회 실행 결과(SUCCEEDED, Slack HTTP 200): [CRAWLER_MANUAL_RUN_RESULT.md](CRAWLER_MANUAL_RUN_RESULT.md)
- **서버 Slack 설정: 완료** (2026-11-12 18:41 KST, PM 승인 CRAWLER_SLACK_02)
  - 변경 파일은 2개뿐입니다: 서버 private `.env`, `automation/compose.release.yaml`
  - `.env` 에 `SLACK_WEBHOOK_URL` 1줄을 추가했습니다(값은 SSH stdin 으로만 전달). 로컬 `SLACK_WEBHOOK_RUL` 과 값이 같음을 확인했습니다.
  - overlay 에 `SLACK_WEBHOOK_URL`/`SLACK_WEBHOOK_RUL` 전달 2줄을 추가했습니다. YAML 에 값은 없습니다.
  - 변경 전 sha256(앞 16자): `.env` `7386b9573a178e9d`, overlay `22bda8426b68c8c6`
  - 변경 후 sha256(앞 16자): `.env` `3ca2c0992a04f926`, overlay `1a28183757f90af2`
  - 백업: 같은 경로에 `*.bak-slack-20261112094118`, mode 600. 원본도 mode 600 유지
  - 검증 결과
    - `.env` 와 overlay 를 합친 compose 설정이 유효합니다(`config --quiet`).
    - 배포 로그에 Webhook 이 노출되지 않았습니다.
    - DB 정상, live 환경변수 미설정, 컨테이너 3개 healthy, Auto-CD 타이머 정상.
- **backend 반영: 완료.** 수동 재생성 없이, #250 배포 때 Auto-CD 가 backend 를 재생성하면서 적용되었습니다.
- 실행 결과는 [CRAWLER_MANUAL_RUN_RESULT.md](CRAWLER_MANUAL_RUN_RESULT.md) 에 있습니다.
- 서버 설정 롤백: 두 백업 파일로 원본을 복원합니다. 복원 결과는 위 "변경 전" 해시와 일치해야 합니다.

## 7. 롤백

- 알림만 끄기: 서버 `.env` 의 `SLACK_WEBHOOK_URL` 를 지우고 backend 재생성(다음 배포). 코드는 빈 값이면 아무것도 보내지 않습니다.
- 코드 되돌리기: 이 PR 을 revert → Auto-CD. DB 스키마 변경이 없으므로 DB 조치는 없습니다. 이미 기록된 `MANUAL_RUN`·`SLACK_*` 이벤트는 이력으로 남깁니다.
- 데일리 크롤러 자체 중지: `sudo systemctl disable --now ai-career-crawler-dispatch.timer` + `dispatcher configure --time 03:00 --mode fixture`.
