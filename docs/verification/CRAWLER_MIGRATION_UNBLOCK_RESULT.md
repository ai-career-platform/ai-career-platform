# 크롤러 GCP 이관 차단 해소 결과 (AI_CAREER_CRAWLER_MIGRATION_UNBLOCK, 2026-11-16)

판정 원칙: 실제로 수행한 것만 PASS. 이번 작업의 외부 접촉:
- Staging 접속 시도 0회 (재시도 금지 지시 준수).
- GCP Cloud SQL 0회, JobKorea 0건.
- 자격증명 변경 0.

## 1. 기존 완료 사항 (반복하지 않음)

- 새 PC 의 환경, 로컬 DB, harvest(페이지네이션·중복 제거), 로컬 Source GCP Sync, TLS 리허설.
- 승인 B LIVE 1회: run `8e54090d-34ce-412a-88f1-9a693d0a47ed`, HTTP 7, 신규 5, 실패 0.
- 상세 문서: CRAWLER_LIVE_GCP_1000, CRAWLER_OPERATIONAL_UNBLOCK_PLAN, CRAWLER_STAGING_SAFETY_GATE, CRAWLER_STAGING_SAFETY_CHECK_RESULT, CRAWLER_STAGING_DIRECT_AUDIT.
- 브랜치 `feat/crawler-windows-local-pc`: 시작 HEAD `60db8cd`, 이번 작업 커밋 `3d83ab7` + 이 보고서 커밋. 작업 전 git status 는 깨끗했음.

## 2. Staging 접근 차단 현황 (외부 의존 작업)

- 이 PC 에서 Staging 22번 포트는 시간 초과입니다(17:13 확인). 이번에는 재시도하지 않았습니다.
- 사용 가능한 승인된 관리 도구도 없습니다: VPN 없음, ssh_config 없음, 원격 관리 세션 없음, GitHub·Staging 연동 도구 없음.
- → **STAGING_CHECK_RESULT=NOT_AVAILABLE**. 아래 3절 패키지를 서버 접근 가능한 담당자가 실행해야 합니다.

## 3. Staging 점검 실행 패키지 (담당자용, 한 번에 복사)

스크립트 `poc/staging/automation/safety/staging_readonly_check.sh` 는 이번 작업에서 8b 출처 규칙을 Sync 코드와 같게 고쳤습니다. 그래서 **SHA-256 이 바뀌었습니다** (최신 값은 `efa436a` 기준. CRAWLER_PR_INTEGRATION_AND_CUTOVER_READINESS §7 참고. 정정 2026-11-16: 처음 적은 `4fe2638e…` 는 Windows 작업 사본의 CRLF 줄바꿈으로 계산한 잘못된 값입니다. GitHub·Linux 에서 받는 LF 파일 기준 값은 아래와 같습니다. `.gitattributes` 에 `*.sh eol=lf` 를 추가해 재발을 막았습니다): `50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd` (이전 `a0053fd9…` 는 폐기).

안전성 재확인 결과:

| 확인 항목 | 결과 |
|---|---|
| `bash -n` | OK |
| 쓰기·재시작·cron 수정·자동 등록·외부 HTTP 명령 | 0 |
| SQL 블록 | 5개 모두 `BEGIN READ ONLY … ROLLBACK` |
| 출력 | 전체에 redaction 필터 적용 |

