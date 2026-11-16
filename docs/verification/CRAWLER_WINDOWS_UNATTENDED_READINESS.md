# 크롤러 Windows PC 무인 운영 준비도 검증 (2026-11-16)

선행 문서: [CRAWLER_NEW_PC_SETUP_2026-11-16.md](CRAWLER_NEW_PC_SETUP_2026-11-16.md) (설치·스키마·권한·E2E 기준선).
판정 원칙: 이번 환경에서 실제 실행한 결과만 PASS. 미실행은 `NOT_RUN`, 권한 때문에 할 수 없는 것은 `BLOCKED`.
비밀번호·접속 문자열·Webhook 값은 기록하지 않는다. LIVE·Staging·GCP·Smart App Control은 변경하지 않았다.

## 요약

| 영역 | 판정 | 핵심 근거 |
|---|---|---|
| PostgreSQL 자동 시작(로그인 시) + 장애 재시작 | **PASS** | 감독 실행 작업 `AICP-LocalPostgres`; 강제 종료 → 5초 후 자동 재시작, 데이터 보존 |
| PostgreSQL 부팅 시(로그인 없이) 자동 시작 | **BLOCKED** | 부팅 트리거·S4U 등록은 관리자 PowerShell 필요 (비승격 등록 시 `Access is denied`) |
| 로그아웃 상태 스케줄러 | **BLOCKED / NOT_RUN** | 동일 사유. 관리자 설치 후 4절 절차로 실측 필요 |
| 재부팅 복구 | **NOT_RUN** | 사용자 승인 필요. 재부팅 전 상태 기록 완료(`reboot\before.json`) |
| 무인 실행 안전성 시나리오 12종 | **PASS** | 9절 (이번 환경에서 실측) |
| 로컬 DB 통합/E2E 재검증 | **PASS** (1건 테스트 전제조건 이슈, 7절) | |
| 보안·Secret 분리 | **PASS** (운영 자격증명 교체는 계획만) | 5·6절 |
| 외부 HTTP | **0건** | 모든 실행 `EGRESS_ATTEMPTS=0` |

## 1. Windows 환경

- Windows 11 Pro 10.0.26200 64-bit, i7-1355U, RAM 15.7 GB, C: 여유 153.5 GB(사용률 35%)
- 작업 셸은 **비승격**(관리자 그룹이지만 UAC 필터링), 세션 2(콘솔)
- Smart App Control: `VerifiedAndReputablePolicyState=1`(Enforce) — **변경하지 않음**
- 저장소: `C:\dev\ai-career-platform`, 브랜치 `feat/crawler-windows-local-pc` (기준 HEAD `db37a00`)
- Python 3.12.10 `.venv`, PostgreSQL 18.7 `C:\dev\tools\pgsql18`, 데이터 `C:\dev\crawler-data\pg18` (재설치·재초기화 없음)

## 2. PostgreSQL 자동 시작

### 방식

| 후보 | 결과 |
|---|---|
| Windows 서비스 (`pg_ctl register`) | 관리자 권한 + 서비스 계정 비밀번호 또는 데이터 디렉터리 ACL 변경 필요 → 채택 안 함 |
| Task Scheduler + **감독 실행 스크립트** | **채택**. `scripts/windows/run-postgres-supervised.ps1`가 `postgres.exe`를 포그라운드로 실행하고 종료 코드를 감시 |

