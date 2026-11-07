# T62 — 잡코리아 단일 출처 학습용 정규화 (STEP 01)

## 수동 HTML / HTTP MVP

기존 합성 실행과 별도로, 허용된 HTML 파일 1~10개를 기존 학습 DB에 가져올 수 있습니다.
`CRAWLER_LOCAL_DATABASE_URL`은 기존 로컬 학습 DB/전용 계정을 지정합니다.

```powershell
py -3.12 -m crawler.jobs.import_jobkorea_html --url https://www.jobkorea.co.kr/Recruit/GI_Read/12345678 --html C:\path\permitted.html
```

`--url`과 `--html`을 같은 순서로 반복합니다. HTML 옵션을 생략하면 명시한 URL만
HTTP 요청합니다. 라이브 실행은 제공자의 접근·저장·표시 허용 범위를 확인한 경우에만 사용합니다.
robots 검사, 15초 timeout, 최소 2초 간격, 최대 10건, redirect/403/429/CAPTCHA 중단을 적용합니다.
원본 HTML은 DB에 저장하지 않습니다. 새 스키마 없이 기존 upsert를 사용합니다.

`/training`에서 출처를 선택하면 `/jobs/collected`의 HTTP 수집 또는 가져온 HTML을
카드별로 구분해 표시합니다. 기존 `/jobs`는 합성 공고 전용입니다.
가져온 HTML은 실제 데이터라는 증명이 아닙니다.

**검증 범위:** 기존 JSON-LD 파서를 재사용합니다. 허용된 실제 HTML 샘플이 없어
잡코리아 현행 DOM/JSON-LD 호환성과 라이브 수집은 아직 검증하지 못했습니다.
테스트 HTML은 직접 구성한 예제이며 실제 잡코리아 응답이 아닙니다.
실제 HTML에 JobPosting JSON-LD가 없으면 오류로 기록하며 필드를 추측하지 않습니다.

현재 단계는 **외부 네트워크 호출·DB 저장 없이** 합성 데이터로만 DTO/입력검사를 학습합니다. 잡코리아 공고 페이지를 실제 수집하거나 상용 연동한 구현이 아닙니다.

## 구성

- `normalizer.py`: 공고 제목·기업명·원문 URL·상태·지역·고용형태·날짜 후보 필드 검증 및 DTO 변환
- `fixtures/jobkorea_synthetic.json`: **가상 기업·가상 공고 2건**. URL의 숫자는 실제 공고를 확인한 ID가 아닌 자리표시자이며 접속하지 않음.
- `tests/test_normalizer.py`: 정상 2건, 잘못된 입력·URL·날짜 거부를 위한 순수 Python unittest

## 실행

Repository 최상위 폴더에서 Python 3.12:

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
```

외부 패키지 설치, PostgreSQL, 네트워크가 필요하지 않습니다.

## 다음 단계

잡코리아 실제 HTML 구조의 검증, 실제 Adapter/Worker의 네트워크 fetch, DB 저장, 관리자 스케줄러는 **미구현**입니다. T61 범위·수집 조건을 구분해 검토한 후 작은 단계로 진행합니다.

관련 정책: [JOBKOREA_FIELD_AND_RIGHTS_CONTRACT.md](../docs/data/JOBKOREA_FIELD_AND_RIGHTS_CONTRACT.md).

## STEP 02 — Offline Adapter + CLI Batch Worker

**추가 구현 범위:** `adapters/base.py`의 출처 인터페이스, `adapters/jobkorea_fixture.py`의 JSON Fixture Adapter, `jobs/run_crawler.py`의 CLI 실행·요약 통계. **실사이트 HTTP 요청·DB 저장 기능은 구현하지 않았습니다.**

Repository 최상위에서:

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
py -3.12 -m crawler.jobs.run_crawler --source-id jobkorea --run-id training-001
```

정상 Fixture 기준 예상 출력은 다음과 같으며, **실제 실행 결과가 아니라 기대값**입니다.

```json
{"db_writes":0,"duplicates":0,"external_requests":0,"fetched":2,"invalid":0,"mode":"synthetic_fixture_only","normalized":2,"run_id":"training-001","source_id":"jobkorea","status":"SUCCEEDED"}
```

