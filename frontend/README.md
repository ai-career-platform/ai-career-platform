# AI Career Platform — Frontend

React 기반 Frontend 앱 기본 구조(T19). 기존 `poc/staging/frontend`(정적 HTML+Nginx PoC)는 Staging 운영용으로 그대로 유지하며, 신규 화면은 이 `frontend/`에서 개발합니다.

## 기술 스택

| 구분 | 선택 | 근거 |
|---|---|---|
| UI | React 19 | 팀 표준 스택(PR #19 리뷰에서 확정) |
| 언어 | TypeScript 7 | API 계약(`docs/API_CONTRACT.md`)을 타입으로 고정해 Backend 변경을 빌드 단계에서 감지. 7.x(네이티브 컴파일러)로 타입 검사 속도 향상 |
| 빌드/개발 서버 | Vite 8 | React 공식 문서 권장 빌드 도구, 빠른 HMR, `/api` 개발 프록시 내장 |
| 라우팅 | React Router 8 | React 표준 라우터, `createBrowserRouter` + 라우트 객체 배열 |
| 테스트 | Vitest 5 + Testing Library + jsdom | Vite 설정 재사용, Jest 호환 API |
| Lint | oxlint (`.oxlintrc.json`) | `typescript-eslint`가 TypeScript 7을 아직 지원하지 않아(`<6.1`) TypeScript 비의존 린터로 선택. TS·React·react-hooks·import·vitest 규칙 내장, `--deny-warnings`로 경고도 실패 처리 |
| 런타임 | Node.js LTS ≥ 24 (`.nvmrc`: 24), npm | `package-lock.json` 기준 `npm ci` |

## 빠른 시작 (Windows 11 PowerShell)

Node.js LTS 설치는 [Frontend 개발환경 가이드](../docs/development/FRONTEND_DEVELOPMENT_SETUP.md) STEP 01-1 참고.

~~~powershell
cd frontend
node --version          # v24 이상(LTS)
npm ci                  # package-lock.json 기준 설치
npm run dev:mock        # Backend 없이 Mock 데이터로 실행 → http://127.0.0.1:5173/
~~~

### 실제 Backend와 연결해서 실행

1. 로컬 PoC 스택 기동(가이드 STEP 04~05): `poc/staging`에서 `docker compose --env-file .env up --build -d`
2. `npm run dev` → http://127.0.0.1:5173/
3. 브라우저의 `/api/*` 요청은 Vite 프록시가 `http://127.0.0.1:18080`(로컬 PoC Nginx)로 전달 → FastAPI

프록시 대상을 바꾸려면 `.env.example`을 `.env.local`로 복사해 `DEV_API_PROXY_TARGET`을 수정합니다(`.env.local`은 Git 제외).

## 스크립트

| 명령 | 설명 |
|---|---|
| `npm run dev` | 개발 서버(실제 API, `/api` 프록시) |
| `npm run dev:mock` | 개발 서버(Mock API, `.env.mock`) |
| `npm run lint` | oxlint (경고 포함 실패) |
| `npm run gen:api` | `docs/api/openapi.yaml` → `src/api/schema.gen.ts` 타입 생성 (계약이 바뀌면 실행 후 커밋) |
| `npm run check:api` | 생성 타입이 계약과 같은지 검사 (CI에서 실행) |
| `npm run typecheck` | TypeScript 타입 검사 |
| `npm test` | Vitest 1회 실행 (`npm run test:watch`: 감시 모드) |
| `npm run build` | 타입 검사 + 프로덕션 빌드(`dist/`) |
| `npm run preview` | 빌드 결과 미리보기 |

PR 전 확인 순서: `npm ci` → `npm run lint` → `npm run check:api` → `npm test` → `npm run build`

## 폴더 구조

~~~text
frontend/
├── index.html
├── vite.config.ts        # 개발 서버, /api 프록시, Vitest 설정
├── .env.example          # 환경 변수 예시 (비밀정보 금지)
├── .env.mock             # Mock 모드 설정
└── src/
    ├── main.tsx          # 진입점, Router 생성
    ├── routes.tsx        # 라우트 목록 (새 화면은 여기에 등록)
    ├── api/              # API 계층 (아래 "API 계층" 참고)
    ├── mocks/            # Mock 데이터 (docs/API_CONTRACT.md 기준)
    ├── config/env.ts     # 환경 변수 접근
    ├── layouts/          # 공통 레이아웃 (T20에서 디자인 구현)
    ├── components/       # 공통 UI 컴포넌트 (T20)
    ├── pages/            # 화면 단위 컴포넌트 (T21~T24)
    ├── styles/           # 전역 CSS, 디자인 토큰 초안
    └── test/setup.ts     # 테스트 공통 설정
~~~

## API 계층

| 층 | 파일 | 역할 |
|---|---|---|
| 전송 | `api/http.ts` | `createHttpClient({ baseUrl, fetch, getToken, onUnauthorized })`. 모든 요청이 지나는 한 곳 (헤더·쿼리·오류·취소) |
| 계약 타입 | `api/schema.gen.ts`, `api/schema.ts` | OpenAPI 생성 타입(직접 수정 금지)과 `ResponseOf<'operationId'>`·`BodyOf`·`QueryOf` 도우미 |
| 엔드포인트 | `api/catalog.ts`, `api/me.ts`, `api/index.ts` | 경로와 타입은 여기에만. 화면은 `createApi(http).jobPostings.list(...)`처럼 호출 |
| React 상태 | `api/useQuery.ts` | `useQuery(key, fn)` → `{ status, data, error, retry }`. key 변경 시 이전 요청 취소 |
| Mock | `mocks/mockFetch.ts` | 가상 데이터를 fetch 구현체로 끼움. mock 모드에서도 실제와 같은 코드 경로 |

계약(`openapi.yaml`)과 실제 Backend가 다른 필드는 엔드포인트 파일에서 보정하고 주석으로 이유를 남깁니다(예: `catalog.ts`의 `PostingRequiredSkill`).

## 개발 규칙

- **API 호출은 `src/api/`를 통해서만.** 컴포넌트에서 `fetch`를 직접 호출하지 않습니다. 경로는 Backend 기준(`/health`, `/v1/...`), 기본 URL `/api`는 client가 붙입니다.
- **같은 Origin `/api`만 호출** → CORS 설정 불필요. 다른 Origin 직접 호출 금지.
- **Mock 성공 ≠ 실제 PASS.** Mock으로 개발한 화면은 실제 API 구현 후 `npm run dev`로 다시 검증합니다. 현재 실제 API는 `/health`, `/version`, `/health/db`뿐이며 `/v1/*`은 404가 정상입니다.
- `VITE_*` 환경 변수는 브라우저 번들에 그대로 포함되므로 **API Key·비밀번호를 넣지 않습니다.**
- 성공·로딩·빈 데이터·오류 상태를 모두 화면에 처리합니다.

## 현재 범위와 미정 사항

- Staging 배포(Dockerfile/Nginx 연동)와 CI의 Frontend 작업은 이 PR 범위가 아닙니다(T28·T30에서 별도 PR).
- 디자인 토큰(`src/styles/global.css`)은 초안이며 T20에서 확정합니다.
