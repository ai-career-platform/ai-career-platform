# Staging 안전성 점검 결과 (AI_CAREER_CRAWLER_STAGING_SAFETY_CHECK, STEP 01)

## 1. 점검 일시·방식

- 2026-11-16 17:3x~17:5x KST, 새 Windows PC.
- **Staging 직접 점검: NOT_RUN** (접속 불가, 2절).
- 서버·DB·cron·방화벽·SSH·GCP 변경 0. LIVE 실행 0. GCP Sync 실행 0. 비밀값 출력 0.

증거 등급:

| 등급 | 뜻 |
|---|---|
| **DIRECT** | 이번 점검에서 직접 확인 |
| **DOCUMENTED** | 저장소의 기존 검증 문서에 기록된 읽기 전용 관측. 이번에 다시 확인하지 않음. 주 출처: PR #371 브랜치의 `docs/verification/CRAWLER_RECOVERY_2026-11-16.md`(다른 세션, 2026-11-15 22:16 ~ 11-16 08:36 KST, Staging·Cloud SQL 읽기 전용 조회) |
| **UNVERIFIED** | 어느 쪽 증거도 없음 |

### 정정 (이전 보고서)

[CRAWLER_STAGING_SAFETY_GATE.md](CRAWLER_STAGING_SAFETY_GATE.md), [CRAWLER_OPERATIONAL_UNBLOCK_PLAN.md](CRAWLER_OPERATIONAL_UNBLOCK_PLAN.md) §6 은 main 의 11-12 이전 증거만 근거로 했습니다. 그래서 다음은 **사실과 달랐습니다**.
- "Staging `jobkorea_live` 5건"
- "GCP Sync cron UNKNOWN"
- "Staging 에서 승인된 LIVE 수집 0회"

DOCUMENTED 기준으로 바로잡으면:
- Staging `jobkorea_live` 는 **29건** 입니다.
- 11-12 이후 **비공개 1박 단위 T61 승인 파일**로 실제 LIVE 야간 수집이 있었습니다.
- 08:05 GCP Sync cron 은 **등록·실행 중**이고, Cloud SQL 에 29건이 draft 로 있습니다.

## 2. 서버 접속 여부 — STAGING_CONNECTION=BLOCKED

| 항목 | 결과 (DIRECT) |
|---|---|
| 접속 대상 | `.env` 의 `STAGING_SSH_HOST`/`ALIAS` → 둘 다 사설 10.2.10.x (값 미기록) |
| 이 PC | Wi-Fi 10.2.17.x/23, 기본 게이트웨이 10.2.16.x |
| 라우팅 (`Find-NetRoute`, 패킷 전송 없음) | 10.2.10.0/24 전용 경로 없음 → 기본 경로(0.0.0.0/0)로 게이트웨이에 전달 |
| TCP 22 | 17:13 1회 시도 → **시간 초과**. 재시도하지 않음(지시 준수), 포트 스캔·우회 없음 |
| VPN / ssh_config | VPN 연결 없음, `~/.ssh/config` 없음 |
| 이 PC 방화벽 | TCP 22 대상 차단 규칙 0 |
| 판단 | 이 PC 의 문제가 아니라 **Wi-Fi 대역 → 서버 대역 사이의 ACL·방화벽, 또는 서버 측 SSH 접근 제한** 가능성이 큽니다. **확인되지 않았습니다** |
| 해소 | (a) Staging 대역에서 허용된 PC·콘솔에서 점검 스크립트를 실행하거나 (b) 이 PC 의 IP 에서 22번 포트를 허용하는 네트워크 승인. 참고: DOCUMENTED 에 따르면 DB 는 서버 /24 대역에 15432(socat)로도 열려 있지만, **이 점검에서 사용하지 않습니다**(SSH 경로만 승인 범위) |

## 3. 점검 명령 (읽기 전용 검증 완료, 서버에서 미실행)

스크립트: [`poc/staging/automation/safety/staging_readonly_check.sh`](../../poc/staging/automation/safety/staging_readonly_check.sh) **v2**.

실행:
- 서버에서 `bash staging_readonly_check.sh > staging-check-$(date +%Y%m%d-%H%M%S).txt 2>&1`
- 또는 허용된 PC 에서 `ssh <staging> 'bash -s' < staging_readonly_check.sh > out.txt`