`run-postgres-supervised.ps1`의 동작:
- **중복 시작 방지**: 세션을 넘는 이름 있는 뮤텍스 `Global\AICP-PG-Supervisor-<port>`를 쓰고, 살아 있는 `postmaster.pid`를 검사한다. 이미 실행 중이면 `ALREADY_RUNNING`을 남기고 종료 코드 0으로 끝내며 아무것도 시작하지 않는다.
- **정상 종료**: `stop-local-postgres.ps1`(`pg_ctl stop -m fast`)가 서버를 내리면 postgres가 종료 코드 0을 낸다. 감독 스크립트는 `STOPPED`를 남기고 끝나며 재시작하지 않는다.
- **크래시**: 0이 아닌 종료 코드는 `CRASH`로 기록한다. 5초×n 백오프 후 다시 시작하며 WAL 크래시 복구가 이뤄진다. `-WindowMinutes` 안에 `-MaxCrashes`를 넘으면 `GAVE_UP`을 남기고 종료 코드 1로 끝난다(무한 재시작 없음).
- **데이터 보호**: 데이터 디렉터리를 초기화·삭제·변경하지 않는다. 디렉터리가 없으면 `REFUSED`를 남기고 종료 코드 2로 끝난다.
- **로그**: 감독 이벤트는 `C:\dev\crawler-data\logs\postgres-supervisor.jsonl`, 시작 시 stderr는 `logs\postgres\postgres-*.log`, 서버 로그는 `pg18\log\postgresql-<요일>.log`에 남긴다. 서버 로그는 요일별 7개 파일로 매주 덮어써 크기가 제한된다. 이 설정은 `postgresql.conf` 끝에 추가했고, 원본은 `postgresql.conf.bak-20261116`으로 백업했다.
- **비밀번호 없음**: 실행에 자격증명이 필요 없다(postgres를 사용자 프로세스로 실행).

`start-local-postgres.ps1`은 작업이 등록돼 있으면 작업을 시작하고 `pg_isready`를 기다린다. 작업이 없거나 다른 데이터 경로(일회성 클러스터)이면 기존 `pg_ctl` 방식으로 시작한다.

### 실측

| 검증 | 결과 | 장소 |
|---|---|---|
| 1 정상 시작 | `STARTED`, `pg_isready` 1초 내 accepting | 5433(일회성) / 5432 |
| 2 시작 중복 방지 | 두 번째 감독 스크립트 `ALREADY_RUNNING`(`ANOTHER_SUPERVISOR`), 종료 코드 0, 추가 postmaster 없음 | 5433 |
| 3 DB 접속 | `crawler_local` 접속 OK(상태 보고서 `db_connection=OK`) | 5432 |
| 4 정상 종료 | `pg_ctl stop -m fast` → `STOPPED`, 종료 코드 0, 작업 `Ready` | 5433 / 5432 |
| 5 재시작 후 데이터 보존 | pg_ctl 방식에서 작업 방식으로 전환 시 postings md5 동일(22→22). 정지 후 재기동 시나리오도 md5 동일 | 5432 |
| 5b 크래시 후 보존 | postmaster 강제 종료(`Stop-Process -Force`) → `CRASH`(-1) → 5초 후 `STARTED`, 크래시 전 커밋한 Row 유지 | 5433 |
| 6 오류 시 실패 기록 | 손상된 데이터 디렉터리 → `CRASH`×2 → `GAVE_UP`, 종료 코드 1, 디렉터리 변경 없음 | 임시 디렉터리 |
| 7 권한 부족 시 안전한 실패 | 비승격 상태의 S4U/부팅 작업 등록 → `Access is denied`, 아무것도 등록되지 않음. `register-fixture-task.ps1 -Unattended`는 비승격이면 즉시 `BLOCKED`, 변경 없음. 데이터 디렉터리가 없으면 `REFUSED` 종료 코드 2 | 5432 |

강제 종료 시험은 사용자 데이터 보호를 위해 일회성 5433 클러스터에서만 했다.

현재 등록 상태: `AICP-LocalPostgres` = **로그인 시(Interactive)**, Running. 즉 **로그인해야 시작된다**. 부팅만으로(로그인 없이) 시작하려면 3절의 관리자 설치가 필요하다.
작업 설정: `MultipleInstances=IgnoreNew`, 실행 시간 제한 없음, 실패 시 1분 간격 3회 재시작, 배터리 상태에서도 실행.

## 3. 로그아웃 상태 스케줄러

