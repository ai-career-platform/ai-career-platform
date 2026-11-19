# T61 PM 승인 정책 (모든 에이전트 공통)

> **이 문서가 T61(외부 채용공고 수집) 승인 상태의 단일 기준입니다.** 크롤러·LIVE 수집·승인 파일 작업 전에 이 문서를 먼저 읽습니다.
> 에이전트 공통 규칙은 저장소 루트의 [`AGENTS.md`](../../AGENTS.md) 에 있습니다.

## 1. PM 내부 승인 (2026-11-17 확정, 다시 묻지 않음)

| 항목 | 결정 |
|---|---|
| 크롤러 개발·테스트 | **승인**: 코드 수정, 단위·통합 테스트, Fixture·오프라인 파싱, 일회용 DB |
| 수집 대상 | JobKorea (www.jobkorea.co.kr) |
| 최대 수집 한도 | 1,000건. 코드 상한은 `PM_POLICY_MAX_ITEMS = 1000` 이고, 승인 1건의 `max_harvest_details` 상한입니다 |
| 초기 수집 목표 | 신규 100건. 100건 미만이면 실제 확보 건수로 정상 종료 |
| PostgreSQL 저장·검증 | 허용된 수집 데이터에 한정 |
| 요청 간격 | 최소 2초. 동시 1개 |
| 403 / 429 / CAPTCHA | 즉시 중단, 우회 금지 |
| GCP 전송 | **별도 승인** (승인 C) |
| 야간 자동 실행 | **별도 승인** (`AICP-JobKorea-Nightly` 활성화) |

**이 PM 승인은 JobKorea 의 자동수집·저장 권한을 증명하지 않습니다.** LIVE 요청에는 아래 2절의 제공자 허가가 추가로 필요합니다.

## 2. LIVE 요청 = PM 승인 + 제공자 허가 (코드로 강제)

모든 JobKorea 실요청은 두 검사를 모두 통과해야 합니다. 두 검사는 `crawler/jobs/import_jobkorea_html.live_permission_reason` 에서 함께 실행됩니다.

| 검사 | 코드 | 기록 파일 (Git 밖) | 확인 내용 |
|---|---|---|---|
| ① PM 내부 승인 | `crawler/policy/source_approval_gate.check_collection_permission` | `C:\dev\crawler-data\secrets\t61\<name>.json`<br>(양식 `scripts/windows/templates/t61-harvest-approval.REQUEST.json`) | APPROVED·enabled, 승인자·근거, 유효기간, URL·목적·방법, 요청 수, 페이지·상세 상한 |
| ② 제공자 허가 | `crawler/policy/provider_permission.check_provider_permission` | ①의 `provider_permission_file` 이 가리키는 파일<br>(양식 `scripts/windows/templates/t61-provider-permission.REQUEST.json`) | 아래 목록 |

**② 제공자 허가에서 확인하는 항목:**
- 발급자가 PM 이 아닐 것(자기 발급 금지)
- 허가 종류가 `WRITTEN_PERMISSION`, `API_CONTRACT`, `LICENSE_AGREEMENT` 중 하나일 것
- 근거 위치와 근거 문서 SHA-256 이 있을 것
- 유효기간 안이고, PM 승인 기간이 그 안에 들어갈 것
- 방법·목적·URL prefix 가 허가 범위 안일 것
- `storage_allowed=true` 일 것
- 1일 요청 한도와 최대 건수를 넘지 않을 것

**강제 지점:**
- `_permit` 은 모든 실요청 직전에 실행됩니다. import, harvest `LiveSource`, pagination probe 가 모두 거칩니다.
- `night_crawl.live_gate`
- `harvest.preflight` 는 네트워크 없이 같은 사유를 보고합니다.
- 결과 코드: 허가가 없으면 `PROVIDER_PERMISSION_MISSING`, 그 밖에 `PROVIDER_EVIDENCE_MISSING`, `PROVIDER_EXPIRED`, `PM_WINDOW_EXCEEDS_PROVIDER`, `PROVIDER_OUT_OF_SCOPE`, `PROVIDER_STORAGE_NOT_ALLOWED`, `PROVIDER_REQUEST_LIMIT`, `ITEM_LIMIT`.

**허가 유형은 방법별로 분리됩니다 (2026-11-19):**

