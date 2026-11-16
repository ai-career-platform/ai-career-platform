# 크롤러 LIVE 1회 · GCP 이관 1회 · 일 신규 1,000건 (AI_CAREER_CRAWLER_LIVE_GCP_1000, 2026-11-16)

판정 원칙: 실제로 수행한 것만 PASS.

- 승인이 없어 실행하지 않은 것은 `BLOCKED`, 측정하지 않은 것은 `NOT_MEASURED` 로 적는다.
- 로컬 Fixture·PostgreSQL 결과를 GOAL 1~3 의 PASS 로 대체하지 않는다.
- 비밀번호·접속 문자열·호스트 값은 기록하지 않는다.

이번 작업의 외부 접촉:

| 대상 | 결과 |
|---|---|
| JobKorea HTTP 요청 | **0건** (robots.txt 포함) |
| GCP Cloud SQL 접속 | **0회** |
| Staging 서버 | 변경 없음, 접속 없음 |

## 요약

| 목표 | 판정 | 근거 |
|---|---|---|
| GOAL 1 실제 LIVE 크롤링 1회 | **BLOCKED** | 유효한 T61 승인 없음. T61 상태 `HOLD`, 권한 문의는 `DRAFT_NOT_SENT`, 이 PC에 승인 파일 없음. 실행 경로와 사전 점검(preflight)은 준비 완료(2절) |
| GOAL 2 GCP Cloud SQL 이관 1회 | **BLOCKED** | GCP 쓰기 승인 없음. 이 PC에는 전용 `career_sync` 자격증명·CA 인증서·인증서 호스트명이 없음. 루트 `.env` 의 `*_GCP` 는 관리자 계정이라 동기화 코드가 거부함. 로컬 Source 경로와 실데이터 Dry-run 절차는 구현·테스트 완료(3절) |
| GOAL 3 일 신규 1,000건 | **PARTIAL** | 수집량 개선 10개 항목 구현. 로컬 PostgreSQL 에서 신규 1,050건 INSERT·중복 방지·성능 실측 PASS. **실제 사이트 공급량과 일 신규 실적은 `NOT_MEASURED`**(4절) |

## 1. 최신 상태 재확인

- 브랜치 `feat/crawler-windows-local-pc`, 기존 HEAD `062f929` (origin 과 일치). main `1797f4c`. PR #371 미병합.
- 로컬 DB(5432) 공고 출처별 건수: `jobkorea` 2, `jobkorea_imported` 14, `jobkorea_live` 26.
  - `jobkorea_live` 26건은 **모두 mock HTTP 통합 테스트가 만든 행**입니다(실제 LIVE 실행 0회).
  - 기존 Staging 방식 동기화는 `source_code='jobkorea_live'` 만 보고 고르므로, 이 DB 를 그 방식으로 Source 로 쓰면 테스트 행이 운영 GCP 로 넘어갑니다. 3절의 출처 원장(provenance) 필터로 차단했습니다.
- 도구: `gcloud`·`cloud-sql-proxy`·`gh`·`docker` 없음. `ssh` 는 있으나 사용하지 않았습니다.

## 2. GOAL 1 — LIVE 실행 경로 검증

