# JobKorea 공식 XML API 연동

JobKorea 수집은 HTML 스크래핑 대신 공식 채용정보 XML API 를 씁니다. 근거는 JobKorea 「채용정보 XML 가이드」 V4.1(2023-04-12)입니다.

- 승인 상태와 실행 절차는 [T61_PM_APPROVAL_POLICY.md](T61_PM_APPROVAL_POLICY.md) §2(허가 유형), §3(상태), §4-1(절차)에 있습니다. 이 문서는 구현 설명만 담습니다.
- 가이드 PDF 는 JobKorea 내부자료라 저장소에 넣지 않습니다. 원본은 `C:\dev\crawler-data\secrets\t61\` 에 둡니다.
- 기존 HTML 수집 코드(`crawler/jobs/harvest.py`, `import_jobkorea_html.py`, `night_crawl.py`)는 삭제하지 않았고, 이 경로에서 쓰지 않습니다.

## 코드

| 파일 | 역할 |
|---|---|
| `crawler/adapters/jobkorea_api_xml.py` | XML 응답 해석(EUC-KR), 필드 매핑. 네트워크·DB 없음 |
| `crawler/jobs/jobkorea_api.py` | T61 검사, IP 확인, 요청, 중복 제거, 저장, 원장 기록, CLI |
| `crawler/policy/source_approval_gate.py` | `collection_method='API'` 검사(`_check_api`), endpoint 형식 검사 |
| `crawler/tests/test_jobkorea_api.py` | 단위 테스트 (CI 기본 실행) |
| `crawler/tests/local_jobkorea_api_pg.py` | 실제 PostgreSQL 테스트 (CI 의 일회용 DB, 로컬은 일회용 클러스터만) |

## 요청

- 요청 변수: `Size`(1~100), `Page`, `Ob=1`(등록일순, 가이드 권장), `Keyword`(EUC-KR 퍼센트 인코딩).
- 계정 파라미터가 붙은 호출 URL 은 Git 밖 API 설정 파일에만 있습니다. 출력·로그·DB 에는 `scheme://host/path` 만 남깁니다.
- 요청 사이 최소 2초, 한 번에 1개. 리다이렉트는 따르지 않습니다.
- 다음 경우 실행 전체를 즉시 멈추고 재시도하지 않습니다:
  - 401·403·429, 그 밖의 HTTP 오류, 네트워크 오류;
  - `DataList` 가 아닌 응답(인증 오류 페이지 등).
- 키워드마다 1쪽부터 읽고, 신규 공고가 더 필요할 때만 다음 쪽을 요청합니다.
  - 검색 결과는 최대 500건(`TotalSumCnt`)이므로 `Size=100` 이면 키워드당 최대 5쪽입니다.

## 응답 → `crawler_training.postings`

기존 `NormalizedPosting` 필드를 그대로 씁니다. 응답에 없는 값은 만들지 않습니다.

| XML | 저장 필드 | 처리 |
|---|---|---|
| `GI_No` | `external_posting_id` | 숫자만 허용 |
| `JK_URL` | `source_url` | `https://www.jobkorea.co.kr/Recruit/GI_Read/<id>`. query(API 식별값 포함)는 저장하지 않음 |
| `GI_Subject` | `title` | 필수 |
| `C_Name` | `company_name` | 필수 |
| `AreaCode` | `location_text` | 지역 코드 → 시·도 이름, 중복 제거. `0` 은 비움 |
| `GI_Job_Type` | `employment_type` | 첫 코드: 1 정규직, 2 계약직, 3 인턴, 7 아르바이트. 그 밖은 비움 |
| `GI_W_Date` | `published_on` | `YYYYMMDD` → 날짜 |
| `GI_End_Date` | `expires_on` | `YYYYMMDD` → 날짜. 그 밖의 값은 비움 |

- `source_code`: 실수집 `jobkorea_api`, Fixture `jobkorea_api_fixture`. GCP 동기화 기본값(`jobkorea_live`)과 다르므로 자동으로 전송되지 않습니다.
- `GI_Career`(경력조건) 등은 현재 모델에 칸이 없어 저장하지 않습니다. 필요하면 별도 스키마 변경으로 추가합니다.
- 중복 판정: 이미 저장된 `jobkorea_api`·`jobkorea_live` 공고와 같은 실행의 다른 키워드에서 본 공고는 넣지 않습니다.
- 누적 상한: 두 출처 합계 1,000건. 남은 수만큼만 넣고, 0이면 요청 없이 `CUMULATIVE_LIMIT` 로 멈춥니다.
- 기록: `harvest_runs`(실행), `harvest_pages`(키워드·쪽별 건수), `harvest_items`(신규 공고별 결과).

## 출처 표시 (가이드 요구, 프론트엔드 변경 필요)

이번 작업에서는 운영 프론트엔드를 바꾸지 않았습니다. JobKorea API 공고를 화면에 보이기 전에 아래가 필요합니다.

| 요구 | 현재 | 필요한 변경 |
|---|---|---|
| 채용정보 목록 하단에 JobKorea 출처 표시, `https://www.jobkorea.co.kr` 링크 | 없음 (`JobPostingsPage.tsx` 는 일반 "데이터 출처" 문구만) | 목록 하단에 "잡코리아 제공" 또는 "잡코리아 채용정보 더보기" 링크 |
| 공고 하단 안내문구, "잡코리아" 에 링크 | 없음 | "자세한 채용정보는 반드시 상세정보를 통해 확인하시기 바랍니다. 본 정보는 채용기업과 잡코리아의 동의 없이 무단전재 또는 재배포, 재가공할 수 없습니다." |
| 원문 링크 | 원문 링크 문구 있음 | `source_url` 로 연결. 가이드는 API 링크에 `Oem_Code=C900` 을 쓰므로 표시 시 붙일지 확인 |
| 무단 전재·재배포 금지 | — | 외부 재배포 기능을 만들지 않음 |
