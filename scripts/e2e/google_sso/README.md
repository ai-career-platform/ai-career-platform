# #328 Google SSO 로컬 브라우저 E2E

실제 Google·Staging 없이 **실제 Backend + 실제 PostgreSQL + `/career/` 빌드 + 공유 nginx 흉내 프록시 + 가짜 IdP**로 Google 로그인 흐름 전체를 브라우저에서 확인합니다.

- Mock 성공이나 로컬 성공은 Staging·실제 Google PASS가 아닙니다. 실제 확인은 #267에서 합니다.
- 비밀값은 모두 합성값입니다. 실제 Client Secret·Allowlist·사용자 이메일은 쓰지 않습니다.

| 구성 | 포트 | 파일 |
|---|---|---|
| 프록시: 공유 nginx `/career` 스니펫과 `auth_request` 게이트, 프론트 nginx의 SPA fallback | 9100 | `dev_proxy.py` |
| 가짜 Google IdP: OIDC Code + PKCE, 1회용 code, RS256 JWKS | 9101 | `fake_idp.py` |
| Backend (`APP_ENV=local-dev`, Google 플래그 켬) | 9102 | `backend/app` |
| 일회용 PostgreSQL (루프백 전용) | 임의 | `setup_db.py` |
| 시나리오 10개 | — | `frontend/e2e/google-sso.mjs` |

## 실행 순서 (bash 기준, 값은 모두 합성)

```bash
# 0) 합성 비밀값·Allowlist (저장소 밖 임시 폴더)
E=$(mktemp -d); echo "e2e-client-secret-$RANDOM$RANDOM" > $E/client_secret
python -c "import secrets;print('e2e-cookie-'+secrets.token_hex(24))" > $E/cookie_secret
printf 'allowed.one@e2e.example.com\nlocal.user@e2e.example.com\n' > $E/allowlist.txt

# 1) 일회용 DB 초기화 (career 스키마를 지움 — 루프백 주소만 허용)
python scripts/e2e/google_sso/setup_db.py postgresql://<user>@127.0.0.1:<port>/e2e_google

# 2) /career 빌드
(cd frontend && VITE_BASE_PATH=/career/ VITE_API_BASE_URL=/career/api npx vite build)

# 3) 가짜 IdP, Backend, 프록시 실행 (각각 다른 터미널)
python scripts/e2e/google_sso/fake_idp.py --port 9101 --client-secret-file $E/client_secret
(cd backend && APP_ENV=local-dev JWT_SECRET=<32자 이상 합성값> DATABASE_URL=postgresql://<user>@127.0.0.1:<port>/e2e_google \
  GOOGLE_LOGIN_ENABLED=1 GOOGLE_GATE_ENFORCED=1 GOOGLE_CLIENT_ID=e2e-client.apps.googleusercontent.com \
  GOOGLE_CLIENT_SECRET_FILE=$E/client_secret GOOGLE_ALLOWLIST_FILE=$E/allowlist.txt GOOGLE_COOKIE_SECRET=$(cat $E/cookie_secret) \
  GOOGLE_REDIRECT_URI=http://localhost:9100/career/api/v1/auth/google/callback GOOGLE_TEST_IDP_BASE_URL=http://localhost:9101 \
  PUBLIC_PATH_PREFIX=/career uvicorn app.main:app --host 127.0.0.1 --port 9102)
python scripts/e2e/google_sso/dev_proxy.py --port 9100 --backend http://127.0.0.1:9102 --dist frontend/dist --gate

# 4) 시나리오 (playwright-core 는 저장소 의존성이 아님 — 경로로 지정, T117 과 같은 방식)
(cd frontend && E2E_COOKIE_SECRET=$(cat $E/cookie_secret) E2E_OUT=$E/result.json \
  PLAYWRIGHT_CORE=<playwright-core 경로> CHROME_PATH=<chrome 경로> node e2e/google-sso.mjs)

# 5) DB 결과 요약 (이메일·sub 원문 없이 건수만)
python scripts/e2e/google_sso/setup_db.py postgresql://<user>@127.0.0.1:<port>/e2e_google --report
```

## 시나리오

| ID | 내용 |
|---|---|
| C01 | 신규 사용자: `/career/` 접속 → 게이트 → Google → 약관 화면에서 필수 동의 확인 → 가입(201) → 쿠키는 gate·refresh만 |
| C05 | 새로고침(refresh 회전)·페이지 이동·주소로 연 새 탭·탭 전환 뒤에도 세션 유지 |
| C06a | 일반 로그아웃: 게이트는 유지되고 로그인 화면에 머묾(Google로 튕기지 않음) |
| C04a | 게이트가 켜진 상태에서 로컬 회원가입·로그인이 함께 동작 |
| C04b | 같은 이메일의 로컬 계정이 있을 때 자동 연결을 거부하고 로컬 로그인을 안내 |
| C02 | 완전 로그아웃 → 정적 페이지(루프 없음) → 재접속 → Google → 약관 없이 자동 로그인 |
| C10 | 이미 쓴 callback URL을 다시 열면 거부하고 토큰 교환이 생기지 않음 |
| C03 / C03b | 미허용 계정·로그인 취소: 정적 안내만 보이고 쿠키·계정이 생기지 않으며 리디렉트 루프 없음 |
| C07 | 직접 API: 게이트 없음·위조·만료·Bearer만 있는 요청은 401, 게이트+Bearer는 200, Backend 직통(LAN 재현)은 401, SPA 셸은 302 |