| # | 항목 | 확인 결과 |
|---|---|---|
| 1 | T61 승인 정책 | `crawler/policy/source_approval_gate.py`: 승인 기록 없음·HOLD·만료·비활성·근거 누락·목적 불일치·URL 범위 밖·요청 상한 초과이면 모두 거부합니다. `T61_STEP10`: 문의 `DRAFT_NOT_SENT`, 회신 `NOT_RECEIVED`. `SOURCE_REGISTRY`: `candidate_jobkorea = HOLD`. **현재 유효한 승인 없음** |
| 2 | LIVE 활성화 조건 | 세 가지가 모두 필요합니다. ① 실행 세션의 `CRAWLER_LIVE_SCHEDULE_APPROVED=1` ② 비공개 승인 파일(`--policy-file`) ③ 모든 URL 이 게이트 `ALLOWED`. `crawler-local-env.ps1` 은 LIVE·GCP·Slack 변수를 매번 지웁니다 |
| 3 | 키워드·요청 한도 | 기존 야간 수집은 6키워드 × 첫 페이지 × 상세 5건, 1회 요청 7건, 하룻밤 126건까지입니다. 새 harvest 의 한도는 승인 기록의 `max_search_pages`·`max_harvest_details`·`max_requests` 를 넘을 수 없습니다(사전 점검에서 거부). LIVE 기본 키워드는 T61 야간 키워드 6개로 고정했습니다(아래 결함 2) |
| 4 | Ubuntu 서버와 중복 실행 | 저장소 문서 기준 Staging 의 LIVE 변수 3개는 UNSET 이고 Dispatcher 는 fixture 전용입니다. **서버에 직접 접속해 확인하지는 않았습니다.** 승인 B 실행 전에 PM 이 Staging LIVE 비활성을 확인해야 합니다. PC 안에서는 dispatcher advisory lock (642, 0) 을 공유해 fixture·야간·harvest 가 겹치지 않습니다(테스트 PASS) |
| 5 | 실제 사이트 접근 권한 | 없음. robots.txt 일반 규칙은 `GI_Read` 를 막지 않지만 `/Search` 경로 허용은 검토되지 않았습니다(T61 STEP05). 약관 검토와 권한 문의는 미완료입니다 |
| 6 | 저장 위치 | 로컬 `ai_career_crawler_training.crawler_training.postings` (`source_code='jobkorea_live'`). 실행 이력은 `harvest_runs`/`harvest_pages`/`harvest_items` (마이그레이션 0013, 5432 에 적용) |
| 7 | 크롤러 로그 | 실행별 JSON 결과(stdout)와 DB 실행 이력 3개 테이블에 남깁니다. 상태 보고서 `crawler-status.json` 에 `harvest_today`, `harvest_live_runs_total` 이 표시됩니다 |
| 8 | 승인 만료 시 자동 OFF | 매 요청 직전에 `review_due_utc` 를 확인합니다. 만료되면 `UNAPPROVED_SOURCE` 로 중단하고 요청은 0건입니다(단위 테스트). 실행 마감 시간과 요청 예산도 매 요청 전에 검사합니다 |

**사전 검증 실측 (승인 없이 가능한 범위)**

- `harvest live --check` (승인 파일 없음): `ok=false`, `APPROVAL_FILE_MISSING_OR_INVALID`, `external_requests=0`.
- 실행 시도: 사전 점검 실패로 중단, 요청 0건.
- 저장소의 요청서 양식(`templates/t61-harvest-approval.REQUEST.json`, HOLD)은 게이트가 `NOT_APPROVED` 로 거부합니다.
- 같은 양식을 APPROVED 로 채우면 7요청까지만 허용하고 8요청은 거부합니다.
- 유효한 승인 파일이 있어도 `CRAWLER_LIVE_SCHEDULE_APPROVED=1` 이 없으면 `PM_ACTIVATION_REQUIRED` 로 중단합니다(요청 0건).

**발견·수정한 결함**

1. `crawler-status.ps1`:
   - 예약 Fixture 실행(`AICP_NO_EGRESS=1`)이 상태를 갱신하면 egress 가드의 `EGRESS_ATTEMPTS=0` 줄이 JSON 에 섞였습니다.
   - 그 결과 DB 상태 파싱이 실패했고, `@($null | …)` 이 1로 세어져 **거짓 `LIVE_PRESENT`/ATTENTION** 이 표시됐습니다.
   - 수정: stderr 를 분리하고 null 에 안전하게 셉니다. `reboot-check.ps1` 의 snapshot 도 같은 방식으로 수정했습니다.
   - 수정 후 `AICP_NO_EGRESS=1` 에서도 `health=OK` 입니다.
2. harvest LIVE 기본 키워드를 DB 의 활성 키워드에서 가져오면, 테스트가 남긴 키워드(`T155 …`, `night-…`, `synthetic-night-…`)가 포함됐습니다. LIVE 기본값을 T61 야간 키워드 6개로 고정했습니다. `--keyword` 를 주면 그 값만 씁니다.
3. 승인 파일 로더가 `_comment` 같은 주석 키를 오류로 처리했습니다. 이제 `_` 로 시작하는 주석 키는 무시하고, 그 밖의 모르는 키는 계속 거부합니다.

**승인 B 를 받은 뒤 1회 실행 절차** (요청 7건: robots 1 + 검색 1 + 상세 5)

