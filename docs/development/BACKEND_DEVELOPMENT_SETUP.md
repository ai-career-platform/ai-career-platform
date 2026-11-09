# Backend 개발자 로컬 개발환경 — Windows 11

> 2026-11-06 기준 main SHA `2338031c2dfdcf14c2a7ddba01800cffba10be41`. 문서의 기대 결과는 실제 실행 PASS가 아닙니다. Staging DB 스키마/Seed 미구축, 관리자 비밀번호 배포 금지. 전체 30개 기능/46개 DB 엔터티는 **설계 후보**. 기존 실행 앱은 **PoC**입니다.

## 1. 가이드 목적 및 대상 개발자
FastAPI 로컬 서버/Swagger/pytest/DB 상태 확인과 향후 기능별 Router-Service-Repository-Schemas 개발 시작을 위한 안내. 현행 구현 API는 `GET /health`, `GET /version`, `GET /health/db` 세 가지. `/api/v1` 서비스 API와 CRUD는 **아직 미구현**.

## 2. 사전 준비사항
Windows 11, GitHub 접근, VS Code/Git, Python, 내부망 접근(선택). 현재 `poc/staging/backend/requirements.txt`의 정확한 의존성은 `fastapi==0.115.12`, `uvicorn==0.34.2`, `psycopg[binary]==3.2.9`. Python 3.12는 로컬 권장 버전이며 저장소에 pin되지 않았음. python-dotenv, SQLAlchemy, Alembic은 **현행 PoC 설치 목록에 없음**.

## 3. 개발 도구 설치
### STEP 01 — Git/VS Code/Python 설치
**목적:** 복사 실행 가능한 Python 환경.

**실행:** 공식 설치 https://git-scm.com/download/win · https://code.visualstudio.com/download · https://www.python.org/downloads/windows/ . Python Launcher 및 VS Code Python 확장 설치.

~~~powershell
git --version
code --version
py -0p
py -3.12 --version
py -3.12 -m pip --version
~~~

**기대 결과:** Git/Python 3.12 및 pip 버전 출력. **실패 시:** Python Launcher/PATH/VS Code 재실행 확인. 없으면 3.12 설치.

## 4. GitHub 프로젝트 내려받기
### STEP 02 — GitHub Clone
**목적:** 최신 main 기준 동작 확인.

~~~powershell
New-Item -ItemType Directory -Force "$HOME\projects" | Out-Null
Set-Location "$HOME\projects"
git clone https://github.com/ai-career-platform/ai-career-platform.git
Set-Location .\ai-career-platform
git switch main
git pull --ff-only origin main
Get-ChildItem .\poc\staging\backend
git status --short
~~~

**기대 결과:** main 및 `main.py`/`requirements.txt` 확인. **실패 시:** GitHub 조직 권한/원격 경로 확인. 이미 Clone된 폴더는 중복 clone하지 않고 pull만.

## 5. 환경 설정
### STEP 03 — 가상환경 .venv 및 실제 의존성 설치
**목적:** 시스템 Python과 프로젝트 분리.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging\backend"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import fastapi,uvicorn,psycopg;print(fastapi.__version__,uvicorn.__version__,psycopg.__version__)"
~~~

VS Code → Python: Select Interpreter → `poc/staging/backend/.venv/Scripts/python.exe`. 가상환경 Activate 없이도 위 경로로 실행 가능. **기대 결과:** pinned 패키지 import 및 버전 출력. **실패 시:** pip 통신, 3.12 Launcher, venv 경로 확인.

### STEP 04 — DB 환경변수·Secret
**목적:** 관리자인 `ai_career_poc` 대신 최소 조회 계정으로 DB health만 시험. 서버 접속 정보는 사용자 제공이며 현장 검증 미완료. 현행 `main.py`는 `.env`를 자동 읽지 않습니다.

**실행 (같은 PowerShell 창에서):**

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging\backend"
$env:APP_ENV = "local-dev"
$env:APP_VERSION = "local-working-tree"
$env:POSTGRES_HOST = "10.2.10.104"
$env:POSTGRES_PORT = "15432"
$env:POSTGRES_DB = "ai_career_poc"
$env:POSTGRES_USER = "career_reader"
$Secret = Read-Host "READ ONLY DB password" -AsSecureString
$Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secret)
try { $env:POSTGRES_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }
Remove-Variable Secret,Ptr
~~~