| 방법 | `collection_method` / 목적 | 허용 URL | 제공자 허가 |
|---|---|---|---|
| HTML 수집 (`WEB`) | `WEB` / `harvest_collection` 등 | 검색·상세 페이지 | `allowed_methods` 에 `WEB` |
| 공식 XML API (`API`) | `API` / `api_collection` | API endpoint 의 공개 형태(`scheme://host/path`, query 없음)만 | `API_CONTRACT`, `allowed_methods` 에 `API` |

- API 승인은 HTML 페이지를 허용하지 않고, WEB 승인은 API 를 허용하지 않습니다(`METHOD_NOT_ALLOWED`).
- JobKorea 가 발급한 계정 파라미터가 붙은 실제 호출 URL 과 등록 IP 는 Git 밖 API 설정 파일(`jobkorea-api.json`)에만 둡니다. 승인·허가 파일과 로그에는 공개 형태만 씁니다.
- API 실행(`crawler.jobs.jobkorea_api`)은 첫 요청 전에 송신 IP 가 등록 IP 인지 확인하고, 아니면 요청 없이 `SOURCE_IP_NOT_REGISTERED` 로 멈춥니다.
- 누적 상한 1,000건은 `jobkorea_api` 와 `jobkorea_live` 저장 건수를 합산합니다.
- **읽기 전용 Probe 예외 (PM 결정 2026-11-19):** 목적 `api_probe` 에 한해 제공자 허가의 `storage_allowed` 검사를 하지 않습니다. 그 밖의 허가 검사는 그대로 적용합니다.
  - 적용 조건: `collection_method=API`, 요청 정확히 1회, `Size` 5 이하, PM 승인 `max_harvest_details` 5 이하.
  - 금지: DB 쓰기·원문 파일 저장. `run_api_collection` 은 Probe 소스를 DB 접근 전에 거부합니다(`READ_ONLY_PROBE`).
  - 일반 API 수집(`api_collection`)과 HTML 수집은 여전히 `storage_allowed=true` 가 필요합니다.

**기타 규칙:**
- PM 승인 파일 안에 `provider_permission` 을 직접 써 넣어도 무시합니다. 참조된 별도 파일만 인정합니다.
- 승인 파일이나 `CRAWLER_LIVE_SCHEDULE_APPROVED=1` 하나만으로는 권한 증명이 아닙니다.
- 환경변수는 승인된 실행 프로세스 안에서만 설정합니다.

## 3. 현재 검증된 상태

이 표는 PM 이 증빙을 확인할 때만 갱신합니다.

| 항목 | 상태 | 근거 |
|---|---|---|
| PM 내부 승인 | **YES** (1절) | 본 문서, 2026-11-17 |
| JobKorea 제공자 허가 | **NOT_CONFIRMED** | 서면 허가·계약 없음.<br>API 신청은 미승인.<br>약관상 수집·저장 제한([T61_STEP06](T61_STEP06_JOBKOREA_WEBSITE_TERMS.md), [SOURCE_REGISTRY](SOURCE_REGISTRY.md) §7).<br>문의서는 미발송([JOBKOREA_DATA_PERMISSION_INQUIRY_2026-11](JOBKOREA_DATA_PERMISSION_INQUIRY_2026-11.md)) |
| JobKorea 공식 XML API | **PM 보고: 승인 완료** (2026-11-19).<br>**증빙 미수령**: 승인 메일, 호출 URL, 식별값이 이 PC 에 없음 | `Jobkorea_API_Guide_v4_1.pdf`(V4.1) 는 채팅으로만 받았습니다. 원본 파일이 없어 SHA-256 은 기록하지 못했습니다.<br>2026-11-19 이 PC 의 송신 IP 는 PM 이 알려준 등록 IP 2개와 다릅니다. PM 은 이후 등록했다고 보고했으며, 등록 여부는 승인 메일 또는 `--check` 로 확인합니다 |
| API 읽기 전용 Probe | 2026-11-19 1회 실행: **HTTP 302** (리다이렉트, 따라가지 않음). 공고 수신 0건, DB 쓰기 0 | 승인 안내문 사본(원본 `.eml` 아님) + PM Probe 결정. 저장 허가는 확인되지 않음(`storage_allowed=false`) |
| LIVE 실행 | **차단** (`PROVIDER_PERMISSION_MISSING`) | 2절 코드 |
| 과거 LIVE 기록 | 승인 B 1회 (2026-11-16, run `8e54090d`, 7 요청, 5건) | PM 위험 수용으로 실행했습니다. 제공자 허가 강제 이전의 기록이며, 지금 같은 실행은 차단됩니다 |