```powershell
. .\scripts\windows\crawler-local-env.ps1
$p = 'C:\dev\crawler-data\secrets\t61-harvest-approval.json'   # PM 이 채운 승인 파일 (Git 밖)
& $VenvPy -m crawler.jobs.harvest live --policy-file $p --keyword AX --pages 1 --new 5 --max-requests 7 --check
$env:CRAWLER_LIVE_SCHEDULE_APPROVED = '1'
& $VenvPy -m crawler.jobs.harvest live --policy-file $p --keyword AX --pages 1 --new 5 --max-requests 7
Remove-Item env:CRAWLER_LIVE_SCHEDULE_APPROVED
```

실행 후 검증 SQL:

```sql
SELECT status, stop_reason, http_requests, inserted, updated, unchanged, failed
FROM crawler_training.harvest_runs WHERE run_id = '<run_id>';
```

`harvest_items` 의 outcome 별 건수와 postings 신규 행도 함께 확인합니다.

## 3. GOAL 2 — 로컬 Source → Cloud SQL 이관 경로

| 항목 | 구현·확인 |
|---|---|
| Local Source DB | `GCP_SYNC_SOURCE=local`. loopback `crawler_local` 연결(`validate_local_dsn`), READ ONLY. `CRAWLER_DB_MODE=staging` 이면 거부합니다 |
| Cloud SQL Target | 기존 #337 경로 그대로입니다. TLS `verify-full`(인증서 호스트명 + hostaddr + 인스턴스 CA), `ai_career_poc`, 연결 직후 신원 확인(DB·사용자·SSL·비 superuser) |
| 전용 동기화 계정 | `career_sync` (`target_grants.sql`: DELETE·DDL 없음). `postgres`/`cloudsqlsuperuser`/`cloudsqladmin` 은 코드가 거부합니다. **루트 `.env` 의 `*_GCP` 계정은 관리자 등급이라 사용할 수 없고, 사용하지 않았습니다** |
| 데이터 매핑 | 기존 `map_row`(normalizer 재검증, KST 날짜 경계, 컬럼 길이 제한) |
| External Posting ID·중복 방지·UPSERT | `career.job_posting_external_refs (source_id, external_id)`. 신규는 INSERT, 바뀐 필드만 UPDATE, 같으면 쓰지 않음, 삭제 없음 |
| Draft 유지 | `GCP_SYNC_PUBLISH` 기본값 0 → `draft` 저장 (API 비노출) |
| ROLLBACK | 실행 1회가 Target 트랜잭션 1개입니다. 오류가 나면 전체 롤백하고 실행 기록을 `failed` 로 남깁니다. 로컬 실행 결과에 `inserted_external_ids` 를 남겨, 실행 범위만 되돌리는 SQL 을 만들 수 있습니다(6절 C) |
| 기존 스케줄과 중복 실행 방지 | 로컬 Source 는 `scheduled` 를 거부합니다(1회 실행 전용). Target advisory lock `337001` 로 Staging cron 과 동시에 돌지 않습니다. 크롤러·harvest 가 RUNNING 이면 건너뜁니다 |
| **Fixture·테스트 행 차단** | 지정한 LIVE harvest 실행(`mode='live'`, 종료됨, `http_requests > 0`)이 `harvest_items` 에 기록한 공고만 선택합니다. fixture 실행, HTTP 0 실행, 원장에 없는 `jobkorea_live` 테스트 행, 실패 항목은 제외합니다 |
| Source/Target 일치 | 새 `verify` 모드는 양쪽 읽기 전용으로 선택된 모든 행을 비교합니다(matched / missing / mismatched) |

**로컬 실측** (일회용 클러스터 5434 의 가짜 Target, 운영 아님): `local_gcp_sync_local_source_pg` 7/7 PASS.

- 부적격 실행 ID(fixture / HTTP 0 / 없는 ID / 혼합 / 빈 목록)는 Target 쓰기 전에 거부됩니다.
- Dry-run 은 원장의 2건만 선택하고(테스트 오염 6건, 실패 1건, fixture 1건, HTTP 0 실행 1건 제외) 쓰기 0입니다.
- 실행: INSERT 2, draft, `inserted_external_ids=[101,102]`.
- `verify` `source_target_match=true`. 재실행은 중복 2(쓰기 0). Source 변경 후 `verify` 는 `101:title` 불일치를 탐지합니다.
- harvest RUNNING 이면 `CRAWLER_BUSY` 입니다.
- 실행 종료 뒤 다시 쓰인 행(`updated_at > ended_at`, 예: 같은 ID 를 쓰는 mock 테스트)은 선택하지 않습니다.
- 기존 `local_gcp_sync_pg` 는 9건 중 8 PASS. 나머지 test_08 은 기존 결함입니다(main 과 같은 파일): 오늘 날짜(2026-11-16)에 묶인 time-bomb 이며 PR #371 에서 수정됐습니다.

