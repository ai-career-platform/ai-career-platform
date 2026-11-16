# PR 통합 및 GCP 운영 전환 준비 (AI_CAREER_CRAWLER_PR_INTEGRATION_AND_CUTOVER_READINESS, 2026-11-16)

판정 원칙: 실제로 실행한 것만 PASS.

이번 작업에서 하지 않은 것:
- 운영 서버, GCP, JobKorea 접촉
- 자격증명 변경
- LIVE 실행
- Staging 접속 시도

GitHub 은 인증 없는 공개 API 로 읽기만 했고, 쓰기는 `git push` 로 브랜치를 올린 것뿐입니다.

## 1. PR #371 상태 (2026-11-16 18:3x KST, GitHub API)

| 항목 | 값 |
|---|---|
| 상태 | OPEN, `mergeable=true`, `mergeable_state=clean`, head `c025f51`, base main(`1797f4c`) |
| CI | check-runs 3/3 completed·success: offline-tests, Backend pytest, CI Smoke Test |
| 리뷰 | **0** (`/pulls/371/reviews` = `[]`). 요청된 리뷰어 0. 대화 댓글 2건은 작성자의 리뷰 요청 |
| main 보호 | `protected=true`. 세부 규칙은 인증이 필요해 읽지 못함(401). 응답에 보이는 required status checks 는 없음 |
| 병합 | **하지 않음.** 독립 승인 리뷰가 없음. 이 PC 에는 GitHub 인증 수단(gh, 토큰, 연동 도구)이 없어 리뷰어 지정도 못 함. 자격증명 추출이나 보호 규칙 우회는 하지 않음 |

## 2. Windows 브랜치 상태

| 항목 | 값 |
|---|---|
| 브랜치 | `feat/crawler-windows-local-pc` = origin, HEAD **`efa436a`** (+ 이 보고서 커밋). 시작 시 `2baefa5`, 미커밋 변경 0 |
| 이번 커밋 | `37fdb79` (전환 조건 강화·분석기 우선순위), `2cec971` (`.gitattributes` `*.sh eol=lf`, SHA 정정), `efa436a` (독립 리뷰 지적 해결) |
| PR | **미생성**: GitHub 인증 수단이 없음 |
| PR 링크 | https://github.com/ai-career-platform/ai-career-platform/compare/main...feat/crawler-windows-local-pc |
| PR 본문 | [WINDOWS_CRAWLER_PR_BODY.md](WINDOWS_CRAWLER_PR_BODY.md) (요청한 10개 항목 + 리뷰 체크리스트, 붙여넣기용) |
| CI | PR 이 없어 실행되지 않음 |
| 리뷰 | 0 |
| 병합 | 아니오 |

## 3. 충돌 해결 결과

- **통합 브랜치**: `integration/pr371-windows-crawler` (`ea1c1e5`) 를 새로 만들어 push 했습니다. Windows 브랜치와 PR #371 은 수정하지 않았습니다. main 병합용 PR 은 아닙니다.
- **충돌 위치**: `crawler/jobs/gcp_sync.py` 2곳.
  1. `plan()`: PROVENANCE_UNVERIFIED 를 #371 의 `Plan.skip()`(출처별 skip 근거)으로 기록하고, #371 의 `selected_changed` 집계보다 먼저 검사합니다. 출처 미확인 행은 집계도 동기화도 되지 않습니다.
  2. 보조 함수: Windows 쪽(`verify_target`, `other_writers`, `cutover_refusal`)과 #371 쪽(`check_accounting`)을 모두 유지합니다.
- **병합 후 `_locked_sync` 순서**: 단일 writer·전환 검사 → 하루 1회 검사 → `last_synced_at` → plan → `COUNT_MISMATCH` 집계 검사 → dry-run 또는 적용 → 단일 트랜잭션 롤백.
- **원칙별 확인**:

