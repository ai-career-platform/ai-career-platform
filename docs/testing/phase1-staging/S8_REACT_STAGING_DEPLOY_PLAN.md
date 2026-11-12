# S8/10 — Staging React 통합 배포 사전 검토 (F-02)

> 작성: 2026-11-12, 기준 main `c7dc2e19e4ecd0ad6d9591d6fdc329f3a81ff7ce` (Staging 실행 SHA 와 같음)
> - 이 문서는 **설계 검토만** 담고 있습니다. Staging 배포, DB 변경, Auto-CD·Compose·Nginx·워크플로 변경은 **하나도 실행하지 않았습니다.**
> - 앞 단계 결과([중간 보고서](STAGING_TEST_INTERIM_REPORT.md), [매트릭스](STAGING_IMPLEMENTED_FEATURE_MATRIX.md))를 그대로 씁니다.
> - 로컬에서 확인한 것은 React 프로덕션 빌드 산출물 점검 한 가지입니다(§1.3).

## 0. 결론 (추천안)

**추천: 기존 `frontend` 이미지 하나 안에 React 빌드 결과를 넣고, 상태 페이지는 다른 경로로 옮겨 유지합니다.**

1. 컨테이너·Compose 서비스·포트·이미지 이름·배포 스크립트는 **그대로** 둡니다.
2. 바뀌는 것은 `frontend` 이미지의 **내용**뿐입니다.
3. `/` 에서 React 앱을 제공합니다. 기존 상태 페이지는 `/staging-status.html` 로 옮겨 계속 제공합니다.
4. Backend·DB·크롤러·`deploy.py`·`publish.py`·`compose*.yaml`·서버 `.env` 는 변경하지 않습니다.
5. 새 인프라(새 컨테이너, 새 포트, 새 도메인, CDN)는 도입하지 않습니다.

## 1. 현황 분석

### 1.1 `poc/staging/frontend` 와 `frontend/` 비교

| 항목 | `poc/staging/frontend` (현재 Staging) | `frontend/` (React 앱) |
|---|---|---|
| 내용 | 정적 상태 페이지 1장: `index.html`·`status.js`·`status.css`. Backend 연결·버전 표시, `/api/training` 링크 | React 19 + react-router 8 SPA, Vite 8 빌드. 화면 27개 일감 |
| 빌드 | 없음. nginx 이미지에 파일 3개를 복사 | `npm ci` → `tsc -b && vite build` → `dist/`. Node 24(`.nvmrc` 24, `engines >=24`) |
| 경로 | `/` 하나 | 루트 기준 경로 약 30개(`/login`, `/job-postings`, `/me/skills` …). **`basename` 없음** |
| API 호출 | `fetch('/api/health')` 등 | `VITE_API_BASE_URL=/api` + `/v1/...` → **같은 Origin `/api/v1/...`**, `credentials: same-origin` |
| 인증 | 없음 | access token 은 메모리에 둡니다. refresh 는 HttpOnly 쿠키(`Path=/api/v1/auth`, `SameSite=Strict`, **`Secure`**). GET 이 아닌 요청에는 `X-CSRF-TOKEN` 을 붙입니다 |
| 기능 플래그 | — | `VITE_*` 를 **빌드할 때** 정합니다. Mock 전용 화면 10개는 `VITE_API_MOCK=true` 일 때만 켜집니다 |
| 게시 | `staging-publish.yml` 의 `context: ./poc/staging/frontend` | **게시 대상 아님 (F-02 원인)** |
| CI | `crawler-mvp.yml` 이 이미지를 빌드하고 `docker_route_smoke.py` 실행 | `frontend-ci.yml`(lint·tsc·test·build). **게시 게이트와 연결되어 있지 않음** |

### 1.2 Backend `/api/v1/*` 와 PostgreSQL 구조 (변경 없음)
- **Nginx**
  - `location /api/v1/` → `backend:8000` 으로 보냅니다. prefix 는 그대로 두고, `Authorization` 헤더를 전달합니다.
  - `location /api/` → `backend:8000/` 로 보냅니다. `/api` 를 떼고 PoC Health·크롤러 경로로 갑니다.
  - React 의 `/api/v1/...` 호출은 **지금 설정 그대로** Backend 서비스 API 에 닿습니다. `/api/health` 처럼 `/api` 를 떼는 PoC 경로도 기존 규칙으로 처리됩니다.
