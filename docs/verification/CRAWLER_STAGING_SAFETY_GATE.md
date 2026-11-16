# Staging 안전 게이트 · 첫 LIVE 1회 · 운영 전환 준비 (AI_CAREER_CRAWLER_STAGING_SAFETY_GATE, 2026-11-16)

판정 원칙: 실제로 수행한 것만 PASS. 비밀값은 출력·기록하지 않습니다.

> **정정 (2026-11-16, [CRAWLER_STAGING_SAFETY_CHECK_RESULT.md](CRAWLER_STAGING_SAFETY_CHECK_RESULT.md))**: 이 문서의 Staging 판단은 main 의 11-12 이전 증거만 근거로 했습니다. PR #371 브랜치의 CRAWLER_RECOVERY_2026-11-16 에 기록된 내용은 다음과 같습니다.
> - Staging `jobkorea_live` 는 29건입니다.
> - 1박 단위 T61 승인으로 실제 LIVE 야간 수집이 있었습니다.
> - 08:05 GCP Sync cron 은 활성이고, Cloud SQL 에 29건이 draft 로 있으며 공개는 0 입니다.
> - 여기의 fail-closed 가드는 승인된 Staging Sync 까지 멈추므로, 범위를 좁히기 전에는 배포하지 않습니다.

선행 문서: [CRAWLER_OPERATIONAL_UNBLOCK_PLAN.md](CRAWLER_OPERATIONAL_UNBLOCK_PLAN.md) (6.3 Staging 점검, 7 GCP, 11 승인 항목).

## 0. 이번 작업에서 실제로 일어난 일

| 시각 (KST) | 내용 |
|---|---|
| 17:0x | Staging SSH 사용 승인(사용자: "모든 ssh 권한 승인"). 읽기 전용 점검만 하도록 범위를 제한함 |
| 17:13 | SSH 시도 → **TCP 22 연결 시간 초과**. Staging 은 사설 대역(10.2.10.x)이고 이 PC 는 10.2.17.x 대역. 호스트·별칭 모두 같은 결과. 다른 포트나 경로는 시도하지 않음. **Staging 접속 0회, 변경 0** |
| 17:1x | 사용자 정보: API 신청은 제출했으나 승인 대기(시점 미정), 크롤링으로 진행 결정 |
| 17:20 | **승인 B** (PM 위험 수용) 승인 파일 작성: AX, 1페이지, 상세 5, 요청 7, 2시간 유효 |
| 17:21:19 ~ 17:21:37 | **LIVE 1회 실행, SUCCEEDED**. 직후 승인 파일 삭제(즉시 OFF) |

## 1. GOAL 1 — 첫 실제 LIVE 크롤링 (PASS, 1회)

| 항목 | 값 |
|---|---|
| 근거 | 승인 B, PM 세션 승인. `evidence_ref=private:PM-RISK-ACCEPTANCE-20261116-APPROVAL-B`. **JobKorea 허가는 아님**(NOT_OBTAINED, API 신청 대기) |
| run_id | `8e54090d-34ce-412a-88f1-9a693d0a47ed` (`harvest_runs`, mode=live) |
| HTTP 요청 | **7** (robots 1 + 검색 1 + 상세 5) = 상한. 차단·403·429·CAPTCHA 0. 소요 18초 |
| 검색 결과 1페이지 | 링크 **20**, 신규 20, 기존 0, 키워드 간 중복 0 (페이지당 링크 수 L=20 **실측 1건**) |
| 결과 | **INSERT 5**, UPDATE 0, unchanged 0, 실패 0 |
| 파서 | 실제 상세 페이지 5/5 에서 JSON-LD 를 추출했고, 제목·기업·근무지·고용형태·등록일·마감일이 모두 채워짐(합성 fixture 외 첫 실증) |
| 저장 | 로컬 DB(5432) `crawler_training.postings` `jobkorea_live` 신규 5 (공고번호 50224839, 50246410, 50309869, 50350626, 50359556) |
| GCP 선택 검증 | 로컬 Source `read_source(run_id)` = 정확히 **5행**. 테스트 `jobkorea_live` 26행은 제외(읽기만 함, GCP 미접속) |
| 종료 | 승인 파일 삭제. 상태 보고서 `harvest_live_runs_total=1` → `LIVE_PRESENT`(설계상 표시) |
| 증거 | `C:\dev\crawler-data\logs\live-approval-b-20261116-172118\run.json` |