- 소스는 `jobkorea` 한 가지만 허용합니다.
- 필수 필드·날짜 오류는 `invalid`에 집계하고, 동일 `source_code+external_posting_id`는 `duplicates`에 집계합니다. **DB 멱등성은 아직 미구현**입니다.
- 실패한 Fixture JSON 또는 잘못된 소스/실행 ID는 종료코드 2, 레코드 검증 오류·중복이 있으면 종료코드 1, 모두 정상이면 0을 반환합니다.
- 이 단계는 HTTP 요청·재시도·rate limit·스케줄·실 DB 연동을 다루지 않습니다.

## STEP 03 — 임시 저장 계약과 중복 방지 (in-memory)

- `crawler/storage/memory.py`: `PostingStore.upsert()` Protocol과 `MemoryPostingStore` 구현.
- 키: `(source_code, external_posting_id)`. 신규는 `inserted`, 동일 내용은 `unchanged`, 같은 키의 변경 데이터는 `updated` 반환.
- **같은 배치 내 중복:** 첫 번째 유효 공고만 저장 후보로 인정하며 나중에 나타난 동일 키는 `duplicates`에 집계.
- **반복 배치 테스트:** Python 코드에서 동일 `MemoryPostingStore` 객체를 전달하면 두 번째 실행에서 중복 DB 삽입 없이 `unchanged`로 계산.
- **중요:** 이 저장소는 **Python 메모리 안에만 존재**하며, CLI를 종료하면 소멸합니다. PostgreSQL·SQLite·파일에 저장하지 않으며 `db_writes=0`, `external_requests=0`입니다. `inserted/updated`는 **메모리 작업 건수**이지 DB 적재 건수가 아닙니다.

Windows 11 PowerShell에서 저장소 최상위:

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
py -3.12 -m crawler.jobs.run_crawler --source-id jobkorea --run-id training-001
```

기존 STEP 01~02 테스트 15개 + 신규 저장 계약 테스트 7개 = **총 22개 테스트 예상**. 새 CLI 출력에는 `store: "in_memory_only"`, `inserted: 2`, `updated: 0`, `unchanged: 0`가 추가됩니다. 이는 기대값이며 실제 로컬 실행 결과는 별도 검증해야 합니다.

**후속 단계:** 격리된 로컬 DB에 대한 실제 Persistence Adapter 구현·테스트는 별도 PR/승인 범위로 분리합니다. 실제 잡코리아 페이지 접근, 운영 DB, Ubuntu Staging, 자동 수집·스케줄은 이번 PR에 포함하지 않습니다.

## STEP 04 — 격리된 로컬 PostgreSQL 저장소 (OPT-IN)

**목표:** 기존 합성 Fixture 2건을 로컬 학습 DB에 INSERT하고 동일 데이터 재실행은 `unchanged`, 변경된 합성 공고는 `updated`로 검증한다. **실제 잡코리아 웹페이지 요청은 여전히 0건**이다. 메모리 CLI 기본 동작과 기존 테스트는 유지된다.

### 1. 안전 경계

- Windows 11 PC의 **별도 로컬 데이터베이스 `ai_career_crawler_training`**만 연결 가능. 외부 호스트·기존 `ai_career_poc`·Staging/운영 DB를 지정하면 코드에서 거부한다.
- **전용 비관리자 PostgreSQL 계정**을 사용하고, 해당 학습 DB의 `crawler_training.postings` 테이블에만 필요한 권한을 부여한다. `postgres` 및 `ai_career_poc` 사용자명은 연결 거부.
- DB/계정/스키마를 프로그램에서 자동 생성하지 않는다. DB 관리자가 **로컬 DB임을 확인한 후** 별도 생성하고, 해당 DB에서만 [학습용 SQL](storage/local_training_schema.sql)을 적용한다.
- 잡코리아 실데이터, API, 로컬 외부 사이트 요청, DDL Migration, 정식 `career` 스키마, Ubuntu Staging/운영 배포는 범위 외.
- 비밀번호·DB 연결 URI를 Git에 커밋하거나 이슈·PR·채팅에 복사하지 않는다. 연결 설정은 실행 프로세스의 환경변수에서만 받는다.

### 2. 환경 준비

로컬 PostgreSQL의 전용 DB와 최소권한 역할 설정이 완료된 후, `crawler`가 사용할 패키지를 같은 로컬 가상환경에 설치한다.

```powershell
py -3.12 -m pip install "psycopg[binary]==3.3.4"
```

학습용 DDL은 `crawler/storage/local_training_schema.sql`에 있다. **다른 DB로 실행하지 말 것.** DDL을 적용하려면 로컬 DB 관리자에게 `ai_career_crawler_training` DB 및 계정 권한을 먼저 확인한다.

### 3. 오프라인 기본 검증 (DB 불필요)

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
py -3.12 -m crawler.jobs.run_crawler --source-id jobkorea --run-id training-001
```