| 원칙 | 결과 |
|---|---|
| 양쪽 기능 보존 | 유지 |
| 출처 검증 | 유지 |
| 승인 게이트 | 변경 없음 |
| 이중 동기화 차단 | 유지 |
| #371 날짜 수정 | 유지 (gcp-sync test_08 PASS) |
| Staging 승인 행 이관 | 유지 |
| fixture·출처 불명 제외 | 유지 |
| draft 기본값 | 유지 |

- **권장 병합 순서**: #371 리뷰·병합(squash) → Windows 브랜치를 main 위로 rebase(같은 해결) → PR 생성 → CI → 독립 리뷰 → 병합.
  - Windows PR 에 #371 커밋을 섞지 않아 중복을 피합니다.

## 4. 통합 테스트 Evidence (이번에 실제 실행, 새 클러스터, egress 0)

통합 브랜치 `ea1c1e5`, PostgreSQL 18.7 일회용 클러스터(5435, 매번 새로 생성). 로그: `C:\dev\crawler-data-int\logs\tests-20261116-182912\`.

| 묶음 | 실행 | PASS | FAIL | SKIP |
|---|---|---|---|---|
| 크롤러 단위 | 554 | 549 | 0 | 5 (Linux 전용) |
| backend training 단위 | 21 | 21 | 0 | 0 |
| pg-gcp-sync (#371 time-bomb 수정 포함) | 12 | 12 | 0 | 0 |
| pg-gcp-sync-local-source | 7 | 7 | 0 | 0 |
| pg-gcp-sync-staging-provenance | 8 | 8 | 0 | 0 |
| pg-harvest-1000 | 9 | 9 | 0 | 0 |
| pg-html-integration | 2 | 2 | 0 | 0 |
| pg-t64-integration | 14 | 14 | 0 | 0 |
| pg-night-executor-caller | 16 | 15 | 0 | 1 |
| pg-night-integration | 13 | 13 | 0 | 0 |
| pg-t155-admin-read / write | 3 / 6 | 3 / 6 | 0 | 0 |
| pg-t152-artifact-audit | 2 | 2 | 0 | 0 |
| pg-night-e2e | 7 | 7 | 0 | 0 |
| **PG 합계** | **99** | **98** | **0** | **1** |
| 미실행 | staging-mode·t64-permissions (`db:5432` 하드코딩, NOT_APPLICABLE), Docker 컨테이너 테스트(미설치) | | | |

Windows 브랜치 단독(`efa436a`):
- 크롤러 단위 546 (541 PASS, 5 SKIP).
- provenance 8/8, local-source 7/7.
- 기존 gcp-sync 11/12: test_08 은 main 의 기존 날짜 결함이고 #371 이 수정합니다.

요청 항목과 증거:

| 항목 | 증거 (테스트) |
|---|---|
| LIVE Run ID 필터 | local-source 01·02 (fixture run·HTTP 0 run·없는 ID 거부, 원장 행만 선택) |
| 신규 INSERT / Duplicate / UPDATE | local-source 03·05, gcp-sync 02·03·04 (변경 필드만 UPDATE) |
| 승인된 Staging 공고 동기화 | provenance 01·02 (승인 job 2건 + 나중 밤에 다시 확인된 1건) |
| 출처 불명·Fixture 제외 | provenance 01·02·00: job 없음, 테스트 시계, 실패 job, **나중에 덮어쓴 payload**, 원장만 있는 행 |
| 승인 없는 동기화 거부 | local-source 01, provenance 01 |
| 이중 동기화 거부 | provenance 03·04·05·06·07 |
| 재실행 멱등성 | local-source 05, gcp-sync 03, provenance 04 |
| 실패 시 ROLLBACK | gcp-sync 05 (apply 중 예외 → Target fingerprint 불변, run failed) |
| Draft 유지 | local-source 03, provenance 04 (draft 아닌 행 0) |
| 실데이터 Dry-run | run `8e54090d`(실제 5건) → 일회용 TLS Target(Staging 의 50350626 과 구 코드 sync 기록을 재현): **INSERT 4, duplicate 1**, `already_in_target=1`. run 은 `OTHER_SYNC_SOURCE_ACTIVE` 로 거부, Target refs 1 → 1. 증거 `C:\dev\crawler-data\logs\gcp-dryrun-real-run-20261116-183006.json` |

운영 자격증명은 쓰지 않았습니다. Target 은 모두 로컬 일회용 DB 입니다.

## 5. 독립 리뷰 상태

- **GitHub 승인 리뷰: 0** (#371, Windows 브랜치 모두).
- 저장소 밖 독립 검토: 새 컨텍스트의 리뷰 에이전트에게 통합 diff 만 주고 결론은 주지 않았습니다. 이것은 GitHub 승인 리뷰가 아니며 병합 조건을 충족하지 않습니다.
- 검토 결과 우회 경로 2건과 강건성 결함들이 나왔고, 모두 `efa436a` 에서 고치고 테스트했습니다.

| # | 지적 | 수준 | 조치 |
|---|---|---|---|
| 1 | PARTIAL 실행(`failed` 로 저장되지만 실제로 씀)이 writer 판정에서 빠져 단일 writer 를 우회 | 높음 | 모든 상태의 실행을 셈 (provenance 07) |
| 2 | 승인 job 이 증명한 뒤 payload 가 덮어써져도 Staging 행이 이관됨 | 중~높음 | `p.updated_at ≤ 증명 job 종료` 조건 추가. 점검 스크립트 8b 도 같은 규칙(`JOB_LINKED_PAYLOAD_CHANGED`) (provenance 00·01) |
| 3 | 중단된 실행의 `running` 행이 staging 으로 귀속돼 자기 writer 를 7일간 막음 | 중 | 행을 넣을 때부터 writer 표시. stale 정리 때도 표시 유지. 1시간 넘은 running 은 진행 중으로 보지 않음 (provenance 06) |
| 4 | 7일만 기다리면 전환 확인 없이 두 번째 writer 진행 | 중하 | 시간 창 제거. writer 는 이후의 **확인된 전환 실행**으로만 은퇴 (provenance 04·06) |
| 5 | `error_summary` 가 JSON 객체가 아니면 모든 sync 중단 | 하 | `_summary_obj` 가 예외를 내지 않음 (단위·provenance 06) |
| 6 | 분석기: 8b SQL 실패 시 0행으로 `OK`, journal 줄을 cron 으로 셈 | 중하 | `INCOMPLETE` 처리, crontab 부분만 셈 (단위) |
| 7 | 스크립트: SET/UNSET·키 이름 줄이 가려짐, `--flag 값`·JSON 형식 비밀은 마스킹 안 됨, 8b 키워드 JOIN 이 Sync 와 다름 | 하 | 모두 수정, 마스킹 시험 확인 |
| 8 | 단일 writer 로 거부된 정기 실행이 알림 없이 멈춤 | 하 | Slack 알림, `reason` 유지 (단위) |
| 9 | 전환 증거가 설정 파일에 남아 이후 모든 실행을 허용 | 하 | 래퍼 매개변수(`-CutoverConfirmed -CutoverEvidence`)로만 받음 |

## 6. 실제 병합 여부

- PR #371: **미병합** (리뷰 0).
- Windows 브랜치: **PR 미생성, 미병합**.
- 통합 브랜치: 시험용. main 으로 병합하지 않음.
- GitHub 에서 확인: `merged=false`.

## 7. Staging 점검 대기 상태

- 결과: **NOT_AVAILABLE**. 29건은 검증 완료로 표시하지 않습니다.
- 이번에 Staging 접속은 시도하지 않았습니다.
- 스크립트를 고쳤으므로 **최신 SHA-256 = `50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd`** (LF blob, `efa436a`). 이전 값은 모두 폐기합니다.
  - `a0053fd9…`, `4fe2638e…`(CRLF 오계산), `6db6448a…`
- 정적 검증: `bash -n` OK, 쓰기·재시작·cron·외부 HTTP 명령 0, SQL 5블록 모두 READ ONLY + ROLLBACK, 마스킹 시험 OK.
- 담당자용 명령 (Staging 서버 또는 승인된 관리 PC, 배포 사용자):

```bash
set -eu
WORK=$(mktemp -d /tmp/aicp-check-XXXX) && cd "$WORK"
# 1) 받기: 저장소가 공개가 아니면 scp 로 같은 파일(브랜치 feat/crawler-windows-local-pc)을 복사
curl -fsSL -o staging_readonly_check.sh \
  https://raw.githubusercontent.com/ai-career-platform/ai-career-platform/feat/crawler-windows-local-pc/poc/staging/automation/safety/staging_readonly_check.sh