## 2. Staging 점검 (BLOCKED — 네트워크)

- 접근: 자격증명은 `.env` 에 있고(`STAGING_SSH_*`, 값 미출력) 사용자가 사용을 승인했습니다. 그러나 **이 PC 에서 Staging 22번 포트에 닿지 않습니다**(시간 초과). 방화벽·라우팅·VPN 문제로 보이며, 인프라 변경이 필요해 시도하지 않았습니다.
- 대신 **한 번에 실행하는 읽기 전용 점검 스크립트**를 저장소에 추가했습니다: [`poc/staging/automation/safety/staging_readonly_check.sh`](../../poc/staging/automation/safety/staging_readonly_check.sh).
  - Staging 호스트에서 `bash staging_readonly_check.sh > out.txt`, 또는 접근 가능한 PC 에서 `ssh <staging> 'bash -s' < staging_readonly_check.sh`.
  - 점검 항목:
    - 컨테이너, 타이머, GCP Sync cron 줄 수, gcp-sync 파일 존재 여부(내용 미출력), 로그의 상태 필드만
    - backend 의 LIVE·GCP 변수 SET/UNSET
    - DB `BEGIN READ ONLY` 조회: 출처별 건수·시각, `jobkorea_live` 5건의 URL·제목·기업·날짜, runs, night 작업, 출처 간 중복 ID, 키워드 발견, raw artifact 수, 스케줄
    - 셸 기록과 11-08 backend 로그의 import 흔적
  - 쓰기·재시작·설정 변경 없음.

| 확인 대상 | 결과 |
|---|---|
| PostgreSQL 상태, cron, 마지막 GCP Sync, GCP 전송 여부 | **UNKNOWN** (미접속) |
| 5건의 생성·수정 시각 | 저장소 증거상 마지막 기록 **2026-11-08 09:50:48 KST**, 이후 변화 없음 |
| 수집 출처 / 실제 HTTP 증거 / 승인 이력 | **UNKNOWN**. 정황: #85(live 수집 도구) 08:55 병합, #88 이미지 09:43, 기록 09:50. 당시 도구는 T61 게이트 밖(#254, 11-12 이전). runs 기록 없음(CLI 경로). T61 승인 기록은 존재하지 않음 |
| 판정 | `STAGING_5_ROWS_ORIGIN=UNKNOWN`, `STAGING_UNAPPROVED_COLLECTION=SUSPECTED` (실제 수집이라면 무승인) |

참고: 이번 LIVE 의 공고번호 50246410, 50309869 는 T61 STEP 07 문의서와 기존 테스트 fixture 에 나오는 번호입니다(사용자가 저장한 HTML·링크 예시). Staging 5건과 같은지는 점검 스크립트 결과로 비교할 수 있습니다.

## 3. GCP 오염 가능성 (STEP 02)

**코드 확인**: Staging Source(`read_source`, run ID 없음)는 `crawler_training.postings` 전체를 읽고, `plan()` 에서 `source_code == 'jobkorea_live'` 인 행을 **라벨만으로** 선택합니다. 출처 원장이 없습니다.

