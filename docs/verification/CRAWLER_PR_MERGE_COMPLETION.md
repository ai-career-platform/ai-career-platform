# PR #371 및 Windows 크롤러 main 반영 (AI_CAREER_CRAWLER_PR_MERGE_COMPLETION, 2026-11-16)

판정 원칙: 실제로 실행하고 확인한 것만 PASS. GitHub 상태는 공개 API 로 직접 다시 읽었습니다.

이번 작업에서 하지 않은 것:
- 운영 서버·GCP·Staging·JobKorea 접촉, LIVE 요청
- 자격증명 추출·변경, 보호 규칙 우회
- main 직접 커밋, 강제 push
- 에이전트에 의한 PR 병합·승인

GitHub 쓰기는 일반 `git push` 로 브랜치 2개를 올린 것뿐입니다.

## 1. PR #371

| 항목 | 값 (2026-11-16 21:5x KST) |
|---|---|
| 상태 | **MERGED** (`merged_at` 2026-11-16T12:49:03Z = 21:49 KST) |
| 병합한 사람 | `GilbertMoon` (PR 작성자 계정). 에이전트가 병합한 것이 아닙니다 |
| 방식 | Squash. Merge commit **`a134e40`** (`a134e4080b4d94345db6016e7724589f71a63112`), 부모 1개 |
| 병합된 head | `c025f51`. main 트리가 `c025f51` 트리와 동일함을 확인 |
| CI | head `c025f51` check-runs 3/3 success: offline-tests, Backend pytest, CI Smoke Test |
| 승인 리뷰 | **0** (`/pulls/371/reviews` = `[]`) |
| 미해결 리뷰 의견 | 인라인 리뷰 댓글 0. 대화 댓글 2건은 작성자의 리뷰 요청 |

