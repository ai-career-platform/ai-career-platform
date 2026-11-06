# React Frontend — Vitest 단위/컴포넌트 테스트

> 현재 `frontend/package.json`에 **Vitest + Testing Library + jsdom**이 설치 대상으로 등록되어 있습니다. Playwright는 별도의 브라우저 E2E 도구로 아직 도입되지 않았습니다.

## STEP 01. 설치 (Windows 11)

Node.js LTS 및 npm을 설치한 뒤 저장소의 `frontend`에서 실행합니다.

```powershell
Set-Location "$HOME\projects\ai-career-platform\frontend"
node --version
npm ci
```

`package-lock.json`과 `package.json`의 일치 여부를 먼저 확인하고, 설치 오류가 나면 임의로 `npm install`하여 lockfile을 변경하지 말고 담당자에게 보고하세요.

## STEP 02. 정적 검사 → 단위 테스트 → 빌드

```powershell
npm run lint
npm run typecheck
npm test
npm run build
```

현재 `npm test`는 `vitest run`입니다. `npm run test:watch`는 개발 중 변경 감지용이며 PR 제출용 일회성 테스트 결과 대신 사용할 수 없습니다.

## STEP 03. 보고할 테스트 범위

- 컴포넌트 표시, 로딩/빈 데이터/오류 상태
- 폼 입력 검증과 버튼 상호작용
- API Client 정상/실패·상태코드 매핑
- Mock 응답과 실제 서비스 API 응답을 구분

`frontend/src/App.test.tsx`, `frontend/src/api/client.test.ts`, `frontend/src/test/setup.ts`를 참고합니다. `npm test` PASS를 실제 브라우저 E2E나 Staging 통합 PASS로 표현하지 마세요.

## STEP 04. 테스트 결과 증빙

PowerShell에서 다음처럼 실행 로그를 별도 파일에 보관할 수 있습니다.

```powershell
New-Item -ItemType Directory -Force .\test-results | Out-Null
npm test *> .\test-results\vitest-console.log
$LASTEXITCODE
```

현재 구성에서 JUnit reporter나 커버리지 확장 패키지를 설치했다고 가정하지 않습니다. CI에서 JUnit XML 및 커버리지 보고가 필요하면 전용 PR로 설정을 추가하고 정확한 생성 파일을 확인하세요. `test-results/` 로그와 결과는 민감정보 검사 후 PR 첨부/Actions Artifact에 저장합니다.

최종 보고 양식은 [TEST_REPORT_TEMPLATE.md](TEST_REPORT_TEMPLATE.md)를 사용합니다.
