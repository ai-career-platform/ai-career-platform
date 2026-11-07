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
