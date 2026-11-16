# 크롤러 신규 Windows PC 환경 구축 검증 (2026-11-16)

- 대상: 기존 Ubuntu Staging 크롤러(디스크 100%)를 대체할 **독립 Windows 11 PC**의 로컬 크롤러 환경
- 범위: 로컬 PostgreSQL 18.7, Python 3.12 venv, Fixture/Offline 실행, 로컬 DB 통합·E2E, Windows Task Scheduler
- 범위 외(미변경): 기존 Staging 서버, GCP Cloud SQL, LIVE 수집, GCP Sync, Slack 실제 송신
- 판정 원칙: 실제 실행한 명령·종료코드·DB Row·로그만 PASS로 기록. 미실행은 `NOT_RUN`.
- 비밀번호·접속 문자열·Webhook 값은 이 문서와 로그 어디에도 기록하지 않음.

## 1. PC 환경

| 항목 | 값 (실측) |
|---|---|
| OS | Windows 11 Pro 10.0.26200 (build 26200), 64-bit |
| CPU | 13th Gen Intel Core i7-1355U (10 cores / 12 threads) |
| RAM | 15.7 GB |
| 디스크 | C: 236.3 GB 중 여유 약 156 GB (구축 전 측정) |
| 셸 | Windows PowerShell 5.1, Git Bash (git 2.55.0) |
| 권한 | 관리자 그룹 소속이나 UAC 필터링(비승격) 상태로 작업 — **관리자 권한 없이 전 과정 완료** |
| Smart App Control | **Enforce(켜짐)** — 서명 없는 DLL 로드 차단 (아래 4절 참고) |
| 미설치 | Docker Desktop, WSL2 배포판, Node.js/npm, GitHub CLI(`gh`) |

## 2. PostgreSQL 18.7

| 항목 | 값 |
|---|---|
| 배포본 | EDB 공식 `postgresql-18.7-1-windows-x64-binaries.zip` (설치 프로그램·서비스 등록 없음) |
| ZIP SHA-256 | `EAD0BBC27FB678FA24DCF86B738981323042ABD073C744103BF7F3AED23F9A33` |
| 서명 | `postgres.exe`, `psql.exe`, `initdb.exe`, `libpq.dll`, `libssl-3-x64.dll`, `libcrypto-3-x64.dll` 모두 Authenticode **Valid (EnterpriseDB Corporation)** |
| 바이너리 | `C:\dev\tools\pgsql18` (pgAdmin·StackBuilder·symbols 제외) |
| 데이터 | `C:\dev\crawler-data\pg18` — 사용자가 initdb로 새로 초기화한 클러스터 (과거 데이터 복원 없음) |
| 네트워크 | 127.0.0.1:5432 만 LISTEN (`listen_addresses` 기본값 `localhost`) |
| 인증 | `pg_hba.conf` 전 항목 `scram-sha-256`, trust 없음, 원격 주소 없음 |
| 데이터 디렉터리 ACL | 현재 사용자 + SYSTEM 만 (상속 제거) |
| 실행 방식 | 사용자 프로세스(`pg_ctl`), Windows 서비스 아님 |

Staging은 Docker `postgres:18.1` (`poc/staging/compose.yaml`) — 같은 18 메이저이므로 `pg_dump`/`pg_restore` 이전이 가능하다.

## 3. DB 연결 설정 (환경변수 매핑)

크롤러 코드가 실제로 읽는 변수 (코드 조사 결과):

| 변수 | 사용처 | 이 PC의 값 |
|---|---|---|
| `CRAWLER_LOCAL_DATABASE_URL` | `crawler/storage/postgres.py`, `staging.py`, `backend/training_jobs_api.py` | `postgresql://crawler_local@127.0.0.1:5432/ai_career_crawler_training` (**비밀번호 없음**, pgpass 사용) |
| `CRAWLER_DB_MODE` | `crawler/storage/staging.py` | `local` (`staging`이면 `db:5432` 컨테이너 전용 경로) |
| `CRAWLER_STAGING_DATABASE_URL` | staging 모드 전용 | 설정 안 함 (세션에서 강제 제거) |
| `CRAWLER_DATABASE_URL` | **코드에 없음** | — |
| `DATABASE_URL` | 서비스 백엔드(`backend/app`, career 스키마) — 크롤러는 사용 안 함 | 설정 안 함 (세션에서 제거) |