| 항목 | 현재(검증됨) | 무인 설치(`-Unattended`, 관리자 필요) |
|---|---|---|
| 로그온 유형 | Interactive ("사용자가 로그온할 때만") | **S4U** = "사용자 로그온 여부에 관계없이 실행" + "암호 저장 안 함" |
| 실행 계정 | `LAPTOP-8VMOVISB\TEST`, RunLevel Limited | 같음 (비관리자 토큰) |
| 자격증명 보관 | 없음 | **없음** — S4U는 비밀번호를 저장하지 않음. DB 비밀번호는 ACL이 제한된 pgpass |
| 네트워크 | no_egress 가드(루프백 외 차단) | 가드 + S4U 토큰에는 네트워크 자격증명이 없음 |
| 작업 경로 | `\AICP-Crawler-Fixture`, `\AICP-LocalPostgres` (루트 폴더) | 같음 |
| 작업 디렉터리 | `C:\dev\ai-career-platform` | 같음 |
| 로그 | `C:\dev\crawler-data\logs\scheduler\fixture-YYYYMMDD.jsonl`, 상태 `status\crawler-status.json` | 같음 |
| 실패 시 재시도 | Task Scheduler는 비정상 종료 코드로 재실행하지 않음(시나리오 7: `LastTaskResult=1` 기록만). 다음 주기에 다시 실행되고 dispatcher 재시도 예산이 적용됨 | 같음 |
| 중복 실행 방지 | `IgnoreNew` + `Global\AICP-Crawler-Fixture` 뮤텍스 (세션 0과 대화형 세션 사이에서도 유효) + dispatcher DB advisory lock | 같음 |
| 종료 코드 | 0 정상·잠금으로 건너뜀, 1 실패, 3 자동 OFF, 4 거부(LIVE/enabled) | 같음 |
| PG 시작 트리거 | 로그인 시 | **부팅 시** |

실측:
- 비승격 상태에서 S4U 작업, 부팅 트리거(S4U), 부팅 트리거(Interactive) 등록을 모두 시도했고 세 가지 모두 **`Access is denied`**였다. 우회는 하지 않았다.
- Interactive 작업의 자동 실행 로그에는 `session=2, interactive_logon=true, batch_logon=false`가 기록된다. 무인 실행이면 `batch_logon=true`, 세션 0이 기록되어야 한다.
- 로그아웃 상태 실측은 **NOT_RUN**이다. 화면 잠금은 로그아웃 시험으로 인정하지 않는다.

### 관리자 설치 + 로그아웃 시험 절차 (사용자 실행)

```powershell
# 관리자 PowerShell (Run as administrator), 저장소 루트
.\scripts\windows\register-fixture-task.ps1 -Unattended -IntervalMinutes 5 -ValidHours 2
.\scripts\windows\reboot-check.ps1 -Phase Before
# 1) 로그아웃(시작 > 로그아웃) → 15분 이상 대기 → 다시 로그인
# 2) 확인: 로그아웃 시간대 fixture-*.jsonl 항목에 batch_logon=true, session=0, status=SUCCEEDED, egress_attempts=0
.\scripts\windows\crawler-status.ps1
```

선택적 강화(관리자): 기본 Python 실행 파일의 아웃바운드를 차단하는 Windows 방화벽 규칙. pip 같은 다른 사용 용도에도 영향이 있어 이번에는 적용하지 않았다.

## 4. 재부팅 후 동작

- **REBOOT_TEST=NOT_RUN** — 실제 재부팅은 사용자 승인 후에만 한다.
- 재부팅 전 상태 기록: `C:\dev\crawler-data\reboot\before.json`(14:4x)
  - HEAD `db37a00`(`feat/crawler-windows-local-pc`), 마지막 부팅 2026-08-18 14:51
  - PostgreSQL accepting, postings 42 / runs 18, 실행 중인 run 0
  - 작업: `AICP-LocalPostgres` Running(Interactive), `AICP-Crawler-Fixture` Disabled(자동 OFF 상태)
  - LIVE 스케줄 0 / LIVE run 0 / LIVE 환경변수 없음, C: 여유 153.5 GB, 데이터 `C:\dev\crawler-data\pg18`