- **Backend**: `Dockerfile.integrated` 의 `main.py` 가 `create_app()`(T13~)과 크롤러 조회 앱을 함께 띄웁니다. DB 는 private `.env` 의 `POSTGRES_*` 로 내부 `db:5432` 에 붙습니다. S3 에서 `/health/db` 와 카탈로그 조회가 PASS 였습니다.
- **같은 Origin 입니다.** 브라우저 → nginx(:80, 호스트 18080) → backend 경로이므로 CORS 가 필요 없습니다.
  - Backend 에는 CORS 미들웨어가 없고, `csrf.py` 는 "외부 Origin 허용 CORS 추가 금지"를 요구합니다.
  - 이 설계는 CORS 를 추가하지 않습니다.

### 1.3 로컬 빌드 점검 (2026-11-12, `vite build --mode production`, `VITE_API_MOCK=false`)

| 점검 | 결과 | 의미 |
|---|---|---|
| 산출물 | `index.html`, `assets/index-*.js`(623 KB, gzip 187 KB), `assets/index-*.css` | 상태 페이지 파일(`status.js`·`status.css`)과 이름이 겹치지 않음 |
| 인라인 `<script>`·`<style>` | 0 | **현재 CSP(`script-src 'self'; style-src 'self'`)를 그대로 써도 동작** |
| 외부 Origin 호출 | 없음(번들 안의 URL 은 문서 링크·합성 예시 값뿐) | `connect-src 'self'` 유지 가능 |
| Mock 데이터 | 합성 Mock 모듈 문자열이 번들에 포함됨(실행은 빌드 플래그로 꺼짐, 비밀값 없음) | 위험 낮음(§4 R6) |
| 실행하지 못한 것 | 로컬에 Docker 가 없어 이미지 조립·`nginx -t` 는 못 함 | 구현 PR 의 `crawler-mvp.yml` smoke 에서 확인(§3) |

### 1.4 배포 자동화 제약 (`poc/staging/automation`)
- `deploy.py` 가 하는 일
  - `release.json` 의 **frontend·backend digest** 두 개만 `compose.release.yaml` overlay 로 교체합니다(`up -d --no-build --no-deps frontend backend`).
  - 서버의 `compose.yaml`·`.env` 해시가 바뀌면 `PROTECTED_FILE_CHANGED`, 기준 해시와 다르면 `COMPOSE_BASELINE_MISMATCH` 로 멈춥니다.
- 배포 후 Health 확인
  - `/`, `/api/health`, `/api/version`, `/api/health/db` 가 **리다이렉트 없이 200** 이어야 합니다.
  - `version` 은 새 SHA 와 같아야 합니다.
  - 컨테이너가 healthy 여야 하고, DB 컨테이너 ID 는 바뀌지 않아야 합니다.
- **자동 롤백은 없습니다.** 실패하면 `hold.json` 을 남기고 멈춥니다. 이전 SHA 로 되돌리는 배포는 `NON_FORWARD_DEPLOYMENT` 로 거부됩니다.
- 게시 게이트(`publish.py`): `ci.yml` 의 `CI Smoke Test` 성공과 승인된 병합자만 확인합니다. **Frontend CI 는 확인하지 않습니다.**

→ frontend 이미지 **내용만** 바꾸면 `deploy.py`·`publish.py`·서버 Compose·overlay 를 **건드리지 않고** 기존 Auto-CD 로 배포할 수 있습니다.

## 2. 검토한 방안

| 방안 | 내용 | 변경량 | 판단 |
|---|---|---|---|
| **A. 같은 이미지, React 를 `/` 에** (추천) | frontend 이미지를 다단계 빌드로 바꿈(React 빌드 + nginx). 상태 페이지는 `/staging-status.html` 로 이동 | 이미지·nginx·워크플로 2개·smoke | 서버·Compose·배포 스크립트 무변경. React 코드 무변경 |
| B. 같은 이미지, React 를 `/app/` 에 | 상태 페이지를 `/` 에 그대로 둠 | + Vite `base`, router `basename`, 절대 경로 링크 전수 수정, nginx alias | React 코드 변경 폭이 큼. 회귀 위험 |
| C. React 전용 컨테이너 추가 | 새 서비스·포트 또는 nginx upstream 추가 | + 서버 `compose.yaml`(보호 파일)·overlay·`deploy.py`(서비스 목록·Health)·`publish.py`(digest 3개) | 새 인프라. Auto-CD 보호 장치 대부분 수정 필요 |
| D. 서버에서 수동 빌드·복사 | — | 수동 작업 | digest 추적·Auto-CD 원칙 위반, 제외 |

