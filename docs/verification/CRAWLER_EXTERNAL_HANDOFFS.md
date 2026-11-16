# GCP 이관·데이터 공급 차단 해소: 외부 작업 요청 (2026-11-16)

이 PC 에서 실행할 수 있는 일은 모두 끝났습니다. 남은 일은 아래 A, B, C 담당자의 작업입니다. 결과물이 도착하면 에이전트가 6절 순서로 즉시 실행합니다.

**변경 없음:**
- Staging 점검 스크립트 SHA-256 `50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd` (main `0edc175` blob 기준 재계산)
- 로컬 LIVE 실행 `8e54090d-34ce-412a-88f1-9a693d0a47ed`, 공고 5건 보존

**코드 제약:** GCP 연결은 TLS `verify-full` 직접 연결만 지원합니다. 따라서 네트워크는 B3 의 허용 IP 방식을 씁니다. Cloud SQL Auth Proxy 를 쓰려면 코드 변경이 필요합니다.

## A. Staging 운영자 (서버 배포 사용자로 로그인)

### A1. 읽기 전용 점검 (승인 불필요, 1분)

```bash
set -eu; WORK=$(mktemp -d /tmp/aicp-check-XXXX) && cd "$WORK"
curl -fsSL -o staging_readonly_check.sh \
  https://raw.githubusercontent.com/ai-career-platform/ai-career-platform/main/poc/staging/automation/safety/staging_readonly_check.sh
echo "50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd  staging_readonly_check.sh" | sha256sum -c -
OUT="staging-check-$(hostname)-$(date +%Y%m%d-%H%M%S).txt"
bash staging_readonly_check.sh > "$OUT" 2>&1; echo "exit=$?"
grep -nE '(PASSWORD|TOKEN|SECRET|WEBHOOK|_KEY)=[^<[:space:]]|://[^/@<[:space:]]+:[^@<[:space:]]+@|BEGIN [A-Z ]*PRIVATE KEY' "$OUT" || echo NO_SECRET_PATTERN
sha256sum "$OUT"
```

- **완료 확인:** `sha256sum -c` 가 OK, 마지막 grep 결과가 `NO_SECRET_PATTERN`.
- **전달물:** `$OUT` 파일과 그 해시. 사내 경로로만 보내고 GitHub·공개 채널에는 올리지 않습니다.
- **이 결과로 확정되는 것:**
  - cron 상태와 마지막 Sync 시각
  - 진행 중 Sync 여부
  - `GCP_SYNC_PUBLISH`
  - Staging Sync 계정이 `career_sync` 인지
  - 29건의 출처 4분류 (에이전트가 `analyze_staging_check.py` 로 판정)

### A2. cron 중단 (PM 의 C2 승인 후에만)

```bash
crontab -l > ~/crontab.before-cutover.$(date +%Y%m%d%H%M)
crontab -l | sed -E 's|^([^#].*run_gcp_sync\.sh.*)$|# CUTOVER-DISABLED \1|' | crontab -
date -u; crontab -l | grep -n run_gcp_sync; pgrep -af gcp_sync || echo NO_SYNC_PROCESS
```

- **완료 확인:** `run_gcp_sync` 줄이 `# CUTOVER-DISABLED` 로 시작하고, `NO_SYNC_PROCESS` 가 출력됩니다.
- **증거:**
  - 위 출력 전체 (UTC 시각 포함)
  - 다음 08:05 KST(23:05 UTC) 이후 sync 로그 마지막 줄: 새 실행이 없어야 합니다
- **되돌리기:** `crontab ~/crontab.before-cutover.<시각>`

## B. GCP 관리자 / DBA

### B1. `career_sync` 계정

- **A1 에서 이미 `target_user_is_career_sync=1` 이면:** 계정이 있으므로 B2 검증과 비밀번호 재설정만 하면 됩니다. 비밀번호 재설정은 C3 자격증명 교체와 같이 합니다.
- **없으면 생성:**

```bash
psql "host=<IP> dbname=ai_career_poc user=postgres sslmode=verify-ca sslrootcert=server-ca.pem" \
     -f poc/staging/automation/gcp-sync/create_career_sync_role.sql
psql "...같은 접속..." -c '\password career_sync'          # 프롬프트 입력, 화면·로그에 남지 않음
psql "...career 스키마 소유자로 접속..." -f poc/staging/automation/gcp-sync/target_grants.sql
```

### B2. 권한 검증 (관리자 계정, 읽기 전용)

```sql
SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolconnlimit FROM pg_roles WHERE rolname='career_sync';
  -- 기대: f f f f 3
SELECT t, has_table_privilege('career_sync','career.'||t,'DELETE') AS can_delete
  FROM unnest(array['job_postings','companies','job_posting_external_refs','ingestion_runs','data_sources']) t;
  -- 기대: 모두 f
SELECT has_schema_privilege('career_sync','career','CREATE');                                      -- 기대: f
SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
 WHERE m.member=(SELECT oid FROM pg_roles WHERE rolname='career_sync');                           -- 기대: 0
```

- **증거:** 위 4개 질의의 결과.
- **참고:** 다른 DB 의 CONNECT 권한은 PostgreSQL 기본값(PUBLIC)입니다. career_sync 는 그 DB 의 객체 권한이 없습니다.

### B3. TLS·호스트명·네트워크