- 안전한 재부팅 절차:
  1. `reboot-check.ps1 -Phase Before`
  2. fixture 작업 등록(`-IntervalMinutes 5 -ValidHours 2`; 무인 시험이면 관리자 + `-Unattended`)
  3. `stop-local-postgres.ps1`로 정상 종료
  4. **"다시 시작"**으로 재부팅. "시스템 종료"는 빠른 시작(Fast Startup) 때문에 부팅 시각이 갱신되지 않아 판정이 흐려진다.
  5. (Interactive 설치면 로그인) 10분 대기
  6. `reboot-check.ps1 -Phase After`
- After 판정 항목(자동): 재부팅 여부, PG가 부팅 후 자동 시작했는지, DB 접속, 데이터 보존(md5·건수), 부팅 후 fixture 실행 ≥1회, 무인(BATCH) 실행 여부, 실패 0, egress 0, LIVE 없음, 멈춘 RUNNING 0

## 5. 보안 점검

| 항목 | 결과 |
|---|---|
| `.env` Git 제외 | `.gitignore:154`, 모든 ref의 커밋 중 `.env` 포함 0건 |
| Secret 노출 검사 (값 출력 없이) | `Password`, `Host_GCP`, `Password_GCP`, `SLACK_WEBHOOK_RUL`, `Password_LOCAL` 값: Git 이력 0, 모든 ref 트리 0, 작업 트리 0, 로컬 로그·상태 보고서·스케줄러 파일 0. pgpass 비밀번호 3개: 저장소·이력·로그 0 |
| 검사 불가 | `STAGING_SSH_PASSWORD`는 4자라 결정적 스캔이 불가능 → 약한 비밀번호 자체가 보안 항목 |
| 파일 ACL | `.env`, `pgpass.conf`, 데이터 디렉터리: 현재 사용자 + SYSTEM만 |
| 로컬 전용 계정 | 런타임 `crawler_local`(DML만), 관리자 `postgres`는 초기 설정에만 사용 |
| 운영 DB 연결 기본 OFF | `CRAWLER_DB_MODE=local`, `CRAWLER_STAGING_DATABASE_URL`·`DATABASE_URL`·`GCP_SYNC_*`를 주입해도 환경 스크립트가 제거. `gcp_sync dry-run` → `SOURCE_NOT_STAGING`(연결 없음, egress 0) |
| Slack 실제 발송 차단 | 가짜 Webhook을 `SLACK_WEBHOOK_URL`·`SLACK_WEBHOOK_RUL`에 주입 → 제거 후 `slack-status`=`NOT_CONFIGURED`. 스케줄 실행 결과 `slack=DISABLED` |
| 외부 HTTP 가드 | `203.0.113.10:443`·`https://www.jobkorea.co.kr` → 차단(`EGRESS_ATTEMPTS=2`, 패킷 없음), `127.0.0.1:5432` 허용. dispatcher의 worker 자식까지 `sitecustomize`로 적용(스케줄 실행마다 Python 프로세스 5개, egress 0) |
| Smart App Control | 변경 없음 |

## 6. Secret 분리와 교체 계획 (계획만 — 실행은 PM 승인 후)

이 PC의 로컬 운영에 필요한 비밀은 로컬 PostgreSQL 관리자(`*_LOCAL`, 초기 설정용)와 pgpass(역할 3개)뿐이다. 루트 `.env`에 남아 있는 아래 값은 이 PC에서 필요하지 않다.