방안 A 에서 상태 페이지가 `/` 에서 `/staging-status.html` 로 옮겨집니다. React 의 `/system-status` 화면(T19)도 같은 Health·버전 정보를 보여 줍니다. `deploy.py` 는 `/` 의 내용이 아니라 200 응답만 확인하므로 영향이 없습니다.

## 3. 변경 파일 목록 (구현 PR 예정, 이번 단계에서는 만들지 않음)

| # | 파일 | 변경 | 비고 |
|---|---|---|---|
| 1 | `poc/staging/frontend/Dockerfile.integrated` | **신규** 다단계 빌드 | 아래 예시 |
| 2 | `poc/staging/frontend/nginx.conf` | SPA fallback, `/assets/` 캐시와 없는 파일 404, `index.html` 캐시 금지 | 기존 `/api/v1/`·`/api/` 블록과 보안 헤더·CSP 는 **그대로** |
| 3 | `.github/workflows/staging-publish.yml` | Publish frontend 단계에 `file: ./poc/staging/frontend/Dockerfile.integrated`, `build-contexts: app=./frontend` 추가. "Test exact source" 단계에 `npm ci && npm run lint && npm run typecheck && npm test` 추가(fail-closed) | **Auto-CD 변경 → 승인 필요** |
| 4 | `.github/workflows/crawler-mvp.yml` | smoke 이미지를 `Dockerfile.integrated` 로 빌드(`--build-context app=frontend`). Node 설정 단계 추가 | CI 만 바뀜 |
| 5 | `poc/staging/tests/docker_route_smoke.py` | 아래 단언 추가 | CI 에서 실제 컨테이너로 확인 |
| 6 | `poc/staging/tests/test_frontend_nginx_conf.py` | **신규**(선택) 정적 검사: CSP·보안 헤더 유지, `/api/` 블록 변경 없음, fallback 이 `/api` 를 삼키지 않음 | 빠른 회귀 |
| 7 | `docs/STAGING.md`, `docs/release/RELEASE_RUNBOOK.md` | 상태 페이지 새 경로, 브라우저 접근 조건(§5 인증), frontend 롤백 절차 | 문서 |

**docker_route_smoke.py 에 넣을 단언**
- `/` 는 200 이고 `<div id="root">` 를 포함합니다.
- `/login` 같은 깊은 경로도 200 이고 같은 `index.html` 을 줍니다(SPA fallback).
- `/assets/없는파일.js` 는 404 입니다.
- `/staging-status.html` 은 200 입니다.
- `/api/health`, `/api/v1/me` 같은 기존 단언은 그대로 통과해야 합니다.
- CSP 헤더가 그대로입니다.

**변경하지 않는 파일**
- 서버 쪽: `poc/staging/compose.yaml`(보호 해시), `poc/staging/automation/compose.release.yaml`, `deploy.py`, `publish.py`, `config.example.json`, systemd timer·service, 서버 `.env`
- 이미지·앱 쪽: `poc/staging/backend/**`, `poc/staging/frontend/Dockerfile`(기존 PoC 빌드 호환용), `backend/**`, `frontend/src/**`, `database/**`, `crawler/**`

**Dockerfile.integrated 예시**(구현 PR 에서 버전·digest 고정)
```dockerfile
# 1단계: React 빌드 (named context "app" = 저장소의 frontend/)
FROM node:24.19.0-alpine AS build
WORKDIR /app
COPY --from=app package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY --from=app . .
# 플래그를 명시적으로 고정합니다. Mock 과 승인 전 기능은 모두 꺼짐입니다.
ENV VITE_API_BASE_URL=/api VITE_API_MOCK=false VITE_CRAWLER_ADMIN_UI=false VITE_SKILL_AUTOCOMPLETE=false VITE_BEHAVIOR_TRACKING=false
RUN npm run build

# 2단계: 기존과 같은 nginx 이미지
FROM nginx:1.27.5-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY index.html /usr/share/nginx/html/staging-status.html
COPY status.js status.css /usr/share/nginx/html/
```