| 위험 | 평가 | 근거 |
|---|---|---|
| 테스트 데이터 이관 | **LOW~MEDIUM** | Staging E2E 는 격리된 일회용 DB 에서 실행됨(CRAWLER_NIGHT_12). Staging 운영 DB 의 테스트성 `jobkorea_live` 는 확인되지 않음. 5건의 정체가 불명 |
| 무승인 수집 데이터 이관 | **HIGH (cron 이 활성이면)** | 5건이 11-08 무승인 실제 수집분이면 08:05 KST cron 이 그대로 운영으로 복사 |
| GCP 중복 INSERT | **LOW** | `job_posting_external_refs (source_id, external_id)` 로 식별하는 UPSERT. 재실행 duplicate 만(리허설 1,050 → 0) |
| Draft 공개 노출 | **LOW** (`GCP_SYNC_PUBLISH=0` 기본) / HIGH (1 이면) | Staging `gcp-sync.env` 의 PUBLISH 값은 미확인 |
| 자동 Sync 활성화 | **UNKNOWN** | README 는 "병합 + 배포 + PM 승인 후 cron 등록"이라고만 적음 |

**최소 변경 차단 (구현, 미배포)**: `gcp_sync.execute()` 는 Staging Source 를 **모든 모드에서 연결 전에 거부**합니다(`SOURCE_PROVENANCE_REQUIRED`).
- 예외: `GCP_SYNC_ALLOW_UNVERIFIED_STAGING=1` (PM 의 명시적 결정)일 때만 허용합니다.
- `run_gcp_sync.sh` 는 이 변수를 넘기지 않으므로, **이 버전이 배포되면 cron 경로가 코드에서 닫힙니다.**
- 로컬 Source(LIVE run ID 필터)만 정상 경로로 남습니다.
- 단위 테스트를 추가했습니다(모든 모드 거부, 접속 0, 값 `1` 만 인정). 크롤러 단위 534 PASS.
- 배포 전까지 실제 차단 수단은 **cron 비활성(E1, 승인 필요)** 입니다. GCP 쓰기·삭제는 하지 않았습니다.

## 4. JobKorea 공식 이용 허가 (STEP 03)

자세한 표: [JOBKOREA_DATA_PERMISSION_INQUIRY_2026-11.md §0](../data/JOBKOREA_DATA_PERMISSION_INQUIRY_2026-11.md) (정책 안내 페이지만 열람).

- **확인된 사실**:
  - API 담당 **api@jobkorea.co.kr** (공식 API 페이지에 명시).
  - 대상은 공공기관·학교 중심이고, 일반 기업은 어려울 수 있음.
  - IP 등록 후 고유 링크 발급. 기본 100건, 조건별 최대 500건, 2시간 주기.
  - 상세 내용은 원문 링크로 연결해야 함.
- **미확인**: HTML 자동 수집 허용 여부와 요청량, 저장·재사용 권한, 출처 표시 규정, 이용료·라이선스.
- **대안**:
  - 사람인: 승인 후 access-key, 하루 500회, api@saramin.co.kr.
  - 고용24: 기업회원 전용, 심사 후 인증키, 채용정보 API 있음.
  - 셋 다 저장·가공 조건은 미확인입니다.
- 현재 상태: API 신청 제출됨·승인 대기(사용자 보고). 문의서 최종안 준비 완료, **발송은 PM 승인 후**.

## 5. GCP 실제 연결 준비 (STEP 04)

준비물·명령·검증 SQL·복구는 UNBLOCK_PLAN 7절과 같습니다.
- `scripts/windows/rehearse-gcp-sync.ps1`
- `poc/staging/automation/gcp-sync/create_career_sync_role.sql`
- TLS 리허설 PASS

| 항목 | 상태 |
|---|---|
| 1. career_sync 계정 | SQL 준비·리허설 PASS. 운영 존재 여부 **UNKNOWN** |
| 2. 최소 권한 검증 | 리허설에서 DELETE·CREATE·users 조회 false. 운영 검증 쿼리: `SELECT has_table_privilege('career_sync','career.job_postings','DELETE'), has_schema_privilege('career_sync','career','CREATE');` |
| 3·4. CA·호스트명 | 운영 미확보. 확보 명령은 UNBLOCK_PLAN 7절 C·D |
| 5. 연결 방식 | 아래 표 |
| 6. Windows PC 접속 | **NOT_TESTED** (운영 연결 시험은 승인 C 범위) |
| 7·8. LIVE run 필터·fixture 차단 | 실제 run `8e54090d…` 로 5행 선택, 테스트 26행 제외 확인 |
| 9·10. 1회 Sync·정합성 | 명령 준비(`run-gcp-sync-local.ps1 -Mode dry-run/run/verify -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed`). 미실행 |

