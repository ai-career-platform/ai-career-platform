# DB 개발자 로컬 개발환경 가이드

> 2026-11-06. 확인된 main SHA: 2338031c2dfdcf14c2a7ddba01800cffba10be41. Windows PC 실행은 개발자별 직접 검증 필요. 30개 기능, 46개 DB 후보는 DRAFT이며 Staging 미구현. Staging DDL/DML/Seed/초기화·Docker 변경 및 관리자 비밀번호 공개 금지.
>
> 참고: [온보딩](../ONBOARDING.md), [DB 규정](../DATABASE.md), [아키텍처](../ARCHITECTURE.md), [전체 기능](../FULL_SCOPE_TRACEABILITY.md), [API 초안](../API_CONTRACT.md), [DB 모델](../../database/FULL_DATABASE_MODEL.md), [PR 규정](../CONTRIBUTING.md).


## 1. 가이드 목적 및 대상 개발자
Windows 11 DBeaver로 공유 Staging을 **읽기 전용** 조사하고, 별도 로컬 PostgreSQL 18.1로 ERD/DDL/Migration을 검증합니다. `career_reader`의 실제 읽기/쓰기 차단 권한은 검증 대기(HOLD).

## 2. 사전 준비사항
GitHub 접근 권한, 내부망, Windows 11, DBeaver, VS Code, Git, Docker Desktop(WSL2 Linux containers), Staging 조회 계정 비밀번호(비공개 전달). 내부망 10.2.10.104:15432 직접 연결이며 SSH tunnel 미사용. 암호화/접근제한은 최종 점검 전까지 HOLD.

## 3. 개발 도구 설치
### STEP 01 — Git, VS Code, DBeaver, Docker Desktop 설치
**목적:** 개발도구 구비. **실행:** https://git-scm.com/download/win, https://code.visualstudio.com/download, https://dbeaver.io/download/, https://www.docker.com/products/docker-desktop/ 에서 Windows용 설치. Docker Desktop의 WSL2 Linux mode 활성화.

~~~powershell
git --version
code --version
docker --version
docker compose version
docker info --format '{{.OSType}}'
~~~

**기대 결과:** 버전 출력, OSType linux, DBeaver 실행. **실패 시:** PATH, 터미널 재시작, WSL2 활성화, Docker daemon 확인.

## 4. GitHub 프로젝트 내려받기
### STEP 02 — main Clone 및 동기화
**목적:** 최신 설계 자료 조회. **실행:**

~~~powershell
New-Item -ItemType Directory -Force "$HOME\projects" | Out-Null
Set-Location "$HOME\projects"
git clone https://github.com/ai-career-platform/ai-career-platform.git
Set-Location .\ai-career-platform
git switch main
git pull --ff-only origin main
git status --short
~~~

**기대 결과:** main 최신 파일 목록, 작업 트리 깨끗함. **실패 시:** GitHub 조직 권한·`git --version`·`git remote -v` 확인. 이미 Clone한 경우 중복 Clone 대신 기존 폴더에서 pull.

## 5. 환경 설정
### STEP 03 — Staging DBeaver 연결
**목적:** 변경 없는 구조 조회. **실행:** DBeaver → Database → New Connection → PostgreSQL; Host `10.2.10.104`, Port `15432`, Database `ai_career_poc`, Username `career_reader`, Password는 별도 비공개 수령. SSH Tunnel 끔; TLS/SSL mode는 관리자에게 정책·인증서 확인 (강제 disable 금지). 연결 이름 `STAGING - READ ONLY` 설정. Test Connection.

~~~powershell
Test-NetConnection 10.2.10.104 -Port 15432
~~~

**기대 결과:** 연결 성공 시 SQL Editor 사용 가능. TCP 성공 ≠ DB 인증/권한/TLS 검증. **실패 시:** 방화벽/내부망, 인증값, pg_hba, TLS 정책 담당자 문의.

### STEP 04 — 스키마·테이블·뷰 조회
**목적:** 실제 구조 및 계정 속성 확인. **실행:** DBeaver → SQL Editor; 다음 SELECT만 실행:

~~~sql
SELECT current_database(), current_user, version();
SELECT schema_name FROM information_schema.schemata
 WHERE schema_name NOT IN ('pg_catalog','information_schema');
SELECT table_schema,table_name,table_type FROM information_schema.tables
 WHERE table_schema NOT IN ('pg_catalog','information_schema')
 ORDER BY table_schema,table_name;
SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolcanlogin
 FROM pg_roles WHERE rolname=current_user;
SELECT has_schema_privilege(current_user,'public','CREATE') AS public_can_create;
~~~

DBeaver Navigator → Schemas → public → Tables/Views 확인. **기대 결과:** 기존 조사상 `public`만 있고 사용자 테이블 0개; `career`는 아직 설계 후보. **실패 시:** permission denied/테이블 부재는 실제 권한·미구축 가능성으로 보고, 직접 GRANT/CREATE 금지.

## 6. 로컬 실행
### STEP 05 — PC에서 격리 PostgreSQL 18.1 실행
**목적:** Staging 보호하며 개인 SQL 테스트. **실행 (Windows PowerShell, Ubuntu 서버에서 실행 금지):**

