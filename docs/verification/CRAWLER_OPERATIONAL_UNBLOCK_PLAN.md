# 크롤러 운영 차단 요인 해소 계획 (AI_CAREER_CRAWLER_OPERATIONAL_BLOCKER_RESOLUTION, 2026-11-16)

판정 원칙: 실제로 수행한 것만 PASS. 승인이 없어 실행하지 않은 것은 `BLOCKED`, 측정하지 않은 것은 `NOT_MEASURED`.

이번 작업의 외부 접촉:

| 대상 | 결과 |
|---|---|
| JobKorea | **0건** |
| GCP Cloud SQL | **0회** |
| Staging | **접속 없음** |
| 재부팅·자격증명 교체·서비스 중단 | **없음** |
| GitHub | 읽기 전용 공개 API 조회만 |

## 0. 요약

| 목표 | 상태 | 이번에 해소한 것 | 남은 결정 |
|---|---|---|---|
| GOAL 1 LIVE 1회 | **BLOCKED** | 사업 목적의 공식 문의서와 발송 경로(api@jobkorea.co.kr), 대안 공급원 비교 | 문의 발송 승인 → 회신 → T61 승인 B |
| GOAL 2 GCP 1회 | **BLOCKED** (경로는 리허설 PASS) | `career_sync` 생성 SQL, TLS·CA·호스트명 절차. **TLS verify-full 실제 리허설**: 1,050행 dry-run→run→verify→재실행→롤백, 부정 사례 3종 | 운영 계정·CA 발급, PC IP 허용, 승인 C |
| GOAL 3 일 1,000건 | **PARTIAL** | 요청량 공식과 시나리오 표, 키워드 확장 후보, 비용 추정, 공식 API 대안 | 공급량 실측(승인 D-1) |
| **우선 위험** | **HIGH (미확인)** | Staging `jobkorea_live` 5건이 **실제 무승인 수집분일 가능성**을 커밋 시각으로 특정함(6절) | Staging 읽기 전용 점검, GCP Sync cron 상태 확인 |

## 1. 기존 환경 구축 완료 사항 (반복하지 않음)

- Windows 11 Pro, Python 3.12.10, PostgreSQL 18.7 (`C:\dev\crawler-data\pg18`), 최소 권한 `crawler_local`, 스키마와 마이그레이션 0002~0013.
- 자세한 내용: [CRAWLER_NEW_PC_SETUP_2026-11-16.md](CRAWLER_NEW_PC_SETUP_2026-11-16.md), [CRAWLER_WINDOWS_UNATTENDED_READINESS.md](CRAWLER_WINDOWS_UNATTENDED_READINESS.md), [CRAWLER_LIVE_GCP_1000.md](CRAWLER_LIVE_GCP_1000.md).
- 로그인 상태 스케줄러와 무인 안전성 시나리오 12종 PASS. harvest(페이지네이션·중복 제거·신규 우선)와 로컬 Source GCP Sync 구현 완료.
- 현재 HEAD: 브랜치 `feat/crawler-windows-local-pc` = origin = `7060409` 에서 출발했고, 이번 작업 커밋은 맨 아래에 기록합니다. main `1797f4c`, 브랜치는 main 보다 커밋 3개 앞서고 뒤처진 것은 없습니다.
- 메인 DB 상태: `health=OK`, LIVE run 0, harvest LIVE run 0, Fixture 작업은 Disabled(만료로 자동 OFF).

## 2. GOAL 1 차단 요인

| # | 차단 요인 | 근거 | 해소 조건 |
|---|---|---|---|
| 1 | 제공자 허가 없음 | 약관 제18조 ④ 등 사전 동의 제한(T61 STEP 06). API 약관 제5·7조가 DB 수집·저장과 충돌 | 5절 문의 → 서면 회신 |
| 2 | T61 `HOLD` | SOURCE_REGISTRY `candidate_jobkorea=HOLD` | 회신 범위 안에서 PM 이 승인 파일 작성 |
| 3 | `/Search` 경로 robots 미검토 | T61 STEP 05 는 `GI_Read` 만 검토 | 승인 B 직전에 robots.txt 를 사람이 확인(코드도 매 요청 검사) |
| 4 | Staging 동시 LIVE 여부 미확인 | 서버 접근 없음 | 6절 점검 |
| 5 | 페이지 매개변수 `Page_No` 미검증 | 실사이트 요청 0 | 승인 B 는 1페이지만, D-1 에서 확인 |

