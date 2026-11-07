# 학습용 채용공고 검색·필터 실습

> SYNTHETIC_ONLY / READ_ONLY / LOCALHOST_ONLY / PRODUCTION_API_UNCHANGED

## 추가 기능

- 제목 부분 검색: `GET /jobs?title=Python` (대소문자 구분 없이 포함 검색)
- 지역 정확히 일치: `GET /jobs?location=경기`
- 고용형태: `GET /jobs?employment_type=contract`, 허용값 `full_time` 및 `contract`
- 동시 검색: `GET /jobs?title=Python&location=경기&employment_type=contract`
- 이전 `GET /jobs?limit=20` 기본 동작은 유지
- 검색어는 SQL 문장에 직접 삽입하지 않고 **바인딩 파라미터**로 전달. 제목 검색은 `strpos(lower(title), lower(%s))` 방식으로 검색문자 `%` 등을 특수 와일드카드로 해석하지 않음
- 소스는 `jobkorea`, 합성 ID `SYNTH-%` 범위로 유지. 기존 `crawler_training.postings`에서 SELECT만 실행

## 브라우저

기존 로컬 서버를 종료(`Ctrl+C`)하고, DB 접속 환경변수 설정된 PowerShell 세션에서 다시 실행:

```powershell
py -3.12 -m uvicorn backend.training_jobs_api:app --host 127.0.0.1 --port 8001
```

`http://127.0.0.1:8001/training`에서 제목·지역·고용형태 조건을 선택해 **검색**을 누른다. `다시 조회` 버튼도 현재 필터 조건으로 재조회한다.

합성 공고 2건 기준 예상:
- 필터 없음: 2건
- `title=Python`: 1건 (`SYNTH-AX-002`)
- `location=서울`: 1건 (`SYNTH-AX-001`)
- `employment_type=contract`: 1건 (`SYNTH-AX-002`)
- `title=Python&location=서울`: 0건 (빈 결과 안내)

## 검증

```powershell
py -3.12 -m unittest discover -s backend/training_tests -v
```

기존 10개와 신규 8개 = **18개 예상**. 브라우저 필터 직접 사용에 대한 사용자 확인은 별도 필요.

## 범위

실사이트 수집 금지, PostgreSQL INSERT/UPDATE/DELETE 없음, 운영 Backend/정식 Frontend 코드 변경 없음. 현재 페이지는 로컬 단기 실습용이고 인증 기능을 포함하지 않는다.