## 4. 제공자 허가를 받은 뒤의 절차

1. **증빙 보관:** JobKorea 가 발급한 서면 허가, 계약 또는 API 약관 원본을 비공개 위치에 둡니다.
   - SHA-256: `Get-FileHash <파일> -Algorithm SHA256`
2. **제공자 허가 파일 작성:** `t61-provider-permission.REQUEST.json` 을 복사합니다.
   - 증빙에 적힌 범위 그대로 씁니다: 기간, 목적, URL, 1일 요청 수, 저장 허용, 최대 건수.
   - 저장 위치: `C:\dev\crawler-data\secrets\t61\jobkorea-provider-permission.json`
3. **PM 승인 파일 작성:** `t61-harvest-approval.REQUEST.json` 을 복사합니다.
   - APPROVED, enabled, 승인자, 근거를 채웁니다.
   - 기간은 제공자 허가 안이어야 합니다.
   - 초기 100건이면 `max_harvest_details=100`, `max_requests`·`max_search_pages` 는 실행 계획에 맞춥니다.
   - `provider_permission_file` 경로를 지정합니다.
4. **사전 점검 (네트워크 없음):** `python -m crawler.jobs.harvest live --policy-file <PM 승인> --pages 5 --new 100 --max-requests 140 --check`
   - `ok: true` 여야 합니다.
5. **실행:** 해당 프로세스에만 `CRAWLER_LIVE_SCHEDULE_APPROVED=1` 을 설정하고, 같은 명령을 `--check` 없이 실행합니다.
6. **기록:** 3절 표를 실제 근거로 갱신합니다. 1회성 승인은 실행 후 파일을 삭제합니다.

### 4-1. 공식 XML API 로 수집할 때

1. **증빙 보관:** JobKorea API 승인 메일 원본(`.eml` 또는 PDF)과 가이드 PDF 를 `C:\dev\crawler-data\secrets\t61\` 에 둡니다.
   - 승인 메일의 SHA-256 을 계산합니다.
2. **API 설정:** `scripts/windows/templates/jobkorea-api-config.REQUEST.json` 을 복사합니다.
   - 저장 위치: `C:\dev\crawler-data\secrets\t61\jobkorea-api.json`
   - 승인 메일의 호출 URL 을 그대로 넣고, 등록 IP 를 적습니다.
3. **제공자 허가:** `t61-api-provider-permission.REQUEST.json` 을 승인 메일의 범위 그대로 채웁니다.
   - 저장 위치: `C:\dev\crawler-data\secrets\t61\jobkorea-api-provider-permission.json`
4. **PM 승인:** `t61-api-approval.REQUEST.json` 을 채웁니다. 초기 100건이면 `max_harvest_details=100`.
5. **사전 점검:** `python -m crawler.jobs.jobkorea_api live --policy-file <PM 승인> --api-config <API 설정> --check`
   - JobKorea 요청은 0건이고, IP 확인 요청 1건만 보냅니다.
   - `ok: true` 와 `source_ip_registered: true` 여야 합니다.
6. **연결 확인:** 해당 프로세스에만 `CRAWLER_LIVE_SCHEDULE_APPROVED=1` 을 설정하고 `--probe` 로 실행합니다.
   - `Size=5` 요청 1건이며 DB 에 쓰지 않습니다.
7. **수집:** 같은 프로세스에서 `--new 100` 으로 실행합니다.
   - 결과는 `crawler_training.harvest_runs`·`harvest_items` 와 `postings`(`source_code='jobkorea_api'`) 로 확인합니다.

## 5. 에이전트 행동 규칙

- 1절의 내부 개발·테스트 범위는 승인된 것으로 보고 다시 묻지 않습니다.
- 제공자 허가가 없으면 LIVE 요청을 하지 않습니다. 보고는 이 형식으로만 합니다: `BLOCKED_PERMISSION: PROVIDER_PERMISSION_MISSING (docs/data/T61_PM_APPROVAL_POLICY.md §3)`
- 승인·허가 파일을 만들거나, 값을 추정하거나, 승인 플래그로 우회하지 않습니다.
- 실제로 확인한 상태만 3절에 기록합니다. 상태는 이 문서 한 곳에서만 관리하고 다른 문서는 여기를 링크합니다.