> **주의.** PM 조건은 "실제 GitHub 승인 기록 확인 후 병합"이었습니다. GitHub 기록상 승인 리뷰 없이 작성자 계정으로 병합됐으므로, **독립 승인 조건은 충족되지 않았습니다**.
> 이 계정은 자기 PR 을 승인할 수 없습니다. 사후 독립 리뷰가 필요하면 병합된 PR 에 리뷰를 남기거나, `a134e40` 을 대상으로 리뷰 이슈를 열어야 합니다.
>
> 참고로 최근 main 병합 PR(#330–#350)에도 리뷰 기록이 없습니다. main 보호 규칙의 세부 설정은 인증이 없어 읽지 못했습니다(401).

## 2. Windows 브랜치 정리 (STEP 03)

| 항목 | 값 |
|---|---|
| 브랜치 | `feat/crawler-windows-local-pc` = origin, HEAD **`129d1e1`** (+ 이 보고서 커밋) |
| 새 커밋 | `7dbf2e6`: 테스트 실행기 수정. 단계별 DSN 덮어쓰기 시 hashtable `+` 가 중복 키로 오류를 출력하던 문제<br>`129d1e1`: main(`a134e40`) 병합 |
| 충돌 | `crawler/jobs/gcp_sync.py` 1파일 2곳 |
| 해결 | 검증된 통합 브랜치의 해결과 동일합니다. 결과 트리 = `integration/pr371-windows-crawler` **`558e48e`** 트리 (git tree hash 일치) |
| 병합 방식 | merge. rebase 나 강제 push 를 쓰지 않아 기존 브랜치 이력을 덮어쓰지 않았습니다 |
| #371 중복 포함 여부 | 없음. main 대비 diff 는 Windows 측 변경만(52파일, 커밋 15개) |
| 통합 브랜치 | `integration/pr371-windows-crawler` `558e48e` push. 기록용이며 main 병합 대상이 아닙니다 |

`129d1e1` 의 main 대비 diff 를 이렇게 확인했습니다:
- #371 만 바꾼 8파일은 main 과 동일합니다.
- 양쪽이 같이 바꾼 `import_jobkorea_html.py` 와 `test_gcp_sync.py` 에는 Windows 측 줄만 남아 있습니다.

**기능 보존 확인 (기계 검사):**
- #371 이 바꾼 11파일 중 10파일: #371 diff 의 역적용 검사(`git apply --check -R`)를 통과합니다. 즉 #371 변경이 그대로 들어 있습니다.
- `gcp_sync.py`: #371 추가 42줄 모두 존재.
  - Windows 측 추가 274줄 중 273줄 존재.
  - 빠진 1줄은 `result.skipped.append((key, 'PROVENANCE_UNVERIFIED'))` 이고, #371 API 인 `result.skip(row, 'PROVENANCE_UNVERIFIED')` 로 바뀐 것이 의도한 해결입니다.
  - #371 이 삭제한 줄은 하나도 남아 있지 않습니다.

| 필수 보존 기능 | 위치 | 테스트 |
|---|---|---|
| #371 날짜 오류 수정 | `local_gcp_sync_pg.test_08` (현재 시각 기준) | pg-gcp-sync 12/12 |
| 키워드 간 중복 제거 | `night_crawl.py` (#371, 역적용 검사 통과) | unit `test_night_crawl`, pg-night-integration 13/13 |
| Skip 사유 | `Plan.skip()`, `skipped_by_source` | `test_skip_reasons_by_source_and_per_record_items` |
| 승인된 LIVE Run ID 검증 | `read_source(live_run_ids)`, `LIVE_RUN_NOT_ELIGIBLE` | local-source test_01 |
| Fixture·출처 불명 공고 차단 | harvest 원장 선택, `PROVENANCE_UNVERIFIED` | local-source test_02, staging-provenance test_01·02 |
| Staging 공고별 출처 검증 | `STAGING_PROVENANCE_SQL` | staging-provenance test_00–02 |
| 단일 Sync Writer | `other_writers`, `cutover_refusal` | staging-provenance test_03–07 |
| Cutover 증거 검증 | `CUTOVER_EVIDENCE_REQUIRED` | staging-provenance test_04, unit `test_cutover_refusal_order` |
| Draft 기본 | `status: ... if publish else 'draft'` | pg-gcp-sync test_02·07, local-source test_03 |
| 재실행 멱등성 | duplicate 판정 | pg-gcp-sync test_03, local-source test_05 |
| 운영 Secret 보호 | `.env` 미사용, 관리자 계정 거부(`REFUSED_USERS`, `rolsuper`) | pg-gcp-sync test_09, 이전 TLS 리허설 음성 사례 |

## 3. 통합 회귀 테스트 (STEP 04, 이번에 실제 실행)

- 대상 코드: `558e48e`. 트리가 Windows PR head `129d1e1` 과 동일합니다.
- DB: 새로 만든 일회용 PostgreSQL 18.7 클러스터(`C:\dev\crawler-data-int3`, 127.0.0.1:5436). 운영 DB·자격증명은 쓰지 않았습니다.
- 로그: `C:\dev\crawler-data-int3\logs\tests-20261116-214411\summary.json`
- 결과: 17단계, 실패 0, `EGRESS_ATTEMPTS=0`(외부 요청 0)

| 스위트 | 실행 | PASS | FAIL | SKIP |
|---|---|---|---|---|
| Crawler unit | 554 | 549 | 0 | 5 (Linux 전용) |
| Backend | 21 | 21 | 0 | 0 |
| PostgreSQL 합계 | 99 | 98 | 0 | 1 |
| ├ gcp-sync | 12 | 12 | 0 | 0 |
| ├ gcp-sync local-source | 7 | 7 | 0 | 0 |
| ├ gcp-sync staging-provenance | 8 | 8 | 0 | 0 |
| ├ harvest | 9 | 9 | 0 | 0 |
| ├ html | 2 | 2 | 0 | 0 |
| ├ t64 | 14 | 14 | 0 | 0 |
| ├ night executor/caller | 16 | 15 | 0 | 1 |
| ├ night integration | 13 | 13 | 0 | 0 |
| ├ t155 read / write | 3 / 6 | 3 / 6 | 0 | 0 |
| ├ t152 | 2 | 2 | 0 | 0 |
| └ night e2e | 7 | 7 | 0 | 0 |

- 실행하지 않은 것:
  - pg-staging-mode, pg-t64-permissions: `db:5432` 하드코딩이라 해당 없음
  - Docker 컨테이너 테스트: 이 PC 에 Docker 가 없음
- 실행기 수정(`7dbf2e6`) 전인 `fcf4866` 에서도 같은 수치로 한 번 실행했습니다(`C:\dev\crawler-data-int2\logs\tests-20261116-214216`).

**지정 확인 항목:**

| # | 항목 | 테스트 | 결과 |
|---|---|---|---|
| 1 | Source 중복 감지 (두 번째 writer) | staging-provenance test_03, test_05 | PASS |
| 2 | 실패한 Sync 도 writer 활동 | staging-provenance test_07 | PASS |
| 3 | Cutover 26시간 조건 | staging-provenance test_04 (`OTHER_SYNC_RECENT`), unit `test_cutover_refusal_order` | PASS |
| 4 | Cutover Evidence 필수 | staging-provenance test_04 (`CUTOVER_EVIDENCE_REQUIRED`) | PASS |
| 5 | 승인 공고 출처 검증 | staging-provenance test_00–02 | PASS |
| 6 | 승인 이후 수정된 데이터 차단 | staging-provenance test_00 (`JOB_LINKED_PAYLOAD_CHANGED`), local-source test_07 | PASS |
| 7 | Fixture row 전송 차단 | local-source test_01·02, staging-provenance test_01 | PASS |
| 8 | 동일 Posting ID 중복 방지 | pg-gcp-sync test_03·06, unit `test_identical_row_is_duplicate_and_not_written`, `test_duplicate_url_inside_source_is_skipped` | PASS |
| 9 | 트랜잭션 Rollback | pg-gcp-sync test_05·10 | PASS |
| 10 | Draft 유지 | pg-gcp-sync test_02·07, local-source test_03 | PASS |

## 4. Windows PR (STEP 05)

| 항목 | 값 |
|---|---|
| PR | **미생성** |
| 이유 | 이 PC 에 GitHub 로그인이 없음. 저장된 git 자격증명(Git Credential Manager)은 읽지 않았습니다 |
| 준비한 것 | 공식 GitHub CLI v2.62.0 휴대용을 `C:\dev\tools\gh-2.62.0` 에 설치(공식 checksum 일치). 로그인은 사용자가 브라우저 장치 코드로 해야 합니다 |
| 로그인 명령 | `C:\dev\tools\gh-2.62.0\bin\gh.exe auth login --hostname github.com --git-protocol https --web` |
| 생성 명령 | `gh pr create --base main --head feat/crawler-windows-local-pc --title "feat(crawler): Windows local crawler and safe GCP sync cutover" --body-file docs/verification/WINDOWS_CRAWLER_PR_BODY.md` |
| 웹 대안 | https://github.com/ai-career-platform/ai-career-platform/compare/main...feat/crawler-windows-local-pc (본문: [WINDOWS_CRAWLER_PR_BODY.md](WINDOWS_CRAWLER_PR_BODY.md), 최신 결과 반영) |
| 충돌 | 없음. 이미 main 을 포함하고 있음 |
| CI / 리뷰 / 병합 | 실행 안 됨 / 0 / 아니오 |
| 리뷰어 | GilbertMoon 이 아닌 쓰기 권한자가 필요합니다. 기여 수 기준 후보: sangjae-lee97, Crasnec, apll970502, kixxuya. 실제 쓰기 권한은 인증이 없어 확인하지 못했습니다 |

## 5. Staging 배포 전 검증 (STEP 06, 배포하지 않음)

| 항목 | 내용 |
|---|---|
| 현재 Staging 배포 코드 | 확인하지 못함. 점검 스크립트 2절(`fail_closed_guard_present`, `local_source_mode_present`)이 판정합니다 |
| 신규 guard 와 기존 cron | 호환됩니다.<br>- cron 은 `run_gcp_sync.sh scheduled` 를 실행하고, `GCP_SYNC_SOURCE` 미설정이면 `staging` 입니다.<br>- writer 가 `staging` 이고 이전 실행(구 코드 기록 포함)도 모두 `staging` 이므로 다른 writer 가 없어 거부되지 않습니다.<br>- 거부되면 `SKIPPED` 와 Slack 알림이 남습니다. |
| 승인 LIVE 공고 이관 | `LIVE_JOB_LINKED` 행은 계속 동기화됩니다 (staging-provenance test_01·02: 승인 3건 insert) |
| 출처 불명 공고 | `PROVENANCE_UNVERIFIED` 로 skip 됩니다. 이미 GCP 에 들어간 행은 삭제하지 않습니다 (sync 계정에 DELETE 권한 없음, test_09) |
| 기존 Draft 데이터 | 보존됩니다. sync 는 insert/update 만 하고 `GCP_SYNC_PUBLISH≠1` 이면 draft 입니다 |
| DB Migration | Target(GCP)은 없습니다.<br>Staging crawler DB 는 필수 아님: 0013(harvest)은 local source 전용이고, 출처 테이블이 없으면 모든 행을 skip 합니다(fail-closed). |
| 배포 전 백업 | 1. Cloud SQL on-demand 백업<br>2. Staging crawler DB `pg_dump -n crawler_training`<br>3. 현재 배포 commit/이미지 태그 기록<br>4. `crontab -l` 사본 |
| 배포 후 검증 SQL (Target, 읽기 전용) | `SELECT status, error_summary, started_at FROM career.ingestion_runs WHERE source_id = (SELECT source_id FROM career.data_sources WHERE code = 'jobkorea_live') ORDER BY started_at DESC LIMIT 3;`<br>→ 최근 실행의 `error_summary` 에 `"source": "staging"`, skip 사유에 `PROVENANCE_UNVERIFIED` 가 보여야 합니다.<br>`SELECT count(*) FROM career.job_postings WHERE status <> 'draft';` → 배포 전과 같아야 합니다. |
| 실패 시 Rollback | 1. 이전 commit/이미지로 재배포 (스키마 변경이 없어 코드만 되돌리면 됨)<br>2. 문제 실행이 쓴 행은 실행 결과의 `inserted_external_ids` 기준으로 실행 범위만 되돌립니다 (CRAWLER_LIVE_GCP_1000.md 6절 C) |
| Staging 29건 출처 | **미점검**. 검증 완료로 표시하지 않습니다 |

**점검 스크립트:**
- 파일: `poc/staging/automation/safety/staging_readonly_check.sh`
- SHA-256 재계산 값: `50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd`
  - `129d1e1`·origin·통합 브랜치의 git blob(LF)과 작업 사본이 모두 같은 값이고, CR 문자 0
  - 지난 보고 값과 같습니다
- 실행: Staging 접속은 시도하지 않았습니다. 담당자 명령은 [CRAWLER_PR_INTEGRATION_AND_CUTOVER_READINESS.md](CRAWLER_PR_INTEGRATION_AND_CUTOVER_READINESS.md) 7절을 그대로 쓰면 됩니다. 다운로드 URL 의 브랜치(`feat/crawler-windows-local-pc`)에 같은 파일이 있습니다.

## 6. GCP 운영 전환 사전 조건 (STEP 07, 이관 실행 안 함)

| # | 조건 | 상태 |
|---|---|---|
| 1 | Staging 출처 점검 | 미실행 (담당자 실행 필요) |
| 2 | 배포된 GCP Sync 보호 코드 검증 | 미충족: Windows PR 미병합, 미배포 |
| 3 | `career_sync` 최소 권한 계정 | 미확인 (승인 C) |
| 4 | TLS 인증서와 호스트명 | 미확인 (승인 C) |
| 5 | 네트워크 연결 확인 | 미확인 (승인 C) |
| 6 | Staging cron 중단 증거 | 없음 |
| 7 | 진행 중 Sync 없음 | 코드가 검사합니다(`OTHER_SYNC_RUNNING`). 운영에서는 미확인 |
| 8 | 26시간 Sync 무실행 | 코드가 검사합니다(`OTHER_SYNC_RECENT`). 운영에서는 미확인 |
| 9 | 단발성 Cutover Evidence | wrapper 매개변수(`-CutoverEvidence`). 미발급 |
| 10 | PM GCP 쓰기 승인 | 없음 |

**GCP_CUTOVER_READY = NO.** 코드 측 차단 장치는 구현과 테스트를 마쳤지만, 운영 조건 1–6·9·10 이 충족되지 않았습니다.

## 7. 남은 승인과 다음 순서

1. **PR #371 사후 독립 리뷰** (선택이지만 권장): GitHub 기록상 승인 0인 채 병합됐습니다.
2. **Windows PR 생성**: `gh auth login` 후 에이전트가 생성하거나, 웹에서 생성합니다. 이어서 CI → 독립 승인 리뷰(GilbertMoon 외) → squash 병합.
3. Staging 점검 스크립트 실행(위 SHA) → 이 PC 에서 `analyze_staging_check.py` 로 29건 분류.
4. Staging 배포 승인: 5절의 백업 → 배포 → 검증 SQL → 실패 시 Rollback.
5. 자격증명 교체 (Staging DB·SSH, Slack webhook, Cloud SQL 관리자).
6. 승인 C: `career_sync`, CA·호스트명, 네트워크 → 운영 dry-run.
7. Cutover:
   1. Staging cron 중단과 증거 확보
   2. 26시간 이상 대기
   3. `run-gcp-sync-local.ps1 -Mode run -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed -CutoverConfirmed -CutoverEvidence "<ref>"`
   4. `verify`

## 8. 최종 결과

```
TASK=AI_CAREER_CRAWLER_PR_MERGE_COMPLETION
PR_371_STATUS=MERGED (squash, by author account GilbertMoon, 2026-11-16 21:49 KST)
PR_371_APPROVALS=0 (no GitHub approval record; independent-approval condition NOT met)
PR_371_CI=3/3 SUCCESS
PR_371_MERGED=YES
PR_371_MERGE_SHA=a134e4080b4d94345db6016e7724589f71a63112
WINDOWS_PR_URL=NOT_CREATED (no GitHub login; compare link + body ready)
WINDOWS_PR_APPROVALS=0
WINDOWS_PR_CI=NOT_RUN
WINDOWS_PR_MERGED=NO
WINDOWS_MERGE_SHA=N/A
INTEGRATION_BRANCH=integration/pr371-windows-crawler 558e48e (tree == feat/crawler-windows-local-pc 129d1e1)
MERGE_CONFLICTS_RESOLVED=YES (gcp_sync.py 2 hunks; main merged into Windows branch, no rebase/force)
CRAWLER_UNIT_TESTS=554 ran / 549 pass / 0 fail / 5 skip
BACKEND_TESTS=21/21
POSTGRESQL_TESTS=99 ran / 98 pass / 0 fail / 1 skip
GCP_SYNC_TESTS=gcp-sync 12/12, local-source 7/7, staging-provenance 8/8
MAIN_HEAD=a134e40
STAGING_DEPLOYED=NO
GCP_WRITES=0
LIVE_REQUESTS=0
STAGING_AUDIT=NOT_RUN (package READY, SHA-256 50996b38…af7bd)
GCP_CUTOVER_READY=NO
REPORT_PATH=docs/verification/CRAWLER_PR_MERGE_COMPLETION.md
REMAINING_BLOCKERS=Windows PR creation (GitHub login) + independent approval + CI; Staging audit; Staging deploy approval; approval C; credential rotation; cutover evidence; GCP write approval
NEXT_PM_ACTION=log in gh (or open PR on web) -> independent reviewer approves Windows PR -> squash merge; run Staging audit
FINAL_STATUS=PARTIAL
```