준비 완료 상태: 사전 점검 `harvest live --check`, 요청 7건 상한 실행 명령, 만료 시 자동 OFF, 요청서 양식(HOLD 상태로는 게이트가 거부).

## 3. GOAL 2 차단 요인

| # | 차단 요인 | 상태 |
|---|---|---|
| 1 | GCP 쓰기 승인 | 없음 (승인 C) |
| 2 | `career_sync` 계정 | 운영에 존재하는지 **미확인**(#337 문서에는 생성 절차만 있음). 생성 SQL 작성·리허설 PASS (7절 A) |
| 3 | CA 인증서·인증서 호스트명 | 이 PC 에 없음. 확보 방법 7절 C·D |
| 4 | PC → Cloud SQL 네트워크 | 미검증(접속 시도 0). 7절 E |
| 5 | 루트 `.env` `*_GCP` | 관리자 계정이라 코드가 거부합니다. **사용하지 않습니다.** 장기적으로 PC 에서 제거하거나 교체해야 합니다(PM 결정, 14절) |
| 6 | 이관할 실제 데이터 | GOAL 1 의 LIVE run 이 있어야 합니다(로컬 Source 는 LIVE run ID 로만 선택) |

## 4. GOAL 3 현재 상태

- 구현: 페이지네이션, ID 조기 추출, DB·키워드 간 중복 제거, 신규 우선, 선택적 재확인, 페이지·키워드 지표, 공급량 측정 모드, 일일 보고.
- 로컬: 1,050건 INSERT 1.7초 (가상 데이터).
- 실제 공급량·실적: **NOT_MEASURED** (LIVE 0회).
- 이번 작업에서 PR #371 과 통합한 상태로 전체 회귀를 다시 확인했습니다(9절).

## 5. JobKorea 공식 문의

- 문의서: [docs/data/JOBKOREA_DATA_PERMISSION_INQUIRY_2026-11.md](../data/JOBKOREA_DATA_PERMISSION_INQUIRY_2026-11.md) (`DRAFT_NOT_SENT`).
  - 포함 항목: 서비스 소개, 목적, 필드, 하루 신규 약 1,000건(**목표, 보장 아님**), 최대 요청량 약 1,300/일, 주기, 중복 제거, 출처 표시, 보관·삭제, 제공 방식, API·라이선스 가능 여부.
- 발송 경로:
  1. API 담당 api@jobkorea.co.kr / https://www.jobkorea.co.kr/service/api
     - 웹 검색 결과 기준, 공공기관·학교 대상이고 일반 기업은 불가할 수 있습니다.
     - 이 PC 에서는 페이지를 직접 열지 않았으므로, 발송자가 원문을 다시 확인해야 합니다.
  2. 고객센터 helpdesk@jobkorea.co.kr / https://www.jobkorea.co.kr/help/inquiry
- 대안 공급원(같은 문서 4절): 사람인 오픈API(하루 500회, 승인제), 고용24 OPEN-API(인증키, 출처 표시 의무). 모두 HOLD 이며 저장·가공 권한은 미확인입니다.
  - 공식 API 는 호출 1회에 여러 건을 받으므로, 요청 수와 차단 위험이 웹 상세 수집보다 작습니다.
- 차단·CAPTCHA 우회: 하지 않습니다. 코드는 401/403/429/CAPTCHA/리다이렉트에서 즉시 중단합니다.

## 6. Staging 테스트 데이터 위험 (최우선)

### 6.1 확인된 사실 (저장소 증거만, 서버 접근 없음)

| 항목 | 값 | 출처 |
|---|---|---|
| Staging `postings` | `jobkorea` 2 · `jobkorea_imported` 28 · `jobkorea_live` **5** (11-08 이후 변화 없음) | `docs/testing/crawler/evidence/slack03/s03_pre_out.txt`, `night03`, `night04`, CRAWLER_NIGHT_12 |
| `jobkorea_live` 5건 마지막 기록 시각 | **2026-11-08 09:50:48 KST** | `s03_pre_out.txt` |
| 그 직전 이벤트 | #85 "complete bounded **live** JobKorea collection" 병합 **08:55**, #88 Staging 이미지 패키징 **09:43** | git log |
| 그 시점의 Live 경로 | `import_jobkorea_html --list-url/--url` 는 **T61 게이트를 거치지 않았음**. 게이트 강제는 #254 (11-12) | CRAWLER_LIVE_TEST_RESULT §1·§5, git log |
| Staging 실행 기록 | runs 1~2 (모두 Fixture), night_job_results 0 | 위 증거 |
| 이 PC 의 `jobkorea_live` 26건 | **테스트 행으로 확인**: 합성 ID 패턴(`10097100000…`, `10588600000…`), fixture 제목, harvest 원장 없음 | 이번 조회 |

**판단: 미확정입니다.** Staging 의 5건은 #85 배포 7분 뒤에 기록됐고, 실행 기록(runs)이 없는 CLI 경로로 저장됐습니다. 따라서 **T61 승인 없이 실제 JobKorea 에서 수집된 데이터일 가능성이 높습니다**. 이름이 `jobkorea_live` 라는 것만으로는 판단하지 않았고, payload 를 확인해야 확정됩니다(6.3).

### 6.2 위험

| 경로 | 위험 | 수준 |
|---|---|---|
| Staging GCP Sync cron(08:05 KST, `scheduled`) | Staging 방식은 출처 필터 없이 `jobkorea_live` 전체를 고릅니다. 5건이 운영 Cloud SQL 로 복사되고, `GCP_SYNC_PUBLISH=1` 이면 서비스에 노출됩니다 | **HIGH** (cron 이 활성이면) / cron 상태 **미확인** |
| 무승인 수집분 보관 | 약관 제한 대상 데이터를 보관 중일 수 있음 | **MEDIUM** (권리 판단 필요) |
| 이 PC → GCP | 로컬 Source 모드는 LIVE run 원장으로만 고르고, 테스트 26건을 배제함을 리허설로 확인 | LOW |

### 6.3 읽기 전용 점검 (STAGING_READ_ONLY_CHECK=BLOCKED: 이 PC 에 접근 수단·승인 없음)

Staging 접근 권한자가 실행합니다. **아무것도 변경하지 않습니다.**

```bash
cd /home/kant/ai-career-staging-poc
docker compose --project-name ai-career-staging-poc ps                      # 1. PostgreSQL·backend 상태
systemctl list-timers 'ai-career-*' --all --no-pager                         # 2. dispatcher·night 타이머
docker compose --project-name ai-career-staging-poc exec -T backend \
  sh -c 'for v in CRAWLER_NIGHT_ENABLED CRAWLER_LIVE_SCHEDULE_APPROVED CRAWLER_NIGHT_POLICY_FILE GCP_SYNC_PUBLISH; do [ -n "$(printenv $v)" ] && echo "$v=SET" || echo "$v=UNSET"; done'   # 값 미출력
crontab -l 2>/dev/null | grep -c run_gcp_sync.sh                               # 3. GCP Sync cron (0 이면 비활성)
ls -l gcp-sync/ gcp-sync/logs/ 2>/dev/null; tail -n 5 gcp-sync/logs/gcp-sync.log 2>/dev/null   # 10. 전송 이력
```

```sql
-- docker compose ... exec -T db psql -U <읽기 전용 또는 crawler_staging> -d ai_career_crawler_training
BEGIN READ ONLY;
SELECT source_code, count(*), min(updated_at), max(updated_at)
  FROM crawler_training.postings GROUP BY 1 ORDER BY 1;                     -- 4
SELECT external_posting_id, payload->>'source_url', payload->>'title', payload->>'company_name',
       payload->>'published_on', updated_at
  FROM crawler_training.postings WHERE source_code = 'jobkorea_live' ORDER BY updated_at;   -- 5/6/8 (합성: 큰 연속 ID·fixture 제목 / 실제: 8자리 실 공고번호·실 기업명)
SELECT run_id, mode, trigger, status, started_at, fetched_count, inserted_count
  FROM crawler_training.runs ORDER BY started_at;                           -- 7
SELECT count(*) FROM crawler_training.night_job_results;                    -- 7
SELECT external_posting_id, array_agg(source_code) FROM crawler_training.postings
  GROUP BY 1 HAVING count(*) > 1;                                           -- 9 (출처 간 같은 ID)
SELECT k.keyword, d.external_posting_id, d.first_seen_at FROM crawler_training.keyword_posting_discoveries d
  JOIN crawler_training.search_keywords k USING (keyword_id) WHERE d.source_code = 'jobkorea_live';
ROLLBACK;
```

```sql
-- 10. GCP 로 이미 전송됐는지 (Cloud SQL, 읽기 전용 계정, 승인 C 범위의 읽기)
SELECT i.status, i.started_at, i.error_summary->>'inserted' FROM career.ingestion_runs i
  JOIN career.data_sources s USING (source_id) WHERE s.code = 'jobkorea_live' ORDER BY i.started_at;
SELECT count(*), count(*) FILTER (WHERE p.status <> 'draft') FROM career.job_postings p
  JOIN career.data_sources s USING (source_id) WHERE s.code = 'jobkorea_live';
```

**차단 조치 (승인 필요, 실행 안 함)**:
- E1. cron 이 활성이면 `crontab -l | grep -v run_gcp_sync.sh | crontab -` 로 끕니다(README 의 비활성 명령, 되돌리기 가능).
- E2. 5건이 실제 수집분이면 PM·권리 판단에 따라 격리하거나 삭제합니다(owner 계정, 백업 후).
- E3. GCP 에 이미 전송됐다면 #337 README 의 롤백, 또는 7절 J 의 ID 범위 삭제를 합니다.

## 7. GCP 전용 계정 및 TLS 준비

| | 내용 |
|---|---|
| **A. 계정 생성 SQL** | [`create_career_sync_role.sql`](../../poc/staging/automation/gcp-sync/create_career_sync_role.sql): LOGIN, superuser·createdb·createrole·replication·bypassrls 없음, CONNECTION LIMIT 3, statement 120s / lock 10s / idle-in-tx 60s, CONNECT 만 허용. **비밀번호는 파일·인자에 넣지 않고** `\password career_sync` 또는 Cloud Console 사용자 화면에서 설정 |
| **B. 최소 권한** | [`target_grants.sql`](../../poc/staging/automation/gcp-sync/target_grants.sql) (career owner 로 실행): data_sources SELECT. companies·job_postings·external_refs·ingestion_runs 는 SELECT/INSERT + 지정 컬럼 UPDATE 만. **DELETE·DDL·다른 테이블(users 등) 없음**. 리허설에서 `has_table_privilege` 로 DELETE=false, CREATE=false, users SELECT=false 확인 |
| **C. TLS 인증서 확보** | Cloud Console > SQL > 인스턴스 > 연결 > 보안 > **서버 CA 인증서 다운로드**(`server-ca.pem`, 공개 인증서), 또는 `gcloud sql instances describe <INSTANCE> --format='value(serverCaCert.cert)'`. 저장 위치: `C:\dev\crawler-data\secrets\gcp-server-ca.pem` |
| **D. CA·호스트명 검증** | 코드 고정값 `sslmode=verify-full`. `GCP_SYNC_TARGET_HOST` = 서버 인증서의 이름(Cloud SQL 의 DNS 이름, 예: `<instance>.<region>.sql.goog` 형식. 정확한 값은 Console 이나 `gcloud sql instances describe --format='value(dnsName)'` 으로 확인), `GCP_SYNC_TARGET_HOSTADDR` = 인스턴스 IP. 확인: `openssl x509 -in server-ca.pem -noout -subject -enddate`. 이름이 틀리면 `TARGET_TLS_FAILED` (리허설로 확인) |
| **E. PC 연결 허용** | ① 승인 네트워크에 이 PC 의 공인 IP/32 만 1회 기간 한정 추가(작업 후 제거). 또는 ② **Cloud SQL Auth Proxy**(IAM 인증, IP 허용 불필요. 이 PC 에 미설치이고, 설치는 별도 승인). 점검: `Test-NetConnection <IP> -Port 5432` (승인 C 이후, TCP 연결만) |
| **F. 전용 환경변수** | `C:\dev\crawler-data\secrets\gcp-sync.env` (양식 [`gcp-sync.env.example`](../../scripts/windows/templates/gcp-sync.env.example)): HOST, HOSTADDR, PORT, DB=ai_career_poc, USER=career_sync, PASSWORD, PUBLISH=0. ACL 은 본인·SYSTEM. 루트 `.env` 는 읽지 않음 |
| **G. Dry-run** | `.\scripts\windows\run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId <LIVE run id>` (쓰기 0) |
| **H. 1회 Sync** | `.\scripts\windows\run-gcp-sync-local.ps1 -Mode run -LiveRunId <같은 id>` → 결과 JSON 의 `inserted_external_ids` 를 비공개 보관 |
| **I. 검증** | `-Mode verify` (양쪽 읽기 전용 비교, `source_target_match=true` 가 기준). SQL: `SELECT count(*) FROM career.job_posting_external_refs r JOIN career.data_sources s USING (source_id) WHERE s.code='jobkorea_live' AND r.external_id = ANY('{…}')` 가 원천 건수와 같은지, `status='draft'` 만 있는지 |
| **J. 복구** | 실행 중 오류는 자동 전체 롤백(`ingestion_runs.failed`). 실행 후 되돌리기(career owner): `DELETE FROM career.job_postings p USING career.job_posting_external_refs r, career.data_sources s WHERE r.job_posting_id=p.job_posting_id AND r.source_id=s.source_id AND s.code='jobkorea_live' AND r.external_id = ANY('{…}')` + 그 출처의 참조 없는 companies 삭제. draft 상태라 사용자 영향 없음. **리허설에서 이 SQL 로 1,050 → 0 확인** |

### 7.1 로컬 리허설 (운영 아님: 일회용 클러스터 5434, `scripts/windows/rehearse-gcp-sync.ps1`)

구성:
- 자체 서명 CA 와 서버 인증서(`gcp-sync-rehearsal.local`), 서버 `ssl=on`.
- 실제 `career` 스키마(0001~0003), `create_career_sync_role.sql` + `target_grants.sql`.
- Source 는 합성 "live" run 1,050행과 미끼 행 7개(fixture run 4, 원장 없는 행 3).

| 단계 | 결과 |
|---|---|
| dry-run | DRY_RUN, fetched 1,050, insert 계획 1,050, 0.47초 |
| run | SUCCEEDED, inserted 1,050, 0.92초 (loopback TLS) |
| verify | matched 1,050 / missing 0 / mismatched 0, `source_target_match=true` |
| 재실행 | inserted 0, duplicate 1,050 |
| Target 점검 | draft 아닌 행 0, **미끼 복사 0**, `career_sync` DELETE·CREATE·users 조회 모두 false |
| 부정: fixture run ID | `LIVE_RUN_NOT_ELIGIBLE` (접속 전 거부) |
| 부정: 인증서 이름 불일치 | `TARGET_TLS_FAILED` |
| 부정: 관리자 계정 | `TARGET_USER_NOT_ALLOWED` (접속 전 거부) |
| 롤백 SQL | 성공, refs 0. 이후 verify missing 1,050 |
| 비밀값 | 리허설 비밀번호는 실행 후 삭제, 출력 없음 |

증거: `C:\dev\crawler-data-goal3\logs\gcp-rehearsal-20261116-165137\evidence.json`.

**Cloud SQL 실제 연결·쓰기는 수행하지 않았습니다.**

## 8. Windows 무인 운영

관리자 권한: 현재 셸은 비승격(`elevated=False`)이며 우회하지 않습니다. 아래는 **관리자 PowerShell 에서 사용자가** 실행합니다.

```powershell
# 관리자 PowerShell ("관리자 권한으로 실행")
cd C:\dev\ai-career-platform
.\scripts\windows\reboot-check.ps1 -Phase Before
.\scripts\windows\register-fixture-task.ps1 -Unattended -IntervalMinutes 5 -ValidHours 2   # S4U + 부팅 트리거, fixture 전용, 2시간 후 자동 OFF
Get-ScheduledTask AICP-* | Select TaskName, State, @{n='Logon';e={$_.Principal.LogonType}}   # 기대값: S4U
.\scripts\windows\stop-local-postgres.ps1
# (1) 로그아웃 시험: 로그아웃 → 15분 대기 → 로그인
# (2) 재부팅 시험: 시작 > 전원 > "다시 시작" (시스템 종료 아님) → 로그인하지 않고 15분 대기 → 로그인
.\scripts\windows\reboot-check.ps1 -Phase After     # 모든 항목 True 여야 PASS
```

| 검증 항목 | 판정 근거 (`after-checks.json` 등) |
|---|---|
| PostgreSQL 부팅 자동 시작 | `postgres_autostarted_after_boot` (postmaster 시작 > 부팅 시각) |
| 로그아웃 상태 실행 | `fixture_ran_unattended_batch` (BATCH 로그온 SID) |
| 작업 중복 방지 | IgnoreNew + Global 뮤텍스 + advisory lock. 기록상 `SKIPPED_LOCKED` 만 있고 겹침 0 |
| 장애 후 자동 복구 | 감독 작업 재시작(기존 시나리오 PASS). `no_failed_cycles_after_boot` |
| 데이터 보존 | `postings_preserved`, `postings_md5_unchanged_if_no_new_rows` |
| Fixture 자동 실행 | `fixture_ran_after_boot` ≥ 1 |
| LIVE 자동 OFF | `no_live`. 정책 만료 → 작업 Disabled(`AUTO_OFF`) |

실패 시 `register-fixture-task.ps1 -Unregister` 로 제거한 뒤 Interactive 로 다시 등록합니다(관리자 불필요). 데이터 디렉터리는 건드리지 않습니다.

현재 상태: WINDOWS_ADMIN_INSTALL / LOGOFF_TEST / REBOOT_TEST = **NOT_RUN**.

## 9. PR 검토 및 병합

| 항목 | 결과 |
|---|---|
| PR #371 (`fix/crawler-p0-365-dedupe-skip-reasons`, head `c025f51`) | OPEN, mergeable=true, **리뷰 0건**, CI 3개 success (offline-tests, Backend pytest, CI Smoke Test). main 보호 규칙 있음 |
| 병합 | **하지 않음** (독립 승인 리뷰 없음) |
| Windows 브랜치 PR | **미생성**. 이 PC 에 `gh` 와 API 토큰이 없고, git 자격증명을 추출해 쓰지 않습니다. 생성 링크: https://github.com/ai-career-platform/ai-career-platform/pull/new/feat/crawler-windows-local-pc |
| Windows 브랜치 CI | 실행 이력 0 (PR 이 없어 트리거되지 않음) |
| #371 과 통합 | `gcp_sync.py` 에서 **충돌 1곳**(양쪽이 서로 다른 함수를 같은 자리에 추가). 둘 다 유지하면 해결됨. 임시 worktree 에서 병합한 결과를 새 클러스터 5435 에서 전체 실행: 크롤러 단위 **541**, backend 21, PG 전 단계 PASS (gcp-sync 12 — #371 이 time-bomb 수정, local-source 7, harvest 9, t155 read 3, night e2e 7 등). 해당 없음은 staging-mode·t64-permissions(`db:5432` 하드코딩), Docker 미실행. 임시 worktree 는 삭제했고 아무것도 push 하지 않았습니다 |
| 권장 병합 순서 | ① #371 독립 리뷰 → 병합 ② Windows 브랜치를 main 기준으로 rebase(충돌 위 방식으로 해결) → PR 생성 → CI → 독립 리뷰 → 병합 |
| 보안 리뷰 | 이전 독립 리뷰(게이트 우회·테스트 행 이관 경로 없음, 지적 5건 반영)는 CRAWLER_LIVE_GCP_1000 §7 참고. 이번 추가분(SQL·리허설 스크립트)은 운영 비밀을 다루지 않습니다 |

## 10. 일 신규 1,000건 추진 계획

### 10.1 실측 근거

- **승인된 실제 데이터: 0건.** 따라서 키워드별 신규율, 중복률, 페이지별 발견율, 요청당 INSERT 비율의 **실측값은 없습니다(NOT_AVAILABLE)**.
- 아래 수치는 공식에 가정값을 넣은 **추정**이며 확정값이 아닙니다.

### 10.2 요청량 공식

변수:
- `L`: 검색 결과 페이지당 링크 수 (미검증. 합성 fixture 는 20)
- `r`: 링크 중 신규 비율
- `N`: 목표 신규 건수

요청 수 ≈ 1 (robots) + ⌈N / (L·r)⌉ (검색 페이지) + N (상세) + 재확인 수.
소요 시간 ≈ 요청 수 × (최소 간격 2초 + 응답 약 0.5초).

| 목표 N | r=0.85 (첫 실행, 누적분) | r=0.3 | r=0.1 (정상 상태 가정) | 시간 (r=0.85 / 0.1) |
|---|---|---|---|---|
| 100 | 107 | 118 | 151 | 약 4.5분 / 6.3분 |
| 300 | 319 | 351 | 451 | 약 13분 / 19분 |
| 1,000 | 1,060 | 1,168 | 1,501 | 약 44분 / 63분 |

(L=20 가정. 재확인 200건을 더하면 +200 요청, 약 +8분.)

공급 상한:
- 키워드 k 개 × 최대 페이지 p × L 이 하루에 볼 수 있는 링크 수입니다(게이트 상한 p ≤ 50).
- r=0.1 이면 N=1,000 에 약 500 페이지가 필요하므로, **키워드 10개 이상 × 50 페이지** 또는 r 이 더 높은 키워드가 필요합니다.
- 6개 AI·데이터 키워드만으로 정상 상태에서 하루 신규 1,000건이 나올지는 **불확실하며, 부족할 가능성이 높습니다**(추정).

### 10.3 키워드 확장 후보 (승인 D 에서 허가 URL 로 지정. 서비스 대상 직무와 맞을 때만)

- 현재 DB enabled: AI, Python, 데이터 분석, LLM, 업무 자동화, AI 엔지니어, AX, 빅데이터, 머신러닝, 딥러닝.
- 후보: 데이터 엔지니어, 데이터 사이언티스트, MLOps, 백엔드, 프론트엔드, 풀스택, 클라우드, DevOps, 정보보안, SQL, Java, 서비스 기획, PM.
- 키워드 사이 중복률은 harvest 의 `cross_duplicates` 로 실측합니다.

### 10.4 비용

| 항목 | 값 | 근거 |
|---|---|---|
| 로컬 저장 | 평균 행 약 0.5 KB (payload 437 B) → 1,000건/일 ≈ 0.5 MB/일 (인덱스 포함 약 1 MB), 1년 약 0.4 GB | 메인 DB 실측 |
| 로컬 처리 | 1,050 INSERT 1.7초 | 이전 실측 |
| GCP Sync | loopback TLS 1,050행 0.92초. Cloud SQL 은 행당 약 3회 왕복이라 RTT 30 ms 가정 시 약 1.5분(**추정**). 1회 트랜잭션 | 리허설 실측 + 추정 |
| GCP 저장 | posting + ref + company 로 행당 약 1~2 KB 추정 → 1,000건/일 약 1~2 MB/일 | 추정 |

### 10.5 단계 (각각 승인 D 의 하위 단계)

1. 공급량 측정 `--new 0 --revisits 0` (상세 0, 6키워드 × 10페이지 = 61요청): L, r, `Page_No` 실측.
2. 하루 신규 100건.
3. 하루 300건.
4. 하루 1,000건.

각 단계마다 3일 동안 403/429 가 0 이고 신규 목표를 달성해야 다음 단계로 갑니다. 공식 API 를 승인받으면 그 경로를 우선합니다(5절).

## 11. 승인 요청 항목

| | A. Windows 관리자 설치 + 로그아웃·재부팅 | B. 단발성 LIVE | C. GCP Sync 1회 | D. 수집량 확대 |
|---|---|---|---|---|
| 목적 | 로그인 없이 부팅 후 PG 와 fixture 자동 실행 검증 | 실제 수집 경로·파서·`Page_No` 1회 검증, 실제 공고 확보 | 실제 수집분을 운영 DB 에 draft 로 1회 이관 | 일 신규 1,000건 |
| 대상 | 이 PC (작업 스케줄러, 재부팅) | www.jobkorea.co.kr `/robots.txt`, `/Search/?stext=AX&tabType=recruit`, `/Recruit/GI_Read/*` 5건 | Cloud SQL `ai_career_poc.career` (job_postings, companies, external_refs, ingestion_runs) | JobKorea(허가 범위) 또는 공식 API |
| 예상 변경 | 작업 2개를 S4U/부팅 트리거로 재등록, 재부팅 1회 | 로컬 postings +≤5, harvest_* 기록 | INSERT ≤5 (draft), ingestion_runs 1 | 로컬 일 +100~1,000, GCP 일 1회 |
| 명령 | 8절 | 아래 12절 B | 12절 C | 12절 D |
| 한도 | 외부 요청 0 | **요청 7**, 재시도 0, 2시간 유효 | 트랜잭션 1, 행 ≤ B 결과 | 단계별: 61 → 약 110 → 약 330 → 약 1,300 요청/일 |
| 선행 조건 | 관리자 계정 사용자 입회 | 5절 서면 허가(범위 명시), Staging LIVE OFF 확인(6.3), 승인 파일 작성 | B 완료, `career_sync`·CA·호스트명·IP 허용, 6.3 의 GCP 점검 | B·C 완료, 허가 범위 ≥ 단계, D-1 실측 |
| 위험 | 재부팅 중 수 분 중단 | 허가 범위 위반, 차단 | 운영 DB 쓰기 | 대량 수집 권리·차단, 공급 부족 |
| 검증 | `reboot-check -Phase After` 전 항목 True | `harvest_runs.status`, `http_requests≤7`, 신규 행, 차단 0 | `verify` match=true, draft 만 | `harvest report` 일별, 403/429=0 |
| 중지·복구 | `-Unregister` → Interactive 재등록 | 승인 파일 삭제 = 즉시 OFF. 로컬 행은 owner 가 run ID 로 삭제 가능 | 자동 롤백, 또는 7절 J ID 삭제 | 승인 파일 만료·삭제, 단계 축소 |
| 승인자 | PM (+ PC 관리자) | PM + 권리 확인 책임자 (JobKorea 회신 근거) | PM + GCP/DB 관리자 | PM + 권리 확인 책임자 |
| 유효 기간 | 실행일 1일 | 승인 파일 `valid_from`~`review_due` 2시간 | 1회, 24시간 | 단계별 7일, 재승인 |

## 12. 실제 실행 단계별 명령

```powershell
cd C:\dev\ai-career-platform; . .\scripts\windows\crawler-local-env.ps1
# B. 단발성 LIVE (승인 파일: templates\t61-harvest-approval.REQUEST.json 을 PM 이 채워 secrets 에 저장)
$p = 'C:\dev\crawler-data\secrets\t61-harvest-approval.json'
& $VenvPy -m crawler.jobs.harvest live --policy-file $p --keyword AX --pages 1 --new 5 --max-requests 7 --check
$env:CRAWLER_LIVE_SCHEDULE_APPROVED = '1'
& $VenvPy -m crawler.jobs.harvest live --policy-file $p --keyword AX --pages 1 --new 5 --max-requests 7   # 출력의 run_id 기록
Remove-Item env:CRAWLER_LIVE_SCHEDULE_APPROVED; Remove-Item $p    # 즉시 OFF
& $VenvPy -m crawler.jobs.harvest report --days 1

# C. GCP Sync 1회 (secrets\gcp-sync.env + secrets\gcp-server-ca.pem 준비 후)
.\scripts\windows\run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId <run_id>
.\scripts\windows\run-gcp-sync-local.ps1 -Mode run     -LiveRunId <run_id>
.\scripts\windows\run-gcp-sync-local.ps1 -Mode verify  -LiveRunId <run_id>    # source_target_match=true

# D-1. 공급량 측정 (상세 0)
& $VenvPy -m crawler.jobs.harvest live --policy-file $p --pages 10 --new 0 --revisits 0 --max-requests 61 --check
# D-2~4. 단계별 (승인 값 이하)
& $VenvPy -m crawler.jobs.harvest live --policy-file $p --pages 20 --new 1000 --revisits 200 --max-requests 1300 --deadline-seconds 7200
```

## 13. 잔여 BLOCKER

1. JobKorea 서면 허가 없음 (문의 미발송).
2. T61 HOLD, 승인 파일 없음.
3. Staging `jobkorea_live` 5건의 출처, GCP Sync cron 상태, GCP 전송 여부 **미확인** (서버 접근 없음).
4. 운영 `career_sync` 존재 여부, CA, 인증서 호스트명, PC 네트워크 허용 미확보.
5. 관리자 설치·로그아웃·재부팅 시험 미실행.
6. PR #371 독립 리뷰 없음. Windows 브랜치 PR 미생성(GitHub 인증 수단 없음).
7. 실제 공급량 미측정.
8. 루트 `.env` 에 운영 관리자 자격증명(`*_GCP`)과 실제 Slack Webhook 이 남아 있음. 코드는 쓰지 않지만 PC 보관 위험이 있음.

## 14. PM 결정 사항

1. **(긴급)** Staging 읽기 전용 점검(6.3) 실행자를 지정하고 결과를 봅니다. cron 이 활성이면 E1(비활성) 승인.
2. 5건이 실제 수집분이면 처리 방침(격리·삭제·문의 회신까지 보류).
3. 문의서(5절) 발송 승인과 발송 담당자. 사람인·고용24 API 신청을 병행할지.
4. 승인 A 일정(관리자 입회, 재부팅 허용 시간).
5. GCP: `career_sync` 생성·CA 발급·연결 방식(IP 허용 vs Auth Proxy) 담당자와 승인 C.
6. 루트 `.env` 의 관리자 `*_GCP` 와 Slack Webhook 처리(삭제, 또는 교체 후 비밀 저장소로 이전).
7. PR #371 독립 리뷰어 지정. Windows 브랜치 PR 생성(gh 인증 또는 웹 UI).
8. 키워드 확장 목록과 승인 D 단계별 한도.