**nginx.conf 바뀌는 부분**(요지)
- `location /` 의 `try_files $uri $uri/ =404;` → `try_files $uri /index.html;`
  - `/api/` 는 별도 location 이라 fallback 에 걸리지 않습니다.
- `location /assets/ { try_files $uri =404; add_header Cache-Control "public, max-age=31536000, immutable"; … }`
  - nginx 는 하위 블록에 `add_header` 가 있으면 상위 헤더를 물려받지 않습니다. 그래서 보안 헤더 4종을 이 블록에도 다시 적습니다.
- `location = /index.html { add_header Cache-Control "no-cache"; … }`

## 4. 영향 범위와 위험

| 대상 | 영향 | 근거 |
|---|---|---|
| Backend 컨테이너·이미지 | **없음** | backend 이미지 빌드 단계와 Dockerfile 변경 없음. 같은 SHA 면 backend digest 도 그대로 |
| PostgreSQL(앱 DB, 크롤러 DB) | 스키마·설정 **없음** | DB 컨테이너는 `--no-deps` 로 손대지 않음. `deploy.py` 가 DB 컨테이너 ID 불변을 검사 |
| 크롤러 | **없음** | `/api/jobs`·`/api/jobs/collected`·`/api/training` 은 backend 경로. 상태 페이지의 `/api/training` 링크도 유지 |
| Auto-CD | 게시 워크플로 frontend 단계만 바뀜 | 배포 측(`deploy.py`) 무변경 |
| 다른 프로젝트 컨테이너(호스트의 18개) | 없음 | 포트·네트워크·볼륨 무변경 |

| ID | 위험 | 정도 | 대응 |
|---|---|---|---|
| R1 | `/` 의 내용이 상태 페이지에서 React 로 바뀜 | 낮음 | `deploy.py` 는 200 만 확인. 상태 페이지는 `/staging-status.html` 로 유지. 문서에 기록 |
| R2 | 게시 게이트가 Frontend CI 를 보지 않음 → 깨진 React 가 게시될 수 있음 | 중간 | 게시 워크플로의 "Test exact source" 에 lint·typecheck·test 추가. 빌드는 `tsc -b` 를 포함하므로 실패하면 게시가 중단됨 |
| R3 | **refresh 쿠키가 `Secure`** 인데 Staging 은 `http://<host>:18080` | 중간 | 브라우저가 HTTP 에서는 Secure 쿠키를 저장하지 않습니다. 로그인은 되지만 **새로고침하면 로그아웃**됩니다. `AUTH_COOKIE_SECURE=false` 는 계약상 금지이므로 바꾸지 않습니다. QA 는 HTTPS 또는 `http://127.0.0.1`(SSH 터널; 브라우저가 localhost 를 보안 컨텍스트로 봄)로 접속합니다(§5) |
| R4 | 내부망에서 `:18080` 이 열려 있음(O-1) → 누구나 React 회원가입으로 **공유 DB 에 행을 만들 수 있음** | 중간 | 배포 전 결정 필요: 접근 범위(127.0.0.1 바인딩 복원 또는 내부망 허용). 이 설계는 Backend 동작을 바꾸지 않습니다(가입 API 는 지금도 열려 있음) |
| R5 | Mock 전용 화면 10개는 Staging 에서 숨겨짐 | 정보 | 의도된 동작입니다(빌드 플래그 꺼짐). Staging 에서는 "노출되지 않음"만 확인합니다 |
| R6 | 합성 Mock 모듈 문자열이 번들에 포함 | 낮음 | 비밀값 없음, 실행 경로 꺼짐. 후속으로 동적 import 분리 검토 가능(이번 범위 밖) |
| R7 | 번들 623 KB(경고 기준 500 KB 초과) | 낮음 | 기능 영향 없음. `/assets/` 장기 캐시 |
| R8 | 이미지 빌드 시간 증가(`npm ci` + build 약 1~2분) | 낮음 | 게시 타임아웃 25분 안 |
| R9 | 롤백이 앞으로만 가능(CD 정책) | 정보 | §6 절차 |

## 5. React 배포 조건 점검