코드 안전장치(`validate_local_dsn`): 호스트 `localhost/127.0.0.1/::1`만, DB명 `ai_career_crawler_training`만, 사용자 `postgres`/`ai_career_poc` 거부, `hostaddr=127.0.0.1` 고정.

사용자가 추가한 루트 `.env`의 `Host_LOCAL/Port_LOCAL/Database_LOCAL/Username_LOCAL/Password_LOCAL`은 **코드가 직접 읽지 않는 이름**이다. 다음과 같이 연결했다(기존 값은 삭제·변경하지 않음):

- `scripts/windows/local_db_config.py` — `.env`에서 **`*_LOCAL` 5개 키만** 파싱. 다른 키(Staging SSH, GCP, Slack)는 읽지도 `os.environ`에 넣지도 않음. 루프백 호스트·학습 DB명 검증 후 `psycopg.connect(password=...)` 키워드 인자로만 전달 → URL 미생성, 특수문자 인코딩 문제 없음, 출력 없음.
- 관리자(`postgres`) 비밀번호는 `bootstrap_local_db.py`의 **초기 역할/스키마 설정에만** 사용.
- 크롤러 런타임은 `crawler_local` + **pgpass 파일** (`C:\dev\crawler-data\secrets\pgpass.conf`, 저장소 밖, ACL: 현재 사용자+SYSTEM). 비밀번호는 명령행·URL·로그에 나타나지 않음.
- `scripts/windows/crawler-local-env.ps1` — 세션 준비. 루트 `.env`를 **로드하지 않으며** `SLACK_*`, `GCP_SYNC_*`, `CRAWLER_LIVE_*`, `CRAWLER_NIGHT_ENABLED`, `CRAWLER_NIGHT_POLICY_FILE`, `CRAWLER_STAGING_DATABASE_URL`, `DATABASE_URL`, `PGHOST/PGUSER/PGPASSWORD…` 등을 프로세스에서 제거한 뒤 `Assert-CrawlerSafeSession`으로 재확인.

`.env.example`에는 `*_LOCAL` 키 이름만(값 없이) 추가했다.

## 4. Python 환경

| 항목 | 값 |
|---|---|
| Python | 3.12.10 (`winget install Python.Python.3.12 --scope user`, 관리자 불필요) |
| venv | `C:\dev\ai-career-platform\.venv` (`.gitignore` 대상 확인) |
| pip | 26.3 |
| 의존성 | `backend/requirements-dev.txt` 고정 버전 그대로 (psycopg 3.3.4, fastapi 0.115.12, uvicorn 0.34.2, SQLAlchemy 2.0.57, pydantic 2.14.3, pytest 9.0.3, httpx 0.28.1 …) — CI와 동일 |
| `pip check` | `No broken requirements found.` |

**신규 환경 오류 (원인 확인·해결):** 첫 단위 테스트에서 `psycopg` import 실패 —
`DLL load failed … 응용 프로그램 제어 정책에서 이 파일을 차단했습니다`. CodeIntegrity 이벤트 3033/3077 확인 결과 Smart App Control(Enforce)이 `psycopg_binary.libs\libcrypto-3-x64-*.dll`(서명 없음)을 차단.
Smart App Control 해제는 되돌릴 수 없는 OS 보안 설정이므로 변경하지 않고, **`PSYCOPG_IMPL=python`(psycopg 순수 Python 구현) + EDB의 서명된 `libpq.dll`**(PATH에 `C:\dev\tools\pgsql18\bin`)로 해결. 검증 출력 `psycopg_impl=python`, `libpq_version=180007`. 의존성 버전 변경 없음, CI(Linux) 영향 없음.