```bash
# === Staging 서버(배포 사용자 kant) 또는 승인된 관리 PC에서 그대로 실행 ===
set -eu
WORK=$(mktemp -d /tmp/aicp-check-XXXX) && cd "$WORK"
# 1) 파일 받기 (저장소 브랜치 feat/crawler-windows-local-pc). 서버의 기존 체크아웃이나 PC 에서 scp 로 복사해도 됨
curl -fsSL -o staging_readonly_check.sh \
  https://raw.githubusercontent.com/ai-career-platform/ai-career-platform/feat/crawler-windows-local-pc/poc/staging/automation/safety/staging_readonly_check.sh
# 2) 무결성·안전성 확인 (불일치하거나 쓰기 명령이 보이면 중단)
echo "50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd  staging_readonly_check.sh" | sha256sum -c -
bash -n staging_readonly_check.sh
grep -nE '\b(rm|mv|cp|tee|chmod|chown|kill)\b|crontab +-(e|r)|systemctl +(start|stop|restart|enable|disable)|compose[^|]*\b(up|down|restart|stop|start|run|pull|build)\b|\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY)\b' staging_readonly_check.sh \
  | grep -vE '^[0-9]+:\s*#|redacted|^2[0-9]:' && { echo "STOP: unexpected command"; exit 1; } || echo "SAFE_TO_RUN"
# 3) 실행 (1분 이내, 서버에 파일 생성 없음. 결과는 현재 디렉터리에만)
OUT="staging-check-$(hostname)-$(date +%Y%m%d-%H%M%S).txt"
bash staging_readonly_check.sh > "$OUT" 2>&1; echo "exit=$?"
# 4) 결과의 비밀 노출 점검 (아무것도 출력되지 않아야 함)
grep -nE '(PASSWORD|TOKEN|SECRET|WEBHOOK|_KEY)=[^<[:space:]]|://[^/@<[:space:]]+:[^@<[:space:]]+@|hooks\.slack\.com/services/[A-Z0-9]|BEGIN [A-Z ]*PRIVATE KEY' "$OUT" || echo "NO_SECRET_PATTERN"
# 5) 전달: $OUT 파일을 사내 전달 경로(사내 메신저 파일·이메일 첨부)로 PM 에게. GitHub·공개 채널 금지
ls -l "$OUT"; sha256sum "$OUT"
```

- **실패 시 필요한 최소 로그**: `exit=` 값, `$OUT` 의 마지막 30줄(`tail -n 30 "$OUT"`), `docker compose --project-name ai-career-staging-poc ps` 출력, `id; groups`.
  - docker 권한이 없으면 "permission denied" 줄만 전달합니다.
  - sudo 로 다시 실행하지 않습니다(승인 범위 밖).
- curl 은 GitHub 에서 스크립트를 받는 데만 씁니다(서버에서 외부로 나가는 1회 요청). 서버 정책상 외부 요청이 불가하면 `scp` 로 같은 파일을 복사합니다.

## 4. 결과 분석 방법 (분석기 준비 완료)

```powershell
# 이 PC 에서, 받은 결과 파일로 (네트워크·DB 접근 없음)
.\.venv\Scripts\python.exe poc\staging\automation\safety\analyze_staging_check.py <결과파일> --json C:\dev\crawler-data\logs\staging-analysis.json
```

| 분류 | 규칙 |
|---|---|
| **VERIFIED_APPROVED** | 8b `LIVE_JOB_LINKED`: 끝난 night job(SUCCEEDED/PARTIAL), HTTP>0, 실행 시각이 자기 밤(21:00~08:00 KST) 안. night job 은 `live_gate()` 가 ALLOWED 일 때만 생기므로 코드 수준의 승인 증거입니다. 8c 승인 파일 기간과도 맞으면 `approval_basis=approval_file:<이름>`, 파일이 남아 있지 않으면 `gate_enforced_night_job`(PM 이 비공개 승인 기록으로 확인) |
| **VERIFIED_UNAPPROVED** | 승인된 job 이 없고, 10절 셸 기록에 그 ID 의 `import_jobkorea_html` 실행이 있음(게이트 이전 CLI 경로) |
| **VERIFIED_FIXTURE** | `JOB_LINKED_SYNTHETIC_CLOCK`, 또는 배포 이미지의 fixture·테스트 파일에 같은 ID |
| **UNVERIFIED_ORIGIN** | 그 밖의 모든 경우 |

- 합계 검사: 분류 합계 = 8b 행 수 = 8절 `jobkorea_live` 건수. 다르면 `INCONSISTENT`, 절이 빠지면 `INCOMPLETE` (exit 2). **추정값을 만들지 않습니다.**
- 이관 가능 목록(`migratable_ids`)은 VERIFIED_APPROVED 만 담습니다.
- cron 등록·활성(주석 줄 구분)·주기, `GCP_SYNC_PUBLISH` true/false, 배포 코드의 가드 포함 여부, 마지막 sync run, 실행 중 프로세스도 함께 보고합니다.
- 검증:
  - 단위 4건 PASS (합성 결과 파일).
  - 실제 psql 출력 형식으로 파서 확인: 로컬 DB 31행 → 테스트 26 = FIXTURE, 5 = UNVERIFIED.
  - **Staging 실제 공고의 분류는 결과 파일이 없어 만들지 않았습니다.**