**기대 결과:** 환경변수는 현재 PowerShell 세션에만 유지, Git 미추적. **실패 시:** 환경변수를 새 창에 옮기지 말고 동일 세션에서 Uvicorn 실행; 민감값 출력/캡처 금지. 내부망·TLS 및 Reader 권한 검증은 HOLD.

## 6. 로컬 실행
### STEP 05 — 실제 FastAPI 서버 실행
**목적:** 제품 코드 추가 전 PoC 건강상태 확인.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging\backend"
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
~~~

**기대 결과:** `http://127.0.0.1:8000`의 개발 서버 기동. 창을 유지. **실패 시:** 8000 사용 중이면 `Get-NetTCPConnection -LocalPort 8000`, `main:app` 작업 디렉터리, pip 설치 확인. 다른 프로그램 임의 종료 금지.

### STEP 06 — Swagger UI / OpenAPI 확인
**목적:** 구현 API의 실제 목록 확인.

**실행:** 새 PowerShell 창에서:

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/version
(Invoke-RestMethod http://127.0.0.1:8000/openapi.json).paths.PSObject.Properties.Name
Start-Process http://127.0.0.1:8000/docs
~~~

**기대 결과:** /health에 `status: ok`, /version에 local-dev, OpenAPI의 세 경로. 실제 /health/db는 접속 성공 시 200, 네트워크/권한 오류 시 503. **실패 시:** 브라우저/Docker/네트워크 문제가 아닌 Uvicorn 실행 여부 먼저 확인. `/api/health`는 Nginx 경유일 때만 사용.

## 7. 공용 Staging 시스템 연동
### STEP 07 — PostgreSQL 연결 및 CRUD 경계
**목적:** 공유 DB 보호.

~~~powershell
Test-NetConnection 10.2.10.104 -Port 15432
# STEP 05가 실행 중인 상태에서 새 터미널
try { Invoke-RestMethod http://127.0.0.1:8000/health/db } catch { Write-Output "DB HEALTH HOLD: 네트워크/계정/권한을 확인하세요." }
~~~

**기대 결과:** DB 접속+SELECT 1 성공 시 `status: ok`. TCP 성공만으로 DB 사용자 인증/TLS 성공 확정 금지. **실패 시:** Reader 계정/비밀값/내부망/SSL 정책 관리자 확인. `career_reader` 권한은 검증 대기. 기존 `ai_career_poc`은 SUPERUSER이므로 개발자 비밀번호 배포 금지. **전용 비관리자 CRUD 계정 미준비**: INSERT/UPDATE/DELETE 테스트는 [로컬 격리 DB](DB_DEVELOPMENT_SETUP.md)에서만. `career_app`은 초안 SQL에서 NOLOGIN 역할이므로 실제 로그인용 계정으로 오인하지 않음.

### STEP 08 — 계층·API 계약·CORS 설계
**목적:** 구현 설계와 현재 코드를 구별.

**실행:** `poc/staging/backend/main.py`를 열고 API 세 개 확인. 향후 프로젝트 구조 제안(아직 미생성): `app/routers/`(HTTP), `app/services/`(업무 규칙), `app/repositories/`(DB 쿼리), `app/schemas/`(Pydantic DTO), `tests/`. 신규 API 계약은 [API 초안](../API_CONTRACT.md) 및 [추적표](../FULL_SCOPE_TRACEABILITY.md)의 F-ID와 정렬하고 인증, 400/401/403/404/409/422, 페이지네이션을 포함.

현행 `poc/staging/frontend/nginx.conf`는 동일 Origin `/api/`를 FastAPI 내부 `/`로 proxy_pass하여 CORS 필요성을 낮춥니다. 현재 `main.py`에 CORSMiddleware **없음**. 직접 다른 Origin에서 호출하려면 승인된 Origin 허용목록을 별도 구현 PR로 추가. CORS는 인증·인가를 대체하지 않음.

**기대 결과:** 신규 API와 현행 헬스체크를 명확히 구분. **실패 시:** /api/v1의 404는 미구현이 정상. 프록시(502)와 브라우저 CORS 에러는 별도 원인.

## 8. 테스트 및 정상 결과 확인
### STEP 09 — pytest
**목적:** 기초 mock 기반 자동 테스트.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging"
.\backend\.venv\Scripts\python.exe -m pip install pytest==8.3.5 httpx==0.28.1
.\backend\.venv\Scripts\python.exe -m pytest -q tests
~~~

**기대 결과:** `tests/test_health.py` 테스트 실행, 실제 통과 개수 기록. 전체 CRUD/권한/E2E PASS로 확대 해석 금지. **실패 시:** venv interpreter, pytest/httpx 설치, 테스트 출력 확인. 테스트 결과가 없으면 HOLD.

## 9. 자주 발생하는 오류 해결
### STEP 10 — 증상별 진단
**목적:** 원인 분리.

| 문제 | 확인 |
|---|---|
| No module named fastapi | venv의 python으로 실행했는지 |
| Could not import module main | `poc/staging/backend` 작업 폴더 |
| 8000 port in use | 로컬 포트 점유 확인 |
| /api/health 404 | 직접 API는 `/health`, Nginx 경유만 `/api/health` |
| /health/db 503 | Reader 비밀번호/내부망/DB 권한 |
| Browser CORS error | Origin/프록시, 별도 승인된 middleware 필요 |
| /api/v1/ 경로 404 | 설계 문서만 존재, 구현되지 않음 |

**기대 결과:** 오류 기록과 대응 대상 확인. **실패 시:** Secret을 가린 서버 로그만 공유.

## 10. 개발·테스트·PR 제출 절차
### STEP 11 — Git 브랜치·Commit·Push·PR
**목적:** 안전한 리뷰 프로세스.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform"
git switch main
git pull --ff-only origin main
git switch -c feature/REPLACE-REDMINE-ID-backend
# 실제 담당 파일 변경과 테스트 수행
git diff --check
git status --short
git add poc/staging/backend poc/staging/tests
git commit -m "feat(api): implement reviewed feature"
git push -u origin HEAD
~~~

**기대 결과:** GitHub PR(base main) 생성, Redmine Issue, 테스트·Swagger·변경파일·Staging DB 변경 NO·CI 링크 기재. Slack `#ai-career-pr-review` 요청. PM/JM 승인·Squash Merge 이전 main 변경 금지. Redmine 10%→PR 90%→Staging 확인 뒤 100%. **실패 시:** GitHub 권한/보호규칙/CI 로그 확인.

## 11. 최종 완료 체크리스트
- [ ] Git/VS Code/Python 3.12 설치 및 버전
- [ ] main Clone, 정확한 pinned Python 의존성 설치
- [ ] venv·환경변수 Secret 보호 및 로컬 Uvicorn 실행
- [ ] /docs /openapi.json /health /version 검증
- [ ] /health/db PASS 또는 HOLD 및 사유 기록
- [ ] pytest 재현 결과
- [ ] CRUD는 별도 로컬 DB에서만, Staging 변경 없음
- [ ] 계층/API/CORS 설계와 PR/CI/Slack/Redmine 증빙


## 부록 — 정식 Backend 테스트 기준 (현행 main 보완)

기존 STEP 03 및 STEP 09는 **PoC용** 경로입니다. 정식 FastAPI 개발은 `backend/` 디렉터리에서 진행하며, `backend/requirements-dev.txt`에는 pytest/httpx와 실행용 `requirements.txt`가 포함됩니다. 운영 PoC `poc/staging/backend/requirements.txt`의 패키지 버전과 다를 수 있습니다.

```powershell
Set-Location "$HOME\projects\ai-career-platform\backend"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest --collect-only -q
New-Item -ItemType Directory -Force .\test-results | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --junitxml=test-results\pytest-junit.xml
$LASTEXITCODE
```

세부 절차는 [PYTEST_GUIDE.md](../testing/PYTEST_GUIDE.md), [테스트 보고 양식](../testing/TEST_REPORT_TEMPLATE.md)을 따릅니다. 이 명령은 로컬 전용이며 Staging DB에 쓰기 작업을 실행하지 않습니다.