| 조건 | 상태 | 조치 |
|---|---|---|
| 환경변수 | 모두 **빌드 시** `VITE_*` 로 정함. 실행 시 환경변수 없음. 비밀값 없음 | Dockerfile 에 명시적으로 고정(§3). `.env.mock` 은 `mode=mock` 에서만 읽으므로 production 빌드에는 쓰이지 않음 |
| API 기본 경로 | `/api` + `/v1/...` = `/api/v1/...` | nginx 무변경으로 동작 |
| 인증 | Bearer access token(메모리) + refresh 쿠키 `Path=/api/v1/auth`, `HttpOnly`, `SameSite=Strict`, `Secure` | 쿠키 Path 는 nginx prefix 유지 덕분에 일치. **Secure 문제는 R3** |
| CSRF | GET 이 아닌 요청에 `X-CSRF-TOKEN: 1`(custom header 방식) | 같은 Origin 이라 그대로 동작 |
| CORS | 필요 없음(같은 Origin) | **추가하지 않음**(`csrf.py` 요구사항) |
| 라우팅 | 루트 기준 SPA 경로, `basename` 없음 | `try_files $uri /index.html`. `/api/`·`/assets/` 는 fallback 제외 |
| 정적 자원 | `/assets/*` 해시 이름, `index.html` 1개 | assets 장기 캐시, index 캐시 금지 |
| CSP | 인라인 0, 외부 호출 0 | 현재 CSP 그대로 |
| 기능 플래그 | Mock·승인 전 기능 모두 꺼짐 | 서버 플래그도 꺼짐(S3 6b 에서 확인됨) |

## 6. 배포 전후 Health Check 와 Rollback

### 6.1 배포 전 (읽기 전용, 호스트 운영자)
1. `curl /api/version` 으로 현재 SHA 를 기록합니다. `.deploy-state/success.json` 의 frontend·backend digest 도 기록합니다(이것이 롤백 기준).
2. `docker compose ps` 로 상태를 봅니다. DB 컨테이너 ID 와 다른 프로젝트 컨테이너 수를 기록합니다.
3. `df -h /`, `free -h` 를 기록합니다.
4. 외부에서 S3 기준선을 다시 실행합니다(GET 만): health 3개, 공개 카탈로그 정합성, 무인증 401 52건.

### 6.2 배포 중 (자동, `deploy.py` 기존 동작)
- 4개 경로 200, `version` = 새 SHA, 컨테이너 healthy 를 확인합니다.
- DB 컨테이너 ID 불변, `compose.yaml`·`.env` 해시 불변을 확인합니다.
- 실패하면 `hold.json` 을 남기고 멈춥니다.

### 6.3 배포 후 (읽기 전용, 추가)

| 확인 | 기대 |
|---|---|
| `GET /` | 200, `<div id="root">`, CSP·`X-Frame-Options: DENY`·`nosniff` |
| `GET /assets/index-*.js` | 200, `application/javascript`, 장기 캐시 |
| `GET /login`, `/job-postings` (fallback) | 200, 같은 `index.html` |
| `GET /assets/none.js` | 404 |
| `GET /staging-status.html` | 200, 상태 페이지 |
| `/api/health`, `/api/version`, `/api/health/db`, `/api/openapi.json` | 200, 이전과 같음 |
| 무인증 401 52건, 공개 카탈로그 정합성 | S3 와 같음 |
| 브라우저로 `/job-postings` 열기 | 공고 목록 표시, 콘솔 오류 0, 네트워크 요청은 같은 Origin `/api/v1/job-postings` 만 |
| backend digest | 배포 전과 같음(같은 SHA 였다면) |

### 6.4 Rollback
기존 T90 [`RELEASE_RUNBOOK.md`](../../release/RELEASE_RUNBOOK.md) §3 을 그대로 따릅니다. CD 는 앞으로만 배포합니다.

| 방법 | 언제 | 절차 |
|---|---|---|
| **A. 되돌림 PR (기본)** | 대부분 | 구현 PR 을 `git revert` 한 PR → CI → 병합 → 새 SHA 로 게시·배포. frontend 이미지가 PoC 상태 페이지로 돌아감 |
| B. frontend 만 이전 digest 로 고정 (긴급) | Health Gate 실패, 서비스 불가 | **PM 승인 필수.** 운영자가 `previous.json`(또는 배포 전 기록)의 **frontend digest 만** 지정해 `frontend` 서비스만 `up -d --no-build --no-deps frontend` 로 다시 띄웁니다. backend·db 는 손대지 않습니다. 확인 후 `hold.json` 을 정리하고 A 로 정상화 |

