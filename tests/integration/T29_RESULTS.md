# T29 lightweight Frontend ↔ Backend integration QA

판정: **PARTIAL**. 병합된 API Client의 실제 읽기 연결은 PASS다. 인증된 프로필 화면과 직무/기업/공고 화면 통합은 선행 PR 미병합으로 HOLD다. Mock 결과를 실제 통합 PASS로 계산하지 않았다.

- 기준 main / 실제 Staging SHA: `d78496b2e1cc2db4569d115e26456f1d133adca2`
- 검증일: 2026-11-09 KST
- 브랜치: `task/t29-lightweight-integration-qa`
- 새 테스트 파일1개 + 본 보고서만 변경. 앱/인증/DB/Auto-CD/Docker/CI 설정 변경 없음.
- 테스트 파일 SHA256: `6889c4adad046e7ef346745e1297c40e667215e60570d82767a5b5197b89f8a1`

## 선행 구현 상태 (위 기준 SHA)

| 작업 | PR | 실제 상태 | T29 처리 |
|---|---|---|---|
| T17 직무·기술 Backend | #117 | DRAFT / OPEN | HOLD; main에 있다고 가정하지 않음 |
| T18 기업·공고 Backend | #128 | DRAFT / OPEN | HOLD |
| T22 프로필 Frontend | #131 | OPEN, not Draft | 인증된 화면 흐름 HOLD |
| T23 직무·기술 Frontend | #130 | DRAFT / OPEN | HOLD |
| T24 기업·공고 Frontend | #132 | DRAFT / OPEN | HOLD |
| T28 Frontend CI | #133 | MERGED | 기존 lint/test/build 사용 |

선행 PR을 T29 목적상 병합하거나 가져오지 않았다. main의 T19 apiGet/getHealth/getVersion/getDbHealth 및 기존 UI 테스트만 사용한다. T15/T16 Backend와 T20/T21 공통 화면은 main에 있으나 미병합 T22 화면을 대신하지 않는다.

## 기존 검증 재사용과 새 검사

| 요구 항목 | 근거 | 분류·결과 |
|---|---|---|
| `/api` 기본 경로 | 기존 client.test.ts URL 검사, env.apiBaseUrl 확인, 기존 Vite 프록시 | 실제 경로 PASS |
| 응답 DTO | 실제 getHealth/getVersion/getDbHealth 응답의 필드/값 검사 | Health/Version PASS; 인증된 Me DTO Frontend는 T22 HOLD |
| HTTP200 | 실제 health/version/db-health | REAL PASS |
| HTTP401 | 실제 `/api/v1/me` 미인증 | REAL PASS, ApiError.status=401 |
| HTTP404 | 실제 존재하지 않는 GET 경로 | REAL PASS, ApiError.status=404 |
| HTTP422 | 실제 `/api/jobs/collected?limit=0` 읽기 전용 입력 | REAL PASS, ApiError.status=422; T17/T18 검색 기능 PASS를 뜻하지 않음 |
| 네트워크 실패 | 기존 client.test.ts의 fetch rejection→ApiError.status=0 | MOCK 단위 테스트 PASS; 새 중복 검사 없음 |
| Mock/실제 모드 | 기존 mock fixture/unknown404 검사; 새 suite는 mockEnabled=false, VITE_API_MOCK=false 강제 | 모드 구분 PASS |
| 화면 상태·라우팅 | 기존 App/CommonUi/LandingPage 테스트 | DOM/Mock 검사; 실제 UI E2E로 계산하지 않음 |
| 인증된 T15/T16 DB 조회·수정 | 기존 실제 Staging Evidence 및 PostgreSQL CI173개 | REUSED PASS; T29에서 계정 생성/PATCH 없음 |

## 실제 연결 검사

새 파일: `frontend/src/api/client.integration.test.ts` — 기존 Vitest node 환경만 사용한다. 외부 E2E 도구·테스트 서버 구현·DB·Docker 설정을 추가하지 않았다.

기존 개발 서버를 명령으로 잠시 실행했다:

```powershell
cd frontend
$env:DEV_API_PROXY_TARGET = 'http://10.2.10.104:18080'
$env:VITE_API_MOCK = 'false'
npm run dev -- --port 5189
```

다른 터미널에서:

```powershell
cd frontend
$env:T29_REAL_API_ORIGIN = 'http://127.0.0.1:5189'
$env:VITE_API_MOCK = 'false'
npm test -- --run src/api/client.integration.test.ts
```

실제 경로: **기존 getHealth/getVersion/getDbHealth wrappers → apiGet → Node native fetch → 기존 Vite `/api` proxy → Staging Nginx → 실제 Backend**. fetchImpl/vi/MSW Mock을 주입하지 않았다. `/api/v1/me`의 GET/PATCH OpenAPI 등록도 조회했다. **6개 테스트가 총7개의 GET 요청**을 보낸다. POST/PATCH/DELETE·사용자 생성·크롤러 실행 없음.