STEP 03 22개 + STEP 04 신규 11개 = **총 33개 테스트 예상**. DB/네트워크가 없어도 실행 가능하다.

### 4. 로컬 PostgreSQL 실제 검증 (별도 준비 후)

**연결 문자열은 반드시 `CRAWLER_LOCAL_DATABASE_URL` 환경변수로만 입력.** 예시 주소는 구조 설명이며, 실제 비밀번호를 명령행이나 소스에 적지 않는다.

```text
postgresql://<dedicated-training-user>@127.0.0.1:5432/ai_career_crawler_training
```

로컬 PostgreSQL 인증은 별도의 안전한 자격증명 설정(예: 로컬 전용 `pgpass` 파일 또는 세션의 비밀 환경변수)을 사용한다. 설정 완료 후:

```powershell
py -3.12 -m crawler.jobs.run_crawler --source-id jobkorea --run-id pg-training-001 --store postgres
py -3.12 -m crawler.jobs.run_crawler --source-id jobkorea --run-id pg-training-002 --store postgres
```

- 1회: `inserted=2, unchanged=0, db_writes=2` 예상
- 2회: `inserted=0, unchanged=2, db_writes=0` 예상
- **주의:** 위 숫자는 신규/빈 학습 테이블 기준 **예상값**이다. 이 PR에서 실제 Windows PostgreSQL 연결 또는 INSERT/UPDATE를 실행했다고 주장하지 않는다.

### 5. 운영 및 구현 한계

- 현재 구현은 **단일 프로세스·순차 실행 학습용**이며 다중 Worker 경쟁·장애 후 복구·배치 전체 트랜잭션·운영 마이그레이션을 다루지 않는다.
- 테이블 `payload jsonb`는 독립 학습용 저장 형식이며 정식 `career.job_postings` 데이터 모델을 변경하지 않는다.
- `PostgresPostingStore.upsert()`는 공고 1건당 트랜잭션을 수행한다. DB 연결/SQL 오류 시 CLI가 실패하며 성공 결과를 출력하지 않는다.
- 단계 완료는 **테스트 33개 PASS + 실제 로컬 DB에 1회/2회 결과 확인** 후 판정. Staging 적용은 별도 결정.


## STEP 06 — 오프라인 재시도·요청 간격·차단 정책 모의 실습

- `adapters/offline_retry.py`는 **주입받은 가짜 요청 함수**만 실행하는 순수 Python 정책 실습이다. HTTP 라이브러리를 가져오지 않고, Worker CLI / 실제 사이트 수집 경로에도 연결하지 않는다.
- `tests/test_offline_retry.py`: 성공, 5xx, 타임아웃, 연결 실패, 유한 재시도, 지수 백오프 상한, 재시도 간 최소 간격, 403·429 즉시 중지 등 **15개 시나리오**.
- HTTP 429는 서버의 제한 신호로 간주하여 **재시도하지 않고 중지**한다. 403도 즉시 중지한다. 5xx/네트워크 일시 오류만 제한된 횟수(기본 최대 3회)로 재시도한다.
- 모의 요청의 `sleep` 콜백은 대기 시간을 기록하는 가짜 함수다. 실제 시스템 대기·외부 호출·DB 저장은 없다.
- 최소 간격 설정은 **하나의 요청 시퀀스 내부 재시도 사이**의 검증에만 적용된다. 다수 Worker 간 전역 속도제한 또는 실제 외부 요청 속도 제어 기능은 아직 구현되지 않았다.
- 기본 CLI는 계속 `synthetic_fixture_only`로 동작하며 `external_requests=0`이다. T61 실사이트 수집 게이트는 여전히 HOLD.

실습 검증:

```powershell
py -3.12 -m unittest discover -s crawler/tests -v
py -3.12 -m crawler.jobs.run_crawler --source-id jobkorea --run-id step06-check
```

STEP 05까지 기존 33개와 STEP 06 추가 15개를 합해 **총 48개 테스트 예상**이며, 실제 실행 결과는 별도로 확인한다.