| 정적 검증 (DIRECT) | 결과 |
|---|---|
| `bash -n` | 문법 OK |
| 쓰기 명령 검색 (rm/mv/cp/tee/chmod/kill, crontab -e/-r, systemctl start/stop/enable, compose up/down/restart/cp/run, INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/GRANT/COPY, 파일 리디렉션) | **0건**. 일치한 것은 JSON 연산자 `->>` 와 redaction 규칙뿐 |
| SQL | 4개 블록 모두 `BEGIN READ ONLY … ROLLBACK` |
| 비밀값 | env 는 SET/UNSET 만. 비밀 파일은 존재·권한만. `gcp-sync.env` 에서는 `GCP_SYNC_PUBLISH` 의 0/1 만 읽음 |
| 최종 출력 필터 | `*PASS*/*TOKEN*/*SECRET*/*KEY*/*WEBHOOK*/*RUL*=` 값, URL 안의 `user:pass@`, Slack hook 경로, PEM 블록을 마스킹(시험 입력으로 검증) |
| 개인정보 | 공고의 공개 필드(회사·제목·근무지·날짜)만 조회. 사용자 테이블 조회 없음 |

v2 가 확인하는 항목:

| 범위 | 항목 |
|---|---|
| STEP 03 | 컨테이너·이미지, 배포 SHA(`/api/version`), 배포된 `gcp_sync.py` 해시와 **fail-closed 코드 포함 여부**, 타이머 상태, cron 데몬, crontab 의 sync 줄(주석 여부 포함), `/etc/cron*`, journal 의 cron 실행 기록, `gcp-sync.env` 권한·키 이름·`GCP_SYNC_PUBLISH` 값·`career_sync` 여부, sync 로그의 상태 필드, 실행 중 프로세스 |
| STEP 04 | `jobkorea_live` 전 건의 ID·URL·공개 필드·`updated_at`·`xmin`, 커밋 시각(`track_commit_timestamp` 가 on 일 때만), 합성 표지(긴 ID, 합성 제목, 비 JobKorea URL), runs, night/keyword 작업 수, 키워드 발견(최초·최종 시각), 출처 간 중복 ID, 배포 이미지의 fixture·테스트 파일에 같은 ID 가 있는지, 11-08 배포 journal·backend 로그·셸 기록의 import 흔적, T61 승인 파일 존재 여부 |
| STEP 05 | sync 로그의 run_id·fetched·inserted·updated·duplicate·skipped·failed·시각 |

## 4. GCP Sync cron 상태