## 5. GCP 이관 사전 조건과 로컬 Dry-run

### 5.1 실제 LIVE run 의 Dry-run (일회용 TLS Target, 운영 아님)

`scripts/windows/rehearsal/gcp_dryrun_real_run.py` 를 실행했습니다.
- Source: 실제 로컬 DB(읽기 전용 `crawler_local`)의 run `8e54090d…`.
- Target: 일회용 클러스터 5434 의 `ai_career_poc`(career 스키마, `career_sync`, TLS verify-full).
- Target 에는 보고된 운영 상태를 재현해 두었습니다: Staging 이 쓴 50350626 1건, 그리고 구 코드 sync 실행 기록 1건(`source` 키 없음).

| 단계 | 결과 |
|---|---|
| dry-run | fetched **5** → **INSERT 4, duplicate 1** (50350626 은 이미 Target 에 있고 필드 동일), `already_in_target=1`, `other_writers={"staging": …}` |
| run (cutover 미확인) | **FAILED `OTHER_SYNC_SOURCE_ACTIVE`**, Target refs 1 → 1 (쓰기 없음) |

**결론: 5건이 모두 INSERT 되지 않습니다.**
- 운영에서 예상되는 결과는 INSERT 4, 기존 1건은 duplicate(필드가 다르면 UPDATE)입니다. external_refs 로 식별하므로 중복 INSERT 는 불가능합니다.
- 실제 결과는 운영 dry-run 으로 확인합니다.

증거: `C:\dev\crawler-data\logs\gcp-dryrun-real-run-20261116-180029.json`.

### 5.2 요구 항목별 상태

| # | 항목 | 상태 |
|---|---|---|
| 1~3 | LIVE run ID 지정 / 그 run 의 공고만 / fixture·테스트 제외 | 구현·검증 (원장 필터 + `updated_at ≤ ended_at`, 테스트 26행 제외) |
| 4~5 | 기존 Posting ID 충돌 검사 / INSERT·UPDATE·Duplicate 구분 | 구현·검증 (위 5.1). 다른 출처의 같은 URL 은 `URL_CONFLICT` 로 실패 처리(덮어쓰지 않음) |
| 6 | Draft 유지 | `GCP_SYNC_PUBLISH` 기본 0 |
| 7 | Idempotency | 재실행 시 duplicate 만(리허설 1,050 → 0 insert) |
| 8 | 실패 시 ROLLBACK | 실행 1회 = Target 트랜잭션 1개(PG 테스트), 실행 후 되돌리기 SQL 은 UNBLOCK_PLAN 7절 J |
| 9 | Source/Target 비교 | `-Mode verify` |
| 10 | 결과 보고 | 결과 JSON + `ingestion_runs.error_summary` (writer·provenance·skip 사유) |

운영 연결 조건:

| 조건 | 상태 |
|---|---|
| `career_sync` 계정 | SQL·리허설 준비 완료. 운영 존재 여부 UNKNOWN (DOCUMENTED: Staging Sync 가 `career_sync` 로 동작 중일 가능성. 스크립트 5절 `target_user_is_career_sync` 로 확인) |
| 최소 권한 | `target_grants.sql`, 리허설에서 DELETE·DDL·users 조회 false |
| Cloud SQL CA / 인증서 호스트명 | 미확보. Staging 의 `gcp-sync/server-ca.pem` 이 같은 인스턴스 CA(공개 인증서)이므로 담당자가 이 PC 로 복사 가능 |
| 네트워크 | 미검증. 단발은 IP 기간 한정 허용, 정기는 Auth Proxy 검토(Proxy 는 Windows 바이너리 서명·Smart App Control 확인 필요, 현재 미설치) |
| GCP 쓰기 승인 | 없음 |
| 관리자 계정 | 사용하지 않음(코드가 거부) |

## 6. Source/Target 중복 방지 (구현, PR 대기)