금지: `docker compose down -v`, 전역 prune, DB 볼륨 조작, 다른 프로젝트 컨테이너 변경.

이 변경은 DB 를 바꾸지 않으므로 DB 롤백은 필요 없습니다.

## 7. Frontend 27개 일감 Staging 검증 계획

### 7.1 등급
- **R — 로그인 없이 GET 만**: 공유 DB 에 쓰기 없음. 배포 직후 실행 가능합니다.
- **A — 테스트 계정으로 로그인한 뒤 GET 만**
  - 로그인과 refresh 는 세션 행을 씁니다. 그래서 **계정 제공과 세션 기록 허용**이 필요합니다.
  - HTTPS 또는 localhost 접속이 필요합니다(R3).
- **W — 데이터 변경**: 공유 Staging DB 에서는 하지 않습니다. S6 격리 DB 승인 후에만 실행합니다.
- **H — Staging 에서 숨겨져야 함**: Mock 전용이거나 기능 플래그가 꺼진 화면입니다. 메뉴·경로가 노출되지 않는지만 확인합니다. 기능 자체는 N/A 입니다(Mock 증빙은 별도).

| Task | 화면(경로) | 등급 | 확인 내용 | API ↔ DB 대조 |
|---|---|---|---|---|
| T19 | 앱 기동, `/system-status` | R | 번들·CSS 로드, 콘솔 오류 0, 버전 표시 = `/api/version` | — |
| T20 | `/` 공통 레이아웃 | R | 헤더·내비·푸터, 320/1280px | — |
| T21 | `/login` | R → A | R: 화면·검증 메시지(제출 없음). A: 로그인, 메뉴 변화, 로그아웃 | A: 세션 생성은 승인 후 |
| T22 | `/account` | A (수정은 W) | 내 정보 표시 = `GET /api/v1/me` | DB 읽기 권한 있으면 `users` 1행 대조 |
| T23 | `/job-roles` | R | 목록 30·검색·상세, 페이지 넘김 | 화면 = API(S3 에서 DB 정합성 PASS) |
| T24 | `/job-postings` | R | 목록 80·필터·상세·기업 링크, 만료 공고 미표시 | 화면 = API |
| T32 | `/account/privacy` | A (변경은 W) | 동의 상태 = `GET /me/consents`, 정책 3건 | — |
| T34 | `/me/skills` | A (저장은 W) | 보유 기술 = `GET /me/skills`, T17 검색 | — |
| T36 | `/me/target-roles` | A (W) | 목표 직무 표시 | — |
| T38 | `/me/career-history` | A (W) | 경력·프로젝트 목록 | — |
| T40 | `/me/bookmarks` | A (W) | 저장 공고 목록, 공고 상세의 `is_bookmarked` | — |
| T46 | `/recommendations` | A (실행은 W) | `GET /recommendation-runs/latest` 표시 또는 빈 상태 | — |
| T50 | `/me/documents` | A (업로드는 W, T144 평문 저장 해결 전 실제 문서 금지) | 목록·빈 상태 | — |
| T68 | `/market-trends` | A | 추세 차트 = `GET /market-trends` | 지표 테이블 존재는 DB 권한 필요 |
| T94 | `/password-reset` | R (제출은 W) | 화면·입력 검증만. 제출하면 메일·토큰이 생기므로 하지 않음 | — |
| T140 | `/me/skills` 자동완성 | A | 서버 플래그가 꺼져 있으므로 **T17 이름 검색으로 대체 동작**하는지 확인 | — |
| T146 | 공개 화면 전체 | R | 날짜 KST 표기, 접근성 검사(`frontend/e2e/t146-i18n-a11y.mjs`, `scripts/a11y-browser-check.mjs`) | — |
| T82 | `/admin/moderation` | H | 메뉴·경로 미노출 | — |
| T85 | `/admin/audit-events`, `/admin/ai-usage` | H | 미노출 | — |
| T97 | `/me/notifications`, `/me/notification-settings` | H | 미노출 | — |
| T100 | `/job-postings` 고급 필터 | H | 고급 필터 미노출, 기본 필터만 | — |
| T103 | `/me/applications` | H | 미노출 | — |
| T124 | `/company`, `/company-invitations/accept` | H | 미노출 | — |
| T127 | `/company/postings` | H | 미노출 | — |
| T130 | `/me/public-profile`, `/p/:token` | H | 미노출(서버도 404) | — |
| T143 | `/me/data` | H | 미노출 | — |
| T156 | `/admin/crawler` | H | 미노출(`VITE_CRAWLER_ADMIN_UI=false`) | — |

