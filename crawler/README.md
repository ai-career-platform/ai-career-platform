# T62 — 잡코리아 단일 출처 학습용 정규화 (STEP 01)

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