- 프록시 없는 상태:6개 모두 연결 오류로 실패해, 실제 연결 없이 PASS하지 않음을 확인했다.
- 기존 Vite 프록시 실행 후: **6/6 PASS**.
- 전체 Frontend를 실제 API opt-in 환경에서 실행: **22 PASS / 0 FAIL / 0 SKIP** (기존16 + 실제6).
- 종료 후 이번 작업의 Vite 프로세스를 정지했고 5189 listener가 없음을 확인했다. 기존 서버를 중지하지 않았다.

## 기존 명령·CI

| 명령/근거 | 결과 | 실제 DB 여부 |
|---|---|---|
| npm ci | PASS, Node24.19.0/npm11.17.0, lockfile 변경 없음 | N/A |
| npm run lint | PASS | N/A |
| npm test (실제 API opt-in) | 22 PASS | 새6개는 실제 HTTP; DB Health는 실제 SELECT |
| npm test (기본 CI 모드) | 16 PASS / 6 SKIP | 외부 공유 Staging 접속 opt-in 미설정 |
| npm run build | PASS (tsc + Vite) | N/A |
| Backend pytest 동일 main SHA CI | 119 PASS / 54 SKIP, 경고1 | 실DB opt-in 검사54개는 이 job에서 SKIP |
| 기존 T15/T16 PostgreSQL CI | 173 PASS / 0 FAIL / 0 SKIP, PostgreSQL18.1 | 실제 격리 PostgreSQL, source dbaa4ed |
| 기존 T15/T16 Staging Evidence | signup/login/refresh/GET/PATCH/commit/rollback/만료·폐기 PASS | 실제 Staging PostgreSQL |

Backend pytest는 동일 main SHA의 [기존 CI](https://github.com/ai-career-platform/ai-career-platform/actions/runs/42553464329)를 재사용했다. 이전 실DB source `dbaa4ed916200c8262acd5127757c5a197dbacfa`부터 기준 main까지 backend 파일 diff가 없음을 확인했다. [실DB CI](https://github.com/ai-career-platform/ai-career-platform/actions/runs/42549215471)와 기존 `T15_T16_STAGING_DB_EVIDENCE.md`는 T29에서 새로 실행한 테스트로 계산하지 않았다.

새 suite는 `T29_REAL_API_ORIGIN`이 없으면 명확히 SKIP한다. 기본 Frontend CI가 자동으로 공유 Staging에 접속하게 변경하지 않았다. PR의 실제 CI 결과는 PR Checks와 PR 본문의 실행 SHA 기준 결과를 함께 확인한다. opt-in SKIP을 실제 통합 PASS로 표시하지 않는다.

## 데이터 보존·제한

- Staging backend/frontend/PostgreSQL healthy, Auto-CD 정상, T64/T154 Timer disabled/inactive 유지.
- 실제 읽기 검사 직전/직후 앱51개 및 크롤러 전체 테이블 건수·지문 동일. 공고35건 보존.
- 이전 T15/T16 Evidence의 약관0건과 이번 시작 상태3건은 다르다. 이를 T29 변경으로 숨기거나 이전 상태로 되돌리지 않았다. 이번 검사 전후에는3건 및 동일 지문을 유지했다. 나머지 이전 앱 테이블과 크롤러 데이터는 이전 Evidence와도 동일하다.
- 브라우저 로그인/Refresh는 테스트하지 않았다. HTTP Staging에서 Secure cookie 자동 전송 문제는 기존 제한으로 HOLD. Cookie/JWT 설정을 바꾸지 않았다.
- main에는 profile용 Frontend API/화면이 없으므로 사용자 로그인→프로필 수정 화면 E2E를 PASS로 주장하지 않는다.
- T17/T18/T23/T24의 검색/목록 연결은 미병합으로 HOLD. 별도 Backend 구현을 가져오거나 Mock을 실제 결과로 대체하지 않았다.

## 실행 Evidence

로컬 작업 outputs에 보존:
- `t29-frontend-lint.log`, `t29-frontend-test.log`, `t29-frontend-build.log`
- `t29-frontend-ci-mode.log`, `t29-real-readonly-final.log`
- `t29-main-backend-ci.log`
- `t29-staging-readonly.log`, `t29-staging-after.log`
- 기존 `T15_T16_STAGING_DB_EVIDENCE.md`, `t15-t16-final-db-evidence.json`

## 최종 상태

`STAGING_CHANGED=NO`, `DATABASE_CHANGED=NO`, `FINAL_STATUS=PARTIAL`.

PR 생성 후 기존 CI 확인·리뷰 요청까지 수행한다. **PM 최종 검토 전에 main 병합하지 않는다.** 선행 UI/검색 PR들이 정상 병합된 뒤, 현재 테스트를 확장해야 할 최소 누락만 다시 평가한다.
