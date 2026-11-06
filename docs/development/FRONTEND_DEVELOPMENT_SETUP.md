# Frontend 개발자 로컬 개발환경 — Windows 11

> 기준 2026-11-06, main SHA `2338031c2dfdcf14c2a7ddba01800cffba10be41`. Frontend 표준 스택은 **React (Node.js LTS + npm)**입니다(PR #19 리뷰에서 확인). 현재 저장소에서 실행 가능한 화면은 PoC용 **정적 HTML/CSS/Vanilla JavaScript + Nginx**(`poc/staging/frontend`)이며, React 프로젝트 구조(`frontend/`, `package.json`)는 **T19에서 생성**합니다. 전체 기능 30개 및 UI/DB/API 매핑은 **후보 설계**이며 화면/API 구현 완료로 취급하지 않습니다.

## 1. 가이드 목적 및 대상 개발자
프런트엔드 담당자가 Windows PC에서 현행 PoC를 실행하고 DevTools로 Nginx→FastAPI 헬스 API를 검증한 뒤, 미구현 제품 화면을 Mock 데이터로 병렬 개발할 수 있도록 안내합니다.

## 2. 사전 준비사항
Windows 11, GitHub 접근, Git, VS Code, Edge/Chrome, **Node.js LTS(React 개발 필수)**, 선택적으로 Docker Desktop(WSL2 Linux containers; 현행 프록시 통합 실행에 필요). Staging 서버 Ubuntu 26.04의 `/home/kant/ai-career-staging-poc`에는 **이 가이드의 실행 명령을 사용하지 않습니다**. 개인 PC와 Staging은 별개의 환경입니다.

## 3. 개발 도구 설치
### STEP 01 — Git/VS Code/브라우저/Docker
**목적:** 코드 편집 및 로컬 브라우저 검증.

**실행:** 공식 다운로드 https://git-scm.com/download/win · https://code.visualstudio.com/download · https://www.docker.com/products/docker-desktop/ . Edge/Chrome F12로 DevTools를 엽니다. PowerShell:

~~~powershell
git --version
code --version
docker --version
docker compose version
docker info --format '{{.OSType}}'
~~~

**기대 결과:** 버전 출력, Docker linux. **실패 시:** PATH, Docker Desktop 실행, WSL2 확인. Docker가 없는 개발자는 HTML 편집/Mock 설계까지만 진행하고 **현행 Nginx 통합 실행은 HOLD**.

### STEP 01-1 — Node.js LTS 설치 (React 개발 필수)
**목적:** React 개발 서버·빌드·테스트에 필요한 Node.js와 npm 설치.

**버전 정책:** Node.js **LTS(짝수 버전)** 사용. 2026-11 기준 Active LTS는 **26.x**(winget 확인 26.13.0), 24.x는 Maintenance LTS로 동작은 가능하나 신규 설치는 26.x를 권장합니다. 팀 고정 버전은 T19에서 `frontend/.nvmrc` 또는 `package.json`의 `engines`로 확정하며, 확정 후에는 그 버전을 따릅니다. 홀수 버전(Current)은 사용하지 않습니다.

**방법 A — winget (권장, PowerShell):**

~~~powershell
winget show --id OpenJS.NodeJS.LTS --exact      # 설치될 LTS 버전 확인
winget install --id OpenJS.NodeJS.LTS --exact --accept-source-agreements --accept-package-agreements
~~~

이미 설치되어 있으면 `winget upgrade --id OpenJS.NodeJS.LTS --exact`로 갱신합니다.

**방법 B — 공식 설치 파일:** https://nodejs.org/ → **LTS** 탭의 Windows Installer(.msi, x64) 다운로드 → 기본 옵션으로 설치(“Add to PATH” 체크 유지). “Tools for Native Modules”(Chocolatey/빌드 도구) 자동 설치는 **체크하지 않아도 됩니다**.

**설치 후 확인 — 반드시 새 PowerShell 창을 열고 실행:**

~~~powershell
node --version                 # 예: v26.13.0 (LTS 짝수 버전)
npm --version                  # 예: 11.x
(Get-Command node).Source      # C:\Program Files\nodejs\node.exe
npm config get registry        # https://registry.npmjs.org/
npm view react version         # npm 레지스트리 접속 확인(설치 아님)
~~~

**기대 결과:** 버전 출력, registry가 공식 npm, `npm view react version`이 React 최신 버전 번호를 출력.

**실패 시:**
- `node`/`npm` 인식 안 됨 → 설치 후 **열려 있던 터미널·VS Code를 모두 닫고 다시 열기**(PATH 갱신). 그래도 안 되면 `C:\Program Files\nodejs`가 사용자 PATH에 있는지 확인.
- `npm.ps1 파일을 로드할 수 없습니다… 스크립트를 실행할 수 없으므로` → PowerShell 실행 정책 문제. 본인 계정 범위만 변경: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (LocalMachine/관리자 범위 변경 금지). 회사 정책상 변경 불가하면 `npm.cmd --version`처럼 `.cmd`로 실행.
- `npm view` 시간 초과/인증서 오류 → 사내 프록시·방화벽 확인 후 팀에 문의. 임의의 비공식 registry나 `strict-ssl false` 설정 금지.

**React 프로젝트 실행 규칙:** `npm ci`, `npm run dev`, `npm run build`, `npm run lint`, `npm test`는 **`frontend/package.json`이 존재할 때만**(T19 병합 이후) 해당 폴더에서 실행합니다. 의존성 설치는 `package-lock.json`을 기준으로 `npm ci`를 사용하고, 전역 설치(`npm install -g`)로 프로젝트 의존성을 대신하지 않습니다.

## 4. GitHub 프로젝트 내려받기
### STEP 02 — 최신 main Clone
**목적:** 공유 소스 동기화.

~~~powershell
New-Item -ItemType Directory -Force "$HOME\projects" | Out-Null
Set-Location "$HOME\projects"
git clone https://github.com/ai-career-platform/ai-career-platform.git
Set-Location .\ai-career-platform
git switch main
git pull --ff-only origin main
git status --short
Get-ChildItem .\poc\staging\frontend
~~~

**기대 결과:** `index.html`, `nginx.conf`, `Dockerfile`. **실패 시:** GitHub 조직 접근 권한, git remote 확인. 이미 내려받았다면 clone을 중복 실행하지 않고 기존 경로에서 pull.

## 5. 환경 설정
### STEP 03 — 실제 폴더 및 API 경로 확인
**목적:** 존재하지 않는 스택을 가정하지 않음.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform"
Get-Content .\poc\staging\frontend\nginx.conf
Get-Content .\poc\staging\frontend\Dockerfile
Select-String -Path .\poc\staging\frontend\index.html -Pattern 'fetch','getJson','/api/'
~~~

**기대 결과:** JS가 상대경로 `/api/health`, `/api/version`, `/api/health/db` 호출. Nginx의 `proxy_pass http://backend:8000/;`가 `/api/` 접두어를 제거해 Backend `/health` 등으로 전달. PoC에는 `frontend/.env`, Node 패키지, React dev server가 없습니다(React 구조는 T19에서 추가). **실패 시:** 메인 브랜치 및 폴더 확인. 브라우저에서 `file://`로 열면 상대경로 API 프록시가 없으므로 E2E 검증 불가능.

### STEP 04 — 로컬 전용 Compose 환경파일
**목적:** 개인 Docker DB로 Staging과 분리.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging"
Copy-Item .\.env.example .\.env
notepad .\.env
~~~

`POSTGRES_PASSWORD=CHANGE_ME`를 **강력한 개인 로컬 테스트용 비밀번호**로 바꾸고 저장합니다. 실제 Staging의 `ai_career_poc` 관리자 비밀번호를 넣지 않습니다. `POSTGRES_DB`/`POSTGRES_USER`의 PoC 예시는 컨테이너가 **처음 초기화할 때** 적용되며 기존 Named Volume 계정이 변경되지는 않습니다. `.env`는 Git에 포함하지 않습니다. 기존 `ai-career-staging-poc` 이름의 로컬 Docker 프로젝트가 있다면 실행을 중단하고 담당자와 격리를 확인합니다.

**기대 결과:** 로컬 env 파일만 생성. **실패 시:** 저장 권한/경로 확인. 비밀번호 노출 금지.

## 6. 로컬 실행
### STEP 05 — 개인 PC에서 정적 Nginx+FastAPI+Postgres PoC 구동
**목적:** 현행 저장소 설정 재현.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging"
docker compose --env-file .env config --quiet
docker compose --env-file .env up --build -d
docker compose --env-file .env ps
~~~

**기대 결과:** 로컬 `frontend`, `backend`, `db` 모두 healthy. 첫 실행 직후 `frontend`가 20~30초간 `health: starting`으로 보일 수 있으므로 잠시 후 `ps`를 다시 확인합니다. Frontend만 Windows `127.0.0.1:18080:80` 바인딩. Backend `8000`과 PostgreSQL `5432`는 Docker 내부 포트이고 외부 공개하지 않음. DB는 로컬 named volume이며 Staging DB와 무관. `poc/staging/automation/compose.release.yaml`은 GHCR Digest 기반 **배포 전용 overlay**라서 로컬 개발에 적용하지 않음.

**실패 시:** Docker Desktop, `docker compose --env-file .env ps`, `Get-NetTCPConnection -LocalPort 18080` 확인. 다른 Docker 프로젝트·컨테이너·볼륨 삭제 금지. `docker compose down -v` 금지.

### STEP 06 — 브라우저 UI와 DevTools
**목적:** 화면 렌더링 및 Network 검증.

~~~powershell
Start-Process http://127.0.0.1:18080/
Invoke-RestMethod http://127.0.0.1:18080/api/health
Invoke-RestMethod http://127.0.0.1:18080/api/version
Invoke-RestMethod http://127.0.0.1:18080/api/health/db
~~~

브라우저 F12 → Network → 새로고침 → 3개의 API 요청/HTTP 상태/응답 JSON을 확인하고 Console 오류를 기록합니다. **기대 결과:** `Backend connection: Connected`, `PoC status: Operational` (API 3개가 모두 정상일 때). **실패 시:** `Unavailable/Degraded`라면 Network에서 502/503을 구별하고 필요한 경우 **자기 로컬 Compose 프로젝트** 로그만 확인. Staging 로그/비밀번호를 공유하지 않음.

**예외(거부) 케이스 재현 — 개인 로컬 Compose 프로젝트에서만:**

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging"
# 1) 미구현 기능 API → 404가 정상
try { Invoke-WebRequest http://127.0.0.1:18080/api/v1/jobs -UseBasicParsing } catch { $_.Exception.Response.StatusCode.value__ }
# 2) 로컬 DB만 일시 중지 → /api/health/db 503, 화면 PoC status: Degraded
docker compose --env-file .env stop db
try { Invoke-WebRequest http://127.0.0.1:18080/api/health/db -UseBasicParsing } catch { $_.Exception.Response.StatusCode.value__ }
# 3) 복구
docker compose --env-file .env start db
~~~

DB 중지 상태에서는 Backend의 DB 연결 타임아웃(`connect_timeout=3`) 때문에 화면이 수 초간 `Checking...`으로 표시된 뒤 `Degraded`로 바뀝니다. DB 재시작 후 healthy가 될 때까지 10~15초 기다린 뒤 다시 확인합니다.

## 7. 공용 Staging 시스템 연동
### STEP 07 — API Base URL·CORS·프록시
**목적:** 브라우저가 Backend를 찾아가는 실제 경로 이해.

**실행:** 현행 같은 Origin에서 `/api/health`를 사용합니다. Nginx 규칙:

~~~nginx
location /api/ {
    proxy_pass http://backend:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
~~~

Windows 브라우저의 `127.0.0.1`은 자신의 PC이며 **Ubuntu의** `127.0.0.1:18080`과 같지 않습니다. 승인된 HTTPS 도메인/내부망 HTTP 엔드포인트가 없으면 개발 PC에서 Staging UI에 직접 접속할 수 있다고 가정하지 않습니다. Frontend에서 DB 자격증명을 사용하지 않으며 Backend API로만 접근합니다.

**기대 결과:** 같은 Origin Proxy 경로의 API 사용. **실패 시:** 서로 다른 Origin·포트에서 직접 fetch할 때 CORS 문제가 있을 수 있으나 현재 FastAPI에 CORSMiddleware 없음. 허용 Origin과 안전한 Proxy는 Backend 개발자와 합의해 별도 PR로 구현. CORS는 인증/인가 대체 아님.

### STEP 08 — 미완성 API에 Mock 연결
**목적:** Backend 미완성 상태에서 UI 병렬 개발.

**실행:** [기능 F-001~F-030/화면 후보](../FULL_SCOPE_TRACEABILITY.md)에서 담당 ID를 선택하고 [API 계약 초안](../API_CONTRACT.md)의 Request/Response, 상태코드, 권한을 대조합니다. 고정 **가상 데이터** JSON을 별도 JS 모듈 또는 테스트 fixture(추가 구조는 PR 승인 후)로 작성합니다. 성공·로딩·빈 데이터·오류(401/403/404/500) 상태를 모두 시연하고 실제 API로 교체할 시점을 기록합니다. `/api/v1/*`는 아직 구현되지 않았으므로 404가 정상; Mock 성공을 실제 서비스 PASS로 표시하지 않습니다.

**기대 결과:** 화면 디자인/흐름 테스트 가능, E2E는 HOLD. **실패 시:** API 스키마 확정 전 임의 엔드포인트를 실서비스라고 주장하지 않음.

## 8. 테스트 및 정상 결과 확인
### STEP 09 — UI·빌드·Lint·테스트
**목적:** 있는 도구만 사용해 증빙 수집.

**실행:** DevTools Console/Network, 모바일 반응형, 키보드 접근성/label, 성공/빈/실패 UI를 확인. `git diff --check`로 공백 오류 검사. React 프로젝트(`frontend/package.json`)가 생성되기 전(T19 병합 전)에는 `npm ci`, `npm run build`, `npm run lint`, `npm test`를 실행할 대상이 없으므로 **미구현**으로 기록합니다. T19 병합 후에는 `frontend/` 폴더에서 `npm ci` → `npm run lint` → `npm test` → `npm run build` 순으로 실행해 증빙을 남깁니다. 번들러·Lint·테스트 도구의 구체적 선택은 T19 PR에서 확정하고 이 가이드를 갱신합니다.

**기대 결과:** 화면 캡처·Network·Console 및 수동 검증 기록. **실패 시:** 실제 검증하지 않은 항목은 HOLD 표시.

### STEP 10 — HTML 변경 Preview
**목적:** 로컬 UI 변경 검증.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging"
# 본인 PC의 index.html을 수정한 다음 실행:
docker compose --env-file .env up --build -d frontend
Start-Process http://127.0.0.1:18080/
git diff --check
git status --short
~~~

**기대 결과:** 새 HTML 로컬 Preview 및 3개 API 상태 재확인. **실패 시:** Ctrl+F5, 캐시/빌드, compose ps 확인. Compose 의존 서비스 확인이 수반될 수 있으므로 **개인 PC에서만** 실행.

## 9. 자주 발생하는 오류 해결
### STEP 11 — 오류별 확인
**목적:** 진단 범위 명확화.

| 오류 | 해결 |
|---|---|
| `node`/`npm` 인식 안 됨 | 설치 후 터미널·VS Code 재시작, PATH의 `C:\Program Files\nodejs` 확인 (STEP 01-1) |
| `npm.ps1` 실행 정책 오류 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 또는 `npm.cmd` 사용 (STEP 01-1) |
| package.json not found | 저장소 루트·`poc/`에서 실행했거나 T19 병합 전. `frontend/` 폴더에서 실행 |
| Node 버전 불일치 경고(`EBADENGINE`) | `node --version` 확인 후 팀 고정 LTS 버전으로 `winget upgrade` |
| 18080 already in use | 로컬 점유 확인, 기존 프로세스/컨테이너 임의 종료 금지 |
| Nginx /api/ 502 | Docker Backend healthy/컨테이너 네트워크 |
| DB health 503, 화면 Degraded | 로컬 PostgreSQL healthy와 env 확인 |
| CORS error | 다른 Origin 직접 호출 여부, Proxy 또는 별도 승인 middleware |
| file:// fetch 실패 | Nginx 서버 URL에서 테스트 |
| /api/v1 404 | 기능 API가 설계 후보일 뿐 미구현 |
| 화면 갱신 안 됨 | 재빌드/브라우저 캐시 확인 |

**기대 결과:** 원인 분류. **실패 시:** URL/Network 오류와 설정 값을 민감정보 제외 후 팀에 공유.

### STEP 11-1 — 로컬 PoC 중지
**목적:** 작업 종료 시 자기 로컬 컨테이너만 정리.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform\poc\staging"
docker compose --env-file .env stop      # 컨테이너 중지(데이터 유지), 재개는 start
docker compose --env-file .env down      # 컨테이너/네트워크 제거, 볼륨은 유지
~~~

**주의:** `-v` 옵션(볼륨 삭제)과 글로벌 `docker system prune`은 사용하지 않습니다. 다른 Docker 프로젝트에는 영향을 주지 않도록 반드시 `poc/staging` 폴더에서 실행합니다.

## 10. 개발·테스트·PR 제출 절차
### STEP 12 — Git 브랜치·Commit·PR
**목적:** 승인 후 제품에 반영.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform"
git switch main
git pull --ff-only origin main
git switch -c task/t##-short-name   # 작업지시서 규칙, 예: task/t20-common-layout
# index.html 등 담당 파일 수정 및 검증
git status --short
git diff --check
git add poc/staging/frontend
git commit -m "feat(ui): implement reviewed change"
git push -u origin HEAD
~~~

GitHub Pull requests → New pull request: base `main`, compare 본인 브랜치. Redmine ID, Mock 여부, 화면/모바일/Network 테스트 캡처, 변경 파일, Backend API 연동 상태, CI 결과를 작성. Slack `#ai-career-pr-review`에서 PM/JM 리뷰 요청, 승인·Squash Merge 전 main 직접 병합 금지. Redmine 10%→PR/테스트 90%→승인·Staging 검증 뒤 100%.

**기대 결과:** PR 리뷰 대기. **실패 시:** Git 권한·브랜치 보호·CI 로그 확인.

## 11. 최종 완료 체크리스트
- [ ] Git/VS Code/브라우저/Docker 설치(통합 실습 시)
- [ ] 최신 main Clone, 정적 HTML+Nginx 구조 이해
- [ ] Node.js LTS 설치, `node --version`·`npm --version`·`npm view react version` 확인
- [ ] 표준 스택은 React, 현행 PoC 화면은 정적 HTML임을 구분 (React 구조는 T19)
- [ ] 로컬 전용 .env 비밀번호 준비/비공개
- [ ] 로컬 18080 화면 및 3개 API/DevTools 결과
- [ ] CORS/Proxy/API 경로 이해
- [ ] Mock과 실제 Backend API 상태 명확히 구별
- [ ] 빌드/Lint 미구현 사실 기록
- [ ] 화면 캡처·PR·CI·Slack·Redmine, Staging 변경 NO