| 정책 | 구현 (이 브랜치 `3d83ab7`) | 검증 |
|---|---|---|
| 1. Source 하나만 활성 | 모든 실행이 `error_summary.source`(local/staging)를 기록. 최근 7일 안에 다른 writer 의 실행이 있으면 `run` 은 `FAILED OTHER_SYNC_SOURCE_ACTIVE`, `scheduled` 는 `SKIPPED`. PM 이 전환을 확인한 뒤 `GCP_SYNC_CUTOVER_CONFIRMED=1` 일 때만 진행. 구 배포 코드의 실행(`source` 키 없음)은 staging 으로 셈 | PG 3·4·5, 실데이터 dry-run |
| 2. 같은 Posting 중복 INSERT 방지 | external_refs 식별(기존) + `already_in_target` 보고 | PG 3·4 (101 공유 → duplicate) |
| 3. 충돌 감지 | `other_writers`(writer 와 마지막 시각), URL 충돌 실패 처리 | 위 |
| 4. Run ID 기록 | `ingestion_runs` + 로컬 run ID 목록 | 기존 |
| 5. 승인된 공고만 | 로컬: LIVE run 원장. **Staging: 새 provenance 필터** | PG 1·2 |
| 6~10 | advisory lock + flock, 재실행 duplicate, 단일 트랜잭션 롤백, draft, 실행 이력 보존 | 기존 테스트 |

**Staging Guard 축소 (STAGING_GUARD_REFINED=YES, 미배포)**:
- 전체 차단(`SOURCE_PROVENANCE_REQUIRED`)을 없앴습니다.
- 행 단위로 판정합니다(`STAGING_PROVENANCE_SQL`): 승인된 night job 의 발견 기록(first 또는 last seen)이 있는 행만 이관하고, 나머지는 `PROVENANCE_UNVERIFIED` 로 건너뜁니다.
- 합성 데이터 6행 PG 시험:
  - 승인 job 2건과 나중 밤에 다시 확인된 1건은 이관됩니다.
  - 11-08 형 1건(job 없음), 테스트 시계 1건, 실패 job 1건, 원장만 있는 1건은 제외됩니다.
- **점검 스크립트 8b 와 Sync SQL 이 같은 행에 같은 판정**을 내리는지 PG 테스트로 묶었습니다.
- 배포는 PR·리뷰·승인 후입니다.
- 참고: 기록상 운영 Target 에 이미 있는 29건에는 영향이 없습니다(삭제 없음, 이후 재전송만 제한).

## 7. PR 상태

| 항목 | 값 |
|---|---|
| PR #371 | OPEN, head `c025f51`, CI 3/3 success, **리뷰 0** → main 병합 HOLD |
| #371 과 호환성 | `gcp_sync.py` 충돌 2곳. 해법: provenance skip 을 #371 의 `result.skip()` 으로 쓰고, 두 쪽 함수를 모두 유지. 임시 병합본을 새 클러스터에서 전체 실행해 모두 PASS: 단위 547, gcp-sync 12(time-bomb 수정 포함), local-source 7, staging-provenance 6, harvest 9, night 등. 임시 worktree 는 삭제했고 push 하지 않음 |
| Windows 브랜치 PR | **미생성**. `gh` 없음, GitHub 연동 도구 없음, 자격증명을 추출해 쓰지 않음. 웹에서 생성: https://github.com/ai-career-platform/ai-career-platform/compare/main...feat/crawler-windows-local-pc |
| 권장 순서 | #371 리뷰·병합 → Windows 브랜치를 main 에 rebase(위 해법) → PR → CI → 독립 리뷰 → 병합 → Auto-CD 배포 |

PR 본문 초안 (웹 UI 에 붙여넣기):

