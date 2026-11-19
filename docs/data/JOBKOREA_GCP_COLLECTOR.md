# JobKorea 공식 API → GCP Cloud SQL 수집기

JobKorea 공식 XML API 를 GCP VM `ai-career-vm` 에서 호출해 Cloud SQL `ai_career_poc` 의 `career` 스키마에 바로 저장합니다. Windows PC 수집과 GCP 동기화는 이 경로에 쓰지 않습니다.

- 승인 상태와 T61 규칙: [T61_PM_APPROVAL_POLICY.md](T61_PM_APPROVAL_POLICY.md)
- API 해석과 필드 매핑: [JOBKOREA_XML_API.md](JOBKOREA_XML_API.md)

## 구조

```text
JobKorea XML API ──(등록 IP 34.64.45.17)── ai-career-vm
                                             └ 일회용 컨테이너 (실행 중인 backend 이미지, --rm)
                                                 crawler.jobs.jobkorea_collector
                                                   ├ API 요청 (jobkorea_api.LiveApiSource: T61·IP·2초·오류 시 중단)
                                                   ├ XML 해석 (jobkorea_api_xml)
                                                   └ 계획·저장 (gcp_sync.sync_rows, career_sync 권한, TLS verify-full)
                                                        ↓
                                             Cloud SQL ai_career_poc / career.*
```

## 저장 방식

`crawler/jobs/gcp_sync.py` 의 검증된 저장 경로를 그대로 씁니다.

| 항목 | 내용 |
|---|---|
| 중복 기준 | `career.job_posting_external_refs` 기본키 `(source_id, external_id)` = 데이터 출처 + `GI_No`. DB 가 강제하므로 스키마 변경이 필요 없습니다 |
| 신규 | `job_postings` + `job_posting_external_refs` INSERT. 기업은 이름으로 재사용하거나 새로 만듭니다 |
| 기존 | 바뀐 필드만 UPDATE. 같으면 쓰지 않습니다 |
| 빈 값 | API 에 값이 없으면 저장된 값을 비우지 않습니다 (`preserve_on_null`) |
| 키워드 중복 | 같은 실행 안에서 `GI_No` 당 한 건 |
| 원문 URL 중복 | 다른 출처(예: 기존 `jobkorea_live`)가 같은 URL 을 가지면 넣지 않고 `URL_CONFLICT` 로 기록 |
| 상한 | 실행당 `--new`(기본 100), 출처 누적 1,000건. 다 차면 API 요청 없이 `CUMULATIVE_LIMIT` |
| 트랜잭션 | 실행 1회 = 1 트랜잭션. 오류 시 전체 ROLLBACK. API 오류로 멈추면 아무것도 쓰지 않습니다 |
| 공개 여부 | 새 공고는 `draft` (웹사이트에 안 보임). `JOBKOREA_COLLECTOR_PUBLISH=1` 은 출처 표시가 운영에 반영된 뒤 PM 결정으로만 켭니다 |
| 실행 기록 | `career.ingestion_runs` (작성자 `jobkorea_api`, API 요청 수·수신·해석·중복 건수 포함) |
| 동시 실행 | VM 의 `flock` + DB advisory lock 337002(수집기), 337001(저장) |

## 2026-11-19 확인한 사실 (읽기 전용)

| 항목 | 결과 |
|---|---|
| `career_sync` 권한 | `poc/staging/automation/gcp-sync/target_grants.sql` 과 일치: SELECT·INSERT, 필요한 열만 UPDATE, DELETE·DDL 없음 |
| `career.data_sources` | 비합성 출처는 `license_ref` 필수(CHECK). JobKorea API 출처 행은 아직 없음 |
| 웹사이트 조회 | `status IN ('published','closed')` 만 표시. `draft` 는 보이지 않음. 기존 API 변경 없이 표시 가능 |
| VM | Python 3.11(시스템, psycopg 없음). backend 이미지: Python 3.12, psycopg 3.3.4. 컨테이너에서 Cloud SQL 5432 연결 가능. Cloud SQL CA 파일 있음 |
| `.env` 관리자 계정(`postgres`) | `career` 스키마 권한 없음. 카탈로그만 읽을 수 있음 |
| `career.data_sources` 열 | `source_id`(기본값), `code` UNIQUE, `name`, `license_ref`, `retention_days`(>0), `is_active`(기본 true), 시각 열(기본값). 아래 INSERT 로 충분 |
| `career_sync` 비밀번호 | 승인된 저장소 어디에도 없음: Windows `gcp-sync.env` 는 사용자만 있고 비밀번호가 비어 있음, `.env` 없음, GCP Secret Manager 없음, VM 은 CA 파일만 있음 (2026-11-19) |

## 실행 전에 필요한 것