**실데이터 Dry-run 준비**: `scripts\windows\run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId <id>`.

- 설정 파일 `C:\dev\crawler-data\secrets\gcp-sync.env` 와 CA 파일이 없으면 `BLOCKED` 로 끝나며 Target 에 접속하지 않습니다(실측: `GCP_SYNC_ENV_FILE_MISSING`).
- 설정 파일 ACL 이 본인·SYSTEM·Administrators 외에 열려 있으면 거부합니다. 허용된 키만 읽고, 비밀값은 자식 프로세스 환경변수로만 넘깁니다. 루트 `.env` 는 읽지 않습니다.
- 양식: `scripts/windows/templates/gcp-sync.env.example`.

**추가 위험 (확인 필요)**: Staging 방식은 출처 필터 없이 `jobkorea_live` 전체를 고릅니다.

- 이전 보고(CRAWLER_LIVE_TEST_01)에 Staging DB 공고 35건(2/28/5)이 기록돼 있는데, 그중 `jobkorea_live` 가 테스트 E2E 행이라면 Staging cron 동기화가 그 행을 GCP 로 복사할 수 있습니다.
- 권고: Staging GCP Sync cron 을 계속 비활성으로 두고, 로컬 Source 모드로 전환합니다.

## 4. GOAL 3 — 일 신규 1,000건 수집량 개선

### 4.1 기존 구조의 상한

`night_crawl`: 키워드 6 × 검색 1페이지 × 상세 5, 시도 3회, 요청 7 → 하룻밤 최대 신규 30건, 요청 126건. **1,000건 불가.**

### 4.2 구현 (`crawler/jobs/harvest.py`, 마이그레이션 0013, 게이트 확장)

| # | 요구 | 구현 |
|---|---|---|
| 1 | 검색 페이지네이션 | 키워드별 `max_pages` (게이트 상한 50), 페이지 단위 라운드로빈. 페이지 URL `…&tabType=recruit&Page_No=N`. **매개변수 이름 `Page_No` 는 실사이트에서 검증되지 않았습니다**(승인 B 첫 실행에서 확인 필요) |
| 2 | 외부 공고 ID 조기 추출 | 결과 페이지 링크 `/Recruit/GI_Read/<id>` 에서 상세 요청 전에 ID 확보 (`parse_jobkorea_result_page`, 페이지당 200 상한) |
| 3 | 기존 공고 중복 선별 | 페이지마다 DB 조회 1회(`external_posting_id = ANY(...)`). 이미 있는 공고는 상세를 요청하지 않음 |
| 4 | 키워드 간 중복 제거 | 실행 안에서 이미 본 ID 는 `cross_duplicates` 로 세고 다시 처리하지 않음 |
| 5 | 신규 우선 상세 조회 | 계획 = 신규(`max_new_details`) → 재확인(`max_revisits`) 순. 요청 예산은 계획된 상세 몫을 먼저 확보하고 남는 만큼만 페이지를 넘김 |
| 6 | 변경 감지 재확인 | 다시 나타난 기존 공고 중 `revisit_after_hours` 동안 확인하지 않은 것을 오래된 순으로 재조회합니다. 바뀌면 UPDATE, 같으면 unchanged |
| 7 | 키워드별 신규 발견률 | `keyword_stats.new_rate` (실행별, `harvest_runs`) |
| 8 | 페이지별 결과 수 | `harvest_pages` (links / new / known / cross_duplicates / error_code) |
| 9 | INSERT·UPDATE 구분 | `harvest_items.outcome` = inserted / updated / unchanged / failed. 실행 합계도 기록 |
| 10 | 일일 수집량 모니터링 | `harvest report` (KST 일별, mode 별, 목표 1,000 달성 여부). 상태 보고서의 `harvest_today` |
| + | 공급량 측정 모드 | `--new 0 --revisits 0`: 검색 페이지만 읽고 신규 ID 공급량만 셉니다(상세 요청 0). 승인 D 1단계용 |
| + | 안전장치 | 페이지·상세 URL 마다 게이트 검사, robots, 2초 이상 간격, 리다이렉트 차단, 401/403/429/CAPTCHA 시 중단, 요청 예산, 승인 만료, 실행 마감, dispatcher lock, 동시 RUNNING 1개(유니크 인덱스), 죽은 실행 자동 종료(`HEARTBEAT_TIMEOUT`) |

