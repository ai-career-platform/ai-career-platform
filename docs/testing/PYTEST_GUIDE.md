# Backend pytest — 초보 개발자 단계별 실행 가이드

> 정식 Backend `backend/`와 운영 PoC `poc/staging/backend/`는 **서로 다른 앱**입니다. Python 3.12 / Windows 11 PowerShell 기준. 아래 명령은 실행 예시이며 실제 실행 결과가 아닙니다.

## STEP 01. 개발 환경 준비

프로젝트를 clone한 뒤 정식 Backend로 이동합니다.

```powershell
Set-Location "$HOME\projects\ai-career-platform\backend"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip check
```

`requirements-dev.txt`는 `-r requirements.txt`로 실행 의존성도 함께 설치합니다. PostgreSQL 서버/비밀번호가 필요한 테스트는 개인 격리 DB를 사용하며, 공유 Staging 슈퍼유저 자격증명을 쓰지 않습니다.

## STEP 02. 테스트 목록 파악

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
```

`backend/pytest.ini`: `testpaths=tests`, `pythonpath=.`. 현재 테스트 예시는 `test_smoke.py`, `test_errors.py`, `test_db.py`입니다. 의도적으로 제외된 테스트나 수집 실패를 확인합니다.

## STEP 03. 테스트 실행 및 JUnit 결과 저장

```powershell
New-Item -ItemType Directory -Force .\test-results | Out-Null
.\.venv\Scripts\python.exe -m pytest -v --tb=short --junitxml=test-results\pytest-junit.xml 2>&1 |
    Tee-Object -FilePath test-results\pytest-console.log
```

PowerShell 파이프는 종료 코드 판단을 가릴 수 있으므로 반드시 아래와 같이 **별도 실행**하거나 `$LASTEXITCODE`를 확인하세요.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --junitxml=test-results\pytest-junit.xml
$LASTEXITCODE
```

`0`은 선택된 pytest 실행 성공, 그 외는 실패/수집 오류 등을 의미합니다. 테스트 보고에는 JUnit `tests/failures/errors/skipped` 값과 실제 명령·커밋을 기록합니다. 결과 파일은 보안 검토 전 Git에 커밋하지 마세요.

## STEP 04. 실패 테스트만 반복 확인

```powershell
.\.venv\Scripts\python.exe -m pytest -x -vv
.\.venv\Scripts\python.exe -m pytest tests/test_smoke.py -vv
```

- `ModuleNotFoundError`: 다른 Python 인터프리터가 선택됐는지 확인.
- `collected 0 items`: 테스트 폴더/파일명, `pytest.ini` 확인. 0건을 PASS라고 표시하지 않음.
- DB 연결 실패: 로컬/격리 DB의 환경 설정 확인. Staging을 수정해 테스트 통과시키지 않음.
- 예상치 못한 500: 응답 본문과 테스트 Fixture/Mock, 서버 로그의 민감정보 제거 후 첨부.

## STEP 05. PoC 테스트(선택, 별도 환경)

`poc/staging/backend/requirements.txt`에는 pytest/httpx가 없습니다. PoC 전용 가상환경에 필요한 개발 패키지를 추가하고, `poc/staging`에서 실행합니다.

```powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging"
.\backend\.venv\Scripts\python.exe -m pip install pytest==8.3.5 httpx==0.28.1
.\backend\.venv\Scripts\python.exe -m pytest -q tests
```

설치 명령은 기존 `backend/.venv`를 만들어 두었을 때만 동작합니다. 이 실행은 정식 Backend pytest의 대체가 아닙니다.

## STEP 06. PR 증빙

[TEST_EVIDENCE_GUIDE.md](TEST_EVIDENCE_GUIDE.md)에 따라 테스트 명령, PASS/FAIL/SKIP, 실행 환경, Git SHA, JUnit XML 경로와 CI URL을 작성하세요. JUnit/로그에 이메일, 인증 토큰, DB URL/비밀번호가 포함되면 공유·커밋 전에 반드시 제거합니다.
