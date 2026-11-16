# Staging 직접 점검 (AI_CAREER_STAGING_DIRECT_SAFETY_AUDIT) — **BLOCKED: 서버에서 실행되지 않음**

## 1. 점검 일시

2026-11-16 18:0x KST. 준비·검증만 했고 **Staging 에서 실행된 명령은 0개** 입니다.

## 2~3. 실제 접속 환경과 접근 결과

| 항목 | 결과 |
|---|---|
| 작업 환경 | 새 Windows PC (Wi-Fi 10.2.17.x/23). Staging 은 10.2.10.x |
| 접근 A (서버에서 직접 실행) | 이 에이전트는 Staging 셸이 없음 → 담당자 필요 |
| 접근 B (승인된 관리 PC·네트워크) | 이 PC 는 TCP 22 시간 초과(17:13, 1회). 지시대로 **다시 시도하지 않음** |
| 접근 C (승인된 원격 관리 세션) | 이 PC 에 구성된 세션 없음(VPN·ssh_config 없음) |
| 새 경로·포트 탐색 | 하지 않음 |
| **STAGING_CONNECTION** | **BLOCKED** |

## 4. 실행 증거

서버 실행 증거는 **없음**. 대신 아래 점검 도구를 준비하고 검증했습니다.

### 4.1 점검 스크립트 v3 — 실행 전 안전성 검토 (이 PC 에서 수행)

- 파일: [`poc/staging/automation/safety/staging_readonly_check.sh`](../../poc/staging/automation/safety/staging_readonly_check.sh)
- SHA-256: `a0053fd93459a5958cf5d49754cc55f199e0f3a621e716ebd1dad42aff04d275` (LF, 커밋된 내용 기준. 실행 전에 `sha256sum` 으로 대조)

| 요구 | 결과 |
|---|---|
| 읽기 전용 SQL 만 | SQL 블록 5개, 모두 `BEGIN READ ONLY; … ROLLBACK;`. INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/GRANT/REVOKE/COPY/VACUUM **0** |
| 서비스는 조회만 | `docker compose ps/images/exec(조회 명령)/logs`, `systemctl list-timers/is-enabled/is-active`, `journalctl`. start/stop/restart/up/down/run/cp/pull/build **0** |
| cron 은 조회만 | `crontab -l`, `/etc/cron*` grep. `crontab -e/-r`·파일로 crontab 설치 **0** |
| Secret·설정 원문 미출력 | env 는 SET/UNSET. `gcp-sync.env` 는 권한·키 이름·`GCP_SYNC_PUBLISH`(0/1 문자만)·`career_sync` 일치 여부만. 승인 파일은 상태·유효기간·목적·URL 개수·`approved_by_set`/`evidence_ref_set`(참·거짓)만. 출력 전체에 redaction 필터(비밀 키 값, URL 안 자격증명, Slack hook, PEM)를 적용하며, 시험 입력으로 검증함 |
| 외부 HTTP 없음 | `curl` 은 `http://127.0.0.1:8000/api/version`(서버 자신) 1개뿐. wget 없음 |
| GCP 쓰기 없음 | Cloud SQL 접속 명령 없음 |
| 자동 실행 등록 없음 | systemd-run, at, crontab 설치, 타이머 enable **0** |
| 문법 | `bash -n` OK |
| SQL 실검증 | 출처 분류 SQL(8b)을 이 PC 의 로컬 DB(같은 스키마)에서 `crawler_local` 로 읽기 전용 실행, exit 0 |

**검증 중 발견해 고친 결함**: 첫 판에서는 "night job 과 연결되고 HTTP>0"만으로 LIVE 로 분류했습니다. 그러자 로컬의 mock HTTP 테스트 행 26건이 LIVE 로 잘못 분류됐습니다.
- 원인: 테스트 job 은 `night_date`(예: 2034-02-15)와 실제 실행 시각(2026-11-16)이 다릅니다.
- 수정: job 의 실제 시작 시각이 `night_date 21:00 ~ 다음날 08:00 KST` 안에 있어야 `LIVE_JOB_LINKED` 입니다. 아니면 `JOB_LINKED_SYNTHETIC_CLOCK` 입니다.
- 수정 후 로컬 결과: 테스트 26 → `JOB_LINKED_SYNTHETIC_CLOCK`, 이 PC 의 실제 harvest 5 → `DISCOVERY_WITHOUT_JOB`(harvest 는 night job 이 아님).

### 4.2 담당자 실행 방법 (Staging 서버 또는 승인된 관리 PC)