| 등급 | 수 | 일감 |
|---|---|---|
| R | 7 | T19, T20, T21(화면), T23, T24, T94(화면), T146 |
| A | 10 | T22, T32, T34, T36, T38, T40, T46, T50, T68, T140 (T21 로그인 포함) |
| H | 10 | T82, T85, T97, T100, T103, T124, T127, T130, T143, T156 |
| W | (A 일감의 쓰기 부분) | 공유 DB 에서는 실행하지 않음, S6 격리 DB 승인 후 |

### 7.2 도구와 방법
- **브라우저**: 헤드리스 Chrome + `playwright-core`(저장소 의존성에 넣지 않는 기존 방식, T117).
  - `frontend/e2e/t117-scenarios.mjs` 의 real 모드는 회원가입(쓰기)을 포함합니다. 그래서 **Staging 용 읽기 전용 시나리오(R·H)를 따로** 둡니다.
  - 모든 요청을 가로채 `GET` 이 아닌 요청이 나가면 즉시 실패하게 하는 가드를 넣습니다.
- **API 대조**: 화면에 보인 값과 같은 페이지의 네트워크 응답(`/api/v1/...`)을 비교합니다.
- **DB 대조**: S3 의 공개 카탈로그 정합성 결과를 재사용합니다. 사용자 데이터 대조는 **읽기 전용 DB 역할**이 승인된 경우에만 합니다(예: 공개 공고 수 = `published` 이고 만료 전인 행 수).
- **증빙**: 시나리오별 JSON, 화면 캡처(320·1280px), 콘솔 오류 목록. 모두 합성 계정·데이터만 씁니다.
- **판정**: Staging 에서 실제로 실행한 것만 PASS 로 적습니다. Mock 결과는 Staging 결과로 옮기지 않습니다.

## 8. 배포 전 필요한 승인

| # | 승인 사항 | 승인자(제안) | 이유 |
|---|---|---|---|
| 1 | `staging-publish.yml` 변경(frontend 빌드 방식, 게시 전 Frontend 시험) | PM·DevOps | Auto-CD 변경 |
| 2 | `crawler-mvp.yml`·smoke 시험 변경 | 크롤러 담당(문길래) | 공유 CI |
| 3 | Staging `/` 를 React 로 전환, 상태 페이지 `/staging-status.html` 이동 | PM | 사용자에게 보이는 변경 |
| 4 | `:18080` 접근 범위 결정(O-1, R4): 127.0.0.1 바인딩 복원 또는 내부망 허용 | PM·호스트 운영자 | React 회원가입이 공유 DB 에 쓸 수 있음 |
| 5 | QA 접속 경로: HTTPS(기존 ngrok 등) 또는 SSH 터널 권한 | PM·호스트 운영자 | Secure 쿠키(R3). `AUTH_COOKIE_SECURE=false` 는 쓰지 않음 |
| 6 | A 등급용 테스트 계정 제공과 로그인으로 생기는 세션 행 허용 | PM·DB 담당 | 공유 DB 쓰기(세션) |
| 7 | 읽기 전용 DB 역할(대조용) | DB 담당 | 화면 ↔ DB 대조 |
| 8 | W 등급 쓰기 시험의 격리 DB(S6 제안) | PM·DB 담당 | 공유 DB 보호 |
| 9 | 긴급 롤백 B 수행 권한 | PM | `RELEASE_RUNBOOK.md` §3 |

승인 1~3 이 있으면 구현 PR 을 만들 수 있습니다. 승인 4~5 는 배포 전에 정해야 합니다. 승인 6~8 은 A·W 등급 시험 전에 필요합니다.

```text
STEP=S8/10
DEPLOYED=NO
STAGING_CHANGED=NO
DB_CHANGED=NO
AUTO_CD_CHANGED=NO
RECOMMENDED=A (single frontend image: React at /, status page at /staging-status.html)
FILES_TO_CHANGE=7 (2 new)
BACKEND_DB_CRAWLER_IMPACT=NONE
FRONTEND_27=R7 / A10 / H10 (+W isolated)
```