게이트 변경은 opt-in 입니다.

- 기본값 `max_search_pages=1`, `max_harvest_details=0` 이고, 목적은 `harvest_collection` 전용입니다.
- 기존 야간 승인(`night_keyword_collection`, 발견 상세 ≤5)은 전과 똑같이 동작합니다. 기존 게이트 테스트는 수정 없이 PASS 이며, 야간 승인으로 harvest 를 할 수 없음을 테스트로 확인했습니다.

### 4.3 로컬 실측 (Fixture + 일회용 PostgreSQL 5434, `crawler_staging` 권한, egress 0)

합성 fixture: 키워드 6 × 10페이지 × 20링크 = 1,200 링크, 키워드 간 중복 150, 고유 1,050.

| 실행 | 결과 |
|---|---|
| 1회차 (CLI) | SUCCEEDED · 페이지 60 · 신규 1,050 · 중복 150 · 계획 1,050 · **INSERT 1,050** · 실패 0 · 1.67초(**628건/초**) · HTTP 0 |
| 2회차 (같은 입력) | SUCCEEDED · 신규 0 · **상세 요청 0** · 키워드당 2페이지 후 중단(읽기 12) · DB 변화 없음 |
| 키워드별 신규율 | AX 1.00, 나머지 0.85 (각 30건이 AX 와 중복) |
| 재확인 | 오래된 30건 재조회 → updated 1 (제목 변경), unchanged 29 |
| 상세 404 | PARTIAL, failed 1, `HTTP_404` 기록 |
| 동시 실행 | dispatcher lock 보유 중 → `SKIPPED DISPATCHER_LOCKED`, 요청 0 |
| 예산 60 | 사용 ≤ 60, 계획한 상세는 모두 처리 |
| 공급량 측정 | 페이지 60, 신규 ID 1,050, 상세 0 |