```bash
# 저장소 브랜치 feat/crawler-windows-local-pc 의 파일을 서버로 가져온 뒤 (scp 또는 git show)
sha256sum staging_readonly_check.sh        # a0053fd9…d275 와 같아야 함
less staging_readonly_check.sh             # 실행 전 내용 확인
bash staging_readonly_check.sh > staging-check-$(date +%Y%m%d-%H%M%S).txt 2>&1
# 또는 승인된 관리 PC 에서
ssh <staging> 'bash -s' < staging_readonly_check.sh > staging-check.txt 2>&1
```

- 실행 사용자: 배포 사용자(`kant`, docker 그룹). **sudo 불필요**(sudo 가 필요하다고 나오면 그 항목은 건너뜀).
- 소요: 1분 이내. 서버에 파일을 만들지 않습니다(stdout 만).
- 결과 파일은 비밀값이 마스킹된 상태입니다. 그래도 공유 전에 담당자가 한 번 훑어봅니다. 공고 필드(공개 정보)는 포함됩니다.

### 4.3 받아야 할 결과 (스크립트 절 번호)

| 판정 항목 | 절 |
|---|---|
| cron 등록·주석 여부·데몬·실행 기록·주기 | 4 |
| `GCP_SYNC_PUBLISH` (0/1), `career_sync` 사용 여부, env 권한 | 5 |
| sync 실행 이력(run_id·시각·fetched·inserted·updated·duplicate·skipped·failed·publish·slack) | 6 |
| 실행 중 sync 프로세스 | 6 |
| 배포 SHA, `gcp_sync.py` 해시, fail-closed·로컬 Source 코드 포함 여부 | 2 |
| 29건 각각: ID·`updated_at`·`xmin`·키워드·`first_seen_at`·연결 job(시작·종료·HTTP·결과)·evidence 분류, 그리고 분류별 합계 | 8, **8b** |
| 전체 night job 목록 | 8b |
| 승인 파일 유효기간·상태 | **8c** |
| fixture·테스트 파일과 ID 일치 | 9 |
| 11-08 배포 journal·backend 로그·셸 기록·outputs | 10 |

### 4.4 결과를 받은 뒤의 분류 규칙 (29건 각각 정확히 하나)

| 최종 분류 | 조건 (모두 충족) |
|---|---|
| **VERIFIED_LIVE_APPROVED** | 8b `LIVE_JOB_LINKED`, 그리고 그 job 의 `started_at` 이 8c 의 어떤 승인 파일의 `[valid_from_utc, review_due_utc)` 안에 있고 그 파일이 `APPROVED`·`enabled`·목적 `night_keyword_collection`·`approved_by_set`·`evidence_ref_set` |
| **VERIFIED_LIVE_UNAPPROVED** | 8b `LIVE_JOB_LINKED` 이지만, 그 시각을 덮는 유효 승인 파일이 **8c 에 없다는 것이 확인됨**. 승인 파일이 삭제됐을 수 있으므로, PM 의 승인 기록(비공개)과도 대조해 둘 다 없을 때만 이 분류 |
| **VERIFIED_FIXTURE** | `JOB_LINKED_SYNTHETIC_CLOCK`, 또는 9절에서 fixture·테스트 파일에 같은 ID, 또는 8절 합성 표지(긴 ID·합성 제목·비 JobKorea URL) |
| **UNVERIFIED_ORIGIN** | 그 밖의 모든 경우. `DISCOVERY_WITHOUT_JOB`/`NO_DISCOVERY`(예: 11-08 의 5건)이면서 10절에 수집 증거(로그의 live_http 결과와 해당 ID)가 없는 경우 포함 |

- 11-08 의 5건은 10절의 backend 로그나 셸 기록에 `import_jobkorea_html --list-url/--url` 실행과 결과가 남아 있을 때만 "실제 HTTP 수집"으로 볼 수 있습니다.
- 그때도 승인 파일이 없으면 `VERIFIED_LIVE_UNAPPROVED`, 기록이 없으면 `UNVERIFIED_ORIGIN` 입니다.

## 5~6. GCP Sync cron · GCP_SYNC_PUBLISH

| 항목 | 이번 직접 점검 | 기존 기록 (CRAWLER_RECOVERY_2026-11-16, 다른 세션의 읽기 전용 관측, 재검증 아님) |
|---|---|---|
| cron 활성 | **NOT_RUN** | 활성, 08:05 KST (`5 23 * * *` UTC) |
| 마지막 실행 | **NOT_RUN** | `045e68d4…` 2026-11-16 08:05 SUCCEEDED |
| 실행 중 프로세스 | **NOT_RUN** | — |
| `GCP_SYNC_PUBLISH` | **UNKNOWN** | 값 미기록. Target 29건 모두 draft |

## 7~11. 공고 분류 (STAGING_TOTAL_ROWS 포함)

이번 직접 점검으로 확정된 것은 **없음**. 기록상 총 29건(DOCUMENTED). 완료 기준상 분류는 서버 결과가 있어야 합니다.

