# Ubuntu Staging 운영 Runbook

> 2026-11-05 수동 PoC 검증 기록 기반. 변경 전 현재 상태를 재점검하세요.

## 환경
- SSH: `kant@10.2.10.104` (사설 IP, 외부 Actions Runner가 직접 접근할 수 없음)
- OS: Ubuntu 26.04.1 LTS
- 배포 경로: `/home/kant/ai-career-staging-poc`
- Compose 프로젝트: `ai-career-staging-poc`
- Frontend 호스트 바인딩: `127.0.0.1:18080:80`
- Backend: Docker 내부 `8000/tcp`; DB: 내부 `5432/tcp`.
- PoC는 `frontend`, `backend`, `db`로 구성; DB Named Volume `ai-career-staging-poc_postgres_data`.

## 2026-11-05 ~ 2026-11-06 검증 증빙
- `docker compose config --quiet` → PASS.
- Backend/Frontend 이미지 빌드 PASS.
- `docker compose ps db` → healthy.
- `docker compose ps backend` → healthy.
- Backend `/health/db` → HTTP 200; Nginx `/api/health/db` → HTTP 200.
- Frontend `http://127.0.0.1:18080/` → HTTP 200, text/html.
- 브라우저 렌더링 및 ngrok 외부 HTTPS는 아직 검증되지 않았음.
- 당시 다른 운영 컨테이너 18개가 존재했으며 현재 수량은 변할 수 있습니다. 프로젝트 외 리소스 보호가 우선입니다.
- 2026-11-06 PR #4 자동 배포 후 Frontend/Backend/DB Healthy, `/api/version` = `b1ce5e671bac271bc16a0692ab70d88a754c939c`. DB Container ID와 Named Volume 보존 확인.
- 2026-11-06 DB 초기화 전 백업 아카이브 검증 및 일회용 PostgreSQL 독립 복원 PASS. 사용자 정의 테이블 0개 확인; 실제 DB DDL/Seed 미적용.

## 읽기 전용 확인 명령

### 크롤러 이미지 통합 및 승인 경계

게시 워크플로는 저장소 루트에서 `poc/staging/backend/Dockerfile.integrated`를 빌드해
기존 backend 이미지에 `crawler/`와 채용공고 조회 앱을 포함합니다. 원래 PoC
Dockerfile과 기준 `compose.yaml`, 배포 timer는 유지합니다. 홈페이지의 공고 링크는
`/api/training`, 조회 API는 `/api/jobs/collected`입니다. 수집은 HTTP 요청 처리와
분리된 `python -m crawler.jobs.import_jobkorea_html --list-url URL --limit 5`입니다.

서버 변경 전 PM/DB 담당 승인 대상:

1. 기존 PostgreSQL 컨테이너에 별도 DB `ai_career_crawler_training`과 최소 권한
   LOGIN 역할 `crawler_staging` 생성. 기존 앱 DB/스키마/데이터는 수정하지 않습니다.
2. 승인된 별도 DB에만 `crawler_training.postings` 생성(기존 저장소 SQL 계약 재사용).
   계정은 SUPERUSER/CREATEDB/CREATEROLE 권한을 갖지 않습니다.
3. 서버의 release overlay에 새 환경변수 두 개를 추가하고 private `.env`에
   `CRAWLER_DB_MODE=staging`, `CRAWLER_STAGING_DATABASE_URL`을 설정합니다.
   URL은 전용 역할·위 DB·Docker 호스트 `db:5432`만 허용합니다. 비밀번호는
   비공개 전달하며 Compose config/inspect 환경변수를 공개 출력하지 않습니다.
4. 정상 main 리뷰·병합 → 기존 Auto-CD 게시/배포 후, 해당 backend 컨테이너에서
   수동 최대 5건 수집·재실행·API·화면 QA. DB 컨테이너/볼륨 및 다른 프로젝트
   컨테이너 ID를 전후 비교합니다. 승인 전에는 DB DDL/DML이나 서버 설정을 적용하지 않습니다.

자동 배포는 서버 overlay 자체를 동기화하지 않으므로 3번은 승인된 일회성 설정
작업입니다. 설정이 없으면 기존 Health 서비스는 유지되고 공고 조회는 503을 반환합니다.
스테이징 수동 E2E가 통과하기 전에는 T64 스케줄러 구현·활성화로 넘어가지 않습니다.
T64의 기존 DB schedule/run/event 계약을 재사용하는 별도 단계이며 단순 timer를
병렬로 추가하거나 기존 배포 timer를 교체하지 않습니다.

```bash
cd /home/kant/ai-career-staging-poc
docker compose ps
docker compose config --quiet
curl -fsS --max-time 10 http://127.0.0.1:18080/api/health
curl -fsS --max-time 10 http://127.0.0.1:18080/api/version
curl -fsS --max-time 10 http://127.0.0.1:18080/api/health/db
df -h /
free -h
```

