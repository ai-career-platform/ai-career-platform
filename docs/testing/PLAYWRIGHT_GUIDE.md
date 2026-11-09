# Playwright — 브라우저 E2E 자동화 도입 가이드

> **현재 상태: NOT_INSTALLED / NOT_RUN.** `main`에 `@playwright/test`, `playwright.config.*`, `tests/e2e` 시나리오가 없습니다. 이 문서는 설치·도입을 위한 가이드이며 테스트 성공 기록이 아닙니다.

## 1. 역할 및 권장 범위

- **pytest**: Python API·Service·DB 단위/통합 검증
- **Vitest**: React 단위/컴포넌트 검증
- **Playwright**: Chrome 계열 실제 브라우저로 페이지 이동·클릭·폼·API 연결·화면 상태 검증

초기 E2E 최소 시나리오: (1) 홈 페이지 표시 (2) API 장애 시 오류 화면 (3) 기능 구현 후 인증된 사용자 흐름. 미구현 화면에 대한 테스트는 `SKIP/HOLD`로 문서화하고 임의의 PASS를 만들지 않습니다.

## 2. 도입 PR에 포함할 최소 산출물

1. `frontend/package.json`에 검토된 `@playwright/test` 버전 및 `package-lock.json` 갱신.
2. `frontend/playwright.config.ts` — 로컬/CI `baseURL`, 테스트 타임아웃, 재시도·워커, 스크린샷·trace·HTML reporter. 실패 재현이 가능하도록 버전 고정.
3. `frontend/tests/e2e/` — 현실적으로 실행 가능한 Smoke 1~3건.
4. .gitignore에 `playwright-report/`, `test-results/`, 민감한 세션 파일 차단.
5. 테스트 서버 준비(로컬 `npm run dev:mock` 또는 별도 격리 API), CI에서 브라우저 설치 및 artifact 업로드, 최소 1회 CI 실행 증빙.
6. 브라우저/Node 실행 환경과 실행 조건 설명. `FRONTEND_DEVELOPMENT_SETUP.md`와 동기화.

## 3. 설치 및 실행 명령 (도입 PR 반영 **후**)

다음은 추후 적용할 **예시**이며 현재 `main`에서 동작하는 명령이 아닙니다.

```powershell
Set-Location "$HOME\projects\ai-career-platform\frontend"
npm install --save-dev @playwright/test
npx playwright install chromium
npx playwright test
npx playwright show-report
```

실제 PR은 팀이 승인한 버전으로 설치·lockfile 고정 후 리뷰합니다. `npx playwright test`는 config 및 테스트 코드가 있어야 유효합니다. Windows 로컬은 Chromium부터 시작하고 다중 브라우저/모바일은 후속으로 확대합니다.

## 4. 권장 구성값 (아직 미구현)

- `testDir: './tests/e2e'`, `use.baseURL: 'http://127.0.0.1:5173'`
- `use.screenshot: 'only-on-failure'`, `use.trace: 'retain-on-failure'`
- `reporter: [['list'], ['html', {open: 'never'}]]`
- CI에서 `retries: 1`, 로컬은 `retries: 0`, 빌드/서버 준비 실패는 FAIL
- `webServer`는 **로컬 Mock 개발 서버**로 제한하고 공유 Staging 자동 기동/수정 금지

Playwright의 trace·스크린샷·HTML report에는 화면의 개인정보, 쿠키, 토큰, 요청 본문이 노출될 수 있습니다. **합성 테스트 계정·가상 데이터만 사용**, PR 코멘트에 원시 trace를 공개하지 말고 최소 기간 보관하고 접근을 제한하세요.

## 5. CI 채택 기준

- 신규 E2E 워크플로는 별도 PR과 리뷰를 거쳐 반영합니다.
- PR Checks에서 E2E 실행과 실패 시 artifact 업로드를 확인합니다.
- CI에 브라우저 종속성 설치·lockfile 재현성 확보, SHA별 리포트 첨부.
- CI PASS라도 아직 구축하지 않은 다른 브라우저/실DB 시나리오까지 PASS로 확대하지 않습니다.

[테스트 증빙 정책](TEST_EVIDENCE_GUIDE.md) · [테스트 보고 양식](TEST_REPORT_TEMPLATE.md)