**cp949 인코딩:** `PYTHONUTF8` 없이 실행한 최초 main 단위 테스트(510개)에서도 인코딩 실패 0건(유일한 오류는 위 DLL 차단). 이후 실행은 `PYTHONUTF8=1`. DB에 저장된 한글은 UTF-8 hex로 확인(`시니어` = `eb8b88 ec96b4`). Git Bash 콘솔에서 Python 출력이 깨져 보이는 것은 콘솔 표시 문제이며 데이터 문제가 아님.

## 5. DB 스키마

적용 파일(저장소 원본 그대로, 새 테이블 작성 없음): `crawler/storage/local_training_schema.sql` + CI와 동일한 postings GRANT + `crawler/storage/migrations/0002`~`0012`.
모든 파일이 `CREATE … IF NOT EXISTS` / `ON CONFLICT DO NOTHING`이라 재실행해도 기존 객체를 재생성·삭제하지 않음(실제로 2회 적용 확인).

`verify_local_db.py` 실측 (런타임 계정 `crawler_local`로 접속):

| 검증 | 결과 |
|---|---|
| 연결 대상 | `server_addr=127.0.0.1/32`, `server_version=18.7`, `database=ai_career_crawler_training` |
| 스키마 | `crawler_training` 존재, 테이블 17개 (postings, runs, run_events, schedules, search_keywords, keyword_jobs, keyword_posting_discoveries, keyword_checkpoints, keyword_audit_events, raw_artifacts, raw_parse_results, fixture_job_payloads, fixture_job_attempts, fixture_night_slots, admin_commands, night_job_results, night_summaries) |
| postings | `source_code text, external_posting_id text, payload jsonb, updated_at timestamptz`, `PRIMARY KEY (source_code, external_posting_id)` |
| 제약/인덱스 | PK+UNIQUE 25개, 인덱스 34개 |
| 실행 이력 테이블 | runs, run_events, night_job_results, night_summaries |
| INSERT → SELECT → 동일 키 재INSERT | 삽입 OK, 조회 `a`, **UniqueViolation으로 거부** |
| UPDATE → ROLLBACK | 조회 `b` 후 롤백, 잔여 Row **0** |
| 재시작 후 유지 | PG 정지(`pg_ctl status`=3) → 재기동 후 `postings` 22→22, md5 동일, postmaster 시작시각 갱신 |

## 6. 전용 계정 권한

`scripts/windows/bootstrap_local_db.py` (멱등). 새 비밀번호는 `secrets` 모듈로 생성해 pgpass에만 기록. 기존 Staging/GCP 자격증명 재사용 없음.

| 역할 | 용도 | 속성 |
|---|---|---|
| `crawler_student` | DB 소유자, 저장소 DDL 적용 전용 (CI 구조와 동일). 런타임 미사용 | LOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS |
| `crawler_staging` | 마이그레이션이 테이블별 DML GRANT를 부여하는 역할 (테스트가 이 이름을 요구) | 동일 |
| **`crawler_local`** | **크롤러 런타임 로그인** — `GRANT crawler_staging TO crawler_local WITH INHERIT TRUE, SET FALSE` | 동일 |

DB 수준: `REVOKE ALL ON DATABASE ai_career_crawler_training FROM PUBLIC` 후 `crawler_staging, crawler_local`에 `CONNECT, TEMPORARY`; `postgres`, `template1` DB의 PUBLIC `CONNECT, TEMPORARY` 회수.
`ALTER DEFAULT PRIVILEGES`는 사용하지 않음 — 저장소 마이그레이션이 테이블별 명시 GRANT 모델이므로 기본 권한을 넓히면 최소 권한이 깨짐.

`crawler_local` 실측:

