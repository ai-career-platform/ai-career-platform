# 실제 일 1,000건 INSERT 및 GCP 이관 (AI_CAREER_CRAWLER_1000_AND_GCP_EXECUTION, 2026-11-16)

**결론: 두 목표 모두 BLOCKED.**

이번 작업에서 실제로 실행할 수 있었던 것은 읽기 전용 확인뿐입니다. 남은 실행 단계는 모두 사람의 승인이나 외부 담당자의 결과물이 있어야 진행할 수 있습니다. 아래 7절에 각 항목을 하나씩 적었습니다.

이번 작업에서 실행한 외부 요청:

| 대상 | 요청 수 |
|---|---|
| JobKorea | 0 |
| GCP | 0 |
| Staging SSH | 0 (지난번 실패한 접속을 반복하지 않음) |

자격증명은 추출하거나 출력하지 않았습니다. `.env` 는 키 이름만 확인했습니다.

## 1. 확인한 현재 상태 (읽기 전용, 2026-11-16 22:2x KST)

| 항목 | 값 |
|---|---|
| main | `0edc175` (#372). 로컬 실행 사본의 트리가 main 과 동일 |
| 로컬 DB | PostgreSQL 18.7, 127.0.0.1:5432 실행 중 (`AICP-LocalPostgres` 작업 Running) |
| LIVE 실행 | `8e54090d-34ce-412a-88f1-9a693d0a47ed`: live, SUCCEEDED, HTTP 7, 2026-11-16 17:21:19–17:21:37 KST, `harvest_items` inserted 5 |
| LIVE 실행 총계 | 1회, HTTP 7. 그 뒤 LIVE 요청 없음 |
| 로컬 공고 | `jobkorea_live` 31, `jobkorea_imported` 14, `jobkorea` 2. 모두 보존. 이관 대상은 위 실행의 원장 5건뿐 |
| T61 수집 승인 파일 | 없음. 승인 B 는 1회용이었고 사용 후 삭제됨 |
| GCP sync 설정 | 없음. `secrets\gcp-sync.env` 와 `secrets\gcp-server-ca.pem` 모두 없음 |
| `.env` 의 GCP 계정 | 관리자 로그인뿐. 동기화에 쓰지 않습니다. wrapper 는 `.env` 를 읽지 않으며, 관리자 계정은 코드에서도 거부됩니다 |
| Staging 점검 결과 | 없음 (`staging-check-*` 파일 없음) |
| 공식 API 키 | 없음. `.env` 에 JobKorea, Work24, Saramin 키 이름이 하나도 없음 |
| 자동 수집 작업 | `AICP-Crawler-Fixture` Disabled. LIVE 스케줄은 없음 |

## 2. GOAL 2: GCP 실제 이관 (BLOCKED)

| 조건 | 상태 | 근거 |
|---|---|---|
| Staging cron 중단 증거 | **없음** | 점검 결과 미수령. Staging 은 08:05 KST 에 계속 동기화 중인 것으로 간주합니다 |
| 단일 Writer 전환 | 코드는 준비, 운영 조건은 **미충족** | 실제 GCP 의 `career.ingestion_runs` 에 Staging 실행 기록이 있으면, 새 PC 의 실행은 다음 경우 거부됩니다: 26시간 무실행이 아니거나 cutover 증거가 없을 때 |
| `career_sync` 계정 | **없음** | 생성 SQL 은 준비됨: `poc/staging/automation/gcp-sync/create_career_sync_role.sql`. 승인 C 를 받은 DBA 가 실행해야 합니다 |
| TLS / CA / 호스트명 | **없음** | `gcp-server-ca.pem` 과 인증서 호스트명이 필요합니다 |
| 네트워크 | **미확인** | 이 PC 의 공인 IP 를 Cloud SQL 허용 네트워크에 추가하거나, Cloud SQL Auth Proxy(서비스 계정 `cloudsql.client`)가 필요합니다. 둘 다 GCP 변경이라 승인 대상입니다 |
| LIVE Run 필터 | 준비 | `-LiveRunId 8e54090d-…` (#372, 테스트 완료) |
| GCP 쓰기 승인 C | **없음** | |

- 실제 Cloud SQL 에 접속한 적이 없습니다.
  - GCP Sync Run ID, 실제 INSERT/UPDATE 수, Source/Target 일치 여부는 **아직 존재하지 않습니다**.
- 이전의 "4 insert, 1 duplicate" 는 로컬 TLS 모의 Target 에서 나온 값입니다. 실제 GCP 결과로 쓰지 않습니다.
- 실제 INSERT 수는 연결 후 dry-run 으로 다시 계산합니다.
  - Staging 이 이미 같은 공고를 보냈다면 duplicate 로 집계되고 쓰기는 0입니다.

## 3. GOAL 1: 하루 신규 1,000건 (BLOCKED)

| 항목 | 상태 |
|---|---|
| JobKorea 공식 API | 신청됨, **미승인** (사용자 전달, 승인 시점 미정) |
| JobKorea 수집·저장 허가 | **없음** (`docs/data/JOBKOREA_DATA_PERMISSION_INQUIRY_2026-11.md` 문의 준비) |
| 다른 공식 공급원 | Work24 Open API, Saramin API 모두 인증키 없음 |
| 유효한 T61 승인 | 없음 |
| 실제 측정치 | AX 키워드 검색 1페이지: 링크 20, 상세 5, 신규 INSERT 5 (HTTP 7). **이 외의 측정은 없습니다** |
| 24시간 측정 | 시작하지 않음 |
| 순신규 INSERT (24h) | **0**. 측정 구간 없음. 기존 5건은 1회 승인 시험분이며 24시간 KPI 측정이 아닙니다 |

- **허가 없이 하지 않은 것:** 허가된 공급원이 없어 공급량 측정(키워드별 페이지 수, 중복률)도 하지 않았습니다. 이 측정 자체가 JobKorea 에 대한 LIVE 요청이기 때문입니다.
- **참고 계산 (예측이며 PASS 근거 아님):** 1페이지 20링크가 모두 신규라고 가정해도, 1,000건이면 하루 최소 50 목록 요청과 1,000 상세 요청이 필요합니다. 이 규모는 JobKorea 허가나 API 한도 안에서만 정할 수 있습니다.

## 4. Windows 자동화 (STEP 08)

| 항목 | 상태 |
|---|---|
| PostgreSQL 자동 시작 | `AICP-LocalPostgres` 작업 Running (supervised) |
| Task Scheduler | 동작 확인. fixture 작업은 Disabled |
| 승인 만료 시 자동 OFF / 중복 실행 차단 | 구현·테스트됨 (T61 gate, harvest lock) |
| 로그아웃 상태 실행, 재부팅 후 복구 | **미검증**. 관리자 권한(배치 로그온)과 재부팅 승인이 필요합니다 (`CRAWLER_WINDOWS_UNATTENDED_READINESS.md`) |
| LIVE 자동 스케줄 | 만들지 않음. 승인된 공급원이 없습니다 |

## 5. 장애 및 복구

이번 작업에서 실행한 쓰기가 없어 장애도 없습니다.

GCP 이관 후 문제가 생기면, 실행 결과의 `inserted_external_ids` 와 해당 sync run 범위에서만 되돌립니다. 무조건 DELETE 는 하지 않습니다(`CRAWLER_LIVE_GCP_1000.md` 6절 C).

## 6. 승인 후 실행 순서 (에이전트가 즉시 수행)

### GOAL 2 (승인 C 와 아래 7절 1–4 를 받은 뒤)

1. 설정 확인과 TLS 접속: `verify-full`, `career_sync` 로그인.
2. 최소 권한 확인: 관리자 아님, DELETE 불가.
3. `run-gcp-sync-local.ps1 -Mode dry-run -LiveRunId 8e54090d-34ce-412a-88f1-9a693d0a47ed`
   - 실제 신규/중복 수와 `other_writers` 를 확인합니다.
4. `-Mode run -LiveRunId 8e54090d-… -CutoverConfirmed -CutoverEvidence "<승인 참조>"` 를 1회 실행합니다.
   - 이후 `-Mode verify` 로 Source/Target 을 비교합니다.
   - Draft 상태와 공개 API 비노출을 확인합니다.
   - 같은 명령을 재실행해 멱등성을 확인합니다(쓰기 0).

### GOAL 1 (허가된 공급원과 요청 예산 승인 뒤)

1. 공급량 측정: 승인 예산 안에서 키워드별 페이지와 중복률을 잽니다.
2. LEVEL 1 → 2 → 3 (100 → 300 → 1,000), 각 단계는 별도 harvest run 입니다.
3. 24시간 구간을 지정해 `harvest_items` 기준으로 신규 INSERT 를 집계합니다.

## 7. 필요한 단일 승인·외부 작업

### GOAL 2

1. **Staging 담당자:** 점검 스크립트를 실행하고 결과 파일을 전달합니다.
   - 스크립트 SHA-256 `50996b38a99a5b42e6619e7fa686a425254441100405485dafa5af4b2c0af7bd`
   - 명령: `CRAWLER_PR_INTEGRATION_AND_CUTOVER_READINESS.md` 7절. 이제 main 에도 있으므로 URL 의 브랜치를 `main` 으로 바꿔도 됩니다.
   - 이어서 `crontab -l` 에서 `run_gcp_sync.sh` 줄을 주석 처리하고 그 출력을 전달합니다. 이것이 cron 중단 증거입니다.
2. **GCP DBA (승인 C 범위):**
   - `create_career_sync_role.sql` 과 `target_grants.sql` 을 실행합니다.
   - 비밀번호는 `\password` 로 설정합니다.
   - 이 PC 의 `C:\dev\crawler-data\secrets\gcp-sync.env` 에 템플릿 키로 직접 기입합니다. 채팅이나 Git 으로 전달하지 않습니다.
3. **GCP 관리자:**
   - 서버 CA 를 `C:\dev\crawler-data\secrets\gcp-server-ca.pem` 에 둡니다.
   - 인증서 호스트명과 IP 를 알려 줍니다.
   - 이 PC 의 공인 IP 를 허용 네트워크에 추가하거나 Auth Proxy 경로를 정합니다.
4. **PM 승인 C:** 1회, Run `8e54090d`, 최대 5행, draft, 공개 0.
   - cutover evidence 참조값을 함께 줍니다.
   - Staging 마지막 sync 후 26시간이 지나야 실행할 수 있습니다.

### GOAL 1

5. **JobKorea:** 서면 수집·저장 허가 또는 API 승인(키, 한도, 이용 조건). 아니면 Work24 Open API 인증키 등 다른 공식 공급원과 그 이용 조건.
6. **PM 수집 승인 (T61):** 위 공급원 범위 안에서 공급원, 키워드, 일 요청 상한, 유효 기간을 정합니다.

## 8. 판정

| 목표 | 판정 | 이유 |
|---|---|---|
| GOAL 1 (일 1,000) | **BLOCKED** | 허가된 공급원이 없어 측정 0, 24h 순신규 0 |
| GOAL 2 (GCP 이관) | **BLOCKED** | Staging 중단 증거, `career_sync`, CA, 네트워크, 승인 C 모두 없음. 실제 GCP 쓰기 0 |
| 전체 | **BLOCKED** | |