| 비밀 | 위험 | 교체 계획 | 이 PC |
|---|---|---|---|
| Staging SSH 비밀번호(4자) | 약함, 평문 | 키 기반 인증으로 전환 → 비밀번호 로그인 비활성(`PasswordAuthentication no`) → 비밀번호 폐기 | 교체 완료 후 `.env`에서 제거 |
| GCP DB 비밀번호(`Password_GCP`) | 운영 Cloud SQL 계정 평문 | 새 PC 전환 시 GCP Sync 전용 계정을 새로 발급(최소 권한, `poc/staging/automation/gcp-sync/target_grants.sql` 기준) → 전환 검증 → 기존 비밀번호 교체/폐기 | 신규 계정 발급 전까지 사용 금지, 전환 후 제거 |
| Staging DB 비밀번호(`Password`) | 평문 | 이전 완료·Staging 종료 후 폐기. 그 전에는 백업용 읽기 전용 계정 사용 권장 | 제거 |
| Slack Webhook(`SLACK_WEBHOOK_RUL`) | 코드가 읽는 레거시 이름이라 로드되면 실제 발송 | 새 PC 전용 Webhook 발급 → `SLACK_WEBHOOK_URL`로만 주입 → 기존 Webhook 폐기 | 제거 |

절차는 `docs/ops/SECRET_ROTATION_RUNBOOK.md`를 따른다. 교체 → 사용처 반영 → 검증 → 구 값 폐기 → `.env`에서 제거 순서로 진행하며, 각 단계는 PM 승인이 필요하다. 이번 작업에서는 삭제·교체하지 않았다.

## 7. 로컬 DB 통합 테스트 (이번 환경에서 재실행)

PG는 작업 `AICP-LocalPostgres`가 호스팅. 요약 `C:\dev\crawler-data\logs\tests-20261116-143643\summary.json`.

| 코드 | 결과 |
|---|---|
| main @ 5432 | 단위 515 OK(skip 5), backend 21 OK, PG 10개 단계 OK, **`local_t155_admin_read_pg` 1 FAIL** |
| 위 FAIL 원인 | 테스트가 `runs` 테이블이 **비어 있다고 가정**(CI의 새 DB). 이 PC는 오늘 스케줄 실행으로 runs가 17건 있음 → **테스트 전제조건 문제**이며 코드·환경 결함이 아님. 새 일회성 클러스터(5433)에서 같은 테스트 3/3 OK |
| PR #371 @ 새 5433 (worktree `c025f51`) | 단위 523 OK, backend 21 OK, PG 9개 단계 모두 OK(gcp-sync 12 포함), egress 0. `staging-mode`·`t64-permissions`는 `db:5432` 하드코딩이라 5433에서는 NOT_APPLICABLE(이전 실행에서 5432 PASS) |
| E2E (`local_e2e.py`) | **PASS** 11/11 (`logs\e2e-20261116-143715\evidence.json`) |

참고: 일회성 5433 클러스터 설정이 한 번 종료 코드 1로 실패했다(DB만 생성되고 마이그레이션 미적용). 재생성하자 정상이었고 원인은 확정하지 못했다. 일회성 검증용 경로에서만 발생했다.

## 8. 자동 실행 테스트

| 시험 | 결과 |
|---|---|
| Task Scheduler 자동 트리거(새 등록) 14:30:51 | `SUCCEEDED`, `LastTaskResult=0`, dispatch `IDLE`, night `DISABLED`, Slack `DISABLED`, egress 0 |
| 실제 작업 경로 승인 만료 | 만료 정책 + `Start-ScheduledTask` → `AUTO_OFF`, `task_disabled=true`, 작업 **Disabled**, `LastTaskResult=3` |
| 이전 세션 자동 트리거 2회 | 13:58:43 / 14:00:44 SUCCEEDED (선행 문서) |

## 9. 장애 복구·무인 안전성 시나리오 (Fixture, 이번 환경 실측)

`scripts/windows/test-unattended-scenarios.ps1` → `C:\dev\crawler-data\logs\scenarios-20261116-143434\scenarios.json`