# 2) 검증: 해시가 다르면(CRLF 사본 포함) 중단
echo "50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd  staging_readonly_check.sh" | sha256sum -c -
bash -n staging_readonly_check.sh
# 3) 실행 (읽기 전용, 1분 이내)
OUT="staging-check-$(hostname)-$(date +%Y%m%d-%H%M%S).txt"
bash staging_readonly_check.sh > "$OUT" 2>&1; echo "exit=$?"
# 4) Secret 노출 점검: 아무것도 출력되지 않아야 함
grep -nE '(PASSWORD|TOKEN|SECRET|WEBHOOK|_KEY)=[^<[:space:]]|://[^/@<[:space:]]+:[^@<[:space:]]+@|hooks\.slack\.com/services/[A-Z0-9]|BEGIN [A-Z ]*PRIVATE KEY' "$OUT" || echo "NO_SECRET_PATTERN"
# 5) 전달: $OUT 을 사내 전달 경로로 PM 에게 (GitHub·공개 채널 금지). 파일 해시도 함께
sha256sum "$OUT"
```

- 결과를 받으면 이 PC 에서 분석합니다(네트워크·DB 없음):
  `.\.venv\Scripts\python.exe poc\staging\automation\safety\analyze_staging_check.py <파일> --json C:\dev\crawler-data\logs\staging-analysis.json`
  - 4분류 합계를 검사하고, 이관 가능 목록(`migratable_ids`)과 cron·PUBLISH 상태를 출력합니다.
  - 합계가 맞지 않으면 `INCONSISTENT`, 절이 빠지면 `INCOMPLETE` 입니다.

## 8. 출처 검증 (분류와 동기화 정책 정합성)

| 분류 | 판정 근거 | Sync 동작 |
|---|---|---|
| VERIFIED_APPROVED | 끝난 night job(SUCCEEDED/PARTIAL), HTTP>0, 자기 밤(21:00~08:00 KST) 안에 실행, 발견 기록(first/last)이 job 시간 안, **payload 마지막 쓰기 ≤ job 종료**. 8c 승인 파일 기간과 맞으면 `approval_file:<이름>`, 아니면 `gate_enforced_night_job`(night job 은 `live_gate` ALLOWED 뒤에만 생김. 비공개 승인 기록으로 PM 이 확인) | **이관** |
| VERIFIED_UNAPPROVED | 승인 job 없음 + 셸 기록에 그 ID 의 게이트 이전 CLI import | 제외 |
| VERIFIED_FIXTURE | 테스트 시계 job, 또는 배포된 fixture·테스트 파일에 같은 ID. 단 승인 job 이 있으면 APPROVED 가 우선(실제 공고 ID 가 fixture 에도 있음, 예: 50246410) | 제외 |
| UNVERIFIED_ORIGIN | 그 밖(job 없음, 실패 job, payload 변경 등) | 제외 |

- **시간대**: SQL 이 `AT TIME ZONE 'Asia/Seoul'` 를 명시해 서버 시간대와 무관합니다. 분석기는 psql 의 `+09`/`+00` 오프셋을 그대로 해석합니다(`+00` 시험 포함).
- **정합성**: provenance 00 이 점검 스크립트 8b SQL 과 `STAGING_PROVENANCE_SQL` 을 같은 데이터에 실행해 행 단위 결과가 같아야 통과합니다. 분석기의 VERIFIED_APPROVED 는 8b 의 `LIVE_JOB_LINKED` 와 같습니다(단위 시험).
- 승인된 실제 공고가 잘못 막히지 않는지: 승인 job 2건과 다시 확인된 1건이 이관됩니다. fixture 에 같은 ID 가 있어도 APPROVED 입니다.
- Staging 배포는 하지 않았습니다.

## 9. GCP 이중 동기화 차단

| 항목 | 구현과 검증 |
|---|---|
| Source 식별 | 모든 실행이 `error_summary.source`(local/staging)를 행 생성 순간부터 기록. 구 배포 코드의 행(키 없음)은 staging |
| 실행 이력 범위 | **기간 제한 없음**: 모든 상태(succeeded/failed/running)를 셈. 이전의 7일 창은 리뷰 지적에 따라 없앰 |
| Staging Sync 감지 | `other_writers` (마지막 실행 시각, 진행 중 여부) |
| 다른 Source 거부 | `OTHER_SYNC_SOURCE_ACTIVE` (run: FAILED, scheduled: SKIPPED + Slack 알림) |
| `GCP_SYNC_CUTOVER_CONFIRMED` | **단독으로는 부족**. 추가로 상대 writer 진행 중 없음(`OTHER_SYNC_RUNNING`), 상대의 마지막 실행이 26시간 넘게 지남(`OTHER_SYNC_RECENT`: 08:05 일일 cron 이 최소 한 번 빠짐), 증거 참조 필수(`CUTOVER_EVIDENCE_REQUIRED`). 증거 문자열은 `error_summary.cutover` 에 기록. 래퍼에서는 실행마다 매개변수로 줌 |
| 기존 공고 중복 방지 / 같은 ID UPSERT | external_refs 식별. 실데이터 dry-run 에서 50350626 은 duplicate |
| Run ID 기록 | `ingestion_runs` + 로컬 run ID 목록 |
| 실패 ROLLBACK / 재실행 멱등 | 4절 표 |

전환 때 코드 바깥에서 반드시 확인할 것(코드는 일부만 증명함):
1. Staging cron 중단 증거: `crontab -l | grep -c run_gcp_sync.sh` = 0 과 그 다음 08:05 에 sync 로그가 없음. 점검 스크립트 4·6절.
2. 진행 중 Sync 없음: 스크립트 6절 프로세스, Target `running` 행 없음.
3. 기존 Sync 마지막 실행 이력: 스크립트 6절, 코드의 `other_writers`.
4. 새 PC 단일 실행 승인: PM 서면.
5. 운영 Target 연결 확인: 승인 C 의 dry-run.
6. 실패 시 복구 절차: 자동 롤백, 실행 후 ID 범위 삭제 SQL(UNBLOCK_PLAN 7절 J), Staging cron 재등록 명령(README).

**위 조건이 충족되기 전에는 실제 GCP 쓰기를 하지 않습니다.**

## 10. GCP 실제 이관 준비

| 조건 | 상태 |
|---|---|
| 코드 | 준비 완료(위 테스트). 단, 운영 Staging 에는 미배포. 배포 전 Staging cron 은 구 코드라 단일 writer 규칙을 모르므로, 새 PC 쪽 검사와 cron 중단 확인으로 보완해야 함 |
| `career_sync` 계정·최소 권한 | SQL·리허설 준비. 운영 존재 여부 미확인 (스크립트 5절 `target_user_is_career_sync` 로 Staging 이 쓰는 계정 확인 가능) |
| CA / 호스트명 | 미확보. Staging `gcp-sync/server-ca.pem`(공개 인증서)을 이 PC 로 복사 가능. 호스트명은 Cloud SQL 인스턴스 정보에서 확인 |
| 네트워크 | 미검증. 단발은 승인 네트워크에 기간 한정 IP, 정기는 Auth Proxy 검토 |
| 실제 쓰기 | **NOT_RUN** (승인 C 없음) |

## 11. 보안 상태

| 항목 | 결과 (이번 확인) |
|---|---|
| `.env` Git 제외 | 커밋 이력 0 |
| 로그·기록 비밀 노출 | `.env` 의 비밀값 4종(8자 이상)이 로그·상태·스크래치패드·**이 프로젝트의 Claude Code 세션 기록** 1,448개 파일 어디에도 없음(값 미출력, 개수만 확인). 8자 미만 Staging SSH 비밀번호는 오탐 때문에 검사에서 제외 |
| 관리자 계정 | GCP Sync 는 관리자 계정을 거부, 사용 안 함 |
| `career_sync` / TLS | 7·10절 |
| 스크립트 줄바꿈 | `.gitattributes` 로 `*.sh` LF 고정. Windows 작업 사본 CRLF 때문에 생긴 SHA 오보고를 바로잡음 |
| 자격증명 교체 | 계획만(SAFETY_GATE 6절 순서). 실행은 PM 승인 후 |

## 12. 남은 승인 사항

1. **PR #371 독립 승인 리뷰**(GitHub) → squash 병합.
2. **Windows 브랜치 PR 생성**(웹, 본문 준비됨) → CI → 독립 승인 리뷰 → 병합 → Staging 배포(Auto-CD).
3. **Staging 점검 실행**(7절 명령) → 분석기로 29건 분류 → 미확인·미승인 행 처리 결정.
4. **자격증명 회전**(`crawler_staging`, Staging SSH, Slack Webhook, Cloud SQL 관리자) / 이 PC `.env` 의 운영 키 제거.
5. **승인 C**: `career_sync`·CA·호스트명·네트워크, 운영 dry-run.
6. **전환 승인**: Staging cron 중단(증거) → 26시간 이상 공백 확인 → `-CutoverConfirmed -CutoverEvidence` 로 새 PC 실행 → verify.
7. 잡코리아 API 승인 또는 수집 허가 → 일 1,000건 단계(GOAL 3).

## 13. 다음 실행 순서

1. #371 리뷰·병합 → `git rebase origin/main`(Windows 브랜치, 통합 브랜치와 같은 해결) → PR 생성(본문 붙여넣기) → CI·리뷰·병합.
2. 배포 뒤 Staging cron 이 출처 필터와 단일 writer 규칙으로 동작합니다(미확인 행 송신 중단).
3. Staging 점검 → 분류 → 결정.
4. 승인 C:

   ```powershell
   .\scripts\windows\run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed
   ```

5. 전환:
   - Staging 에서 `crontab -l | grep -v run_gcp_sync.sh | crontab -` (승인 후, 백업 후).
   - 다음 08:05 공백 확인(26시간 이상).
   - 실행과 검증:

   ```powershell
   .\scripts\windows\run-gcp-sync-local.ps1 -Mode run -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed -CutoverConfirmed -CutoverEvidence "<cron 중단 증거 참조>"
   .\scripts\windows\run-gcp-sync-local.ps1 -Mode verify -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed
   ```

**FINAL_STATUS=PARTIAL**:
- 코드 통합 검증과 전환 준비는 끝났습니다.
- 다음은 하지 않았습니다(필요 조건 미충족, 불가하거나 승인 대기): PR 병합(리뷰 0), Windows PR 생성(인증 없음), Staging 결과 확보(외부 의존), 실제 GCP 쓰기(승인 C 전).