| # | 항목 | 담당 | 상태 |
|---|---|---|---|
| 1 | JobKorea 저장 허가 근거 (협약서 등) → T61 제공자 허가 `storage_allowed=true` | PM | **없음** |
| 2 | 데이터 출처 행 생성 (스키마 소유자 `ai_career_poc` 로, 아래 SQL) | DBA, 1 의 근거 필요 | 대기 |
| 3 | VM 에 `career_sync` 비밀번호를 담은 `collector.env` | DBA | **없음** |
| 4 | T61 PM 승인 파일 (`collection_method=API`, `api_collection`, `max_harvest_details=100`) | PM | 1 이후 |
| 5 | VM 에 코드 배치 (`/opt/ai-career-gcp/jobkorea-collector/code`) | 승인 후 | 대기 |
| 6 | 웹사이트 목록 출처 표시 (아래 "출처 표시") 와 `publish` 결정 | PM | 대기 |

데이터 출처 행 (2번, 근거 확인 뒤에만):

```sql
INSERT INTO career.data_sources (code, name, license_ref, retention_days)
VALUES ('jobkorea_api', 'JobKorea 공식 채용정보 XML API', '<협약서 등 저장 허가 근거 위치>', <보관 일수>);
```

## 실행 (VM, 수동)

```bash
scripts/gcp/run-jobkorea-collector.sh check            # JobKorea 요청 0, DB 접근 0
scripts/gcp/run-jobkorea-collector.sh dry-run --new 100 # API 요청 + Cloud SQL 계획, 쓰기 없음
scripts/gcp/run-jobkorea-collector.sh run --new 100     # 저장 (1~4 충족 후)
```

결과는 `/opt/ai-career-gcp/jobkorea-collector/logs/` 와 `career.ingestion_runs` 에 남습니다. 정기 실행은 등록하지 않았습니다.

`dry-run` 도 실제 API 를 여러 번 호출하므로 T61 의 `api_collection` 허가(저장 허가 포함)가 필요합니다. 그 전에는 `--fixture-dir` 로 API 없이 계획만 확인할 수 있습니다.

## DB 에 칸이 없는 API 필드

현재 `career.job_postings` 에 없는 항목입니다. 필요하면 별도 스키마 변경을 제안합니다.

| 필드 | 내용 | 비고 |
|---|---|---|
| `GI_Career`, `GI_Career_Year_Cnt` | 경력조건, 경력년수 | 검색·추천에 유용. 신규 열 후보 |
| `GI_Part_No` | 업·직종 코드 | `job_role_id` 와 매핑표가 있으면 열 없이 연결 가능 |
| `GI_Keyword` | 공고 키워드 | 기술 태그 후보 |
| `GI_Pay`, `GI_Pay_Term`, `GI_Pay_Flag` | 급여 | 신규 열 후보 |
| `GI_Edu_CutLine`, `GI_EDU_Options` | 학력 | 신규 열 후보 |
| `GI_Comment` | 상세요강 | `description` 열이 있지만 저장 범위(원문 재가공 제한) 확인 전에는 넣지 않음 |
| `Jikgub`, `Staff`, `GI_Pass_Type`, `Biz_No`, `C_URL`, `GI_E_Date` | 직급, 모집인원, 접수방법, 사업자번호, 기업정보 URL, 수정일 | 필요 시 검토 |

## 출처 표시

| 요구 (가이드 V4.1) | 상태 |
|---|---|
| 공고 하단 안내문, "잡코리아" 링크 | **구현** (`JobPostingsPage.tsx` 상세 영역, 원문이 jobkorea.co.kr 이거나 출처 코드가 `jobkorea*` 일 때). 운영 배포 전 |
| 목록 하단 "잡코리아 제공" · "잡코리아 채용정보 더보기" 링크 | **구현**: 목록 API(`JobPostingSummary`)에 선택 필드 `source`(데이터 출처 코드)를 추가했고, 목록에 JobKorea 공고가 있으면 표시합니다. 운영 배포 전 |

운영 배포와 PM 의 `publish` 결정 전까지 JobKorea 공고는 `draft` 로 둡니다.

## 기존 경로와의 관계

- HTML 수집기와 Windows → GCP 동기화(`gcp_sync`, 출처 `jobkorea_live`)는 그대로 두고 쓰지 않습니다.
- 두 경로가 같은 공고를 넣으려 하면 URL 중복 검사가 막습니다(`URL_CONFLICT`). 중복 공고는 생기지 않습니다.
- 전환 제안: 수집기 첫 `run` 성공 뒤, Windows 측 `jobkorea_live` 동기화와 야간 HTML 수집을 공식 비활성으로 기록하고, 남아 있는 `jobkorea_live` 공고는 PM 결정에 따라 그대로 두거나 `closed` 로 정리합니다.
