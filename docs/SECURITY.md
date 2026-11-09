# 보안·권한·비밀정보 규정

## 웹 요청과 화면 출력
- 인증 쿠키를 발급·사용하는 가입/로그인/갱신/로그아웃 POST는 `X-CSRF-TOKEN: 1`을 요구한다. 값은 비밀 토큰이 아니라 브라우저의 cross-origin custom-header 제한을 이용한다. 외부 HTML form 요청과 헤더 없는 요청은 403으로 거부한다.
- `Sec-Fetch-Site`가 있으면 `same-origin`만 허용한다. 특히 다른 서브도메인의 `same-site` 요청도 거부한다. 이 헤더가 없는 CLI 요청도 CSRF 보호 헤더가 필요하다.
- 브라우저 API는 같은 Origin `/api` 프록시로만 호출한다. 인증 API에 외부 Origin을 허용하는 CORS 설정을 추가하면 custom-header 방식의 전제가 바뀌므로 별도 검토해야 한다. 나머지 사용자 변경 API는 쿠키 대신 명시적인 Bearer 토큰을 검증한다.
- refresh 쿠키는 `HttpOnly; Secure; SameSite=Strict`, access token은 프런트 메모리에서만 관리한다. HTTPS 배포에서 `AUTH_COOKIE_SECURE`를 끄지 않는다.
- 사용자 입력·수집 공고·기업 소개는 React의 텍스트 출력으로 표시한다. `dangerouslySetInnerHTML`, `innerHTML`에 전달하지 않는다. HTML 서식 기능을 추가할 때는 별도 HTML sanitizer 검토가 필요하다. 외부 링크는 `safeExternalUrl`로 http(s)와 자격정보 유무를 검증하고 `noopener noreferrer`를 사용한다.
- 배포 Nginx는 정적 페이지에 CSP를 적용한다. 스크립트와 스타일은 같은 Origin의 파일만 허용하고 inline/eval, object, base URL 변경, iframe 삽입을 차단한다. CSP는 출력 이스케이프를 보완한다.
- Nginx의 `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`는 API와 오류 응답에도 적용한다. `/api/training`은 자체 CSP를 유지한다. React 개발 서버에는 HMR 때문에 이 배포 CSP를 강제하지 않는다.
- 회귀 검증: `backend/tests/test_csrf.py`, `frontend/src/api/client.test.ts`, `frontend/src/pages/JobPostingsPage.test.tsx`. 코드 변경이 실제 서비스에 반영되려면 배포가 필요하다.
- 기준: [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html), [OWASP XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html).

## GitHub
- `main` 보호 Ruleset `protect-main`: PR 리뷰·승인(원칙 1명), CI, Squash Merge.
- 예외 Bypass는 PM 필요 시 PR에서만 제한적으로 사용; 사용 이력·이유 기록 및 정기 재검토.
- PM/JM 외 일반 개발자의 운영 배포·권한 변경 금지.
- GitHub App 설치는 Organization 저장소를 필요한 범위로만 허용.
- 민감정보/토큰/API Key/비밀번호를 코드·PR·Issues·Slack·Actions 로그에 게시하지 않음.

## Ubuntu/DB
- `.env`를 Git에 Commit하지 않으며 권한 600 유지.
- DB Backend 계정에는 SUPERUSER 금지, 필요한 CRUD만 부여.
- 개발자 reader 계정은 SELECT 중심, DDL/DML 불가. 공동 계정은 감사 추적 한계가 있어 개인 계정으로 전환 고려.
- DB 5432 외부 공개 금지; VPN 또는 SSH 터널 등 승인된 경로로만 접속.
- 기존 운영 호스트의 ngrok TCP 5432 터널은 별도 점검 필요; 새 PoC DB 노출과 혼동 금지.
- 테스트용 가상 데이터만 Staging에 사용하고 실사용자의 민감정보를 업로드하지 않음.

## AI/LLM
- 사용자 입력에 포함된 비밀·개인정보는 외부 LLM에 전송하기 전 최소화/마스킹.
- RAG 검색 결과를 신뢰된 시스템 지시로 취급하지 않고 Prompt Injection 방어.
- LLM 호출 예외/타임아웃 시 핵심 서비스 장애로 전파되지 않도록 격리.
- 요청 단위 토큰/비용 기록 시 원문 프롬프트·사용자 개인정보는 최소 수집.

## 권한 승인
- GitHub Actions, GHCR, Vault 등의 서비스 계정/토큰은 역할별 최소 권한.
- Secret 변경/권한 부여는 PM/JM 승인과 기록이 필요.
- 계정 탈퇴/역할 변경 시 권한 즉시 회수.
- 보안 사고 의심 시 관련 토큰 회전, 노출 범위 확인, 감사/복구 기록.