| 분류 | 확정 건수 |
|---|---|
| VERIFIED_LIVE_APPROVED | **UNKNOWN** (참고: 50350626 은 기록상 승인 기간 안의 job `16a8fc29` 수집분, 서버 결과로 확정 필요) |
| VERIFIED_LIVE_UNAPPROVED | **UNKNOWN** |
| VERIFIED_FIXTURE | **UNKNOWN** |
| UNVERIFIED_ORIGIN | **29 (서버 결과 전까지 전체를 이 분류로 둠)** |

## 12. GCP 이관 이력

| 항목 | 값 |
|---|---|
| Staging 로그 직접 조회 | **NOT_RUN** |
| 기록상 | `045e68d4…` (fetched 59, inserted 1, duplicate 28, skipped 30, failed 0, 코드 `1797f4c`), `ce757d96…` (재현만) |
| Cloud SQL 현재 상태 | **UNKNOWN**. 이번에 접속하지 않았고, 승인·읽기 권한이 없음. 기록상 29 draft / 공개 0 은 추정으로 확정하지 않음 |

## 13. 현재 공개 위험과 운영 위험 (증거 / 미확인 / 수준 / 조치 / 승인)

| # | 위험 | 확인된 증거 | 미확인 | 수준 | 권장 조치 | PM 승인 |
|---|---|---|---|---|---|---|
| 1 | 미확인 공고의 GCP 이관 | 기록: 29건 전부 Target 존재 | 어느 행이 미확인인지, 현재 Target | **중~높음** | 서버 결과로 분류 → 미확인 행 ID 목록 → Cloud SQL 읽기 전용 확인(승인) → draft 유지 또는 격리·삭제 결정 | 필요 |
| 2 | 미승인 수집 데이터 혼입 | 11-08 5건 정황(게이트 이전 도구 배포 7분 뒤 기록) | 실제 HTTP 여부, 승인 여부 | **중** (권리) | 10절 로그·셸 기록 확인 | 필요 |
| 3 | 테스트 데이터 혼입 | 기록: Staging E2E 는 격리 DB 사용. 새 PC 테스트 행은 원장 필터로 차단(리허설) | Staging 운영 DB 의 합성 표지 | **낮음** | 8·9절 결과 확인 | 불필요(읽기) |
| 4 | Draft 공개 | 기록: 공개 0 | `GCP_SYNC_PUBLISH` 실값, 현재 공개 상태 | **낮음** (PUBLISH=1 이면 높음) | 5절 값 확인. PUBLISH 변경 금지 규칙 | 변경 시 필요 |
| 5 | Staging·새 PC 이중 동기화 | 같은 source code `jobkorea_live` 와 같은 공고(50350626)가 양쪽에 있음(DIRECT + 기록) | Staging cron 현재 상태 | **중** | 새 PC 의 GCP 이관은 Staging cron 처리 결정 뒤에만. 단일 writer | 필요 |

**일괄 차단 코드 검토** (이 브랜치의 `SOURCE_PROVENANCE_REQUIRED`):
- **미배포라 보호 조치가 아닙니다.**
- 그대로 배포하면 Staging Source 전체를 거부하므로, **승인된 정상 LIVE 공고의 이관까지 막습니다**. 범위가 과도합니다.
- 대안: Staging Source 에서도 8b 와 같은 기준(`LIVE_JOB_LINKED` 이면서 승인 기간 안)을 만족하는 행만 선택하고, 나머지는 `SKIPPED: PROVENANCE_UNVERIFIED` 로 기록합니다.
- 서버 결과로 분류가 확정된 뒤에 설계합니다(이번 단계에서는 구현하지 않음).

## 14. 차단이 필요한 작업

| 작업 | 이유 | 지금 |
|---|---|---|
| 새 PC 의 GCP 이관(승인 C) | 완료 기준 미충족 (이번 지시) | **보류** |
| Staging cron 중지 | 서버 결과(5절·6절)를 보고 결정. 기록상 공개 0, Staging LIVE OFF | 결정 대기 (변경 없음) |
| fail-closed 가드 배포 | 범위 과다 | 보류 |

## 15. 다음 PM 승인 요청

1. **스크립트 실행 담당자 지정**: Staging 셸 권한자가 4.2 의 방법으로 실행하고 결과 파일을 공유. 또는 이 PC 에서 Staging 22번 포트로 가는 경로를 네트워크 담당이 허용(그 경우에만 이 에이전트가 같은 스크립트를 1회 실행).
2. 결과에 따른 분류 확정과 미확인 행 처리 결정.
3. (분류 후) Cloud SQL 읽기 전용 확인 승인: 최소 권한 계정, 미확인 ID 의 Target 상태.
4. cron 유지·중지 결정, 단일 writer 전환 계획.