## React 앱 배포 (F-02, S8 방안 A)

- `frontend` 이미지는 `poc/staging/frontend/Dockerfile.integrated` 로 빌드합니다. 게시 워크플로가 `build-contexts: app=./frontend` 로 React 앱을 넣습니다.
  - 컨테이너·서비스 이름·포트(`127.0.0.1:18080`)·`compose.yaml`·`compose.release.yaml`·`deploy.py`·`publish.py` 는 바뀌지 않습니다.
  - Backend·DB·크롤러 이미지와 설정도 바뀌지 않습니다.
- `/` 는 React 앱입니다. 기존 PoC 상태 페이지는 `/staging-status.html` 로 옮겼습니다(`/status.js`·`/status.css` 그대로). React 의 `/system-status` 화면도 Backend·DB Health 와 버전을 보여 줍니다.
- 화면 경로(`/login`, `/job-postings` …)는 nginx 가 `index.html` 로 돌려줍니다. `/api/`·`/api/v1/` 은 기존 프록시 그대로이고, `/assets/` 의 없는 파일은 404 입니다.
- 이미지 빌드 단계에서 `npm run lint && npm test && npm run build` 가 실패하면 게시가 멈춥니다(게시 게이트가 Frontend CI 를 보지 않으므로).
- Mock·승인 전 화면 플래그는 빌드 시 모두 꺼짐입니다. Mock 전용 화면은 Staging 에 나타나지 않습니다.
- **로그인 유지 제약**: refresh 쿠키는 `Secure` 입니다(`AUTH_COOKIE_SECURE=false` 금지). HTTP 로 접속하면 새로고침 시 로그아웃됩니다. 브라우저 QA 는 HTTPS 또는 `http://127.0.0.1:18080`(SSH 터널)로 합니다.
- **되돌리기**: `docs/release/RELEASE_RUNBOOK.md` §3 을 따릅니다.
  - 기본: 이 변경을 revert 한 PR 을 병합해 앞으로 배포합니다.
  - 긴급: PM 승인 후 `previous.json` 의 **frontend digest 만** 지정해 `up -d --no-build --no-deps frontend` 로 되돌립니다. backend·db 는 손대지 않습니다.

## 운영 보호 조건
- 현재 호스트에는 **다른 운영 컨테이너 18개**가 있어 프로젝트명·네트워크·볼륨·포트를 반드시 구분.
- `.env`는 Git 미추적, 소유자 권한 600 유지. 공개 채팅/로그로 비밀번호 출력 금지.
- `docker compose down -v`, 전역 `docker system prune`, DB 볼륨 삭제, 기존 ngrok 변경 금지.
- CPU/메모리/디스크를 배포 전후 점검하고 컨테이너 재시작 급증 시 배포 중단.
- Staging DB는 초기화하지 않고 공통 Seed/샘플 데이터 보존.
- 문제 발생 시 변경한 **PoC 서비스만** 범위를 특정하여 조치하고 운영 서비스는 변경하지 않음.

## 수동 배포와 복구
- 수동 배포와 자동 배포 E2E 검증 완료(2026-11-06). 현재 배포 SHA는 `/api/version`, systemd journal 및 GitHub Actions에서 다시 확인.
- 자동 배포 기준은 CI 성공·이미지 Digest·허용 승인자·헬스체크. DB Migration은 별도 승인 절차로 실행.
- 장애 시 먼저 `docker compose ps`, 로그에서 비밀정보 배제한 상태로 확인. 승인 없는 광범위 정리/다운 금지.
- ngrok 외부 공개는 별도 검토; Pull형 CD에는 ngrok 불필요.

## main 자동 배포 후 기능 검증 및 일감 종료

개발 PR의 Merge SHA가 게시/Ubuntu Pull을 거쳐 **실제 이 서버에서 배포됐는지** 증명해야 합니다. 자동 배포 타이머 활성화와 CI SUCCESS만으로 완료 처리하지 않습니다. GitHub `staging-publish.yml` 실행/배포 신호 → `ai-career-staging-deploy.timer`·service 실제 반영 → 배포 Manifest/이미지 Digest → `/api/version`/실행 SHA → 해당 기능의 Staging API·DB·Frontend 확인 순서입니다. 현재 PoC 컨테이너가 일반 Health API 위주이므로 **별도 crawler/training 앱은 별도 확인 전 배포된 기능으로 간주 금지**. Redmine은 실제 기능 QA 증빙 확인 후 PM/JM만 100%/Closed. 미반영·미실행·실패는 HOLD. 공용 DB 변경은 별도 승인, 기존 볼륨/컨테이너 보호. [공통 종료 게이트](WORK_ITEM_CLOSURE_GATE.md)를 적용합니다.