```
제목: feat(crawler): Windows local crawler PC, paginated harvest, local-source GCP sync with provenance and single-writer guards

- Windows: local PostgreSQL 18 bootstrap, supervised host, fixture scheduler, status/reboot checks (no LIVE by default)
- Harvest (GOAL 3): pagination, id-first dedup, new-first details, revisits, per-page/keyword metrics; T61-gated live mode (opt-in approval fields)
- GCP sync: local source filtered by real LIVE harvest run ids; Staging source filtered per row by gate-approved night jobs
  (PROVENANCE_UNVERIFIED otherwise); single-writer guard (OTHER_SYNC_SOURCE_ACTIVE until GCP_SYNC_CUTOVER_CONFIRMED=1); verify mode
- Staging read-only check script + offline analyzer
- Evidence: first approved LIVE run 8e54090d (7 requests, 5 inserted); TLS rehearsal 1,050 rows; real-run dry-run 4 insert + 1 duplicate
- Conflicts with #371 in gcp_sync.py: keep both helpers, use result.skip() for PROVENANCE_UNVERIFIED (merged suite all PASS)
Not deployed. No production/GCP writes. Merge only after independent review and CI.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## 8. 일 신규 1,000건 추진

| 지표 | 현재 값 | 출처 |
|---|---|---|
| 키워드별 결과 수 | AX 1페이지 20 | 실측 1회 (run `8e54090d`) |
| 페이지별 고유 Posting ID | 20/20 고유 | 같음 |
| DB 기존 공고 중복률 | 0% (로컬 DB 에 실제 공고가 없었음) | 같음. Staging 기록: 11-12 밤 30 상세 중 25 고유(17% 키워드 간 중복), 11-15 AX 5 중 4 기존 |
| 상세 대비 신규 INSERT | 5/5 (첫 실행) | 같음. 정상 상태 비율 아님 |
| 하루 공급량 | **NOT_MEASURED** | — |
| API·라이선스 | 잡코리아 API 신청 제출·승인 대기(사용자 보고). 사람인(하루 500회)·고용24 는 후보 | 공식 안내 |

- 지표 수집 도구는 준비돼 있습니다: `harvest_pages`, `keyword_stats`, `harvest report`, 공급량 측정 모드 `--new 0`.
- 지시대로 **추가 LIVE 공급량 측정은 보류**합니다.
- 허가(또는 API 승인)가 나면 순서대로 진행합니다:
  1. D-1 공급량 측정 (요청 61)
  2. 100건/일 (≈110~150 요청)
  3. 300건/일 (≈350~500)
  4. 1,000건/일 (≈1,250~1,700, 키워드 10개 이상)
- API 가 승인되면 호출당 최대 500건, 2시간 주기라 웹 상세 수집보다 요청이 크게 줄어듭니다. 그 경로를 우선합니다.

## 9. 잔여 승인 요청 (운영 전환 실행 순서)

1. **Staging 점검 실행** (3절, 서버 담당자) → 4절 분석기로 29건 분류 확정.
2. 분류 결과에 따라 출처 미확인·미승인 행 처리 결정(Staging 은 보존, Target draft 는 격리 또는 삭제).
3. Windows 브랜치 PR 생성(웹) → #371 리뷰·병합 → 이 PR 리뷰·병합 → **provenance 필터·단일 writer 코드를 Staging 에 배포**(배포만 해도 Staging cron 이 미확인 행을 더는 보내지 않음).
4. 자격증명 회전(UNBLOCK_PLAN·SAFETY_GATE 6절 순서).
5. 승인 C: 새 PC 의 `career_sync`·CA·호스트명·네트워크 → `run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed`.
6. **전환**: Staging GCP Sync cron 중지(승인) → `GCP_SYNC_CUTOVER_CONFIRMED=1` 로 새 PC run → verify. 이후 새 PC 가 단일 writer.
7. 잡코리아 API 승인 또는 수집 허가 → 승인 D 단계.

## 10. 다음 실행 명령

```powershell
# (Staging 결과 수신 후) 분류
.\.venv\Scripts\python.exe poc\staging\automation\safety\analyze_staging_check.py <staging-check-*.txt> --json C:\dev\crawler-data\logs\staging-analysis.json
# (승인 C 후) 운영 dry-run → run → verify  (secrets\gcp-sync.env + secrets\gcp-server-ca.pem 준비)
.\scripts\windows\run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed
# 전환 승인과 Staging cron 중지 확인 뒤에만: secrets\gcp-sync.env 에 GCP_SYNC_CUTOVER_CONFIRMED=1
.\scripts\windows\run-gcp-sync-local.ps1 -Mode run    -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed
.\scripts\windows\run-gcp-sync-local.ps1 -Mode verify -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed
```

**FINAL_STATUS=PARTIAL**: 로컬 준비와 코드 검증은 완료했습니다. GOAL 2(실제 GCP 쓰기)와 GOAL 3(일 1,000건)은 PASS 가 아니며, Staging 결과는 외부 의존 작업입니다.