| | 승인 네트워크(IP 허용) | Cloud SQL Auth Proxy |
|---|---|---|
| 인증 | DB 비밀번호 + TLS verify-full (현재 코드 그대로) | IAM 서비스 계정 + 프록시가 TLS 처리. 앱은 127.0.0.1 로 접속 |
| 필요 작업 | 인스턴스 공인 IP, 승인 네트워크에 PC 공인 IP/32 추가(유동 IP 면 재등록) | 프록시 바이너리(Windows, 서명 확인 필요. **Smart App Control** 영향 확인), 서비스 계정 키 또는 사용자 ADC, `roles/cloudsql.client` |
| 코드 영향 | 없음 | `target_settings` 가 host=이름, hostaddr=IP, verify-full 을 요구 → 프록시용 모드 추가 필요(작은 변경) |
| 위험 | IP 노출 범위, 유동 IP | 서비스 계정 키 관리 |
| 권고 | **단발 1회는 IP 허용(기간 한정, 끝나면 제거)**이 가장 작은 변경 | 정기 운영으로 넘어갈 때 검토 |

## 6. 운영 Secrets 위험 해결 준비 (STEP 05, 실행 없음)

| 비밀 (.env 키 이름) | 성격 | 이 PC 에 필요한가 | 조치 계획 |
|---|---|---|---|
| `Host/Port/Database/Username/Password_GCP` | Cloud SQL **관리자**급 | **아니오** (Sync 는 관리자를 거부) | ① 관리자 비밀번호 회전(Cloud Console > 사용자) ② 이 PC 에서 키 삭제 ③ 관리자 비밀번호는 비밀 관리 도구에만 보관 |
| `SLACK_WEBHOOK_RUL` | 실제 Webhook (오탈자 키, 코드는 읽음) | 아니오 (LIVE 알림은 Staging 측) | Slack 앱에서 새 Webhook 발급 → Staging `.env` 교체 → 알림 수신 확인 → **옛 Webhook 폐기** → 이 PC 에서 키 삭제 |
| `STAGING_SSH_*` (비밀번호 8자 미만) | Staging SSH **비밀번호 인증** | 점검에만 필요 | 키 인증(ed25519, 이 PC 전용 키)으로 전환 → 로그인 확인 → 강한 비밀번호로 교체 → 가능하면 `PasswordAuthentication no` |
| `Password_LOCAL`, `Password` | 로컬 PostgreSQL 관리자 등 | 초기 설정에만 | `C:\dev\crawler-data\secrets\` 로 옮기거나 회전(로컬 전용) |

- **회전 순서**(서비스 영향이 작은 순): ① Slack Webhook ② Staging SSH 키 전환 ③ Cloud SQL 관리자 비밀번호 ④ `career_sync` 생성(새 비밀번호, 이 PC `gcp-sync.env` 에만) ⑤ 이 PC `.env` 에서 운영 키 제거.
  - 각 단계에서 새 값으로 동작을 확인한 뒤에 옛 값을 폐기합니다.
- **로컬 저장 위치**: `C:\dev\crawler-data\secrets\` (ACL: 사용자 + SYSTEM, 상속 해제. 기존 pgpass 와 같은 방식). 저장소 밖. 루트 `.env` 는 로컬 개발 기본값만 둡니다.
- **확인 사실**: `.env` 는 git 에 커밋된 적이 없습니다(이력 0). `.env` 의 비밀값(8자 이상 4종)은 **1,064개 git 리비전 어디에도 없습니다**(값을 출력하지 않고 개수만 확인). `.env` ACL 은 사용자 + SYSTEM.
- **장애 복구 경로**:
  - Cloud SQL: 프로젝트 소유자가 Console 에서 비밀번호를 재설정합니다.
  - Staging: 비밀번호 인증을 끄기 전에 키 로그인을 검증합니다. 콘솔(하이퍼바이저) 접근을 확보해 둡니다.
  - Slack: 옛 Webhook 은 새 Webhook 수신을 확인한 뒤에 폐기합니다.
  - 모든 회전은 사용자 승인 후 진행합니다.

## 7. PR 정리 (STEP 06)

| 항목 | 값 |
|---|---|
| PR #371 | OPEN, mergeable, head `c025f51`, **리뷰 0**, CI 3/3 success. main 보호. **병합 HOLD** |
| Windows 브랜치 | 이 작업 커밋 후 push(아래 보고). PR 없음, CI 없음. GitHub 인증 수단이 없어 PR 은 웹 UI 로 생성해야 함 |
| 충돌 | `gcp_sync.py` 1곳(두 함수 모두 유지하면 해결). 통합 전체 테스트 PASS(UNBLOCK_PLAN 9절) |
| 테스트 데이터 보호 | 로컬 Source = LIVE run 원장만. Staging Source = 기본 거부(이번 변경) |

## 8. 일 신규 1,000건 실행 계획 (STEP 07)

- 실측: AX 1페이지 링크 20, 그중 신규 20 (DB 가 비어 있었으므로 신규율 1.0 은 첫 실행 값일 뿐입니다). 그 밖에는 미측정입니다.
- 모든 단계는 **JobKorea 허가 없이 PM 위험 수용으로만** 진행되는 상태입니다. 허가나 API 승인을 받으면 그 범위로 바꿉니다.

| 단계 | 내용 | 요청 수 (상한) | 승인 파일 범위 | 산출 |
|---|---|---|---|---|
| D-1 공급량 측정 | 6키워드 × 10페이지, 상세 0 (`--new 0 --revisits 0`) | **61** | allowed_urls 6, `max_search_pages` 10, `max_harvest_details` 1(게이트상 최소), `max_requests` 61 | `Page_No` 실검증, 키워드·페이지별 링크·신규·중복 (`harvest_pages`) |
| D-2 분석 | DB 대비 중복률, 키워드 간 중복률, 페이지별 신규율, 요청당 신규 수 | 0 | — | 실측 L, r → 필요 요청량 재계산 |
| D-3 100건/일 | 신규 100 | 약 110~150 | pages ≤ 10, details 100, requests ≤ 160 | 3일간 차단 0 확인 |
| D-4 300건/일 | 신규 300 (+재확인 50) | 약 350~500 | details 350, requests ≤ 520 | 〃 |
| D-5 1,000건/일 | 신규 1,000 (+재확인 200), 키워드 10개 이상 | 약 1,250~1,700 | pages ≤ 50, details 1,200, requests ≤ 1,750, deadline 2h | `harvest report` 의 target_met |

- 공식: 요청 ≈ 1 + ⌈N/(L·r)⌉ + N + 재확인. 간격 2초 이상이면 1,000건 단계는 약 45~70분입니다.
- 403/429/CAPTCHA 가 한 번이라도 나오면 그날 중단하고 다음 단계를 보류합니다. 접근 제한은 우회하지 않습니다.

## 9. 다음 행동

1. **Staging 점검 스크립트 실행**: Staging 에 접근 가능한 사람이나 경로(콘솔, 사내망 PC, VPN)로 실행하고 결과 파일을 공유합니다. 또는 이 PC 에서 22번 포트로 가는 경로를 허용합니다(인프라 승인).
2. cron 이 활성이면 E1 비활성 승인. 이번 fail-closed 변경을 배포합니다(PR → 리뷰 → 병합 → Auto-CD).
3. 승인 C: `career_sync` 생성, CA·호스트명, PC IP 기간 한정 허용 → run `8e54090d…` 5행을 1회 Sync → verify.
4. 승인 D-1: 공급량 측정(요청 61).
5. Secrets 회전(6절 순서).
6. PR #371 독립 리뷰. Windows 브랜치 PR 은 웹으로 생성합니다.