| # | 시나리오 | 결과 |
|---|---|---|
| 1 | 정상 실행 | `SUCCEEDED`, dispatch `IDLE`, night `DISABLED`, Slack `DISABLED`, Python 프로세스 5, egress 0 |
| 2 | 중복 실행 | 25초 점유 중 두 번째 → `SKIPPED_LOCKED`(`ANOTHER_RUN_IN_PROGRESS`), 점유한 쪽 `SUCCEEDED` |
| 3 | DB 연결 실패 | 도달 불가 포트 → `FAILED`, `SCHEDULE_READ_FAILED`, 종료 코드 1 |
| 4 | DB 연결 복구 | PG 정상 종료(`pg_isready`=2, 작업 Ready) → 다음 실행이 작업을 시작해 복구 → `SUCCEEDED`, 작업 Running, postings md5 동일(22→22), runs 14→15 |
| 5·6 | 실행 중 중단 / 프로세스 비정상 종료 | 크롤러 사이클을 강제 종료(종료 코드 -1, 로그 항목 없음) → OS가 잠금을 해제 → 다음 실행 `SUCCEEDED`, 멈춘 RUNNING run 0. worker 강제 종료·timeout·stale heartbeat 복구는 PG 통합 테스트(`local_t64_integration`, `local_night_integration`)로 이번 환경에서 재검증 |
| 7 | Windows Task 실패 | 임시 작업(도달 불가 포트) → Task Scheduler `LastTaskResult=1` 기록, 작업은 Ready(다음 주기 가능), 임시 작업 삭제 |
| 8 | 승인 만료 | `AUTO_OFF`, 종료 코드 3 (+ 8절 실제 작업에서 Disabled 확인) |
| 9a | 기능 플래그 강제 ON | 부모 환경에 `CRAWLER_NIGHT_ENABLED=1`, `CRAWLER_LIVE_SCHEDULE_APPROVED=1`, 가짜 Slack URL → 제거되어 night `DISABLED`, Slack `DISABLED`, `SUCCEEDED` |
| 9b | DB 스케줄 enabled (mode=fixture) | `REFUSED`, `LIVE_OR_ENABLED_SCHEDULE_PRESENT`, 종료 코드 4 → 원복(enabled=false, fixture, 03:00) |
| 10 | 최대 요청 수 초과 | 단위 테스트(이번 환경에서 515/523 OK에 포함): `test_10_request_limit_exceeded_denied`, `test_job_budget_above_max_requests_sends_nothing`, `test_budget_three_then_hard_stop`, `test_batch_limit`, PG `test_failed_reservation_is_visible_and_consumes_budget_as_runtime` |
| 11 | 실행 로그 | 모든 실행이 JSONL에 상태·사유·종료 코드·세션·egress를 기록(단, 강제 종료된 실행은 기록할 기회가 없음) |
| 12 | 결과 재조회 | `dispatcher run/events --run-id` → `SUCCEEDED`, fixture, fetched 2, duplicates 2, 이벤트 `MANUAL_RUN → CLAIMED → WORKER_STARTED → SUCCEEDED` |

## 10. 로그 및 모니터링

`scripts/windows/crawler-status.ps1` → `C:\dev\crawler-data\status\crawler-status.json`. 매 fixture 실행 후 자동 갱신되며 Slack이나 네트워크를 쓰지 않는다.

| 지표 | 필드 |
|---|---|
| Windows 작업 상태 | `tasks[]` state / logon_type / last_run / last_result / next_run / missed_runs |
| PostgreSQL 실행·접속 | `postgres.running`, `accepting_connections`, postmaster PID/세션/시작 시각, `supervisor_last_event`, `db_connection` |
| 최근 실행 시각·성공/실패 | `db.recent_runs[]`, `last_success_at`, `last_failure_at`, `runs_currently_running`, `fixture_scheduler.last_*` |
| INSERT / UPDATE / 중복 / 실패 | `db.recent_runs[]` 건수, `db.last_24h_runs` |
| Skipped 사유·경고 | `db.last_24h_warning_error_events`(`run_events` 수준·유형별), `db.last_7d_night_outcomes`(outcome:error_code) |
| 마지막 실행 오류 | `fixture_scheduler.last_error` |
| 디스크·로그 크기 | `disk.free_gb`, `used_percent`, `pg_data_mb`, `logs_mb`, `pg_server_log_mb` |
| LIVE | `live_flags`(세션 변수, LIVE/enabled 스케줄 수, LIVE run 수) |
| 종합 | `health` = OK/ATTENTION + `problems[]` (PG 접속 불가, DB 실패, 마지막 실행 FAILED/REFUSED, LIVE 있음, 디스크 90% 초과) |