| 검사 | 결과 |
|---|---|
| 로그인(pgpass) / superuser·createdb·createrole·replication·bypassrls | 성공 / 모두 false |
| postings SELECT·INSERT·UPDATE | 성공 (롤백) |
| CREATE TABLE(crawler_training, public)·CREATE SCHEMA·ALTER·DROP·TRUNCATE | **거부** |
| DELETE postings | **거부** |
| SET ROLE crawler_staging / CREATE ROLE | **거부** |
| `postgres`, `template1` DB 접속 | **거부** (CONNECT 권한 없음) |

## 7. Fixture/Offline 테스트 (외부 HTTP 없음)

모든 Python 실행은 `scripts/windows/no_egress.py`(루프백 외 socket connect·DNS 차단 및 집계) 아래에서 수행 → 각 단계 `EGRESS_ATTEMPTS=0`.

| 코드 | 명령 | 결과 |
|---|---|---|
| main `1797f4c` | `python -m unittest discover -s crawler/tests -v` | **515 ran, OK, skipped=5** |
| main | `python -m unittest discover -s backend/training_tests -v` | 21 ran, OK |
| PR #371 `c025f51` | 동일 | **523 ran, OK, skipped=5** / 21 OK |

Skip 사유(Windows 비해당, 정상): POSIX SIGTERM/프로세스 그룹/파일 모드 비트/supervisor 4건, 심볼릭 링크 권한 없음 1건 (+ PG 단계의 `POSIX wrapper` 1건).
단위 테스트가 다루는 항목: HTML/JSON-LD 파싱 성공·실패, 필수 필드·날짜 검증, 외부 ID 추출, 배치 내 중복, 기존 공고 변경 감지, 403/429 즉시 중지·재시도 한도, 요청 상한, T61 승인 게이트(만료 포함), 야간 키워드 간 조기 중복 제거·Skipped 사유·COUNT_MISMATCH(PR #371).

## 8. PostgreSQL 통합 테스트

실행 스크립트: `scripts/windows/run-crawler-tests.ps1 -Suite all` (CI `crawler-mvp.yml`의 PG 단계와 동일 모듈·동일 opt-in 변수·동일 역할).

| 단계 | main @ 사용자 클러스터 5432 | PR #371 @ 일회성 클러스터 5433 |
|---|---|---|
| pg-gcp-sync (`local_gcp_sync_pg`) | NOT_RUN (5432에 일회성 superuser 없음) / **5433에서 main 실행: 9 ran, 1 ERROR** | **12 ran, OK** |
| pg-html-integration | 2 OK | 2 OK |
| pg-staging-mode | 1 OK | 1 OK (5432에서 PR 코드로 실행) |
| pg-t64-integration | 14 OK | 14 OK |
| pg-t64-permissions | 1 OK | 1 OK (5432에서 PR 코드로 실행) |
| pg-night-executor-caller | 16 OK (skip 1) | 16 OK (skip 1) |
| pg-night-integration | 10 OK | 13 OK |
| pg-t155-admin-read / t152 audit / t155 admin-write | 3 / 2 / 6 OK | 3 / 2 / 6 OK |
| pg-night-e2e (`staging_night_e2e`, mocked HTTP) | 7 OK | 7 OK |
| docker-caller-container | NOT_RUN (Docker 없음) | NOT_RUN |
| 합계 | 62 PASS, 외부 요청 0 | 77 PASS, 외부 요청 0 |

**BASELINE_FAILURE (신규 환경 오류 아님):** main의 `local_gcp_sync_pg.test_08_scheduled_guards` — `KeyError: 'inserted'`. 테스트가 주입한 "다음 날" 2026-11-16 08:05 KST를 실제 시계가 지나면서 깨지는 날짜 의존 결함이며, 깨끗한 클러스터에서 main으로 재현했고 PR #371(`fix gcp-sync time bomb`)에서 통과한다.
5433은 이 검증만을 위해 만든 일회성 클러스터(생성 비밀번호, 127.0.0.1)이며 사용자 클러스터와 분리. `pg-staging-mode`/`pg-t64-permissions`는 코드가 `db:5432`를 하드코딩하므로 5432에서만 적용된다(5433에서 시도 시 5432로 접속해 인증 거부됨 — 안전장치 정상).

PM 필수 항목 대응:

| 항목 | Evidence |
|---|---|
| 신규 INSERT / 재실행 중복 INSERT 없음 / 제목·날짜 변경 UPDATE | 9절 E2E Row 조회 + `local_html_pg_integration`, `local_t64_integration` |
| 키워드 간 중복 처리, 외부 ID 정합성 | `local_night_integration`(PR #371 조기 중복 제거 +3건), `staging_night_e2e` |
| 파싱 실패 제외 | 9절 `errors=[{stage: parse, reason: HtmlPostingError}]`, DB 미저장 |
| Skipped 사유 저장 / COUNT_MISMATCH | PR #371 `local_gcp_sync_pg` test_02(`skipped_by_source`, `skipped_items`), test_10(`COUNT_MISMATCH` 시 쓰기 0) |
| 트랜잭션 롤백 | `verify_local_db.py` 프로브, gcp-sync test_05, staging-mode 롤백 테스트 |
| 실행 중 중단 후 재시도 / 재접속 | `local_t154_night_executor`·`local_t64_integration`(WORKER_CRASH/timeout·재시도 예산), 10절 PG 정지 후 복구 |
| 실행 이력 / 요약 메시지 | `runs`·`run_events` Row (10절), `staging_night_e2e` 요약(Slack은 캡처 sender, 실제 송신 없음) |

## 9. 로컬 E2E (Fixture HTML → Parser → Normalizer → Posting Store → PostgreSQL → REST API)

`scripts/windows/local_e2e.py` (런타임 계정 `crawler_local`). HTML은 `crawler/fixtures/jobkorea_user_detail_jsonld.html`에서 예약된 합성 ID(99884076x)와 제목 표식 `[LOCAL-E2E 3b38e3cc]`로 생성. CLI는 실제 진입점 `python -m crawler.jobs.import_jobkorea_html --url … --html …`(HTML 지정 시 HTTP 없음).
Evidence: `C:\dev\crawler-data\logs\e2e-20261116-135350\evidence.json` → **status PASS (11/11 checks)**

| 단계 | 입력 | 종료코드 | 결과 |
|---|---|---|---|
| 1 최초 | A, B, 파싱불가 C, A 중복 | 1 (invalid 있음 → 설계대로) | inserted 2, duplicates 1, invalid 1 (`stage=parse, HtmlPostingError`), DB Row 2 |
| 2 동일 재실행 | A, B | 0 | inserted 0, **unchanged 2**, Row 2 유지 |
| 3 변경 | A 제목 변경, B 마감일 변경 | 0 | **updated 2**, A 제목 `시니어 …`, B `expires_on` 2027-01-31 → **2027-03-31**, `updated_at` 증가 |
| 4 API | `GET http://127.0.0.1:<port>/jobs/collected?title=<표식>` (uvicorn `backend.training_jobs_api:app`) | — | **HTTP 200**, 2건, 제목이 DB와 일치, `source_code=jobkorea_imported`, `evidence=imported_html` |
| 4 API 입력검증 | `employment_type=not-a-type` | — | **HTTP 422** |
| 로그 | uvicorn 로그 | — | Traceback/ERROR 0 |
| egress | 모든 CLI | — | `EGRESS_ATTEMPTS=0` |

참고: `/jobs/collected` 응답 모델에는 `expires_on` 필드가 없어 API 응답에서는 null — 마감일 변경은 DB Row로 확인.
크롤러 DB(`ai_career_crawler_training`)와 서비스 DB(career 스키마)는 분리. **서비스 Backend(`backend/app`, career 스키마) API E2E와 Playwright 화면 테스트는 NOT_RUN** (서비스 DB 미구성·Node 미설치; 운영 스키마를 학습 DB에 섞지 않음).

## 10. Windows 스케줄러

선택: **A. Windows Task Scheduler** — Docker(B)·WSL2(C)는 이 PC에 없고 설치에 관리자 권한·재부팅이 필요. Task Scheduler는 관리자 없이 등록 가능하고 구성 요소가 가장 적다.

| 구성 | 내용 |
|---|---|
| `scripts/windows/register-fixture-task.ps1` | `AICP-Crawler-Fixture`(N분 반복, EndBoundary=승인 만료), `AICP-LocalPostgres-AtLogon`(로그온 시 PG 기동). 현재 사용자, Interactive, Limited |
| `scripts/windows/scheduled-fixture-run.ps1` | 안전 세션 → 승인/만료(자동 OFF) → 이름 있는 mutex → PG 기동 → LIVE/enabled 스케줄 있으면 거부 → `dispatcher dispatch`(systemd ExecStart와 동일) → `dispatcher manual-fixture`(FIXTURE 1건) → JSONL 로그 |
| 중복 실행 방지 | Task Scheduler `MultipleInstances=IgnoreNew` + mutex `Local\AICP-Crawler-Fixture`(프로세스 사망 시 OS가 해제) + dispatcher 자체 DB advisory lock |
| egress | `egress_guard/sitecustomize.py`로 dispatcher가 띄우는 worker 자식까지 가드 적용 |
| 로그 | `C:\dev\crawler-data\logs\scheduler\fixture-YYYYMMDD.jsonl` + 실행별 폴더 |

실측 (2분 간격, 1시간 유효로 등록):

| 시나리오 | 결과 |
|---|---|
| Task Scheduler **자동 트리거** 13:58:43, 14:00:44 | 둘 다 `SUCCEEDED`, `LastTaskResult=0`, `NumberOfMissedRuns=0`; dispatch `IDLE/NOT_DUE_OR_DISABLED`, night `DISABLED`, manual-fixture `SUCCEEDED`(runs: fetched 2, duplicate 2), Slack `DISABLED`, Python 프로세스 5개 egress 0 |
| 중복 실행 | 25초 점유 중 두 번째 실행 → `SKIPPED_LOCKED` (`ANOTHER_RUN_IN_PROGRESS`), 첫 실행 `SUCCEEDED` |
| 실패 처리 | 존재하지 않는 포트 지정 → `FAILED`, `SCHEDULE_READ_FAILED`, 종료코드 1 기록 |
| 장애 후 복구 | PG 정지 상태에서 실행 → 스크립트가 PG 기동 후 `SUCCEEDED`; postings md5 동일, runs 5→6, run_events 19→23 |
| 승인 만료 → 자동 OFF | 만료 시각을 과거로 바꾸고 `Start-ScheduledTask` → `AUTO_OFF`, 작업 스스로 **Disabled**, `LastTaskResult=3` |
| 승인 파일 없음 | `AUTO_OFF`, 종료코드 3 |
| 로그온 PG 작업 | 수동 트리거 `LastTaskResult=0`, `pg_isready` accepting |
| 실제 재부팅·로그온 트리거 | **NOT_RUN** (재부팅 필요) |
| 로그오프 상태 실행 | **미구성** — S4U/저장 비밀번호 등록에 관리자 PowerShell 필요 |

현재 상태: `AICP-Crawler-Fixture`는 자동 OFF로 **Disabled**, `AICP-LocalPostgres-AtLogon`은 Ready. LIVE 작업은 등록하지 않았다. DB `schedules`: `jobkorea-daily mode=fixture enabled=false`.

## 11. 외부 HTTP 요청 여부

- 크롤링 대상 사이트·GCP·Slack 요청: **0건** (모든 테스트/E2E/스케줄 실행 `EGRESS_ATTEMPTS=0`, dispatcher `external_requests=0`, Slack `DISABLED`/`NOT_CONFIGURED`).
- 환경 구축을 위한 다운로드만 발생: python.org(winget), get.enterprisedb.com(PG ZIP), PyPI(requirements 고정 버전).
- 기존 Staging 서버 접속·변경 없음, GCP Cloud SQL 접속·변경 없음.

## 12. 운영 서버 전환 계획 (PM 승인 후 수행, 이번에는 미수행)

1. **사전 준비(신규 PC)**: 현재 로컬 DB에는 통합 테스트 Row가 남아 있으므로(CI와 동일 동작) 전환 전 `pg_dump -Fc`로 보관 후 `ai_career_crawler_training`을 비우고 `bootstrap_local_db.py`로 재구성. Staging용 자격증명은 이 PC로 복사하지 않고 새로 발급.
2. **백업(기존 서버, 디스크 100%)**: 서버 디스크에 파일을 만들지 않고 SSH 스트림으로 신규 PC에 직접 저장 — `docker compose exec -T db pg_dump -Fc -n crawler_training -d ai_career_crawler_training` 출력을 신규 PC 파일로 받음. 실행 전 Staging 크롤러 타이머/야간 작업이 멈춰 있는지(또는 실행 창 밖인지) 확인해 일관된 스냅샷 확보.
3. **무결성**: 신규 PC에서 SHA-256 기록, `pg_restore --list` 성공, 테이블별 `count(*)`와 `postings`의 `(source_code, external_posting_id)` 집합 해시를 원본(읽기 전용 SELECT)과 비교.
4. **복원**: `pg_restore --no-owner --role=crawler_student -d ai_career_crawler_training` (18.1 → 18.7, 같은 메이저). 복원 후 마이그레이션 0002~0012 재적용(멱등)으로 GRANT 보정, `verify_local_db.py` 재실행.
5. **보존 항목**: 외부 공고 ID(PK 그대로), `keyword_posting_discoveries`/`keyword_checkpoints`(중복 방지·증분 상태), `runs`/`run_events`/`night_*`(실행 이력·Slack 중복 통지 원장)를 모두 포함해 이전.
6. **Slack**: 새 PC 전용 Webhook을 새로 발급(기존 값 재사용 금지), `SLACK_WEBHOOK_URL`로만 주입. 루트 `.env`의 레거시 `SLACK_WEBHOOK_RUL`은 코드가 읽는 이름이므로 런타임 환경에 절대 로드하지 않는다.
7. **T61 승인 정책**: 승인 JSON은 비공개 파일로 별도 전달하고 만료일을 재확인. 신규 PC에서는 PM 승인 전 `CRAWLER_LIVE_SCHEDULE_APPROVED`/`CRAWLER_NIGHT_ENABLED` 미설정 유지.
8. **중복 실행 방지(전환 순서)**: ① Staging 타이머 비활성(PM 승인) → ② 최종 백업·복원·검증 → ③ 신규 PC 스케줄 활성 → ④ Staging은 즉시 삭제하지 않고 정지 상태로 보존. 두 서버가 동시에 활성인 구간을 두지 않는다.
9. **GCP Sync 전환**: 신규 PC용 Sync 계정·인증서를 새로 발급, `dry-run` → 건수 비교 → `run` 순서. 기존 서버 Sync 정지 확인 후 1회만 활성.
10. **롤백**: 신규 PC 이상 시 신규 스케줄 비활성 → Staging 타이머 재활성(디스크 확보 전제). 전환 후 신규 PC에서 쌓인 Row는 같은 덤프 절차로 역이전 가능.
11. **상시 실행**: 운영 전환 시 로그오프 상태 실행(S4U)과 PG 서비스 등록은 관리자 권한으로 별도 설정.

일 1,000건 확장은 이번 환경 구축과 별개다. 현재 정책(6개 키워드 × 첫 페이지 × 최대 5 상세, ≤126 요청)에서는 불가능하며, 페이지네이션·고유 ID 집계·중복률·요청 예산은 LIVE 확대 승인과 함께 별도 설계한다(외부 요청 확대 없음).

## 13. 남은 문제 / 보안 항목

| 구분 | 내용 | 필요 조치 |
|---|---|---|
| 보안 | 루트 `.env`에 Staging SSH·GCP DB 비밀번호·Slack Webhook이 평문으로 이 PC에 있음. Git 추적·이력에는 없음(`git log --all` 확인, 값 스캔 0건). ACL은 현재 사용자+SYSTEM으로 제한함 | 운영 자격증명은 이 PC에 필요 없으므로 PM 판단하에 **교체(rotation)** 및 이 PC에서 제거 권고 (`docs/ops/SECRET_ROTATION_RUNBOOK.md`). 이번 작업에서 운영 자격증명 교체는 하지 않음 |
| 보안 | `STAGING_SSH_PASSWORD`가 4자리 — 이력 스캔이 결정적이지 않을 만큼 짧고 약함 | 키 기반 인증 전환·교체 권고 |
| 보안 | `SLACK_WEBHOOK_RUL`은 코드가 읽는 레거시 이름 | 런타임에 루트 `.env` 로드 금지 (스크립트가 강제) |
| 환경 | Docker/WSL2 미설치 → 컨테이너 테스트 NOT_RUN | 필요 시 관리자 권한·재부팅·Docker Desktop 라이선스 확인 후 설치 |
| 환경 | Node.js 미설치 → `frontend_collected_test.cjs`, Playwright NOT_RUN | 필요 시 설치 |
| 환경 | 로그오프 상태 실행, 실제 재부팅 테스트 미수행 | 관리자 권한 / 재부팅 필요 |
| 코드 | PR #371 미병합. main에는 gcp-sync 날짜 의존 BASELINE_FAILURE 존재 | 독립 리뷰 후 병합 |
| 데이터 | 로컬 DB에 통합 테스트·E2E Row 존재 | 이전 전 12절 1단계 |
| 도구 | `gh` CLI 미설치 | PR은 웹에서 생성 |

## 14. 완료 조건 판정

| 조건 | 판정 | 근거 |
|---|---|---|
| 독립 PostgreSQL 18.7 연결 | PASS | 5·6절 |
| Fixture 데이터 저장 | PASS | 9절, 10절 runs |
| 같은 공고 중복 INSERT 방지 | PASS | 9절 2단계, PK 위반 거부 |
| 변경 공고 UPDATE | PASS | 9절 3단계 |
| 실행 결과·Skipped 사유 기록 | PASS | runs/run_events(10절), parse 오류 기록(9절), Skipped 사유·COUNT_MISMATCH(PR #371 코드, 8절) |
| 자동 실행 테스트 | PASS (로그인 상태 한정) | 10절 — 재부팅·로그오프 실행은 NOT_RUN |

## 재현 명령 (PowerShell, 저장소 루트)

```powershell
# 0) PG 기동 + 세션 준비 (루트 .env는 로드되지 않음)
.\scripts\windows\start-local-postgres.ps1
. .\scripts\windows\crawler-local-env.ps1
# 1) 역할·스키마 (최초 1회, .env의 *_LOCAL 관리자 계정 사용; 멱등)
.venv\Scripts\python.exe scripts\windows\bootstrap_local_db.py
# 2) DB·권한 검증
.venv\Scripts\python.exe scripts\windows\verify_local_db.py
# 3) 단위 + PG 통합 테스트 (요약: C:\dev\crawler-data\logs\tests-*\summary.json)
.\scripts\windows\run-crawler-tests.ps1 -Suite all
# 4) E2E
.venv\Scripts\python.exe scripts\windows\local_e2e.py
# 5) FIXTURE 스케줄 등록 / 제거
.\scripts\windows\register-fixture-task.ps1 -IntervalMinutes 5 -ValidHours 24
.\scripts\windows\register-fixture-task.ps1 -Unregister
# 일회성 검증 클러스터 (예: 다른 포트·데이터 경로, 생성 비밀번호)
$env:AICP_DATA_ROOT='C:\dev\crawler-data-pr371'; $env:AICP_PG_PORT='5433'; .\scripts\windows\setup-local-postgres.ps1
```