| 항목 | 값 | 등급 |
|---|---|---|
| 등록 | **예**: crontab 에 08:05 KST(`5 23 * * *` UTC) sync 줄 1개 ("crontab now holds only the 08:05 sync line", 11-16 08:25 KST) | DOCUMENTED |
| 활성 | **예**: 11-16 08:05 KST 에 실제 실행됨 | DOCUMENTED |
| 마지막 실행 | `045e68d4-e41d-41fa-8846-e720a7a883a7`, 2026-11-16 08:05:01 KST, scheduled, 1회 시도, SUCCEEDED, Slack 200 | DOCUMENTED |
| 다음 실행 | 2026-11-17 08:05 KST (cron 이 유지된다면) | 추정 |
| 실행 중 프로세스 | UNKNOWN (현재 시점) | NOT_RUN |
| `GCP_SYNC_PUBLISH` | 값을 직접 읽지 못함. 단, Cloud SQL `jobkorea_live` 29건이 **모두 draft** 이고 공개 API 노출 0 → 실효값 0 으로 보임 | DOCUMENTED(간접) |
| 배포 코드 | `1797f4c` (#338). **#371 미배포. 이 브랜치의 fail-closed 가드 미배포 → 보호 수단이 아님** | DOCUMENTED |
| 동시 실행 방지 | wrapper `flock --nonblock` + Target advisory lock `337001` | 코드 확인 (DIRECT) |

## 5. Staging `jobkorea_live` 출처 분류

DOCUMENTED 총 29건 (11-15 22:16 KST: 28, 같은 밤 수동 승인 job 으로 50350626 추가 → 29).

| 분류 | 건수 | 근거 |
|---|---|---|
| **VERIFIED_LIVE** | **1** | 50350626: job `16a8fc29-b12c-4ab7-8a9e-ae9029474dd9`, AX, 7 HTTP, 1박 T61 승인(`jobkorea-t61-night-20261116.json`, 23:00Z 만료) 기간 안. 이번 PC 의 LIVE run `8e54090d` 도 같은 공고를 수집함 (DOCUMENTED + DIRECT 교차) |
| LIVE 기록이 문서로만 있음 (ID 미확인) | 21 | 11-12 야간: "30 detail requests produced 25 distinct IDs", "best observed 21 new" (DOCUMENTED). night_job_results 의 실행 기록이 있다고 문서에 적혀 있으나, ID 단위 대조는 하지 않음 → **ID 확인 전까지 VERIFIED_LIVE 로 세지 않음** |
| **UNVERIFIED_ORIGIN** | **5** | 11-08 09:50:48 KST 기록분. 실행 기록(runs) 없음, 승인 기록 없음, 공고 ID 미기록. 정황: #85(게이트 밖 live 도구) 08:55 병합 → #88 이미지 09:43 → 기록 09:50. **실행 기록이 없다는 것만으로 무승인 수집이라 단정하지 않음** |
| 미귀속 | 2 | 28 − 5 − 21. 11-13 이후 밤의 기록으로 추정되나 근거 없음 |
| **VERIFIED_FIXTURE** | **0** | Staging 운영 DB 에서 합성·fixture 로 확인된 `jobkorea_live` 는 없음. E2E 는 격리 DB 에서 실행됨(CRAWLER_NIGHT_12, DOCUMENTED) |

5건에 대해 STEP 04 의 10개 항목:
- 외부 ID·최초 INSERT 시각·Run ID·키워드·실제 출처·배포 버전: **NOT_RUN** (스크립트 8~10절이 확인함).
  - 테이블에 `created_at` 이 없으므로, 최초 INSERT 시각은 `track_commit_timestamp` 와 discoveries 의 `first_seen_at` 으로만 근사할 수 있음.
- 마지막 UPDATE 2026-11-08 09:50:48 (DOCUMENTED).
- 승인 기록: 문서상 없음.
- GCP 전송: 4절 → 29건 전체가 Cloud SQL 에 draft 로 있으므로 **이 5건도 이미 전송된 것으로 보임** (DOCUMENTED, 29 compared / 0 mismatch).
- 데이터 보존: 삭제·수정하지 않음.

## 6. 과거 GCP 동기화 이력

| Run | 시각 | Source → 결과 | 등급 |
|---|---|---|---|
| `045e68d4…` | 2026-11-16 08:05 KST | fetched 59 (`jobkorea_live` 29 + 2 + 28), inserted 1, updated 0, duplicate 28, skipped 30 (`SOURCE_NOT_SELECTED`), failed 0, 코드 `1797f4c` | DOCUMENTED |
| `ce757d96…` | 이전 실행(시각 미기록) | #371 코드로 읽기 전용 재현: skipped `{"jobkorea": 2, "jobkorea_imported": 28}` | DOCUMENTED |
| 그 이전 (최초 28건 전송) | 미기록 | UNVERIFIED (sync 로그는 스크립트 6절로 확인) | — |

Target (Cloud SQL, 다른 세션의 읽기 전용 조회): `jobkorea_live` postings 29, 모두 draft, URL 29개 고유, refs 29, 중복 INSERT 없음, 필드 대조 29/29 일치.

**GCP_TARGET_ROWS_VERIFIED=NO (이번 점검)**: 이번에는 Cloud SQL 에 접속하지 않았습니다(승인 범위 밖). 위 값은 문서 기록입니다.

## 7~10. 위험 판정

| | 현재 상태 | 확인된 증거 | 미확인 | 실제 영향 | 긴급도 | 필요한 조치 | PM 승인 |
|---|---|---|---|---|---|---|---|
| **A. Sync cron 활성** | 활성(매일 08:05) | DOCUMENTED 실행 기록 | 현재 crontab, PUBLISH 실값 | 승인된 야간 LIVE 결과를 draft 로 옮기는 **설계된 동작**. Staging LIVE 는 현재 OFF(플래그 0 + 루트 kill switch)라 새로 옮길 행이 없음 | **중** | 출처 미확인 행 처리 결정 전까지 유지 또는 일시 중지 결정 | 중지 시 필요 |
| **B. 미확인 5건 이관** | **이미 이관됨(draft)** 으로 보임 | 29건 전체 Target 존재(DOCUMENTED) | 5건의 ID·출처 | 운영 DB 에 출처 불명 데이터가 draft 로 존재. 공개 0 | **중~높음**(권리) | 스크립트로 5건 ID 확보 → Target 에서 해당 refs 확인 → 격리(공개 금지 유지) 또는 삭제 결정 | 필요 |
| **C. 테스트 데이터 혼입** | Staging 운영 DB 에서 fixture 행 미확인. 새 PC 의 26 테스트 행은 원장 필터로 차단(DIRECT, 리허설) | DOCUMENTED + DIRECT | 5건이 테스트일 가능성(낮음) | 낮음 | **낮음** | 스크립트 8~9절의 합성 표지·fixture ID 대조 | 불필요(읽기) |
| **D. Draft 공개** | 공개 0 | 공개 API 76건 중 `jobkorea_live` 0 (DOCUMENTED, 11-16 08:28) | `GCP_SYNC_PUBLISH` 실값 | 현재 없음. `PUBLISH=1` 로 한 번이라도 실행하면 29건이 원천 상태(published)로 바뀜 | **낮음** (PUBLISH 변경 시 높음) | PUBLISH 변경 금지를 운영 규칙으로 명시. 스크립트 5절로 값 확인 | 변경 시 필요 |
| **E. 기존 서버·새 PC 중복 동기화** | 같은 `data_sources.code='jobkorea_live'` 에 쓰는 경로가 둘 | 50350626 이 Staging(→GCP)과 새 PC run `8e54090d` 양쪽에 있음 (DIRECT + DOCUMENTED) | — | 동시 실행은 advisory lock 으로 막힘. 다만 두 원천이 같은 공고를 번갈아 UPDATE 할 수 있음(필드 차이 시). 중복 INSERT 는 아님(external_refs 로 식별) | **중** | 전환 시 Staging cron 중지 → 새 PC 단일 writer. 그 전에는 새 PC Sync 를 시작하지 않음 | 필요 |
| **F. 운영 자격증명 노출** | ① `crawler_staging` 비밀번호가 로컬 세션 기록에 노출, DB 가 서버 /24 에 15432 로 열림 (DOCUMENTED) ② 이 PC `.env` 에 Cloud SQL 관리자급 자격증명, 실제 Slack Webhook, 8자 미만 Staging SSH 비밀번호 (DIRECT, 값 미출력. git 이력 0) | 위 | 회전 여부 | 내부망 접근자가 크롤러 DB 에 접속 가능, PC 유출 시 운영 DB 관리자 권한 | **높음** | 회전(`crawler_staging` → SSH 키 전환 → Slack → Cloud SQL 관리자), 이 PC 에서 운영 키 제거 | 필요 |

**긴급 차단 필요 여부: 즉시 cron 중지 필요성은 "중"** 입니다.
- 공개 노출 0, 중복 INSERT 0 이고, Staging LIVE 는 OFF 라 매일 새 데이터가 들어오지 않습니다.
- 긴급한 것은 다음 두 가지입니다.
  1. **F 의 자격증명 회전**
  2. **B 의 출처 미확인 5건 처리 결정**(이미 운영 DB 에 draft 로 존재)
- **주의**: 이 브랜치의 fail-closed 가드(`SOURCE_PROVENANCE_REQUIRED`)를 그대로 배포하면, 승인된 LIVE 결과를 포함한 Staging Sync 전체가 멈춥니다.
  - 의도한 효과(미확인 행 차단)보다 범위가 넓습니다.
  - 배포 전에 범위를 좁히는 쪽을 권장합니다: night_job_results 와 키워드 발견 기록에 연결된 행만 허용하고 미확인 5건은 제외.
  - 이번 단계에서는 설계만 하고 구현하지 않았습니다.

## 11. 남은 확인 항목 (모두 스크립트 v2 로 확인 가능)

1. 현재 crontab, cron 실행 기록, `GCP_SYNC_PUBLISH` 실값, 실행 중 프로세스, 배포 SHA, 배포 코드의 가드 포함 여부.
2. 5건의 ID·URL·필드·`xmin`/커밋 시각·키워드 발견 시각·fixture 대조, 11-08 배포·로그·셸 기록.
3. 미귀속 2건과 11-12 의 21건을 night_job_results 와 ID 단위로 대조.
4. sync 로그 전체 이력(최초 28건 전송 시점).
5. Cloud SQL 에서 5건 refs 확인(별도 승인, 최소 권한 읽기).

## 12. 후속 조치와 승인 요청 (이번에는 실행하지 않음)

| # | 조치 | 승인 |
|---|---|---|
| 1 | **스크립트 v2 를 Staging 대역에서 실행**(허용된 PC·콘솔), 또는 이 PC IP 에 22번 허용 | 네트워크 담당 / PM |
| 2 | 결과에 따라 5건 처리: Staging 은 보존한 채 Sync 대상에서 제외(코드: 출처 연결 행만 허용), Cloud SQL 의 해당 draft 는 격리 또는 삭제(README 롤백 방식, ID 범위) | PM (+ 권리 판단) |
| 3 | GCP Sync cron: 유지 / 일시 중지(`crontab -l \| grep -v run_gcp_sync.sh \| crontab -`, 백업 후) / 새 PC 로 전환 시 중지 | PM |
| 4 | fail-closed 가드는 **범위를 좁혀서** PR → 리뷰 → 배포 (현재 형태 그대로 배포하지 않음) | PM + 리뷰어 |
| 5 | 자격증명 회전: `crawler_staging`(문서의 §14 절차) → Staging SSH 키 전환 → Slack Webhook → Cloud SQL 관리자. 이 PC `.env` 운영 키 제거 | PM |
| 6 | 새 PC GCP Sync 전환(승인 C)은 **1~3 이 끝난 뒤**. 단일 writer 원칙 | PM |
| 7 | (참고, 범위 밖) Staging 디스크 100% (DOCUMENTED) | 호스트 소유자 |

**FINAL_STATUS=PARTIAL**:
- 문서 증거로 cron·이관·공개 상태는 판정했습니다.
- 서버 직접 점검(DIRECT)은 네트워크 차단으로 NOT_RUN 입니다.
- 5건 출처는 UNVERIFIED_ORIGIN 입니다.