현재 값(14:31): health OK, PG accepting, 최근 run SUCCEEDED, 24시간 7 runs / 실패 0, 디스크 35%, 로그 0.3 MB.
주의: `postings_by_source.jobkorea_live`(13건)와 `night_job_results`는 **mock HTTP 통합 테스트가 남긴 Row**다. `runs`의 LIVE run은 0건이다.

## 11. 기존 Ubuntu 서버 전환 절차 (계획만 — 이번에 이전·변경 없음)

보고된 기존 상태: LIVE 플래그 OFF, root systemd kill switch 적용, GCP Sync 별도 자동 실행, 디스크 100%.

| # | 단계 | 내용 | 승인 |
|---|---|---|---|
| 1 | 기존 서버 상태 확인(읽기만) | `systemctl list-timers`, kill switch, 크롤러·GCP Sync 타이머 상태, `df`, `docker compose ps`, 마지막 run/sync 시각 | — |
| 2 | 기존 Scheduler 중지 승인 | 크롤러(LIVE·야간·dispatch) **와** GCP Sync 타이머를 각각 명시해 중지 승인 | **PM** |
| 3 | DB 일관성 확인 | 중지 후 `runs.status='RUNNING'` 0, `keyword_jobs` RUNNING 0, 진행 중 sync 없음, advisory lock 없음 | — |
| 4 | 백업 | 서버 디스크에 쓰지 않고 SSH 스트림으로 새 PC에 저장: `docker compose exec -T db pg_dump -Fc -n crawler_training -d ai_career_crawler_training`. 이어서 SHA-256 계산, `pg_restore --list` 확인 | **PM**(접속) |
| 5 | 새 PC로 복원 | 새 PC의 현재 학습 DB(테스트 Row)를 덤프로 보관 → `ai_career_crawler_training` 재생성(`bootstrap_local_db.py`) → `pg_restore --no-owner --role=crawler_student` → 마이그레이션 0002~0012 재적용(멱등)으로 GRANT 보정 | **PM** |
| 6 | 외부 ID·이력 검증 | 테이블별 count, `postings (source_code, external_posting_id)` 집합 해시, `keyword_posting_discoveries`/`checkpoints`, `runs`/`run_events`/`night_*`를 원본 읽기 전용 SELECT와 비교 | — |
| 7 | 새 PC 연결·권한 | `verify_local_db.py`(권한 거부 목록), `crawler-status.ps1` health OK, 무인 설치(관리자) + 재부팅·로그아웃 실측 완료 | **사용자**(관리자/재부팅) |
| 8 | 기존 서버 중복 실행 차단 | 크롤러·GCP Sync 타이머 `disable` + kill switch 유지 확인. 기존 GCP Sync 계정 비활성 또는 비밀번호 교체로 **이중 Sync를 자격증명 수준에서도 차단** | **PM** |
| 9 | 새 PC 단발성 실행 승인 | T61 승인 파일(만료일 포함)을 비공개로 전달, LIVE 1회(최소 요청 수) + GCP Sync `dry-run` → `run` 1회 | **PM**(LIVE·GCP) |
| 10 | 결과 검증 | 요청 수 ≤ 상한, inserted/updated/duplicates·Skipped 사유, GCP 쪽 건수와 `COUNT_MISMATCH` 없음, Slack(새 Webhook) 1회 | — |
| 11 | 실패 시 롤백 | 새 PC 작업 Disable → (디스크 확보 후) 기존 서버 타이머 재활성 → 새 PC에서 생성된 Row는 같은 덤프 절차로 역이전 | **PM** |
| 12 | 기존 서버 최종 종료 | 새 PC가 N일 안정 운영(상태 보고서 health OK)한 뒤 종료. 즉시 삭제하지 않고 보존 기간을 둠 | **PM** |