```bash
gcloud sql instances describe <INSTANCE> --format="value(ipAddresses, dnsName, serverCaMode, settings.ipConfiguration.sslMode)"
gcloud sql instances describe <INSTANCE> --format="value(settings.ipConfiguration.authorizedNetworks)"   # 기존 목록 먼저 확인
```

- **CA:** Staging 의 `gcp-sync/server-ca.pem`(공개 인증서)을 이 PC 의 `C:\dev\crawler-data\secrets\gcp-server-ca.pem` 으로 복사합니다. Console 에서 받아도 됩니다.
- **호스트명:** 서버 인증서에 들어 있는 이름(`dnsName` 등)과 공인 IP 를 알려 줍니다. 이름은 공개 정보입니다.
- **네트워크:** 이 PC 의 공인 IP/32 를 허용 네트워크에 추가합니다.
  - `gcloud sql instances patch <INSTANCE> --authorized-networks=<기존목록>,<PC_IP>/32`
  - **주의:** `--authorized-networks` 는 목록 전체를 **교체**합니다. 기존 항목을 반드시 포함해야 합니다.
- **비밀번호 전달:** 이 PC 에서 담당자가 직접 `C:\dev\crawler-data\secrets\gcp-sync.env` 에 기입합니다(템플릿 `scripts/windows/templates/gcp-sync.env.example`). 채팅·메일·Git 으로 전달하지 않습니다.
- **완료 확인:** 에이전트가 실제 TCP → TLS(verify-full) → career_sync 로그인 → 스키마·권한 조회를 실행하고 결과를 기록합니다.

## C. PM 승인 (각각 한 줄 승인이면 충분)

| # | 승인 | 범위 |
|---|---|---|
| C1 | **GCP 쓰기 승인 C** | 1회. Run `8e54090d-34ce-412a-88f1-9a693d0a47ed`, 최대 5행, draft, `GCP_SYNC_PUBLISH=0`. cutover evidence 참조값(예: 결재 번호) 포함 |
| C2 | Staging cron 중단 (A2) | 실행일을 지정. 새 PC 실행은 Staging 마지막 sync 후 **26시간** 뒤부터 코드가 허용합니다 |
| C3 | 자격증명 교체 | Staging DB(`crawler_staging`), Staging SSH, Slack webhook, Cloud SQL 관리자, career_sync |
| C4 | 공식 데이터 수집 | 공급원 1개 선택과 그 조건 수용 (아래 D). 요청 상한과 기간 지정 |

## D. 데이터 공급원 확인 결과 (2026-11-16, 공개 문서만 확인, 신청 이력은 확인 불가)

| 공급원 | 상태 | 핵심 조건 | 1,000건/일 적합성 |
|---|---|---|---|
| JobKorea API | 신청함, **미승인** (사용자 전달) | 공공기관·학교 대상. 개인·일반 기업은 내부 검토로 결정. 1개 사이트 기준, IP 등록. 공고 최대 500개, 2시간 갱신. 저장·재사용 조건과 요금은 공개 문서에 없음. 문의 api@jobkorea.co.kr | **낮음**: 노출 상한 500 이라 일 신규 1,000 공급이 어렵습니다. 저장 허용을 서면으로 받아야 합니다 |
| 사람인 Open API | **미신청** (키 없음) | 앱 등록 후 access-key 발급. 요청당 최대 110건, 일일 요청 상한 존재(수치는 문서 미기재). 저장·재배포 조건은 문서에 없음 | 중간: 키와 이용약관 확인이 필요합니다 |
| 고용24(워크넷) 채용정보 API | **미신청** (키 없음) | 회원가입 후 신청, 담당자 심사 후 인증키 발급(양도 불가). 목록 display 최대 100, startPage 최대 1000, XML, 무료. 공공데이터포털 표기 이용조건은 **공공누리 4유형: 출처표시, 상업적 이용금지, 변경금지** | 공급량은 충분할 수 있습니다. **상업 서비스이거나 데이터를 가공하면 이용조건 위반 소지**가 있어 PM·법무 판단이 필요합니다 |

**권고:**
1. 서비스의 상업성 여부를 정해 공급원을 선택합니다(C4).
2. 선택한 곳에 키를 신청합니다. 고용24는 무료이고 심사가 필요하며, 사람인은 앱 등록입니다.
3. 키를 받으면 승인된 한도 안에서 공급량을 측정합니다.
   - 키워드별 total, 페이지별 ID, 키워드 간과 기존 DB 와의 중복률
4. 그 뒤 100 → 300 → 1,000 단계로 진행합니다.

공급원 어댑터는 아직 없습니다(JobKorea HTML 전용). 키가 생기면 adapter 추가 PR 이 필요합니다.

## 6. 결과물이 도착하면 에이전트가 즉시 실행할 순서

1. A1 결과 분석: 29건 분류, cron, 마지막 sync 시각
2. B3 연결 검증: TCP, TLS `verify-full`, career_sync 로그인, 스키마·권한
3. `run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId 8e54090d-…` 로 실제 신규·중복 수를 산출합니다
4. C1·C2 승인과 A2 증거가 있고 26시간이 지났으면:
   1. `-Mode run … -CutoverConfirmed -CutoverEvidence "<C1 참조>"` 1회
   2. `-Mode verify`
   3. 재실행해 멱등성 확인
   4. Draft 상태와 공개 API 비노출 확인