증거: `C:\dev\crawler-data-goal3\logs\harvest-evidence\` (`run1.json`, `run2.json`, `report.json`), `…\logs\tests-*\summary.json`.

**이 결과는 처리량·중복 방지·페이지 로직의 증거일 뿐이며, 실제 사이트에서 신규 1,000건을 확보했다는 증거가 아닙니다.**

### 4.4 실현 가능성

- **처리 쪽**: 1,000건 INSERT 는 로컬에서 약 2초입니다. 병목은 요청 간격입니다.
  - 신규 1,000건에 필요한 요청 ≈ robots 1 + 검색 약 50~60 + 상세 1,000 ≈ 1,060건.
  - 최소 간격 2초면 약 35분이고, 응답 시간을 더해 약 45~60분입니다. 21:00~08:00 야간 창 1회로 충분합니다.
  - 마감 상한은 11시간이며 `--deadline-seconds` 로 정합니다.
- **공급 쪽 (`NOT_MEASURED`)**: 6개 AI·데이터 키워드가 매일 **새** 공고 1,000건을 공급하는지 알 수 없습니다.
  - 첫 실행은 쌓여 있는 공고를 한꺼번에 받으므로 1,000건을 넘을 수 있습니다.
  - 그 뒤의 일 신규는 시장의 신규 등록량에 달려 있고, 키워드 확대(DB 의 10개 이상)가 필요할 가능성이 큽니다.
  - 실측은 승인 D 1단계(공급량 측정 모드, 상세 0)로 합니다.
- **권한 쪽**: 하루 1,000건 이상의 상세 페이지 수집은 대량 수집입니다. 제공자 권한 확인(T61 문의 발송·회신)과 약관 검토가 선행돼야 합니다.
- **판정**: `DAILY_1000_FEASIBILITY = UNVERIFIED`. 코드는 준비됐고, 공급량과 제공자 권한이 결정합니다.

## 5. 테스트 결과 (이번 작업, 모두 egress 0)

| 묶음 | 결과 |
|---|---|
| 크롤러 단위 (`discover crawler/tests`) | **533 PASS** (skip 5: Linux 전용). 기존 515 + 신규 18 |
| backend training 단위 | 21 PASS |
| PG 전체 (일회용 5434, 새 클러스터) | gcp-sync-local-source 7/7, harvest-1000 9/9, html 2, t64 14, night executor·caller 16, night integration 10, t155 read 3, t152 2, t155 write 6, night e2e 7 PASS |
| 기존 결함 | `local_gcp_sync_pg` test_08 (time-bomb, PR #371 에서 수정) |
| 테스트 전제조건 | `local_t155_admin_read_pg` 는 빈 `runs` 테이블이 필요해, 같은 클러스터에서 두 번째 실행하면 실패합니다(새 클러스터 첫 실행 3/3 PASS, 이번 변경과 무관) |
| 해당 없음 / 미실행 | staging-mode·t64-permissions (`db:5432` 하드코딩), Docker (미설치) |
| 메인 DB 5432 재검증 | `verify_local_db` exit 0: 18.7, `crawler_local` 비 superuser, 테이블 20, PK/UNIQUE 28, DDL·DELETE·TRUNCATE·SET ROLE·다른 DB 접속 모두 거부. 상태 `health=OK`, `harvest_live_runs_total=0` |

## 6. 필요한 승인 (A~D)

| | 범위·대상 | 실행 시간 | 요청 상한 | 위험 | 롤백 |
|---|---|---|---|---|---|
| **A. Windows 관리자 설치 + 로그아웃·재부팅 검증** | 이 PC. 관리자 PowerShell 에서 `register-fixture-task.ps1 -Unattended` (S4U, 부팅 트리거), 로그아웃 → 재부팅 → `reboot-check.ps1 -Phase After` | 약 30분, 재부팅 1회 | 외부 요청 0 (fixture) | 재부팅 중 서비스 중단 수 분. S4U 작업은 네트워크 자격증명이 없음(로컬만 사용하므로 무관) | `register-fixture-task.ps1 -Unregister` 후 Interactive 로 다시 등록 |
| **B. 단발성 T61 LIVE 1회** | JobKorea 검색 `AX` 1페이지 + 상세 5건. 승인 파일: 요청서 양식을 APPROVED 로 채우고, `approved_by`, `evidence_ref`(권리 근거), 2시간 유효 | 승인된 2시간 안 1회, 약 1분 | **7** (robots 1 + 검색 1 + 상세 5), 재시도 없음, 차단 시 즉시 중단 | 약관·robots(`/Search` 미검토) 위반 가능성, IP 차단. 사전 조건: Staging LIVE 비활성 확인 | 데이터는 로컬에만 있고 GCP 이관은 C 전까지 없음. 삭제가 필요하면 owner(`crawler_student`)가 run_id 의 `harvest_items` 로 대상 공고를 정해 삭제(런타임 계정은 DELETE 권한 없음). 승인 파일 삭제 = 즉시 OFF |
| **C. 단발성 GCP Cloud SQL 쓰기 1회** | ① `career_sync` 자격증명, CA, 인증서 호스트명을 `secrets\gcp-sync.env` 에 등록(PM·DBA). ② Cloud SQL 허용 네트워크에 이 PC 공인 IP 추가(현재 미확인). ③ Target 에 `data_sources.code='jobkorea_live'` 존재 확인. ④ dry-run → run → verify, 승인 B 의 run_id 1개만 | 약 10분 | Target 트랜잭션 1회. INSERT ≤ B 수집 건수(≤5), draft | 운영 DB 쓰기. 실패하면 자동 롤백. 출처 필터로 테스트 행 차단 | `inserted_external_ids` 를 `career` owner 로 삭제: `DELETE FROM career.job_postings p USING career.job_posting_external_refs r, career.data_sources s WHERE r.job_posting_id=p.job_posting_id AND r.source_id=s.source_id AND s.code='jobkorea_live' AND r.external_id = ANY('{…}')`. 게시 전(draft)이므로 사용자 영향 없음 |
| **D. 실제 LIVE 수집량 확대** | 선행 조건: 제공자 권한 확인(T61 문의 발송·회신)과 약관·robots `/Search` 검토. 단계적으로 늘림. ① 공급량 측정: 6키워드 × 10페이지, 상세 0, 요청 ≤ 61. ② 상세 100건/일. ③ 300건/일. ④ 1,000건/일 (`max_search_pages` ≤ 10~20, `max_harvest_details` 1,000~1,200, `max_requests` ≈ 1,300/일) | 야간 21:00~08:00, 하루 1회 실행 | 단계별 위 값. 403/429/CAPTCHA 가 한 번이라도 나오면 그날 중단하고 다음 단계 보류 | 대량 수집에 따른 권리 침해·차단 위험, 공급 부족으로 목표 미달 가능 | 승인 파일 만료·삭제 = 다음 요청부터 차단. 단계 축소. 수집분은 C 절차로 따로 이관 |

## 7. 독립 리뷰 (diff 만 전달, 결론 미전달)

결과: 게이트를 우회해 승인 밖 URL 을 요청하는 경로와, 로컬 Source 동기화가 fixture·테스트 행을 고르는 경로를 **찾지 못함**. 지적 사항은 모두 반영했습니다.

| # | 지적 | 조치 |
|---|---|---|
| 1 (중) | 게이트가 `max_harvest_details` 를 직접 강제하지 않음(사전 점검에서만 검사) | 게이트: `requested_calls ≤ 1 + max_search_pages × 승인 검색 URL 수 + max_harvest_details`. `LiveSource` 는 실행 중에도 상세 수를 세어 승인값에서 `DETAIL_BUDGET` 으로 중단 |
| 2 (하) | 래퍼가 `-LiveRunId` 를 검사 없이 `cmd` 줄에 넣음 | UUID `ValidatePattern` 적용. ACL 설명을 실제 동작(본인·SYSTEM·Administrators)에 맞춤 |
| 3 (하) | 실행 행 생성 뒤 try 밖에서 예외가 나면 RUNNING 이 남을 수 있음. CLI 가 DB 오류를 JSON 으로 보고하지 않음 | 키워드·기준 시각 조회를 실행 행 생성 전으로 이동. CLI 는 모든 예외를 JSON 한 줄로 보고. 남은 행은 기존 `HEARTBEAT_TIMEOUT` 회수 |
| 4 (하) | 매우 긴 페이지 번호에서 `int()` 예외 | 페이지 번호 최대 3자리, 넘으면 거부(예외 없음) |
| 5 (하) | 원장이 (출처, ID)만 비교해 나중에 덮어쓴 payload 가 복사될 수 있음 | `postings.updated_at ≤ harvest_runs.ended_at` 조건 추가, PG 테스트 추가 |
| 6 (참고) | 승인 로더가 `_` 주석 키를 허용 | 의도된 변경(2절 결함 3). 그 밖의 모르는 키는 계속 거부 |

## 8. 이번 변경 파일

- 신규:
  - `crawler/jobs/harvest.py`
  - `crawler/storage/migrations/0013_harvest_runs.sql`
  - `crawler/tests/test_harvest.py`
  - `crawler/tests/local_harvest_pg.py`
  - `crawler/tests/local_gcp_sync_local_source_pg.py`
  - `scripts/windows/run-gcp-sync-local.ps1`
  - `scripts/windows/templates/t61-harvest-approval.REQUEST.json`
  - `scripts/windows/templates/gcp-sync.env.example`
- 수정:
  - `crawler/policy/source_approval_gate.py` (harvest 범위 opt-in)
  - `crawler/adapters/jobkorea_html_offline.py` (결과 페이지 전체 파서)
  - `crawler/jobs/gcp_sync.py` (로컬 Source, 출처 필터, verify)
  - `crawler/jobs/import_jobkorea_html.py` (주석 키 무시)
  - `scripts/windows/crawler-status.ps1`, `reboot-check.ps1` (JSON/stderr 분리, LIVE 표시)
  - `scripts/windows/verify_local_db.py` (harvest 지표)
  - `scripts/windows/run-crawler-tests.ps1` (새 PG 단계)
- 로컬 DB 5432: 마이그레이션 0013 적용 (owner `crawler_student`, 관리자 비밀번호 미사용, 기존 데이터 변화 없음).
- 일회용 클러스터 `C:\dev\crawler-data-goal3` (5434): 테스트 전용, 검증 후 정지.