PR #371 미병합 상태에서는 Staging과 새 PC의 크롤러 코드 버전이 다를 수 있다. 전환 전에 같은 커밋을 배포·검증한다.

## 12. 이중 스케줄러 방지

| 작업 | 위험 | 차단 장치 |
|---|---|---|
| A. LIVE 크롤링 | 두 서버가 같은 밤에 같은 키워드를 요청 → 요청 상한 2배, 실행 이력 혼선 | ① 기존 서버 타이머 disable + kill switch ② 새 PC는 PM 승인 전 LIVE 플래그 없음, enabled/LIVE 스케줄이 있으면 실행 거부(`REFUSED`) ③ T61 승인 파일을 한 서버에만 둠 ④ 전환일에 두 서버 상태 보고서를 대조 |
| B. Staging → GCP Sync | 같은 원본을 두 서버가 publish → 중복 처리·`ingestion_runs` 혼선 | ① 기존 Sync 타이머 disable ② 새 PC Sync는 별도 신규 계정으로만 실행 ③ 기존 Sync 계정 비활성 ④ 새 PC Sync 첫 실행은 `dry-run` → 건수 대조 → `run` |
| 공통 | 한 PC 안에서의 중복 | `IgnoreNew` + `Global\` 뮤텍스 + DB advisory lock(시나리오 2) |

A와 B는 같은 순서로 하되 **각각 별도로 승인하고 차단**한다. LIVE를 중지해도 Sync는 따로 돌 수 있다.

## 13. 승인 필요 작업

| 작업 | 승인자 |
|---|---|
| 관리자 PowerShell로 `register-fixture-task.ps1 -Unattended` 실행(부팅 시 PG + 로그아웃 상태 fixture) | 사용자 |
| 실제 재부팅·로그아웃 시험 | 사용자 |
| 운영 자격증명 교체·`.env`에서 제거 | PM |
| Staging 접속·타이머 중지·백업 | PM |
| 운영 데이터 이전·전환 | PM |
| LIVE 단발 실행, GCP Sync 활성 | PM |
| PR #371 병합(독립 리뷰 후), 이 브랜치 PR | 리뷰어 / PM |
| Docker/Node 설치(선택) | 사용자(관리자·재부팅) |

## 14. 다음 운영 전환 단계

1. 사용자: 관리자 PowerShell로 `-Unattended` 설치 → 4절 재부팅 시험 + 3절 로그아웃 시험 → `reboot-check.ps1 -Phase After` 모두 true 확인
2. 리뷰: PR #371 독립 리뷰·병합, 이 브랜치 PR 생성·리뷰
3. PM: 자격증명 교체 계획(6절) 승인 → 새 PC 전용 GCP Sync 계정·Slack Webhook 발급
4. PM: 11절 1~8단계(중지·백업·복원·검증)
5. PM: 단발 LIVE + Sync dry-run/run(9~10단계) → 안정 운영 기간 → 기존 서버 종료(12단계)

### 완료 / 미완료

| 완료 (증거 있음) | 미완료 |
|---|---|
| PG 감독 실행·중복 방지·정상 종료·크래시 재시작·데이터 보존·실패 기록 | 부팅 시 자동 시작(관리자 필요) |
| 로그인 상태 자동 스케줄·자동 OFF·중복 차단·실패 기록 | 로그아웃 상태 실행(관리자 필요 + 실측) |
| 장애 시나리오 12종, 통합·E2E 재검증 | 재부팅 시험(사용자 승인) |
| 보안 점검, Secret 비노출, Slack·운영 DB·외부 HTTP 차단 | 운영 자격증명 교체(PM) |
| 로컬 JSON 상태 보고서 | 데이터 이전·전환(PM) |
| 전환·이중 스케줄러 방지 계획 | PR #371 리뷰 상태 확인(GitHub API 비인증 한도 초과 → UNKNOWN) |