~~~powershell
docker ps -a --format "table {{.Names}}\t{{.Ports}}"
# career-dev-db가 이미 있다면 여기서 중단하고 기존 상태를 확인합니다.
$LocalSecret = Read-Host "LOCAL DB password" -AsSecureString
$Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($LocalSecret)
try { $Plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) } finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }
docker run -d --name career-dev-db -p 127.0.0.1:25432:5432 -e POSTGRES_DB=career_dev -e POSTGRES_USER=dev_local -e "POSTGRES_PASSWORD=$Plain" postgres:18.1
Remove-Variable Plain,LocalSecret,Ptr
docker exec career-dev-db pg_isready -U dev_local -d career_dev
~~~

DBeaver의 별도 연결: `LOCAL - career_dev` / `127.0.0.1:25432` / `career_dev` / `dev_local`. **기대 결과:** accepting connections. **실패 시:** Docker Desktop/WSL2/포트 점유 확인 (`Get-NetTCPConnection -LocalPort 25432`). 컨테이너/볼륨 무단 삭제 금지.

### STEP 06 — 로컬 DRAFT Migration 테스트
**목적:** ERD/DDL 초안 재현. **실행 (개인 PC만):**

~~~powershell
Set-Location "$HOME\projects\ai-career-platform"
Get-Content .\database\security\DRAFT_00_create_roles_schema.sql -Raw | docker exec -i career-dev-db psql -X -v ON_ERROR_STOP=1 -U dev_local -d career_dev
Get-Content .\database\migrations\DRAFT_0001_initial_schema.sql -Raw | docker exec -i career-dev-db psql -X -v ON_ERROR_STOP=1 -U dev_local -d career_dev
docker exec career-dev-db psql -X -U dev_local -d career_dev -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='career';"
~~~

**기대 결과:** 개인 DB에 기술 검증용 10개 초안 테이블. 전체 모델 46개가 생성되는 것은 아님. **실패 시:** DRAFT의 역할/스키마 선행조건, 이미 실행된 비멱등 SQL 확인. 새 **격리 DB**에서 다시 시험; Staging 사용 금지. ERD/SQL 근거는 [DB 10개 초안](../../database/README.md) 및 [DB 전체 후보](../../database/FULL_DATABASE_MODEL.md) 참조.

## 7. 공용 Staging 시스템 연동
### STEP 07 — Staging 조회/변경 승인 분리
**목적:** 실수 방지. **실행:** DBeaver Staging·Local 연결 색상 구분, SQL 탭 호스트 재확인. Staging은 STEP 04의 SELECT만. DDL 변경: Redmine 요청→ERD·Migration·영향·복구안→PM/JM 승인→백업/복원 검증→지정 실행자 작업→결과 기록. **기대 결과:** Staging 변경 0. **실패 시:** 연결 불분명하면 즉시 SQL 실행 중지.

## 8. 테스트 및 정상 결과 확인
### STEP 08 — Evidence 기록
**목적:** 재현 가능한 검증 보고. **실행:** psql 버전, 테이블 개수, SELECT 결과, 실패 SQL/권한 결과, Redmine ID 기록. `database/tests/`와 `.github/workflows/d1-postgres-sql-test.yml`는 격리 테스트 자료. **기대 결과:** 개인 실행 로그 기반 PASS/HOLD 판단. **실패 시:** 실제 계정 SELECT 및 쓰기거부, TLS 검증되지 않으면 HOLD.

## 9. 자주 발생하는 오류 해결
### STEP 09 — 오류 분류
**목적:** 연결·권한·DDL 구분. **실행:** Connection refused→IP/방화벽; password authentication failed→reader 인증; permission denied→GRANT 정책; relation missing→Staging 미구축; SSL error→인증서; duplicate table→로컬 중복 실행. **기대 결과:** 원인과 조치 대상 특정. **실패 시:** 관리자에게 민감정보 제외 로그 공유.

## 10. 개발·테스트·PR 제출 절차
### STEP 10 — 브랜치·Commit·PR
**목적:** 리뷰 가능한 변경 제출. **실행:** 아래 절차에서 실제 변경 파일을 `database/...`로 지정.

~~~powershell
Set-Location "$HOME\projects\ai-career-platform"
git switch main
git pull --ff-only origin main
git switch -c feature/REPLACE-REDMINE-ID-description
# 담당 파일 수정 및 테스트 완료 후
git diff --check
git status --short
git add docs/development
git commit -m "docs: add reviewed change"
git push -u origin HEAD
~~~

**기대 결과:** GitHub Pull requests → New pull request → base `main`, compare 개인 브랜치. 실제 변경 경로로 `git add` 대상을 교체합니다. PR 본문에 Redmine ID, 작업·변경 파일, 테스트 결과(성공/실패/경계), Swagger/UI/SQL 증빙, DB 변경 여부, 복구안과 CI 링크 기록. Slack `#ai-career-pr-review` 요청; PM/JM만 승인 후 Squash Merge. **실패 시:** 권한/CI 오류 점검. Redmine 10%→PR 90%→승인 및 Staging 확인 후 100%; main 직접 Merge 금지.

## 11. 최종 완료 체크리스트
- [ ] Git/VS Code/DBeaver/Docker 설치·버전
- [ ] main Clone, ERD/전체 후보 설계 확인
- [ ] Staging read-only 연결과 별도 권한 검증(HOLD 가능)
- [ ] Schema/Table/View SELECT 결과
- [ ] 개인 PostgreSQL 18.1 / DRAFT 테스트
- [ ] 비밀번호 미공개, Staging 변경 NO
- [ ] PR/CI/Redmine/Slack 기록, main 미병합
