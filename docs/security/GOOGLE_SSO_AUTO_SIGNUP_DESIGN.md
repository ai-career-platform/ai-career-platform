# Google OAuth 자동 회원가입·로그인 상세 설계 (#328 STEP 02)

- 상태: **설계안**. 구현, 배포, 서버·Google Cloud 설정 변경은 하지 않았습니다.
- 범위: Staging `https://sulfite-footbath-next.ngrok-free.dev/career/` 한정입니다. Redmine(`/`)과 `/church/`는 대상이 아닙니다.
- 관련 이슈와 PR: #263(상위), #328(본 이슈), #265·#266·#267, PR #272
- 기준 코드: `main` 82ca9e4 (PR #271 병합 후)

## 0. 확정 전제와 미검증 항목

| 항목 | 값 | 상태 |
|---|---|---|
| Google 프로젝트 | 기존 프로젝트 재사용. ID는 공개 저장소에 적지 않음 | PM 보고 |
| OAuth Web Client | 기존 Client "AI Career Google Login". 신규 생성 없음 | PM 보고 |
| Redirect URI | `https://sulfite-footbath-next.ngrok-free.dev/career/api/v1/auth/google/callback` | PM 보고, **실제 인증 NOT_VERIFIED** |
| scope | `openid email profile`만 사용(민감 scope 없음 → Google 앱 검증 불필요) | 설계 |
| 대상 인원 | 11~30명, 이메일 Allowlist 정확 일치 | 설계 |
| 추가 비용 | Google OAuth와 backend 내부 처리는 0원 | ngrok 요금제·사용량 **NOT_VERIFIED** |
| Backend 컨테이너 외부 HTTPS(oauth2.googleapis.com, googleapis.com JWKS) | 필요 | **NOT_VERIFIED** (STEP 03 첫 점검 항목) |
| Redmine Google 로그인 | 더 이상 사용하지 않음(PM). Redmine 서비스와 플러그인 설정은 변경하지 않음 | 범위 밖 |

## 1. 결론 요약

- **구조:** AI Career Backend가 Google Callback을 직접 처리합니다(#328 STEP 01의 A안).
  - 별도 인증 프로세스(oauth2-proxy)나 Docker 서비스를 추가하지 않습니다.
- **1차 게이트(#263 요구):**
  - Google 인증을 통과하고 Allowlist에 포함되면 Backend가 서명된 `career_gate` 쿠키를 발급합니다.
  - Backend 미들웨어가 이 쿠키로 `/api/v1/*` 전체를 보호합니다.
  - 공유 nginx는 SPA 셸(`/career/`)만 `auth_request`로 같은 Backend 판정에 맡깁니다.
- **2차(앱 계정):** `auth_identities(provider='google', subject=sub)`로 사용자를 찾습니다.
  - 연동된 계정이 있으면 자동 로그인합니다.
  - 처음이면 필수 약관에 한 번 동의한 뒤 계정을 만듭니다.
  - 세션은 기존 `_start_session()`과 refresh 쿠키를 그대로 씁니다.
- **기존 로컬 로그인·회원가입은 유지합니다.** 동일 이메일 로컬 계정을 자동으로 연결하지 않습니다.
- **DB 스키마 변경은 없습니다.** `auth_identities`의 기존 컬럼과 UNIQUE(provider, subject)만으로 충분합니다.
- **두 기능 플래그는 기본값이 꺼짐입니다.** `GOOGLE_LOGIN_ENABLED=0`, `GOOGLE_GATE_ENFORCED=0`이므로 병합되어 Auto-CD로 배포돼도 동작이 바뀌지 않습니다.

## 2. 기존 코드 확인 결과 (재사용 근거)

| 영역 | 위치 | 현재 동작 | 재사용 방식 |
|---|---|---|---|
| Router | `backend/app/routers/auth.py` | `/auth/signup·login·refresh·logout` 제공<br>`_issue()`가 refresh 쿠키(HttpOnly, SameSite=Strict, Path `/api/v1/auth`) 발급<br>라우터 전체에 `require_csrf_protection` 적용 | `_issue()` 그대로 사용<br>새 엔드포인트도 같은 라우터 사용<br>CSRF 검사는 GET에서 이미 생략됨(`dependencies/csrf.py`) → callback(GET)은 영향 없음 |
| AuthService | `backend/app/services/auth.py` | `_start_session()`은 DB 세션 생성, refresh 해시 저장, Access JWT 발급<br>`_validate_consents()`는 현재 정책·필수 동의 검증<br>`DEFAULT_ROLE="job_seeker"` | 그대로 호출<br>`_validate_consents()`만 `SignupRequest` 대신 동의 목록을 받도록 시그니처 일반화(동작 동일) |
| Repository | `backend/app/repositories/auth.py` | `create_user()`는 users, user_profiles, **local** identity, user_roles, user_consents를 한 번에 flush<br>UNIQUE 위반은 `EmailTaken` | `NewUser`에 `identity_provider`·`identity_subject` 추가(기본값 `local`·email_canonical)<br>`password_hash: str \| None`로 변경<br>`find_identity(provider, subject)` 조회 1개 추가 |
| DB | `database/migrations/0001_initial_schema.sql` | `auth_identities(provider varchar(40), subject varchar(255), password_hash)`<br>`CHECK (provider='local' OR password_hash IS NULL)`<br>`UNIQUE(provider, subject)`<br>`users.email_canonical UNIQUE` | Google identity를 `provider='google'`, `subject=sub`, `password_hash=NULL`로 저장<br>**마이그레이션 불필요** |
| 세션·권한 | `AuthService.authenticate()`, `dependencies/auth.py` | 매 요청마다 세션·사용자 상태·역할을 DB에서 다시 읽음(토큰 안의 roles는 신뢰하지 않음) | 변경 없음. Google 사용자도 같은 경로로 권한 검사 |
| 비밀번호 재설정 | `repositories/account_recovery.py` | `provider='local'` identity만 찾음 | 변경 없음. Google 전용 사용자는 재설정 메일을 받지 않고, local identity도 생기지 않음(정상) |
| 프론트 세션 복원 | `frontend/src/auth/AuthContext.tsx`, `loginPreferences.ts` | 앱 시작 시 `POST /auth/refresh` 1회<br>`shouldKeepSession()`이 false면 즉시 logout | 재사용<br>**주의:** Google 리디렉트로 돌아오면 `sessionStorage`의 `login.sessionAlive`가 없어 **방금 만든 세션이 곧바로 로그아웃됨** → §6.4 처리 필요 |
| 가입 화면 | `frontend/src/pages/SignupPage.tsx` | `GET /consent-policies`로 동의 체크박스 생성 | 동의 UI 컴포넌트를 분리해 Google 가입 화면에서 재사용 |

## 3. 최종 OAuth 인증 시퀀스

```text
Browser                    shared nginx (host)              Backend (FastAPI)                 Google
  │ GET /career/...            │                                │                                │
  │──────────────────────────▶│ auth_request /career/_gate ───▶│ GET /api/v1/auth/gate          │
  │                            │◀───────────── 401 (게이트 쿠키 없음)                              │
  │◀── 302 /career/api/v1/auth/google/start?return_to=/career/...                                │
  │ GET …/google/start ───────────────────────────────────────▶│ state·nonce·PKCE verifier 생성  │
  │◀── 302 accounts.google.com/o/oauth2/v2/auth?…  + Set-Cookie career_g_tx (서명, 10분)          │
  │──────────────────────────────────────────────────────────────────────────────────────────▶│ 로그인·동의
  │◀──────────────────────────────── 302 …/career/api/v1/auth/google/callback?code&state ──────│
  │ GET …/google/callback ────────────────────────────────────▶│ 1 tx 쿠키 서명·만료·state 확인  │
  │                                                             │ 2 code + verifier 교환 ───────▶│ token endpoint
  │                                                             │◀────────────── id_token ───────│
  │                                                             │ 3 ID Token 검증(JWKS 서명, iss, │
  │                                                             │   aud, azp, exp, nonce,        │
  │                                                             │   email_verified)              │
  │                                                             │ 4 Allowlist 정확 일치           │
  │                                                             │ 5 identity(google, sub) 조회   │
  │   (a) 연동 계정, active   ◀── 302 /career/auth/google/done?next=… + career_gate + refresh_token
  │   (b) 신규, 이메일 충돌 없음 ◀── 302 /career/auth/google/signup + career_gate + career_g_pending
  │   (c) 동일 이메일 기존 계정 ◀── 302 /career/login?google_error=email_conflict + career_gate
  │   (d) Allowlist 밖·미검증   ◀── 403 HTML(백엔드 직접 렌더, 게이트 쿠키 없음)
  │   (e) 비활성 계정·기타 실패 ◀── 302 /career/login?google_error=failed + career_gate
  │
  │ (a) SPA 부팅 → POST /auth/refresh → Access Token → /career/{next}
  │ (b) 약관 화면 → POST /auth/google/signup {display_name, consents} → 201 TokenResponse + refresh_token
```

- 모든 리디렉트 URL에는 **토큰, 이메일, sub가 들어가지 않습니다.** 들어가는 것은 상대 경로와 고정 오류 코드뿐입니다.
- `career_g_tx` 쿠키는 callback에서 성공·실패와 관계없이 항상 삭제합니다(1회용).
- (d)는 SPA를 렌더하지 않습니다. 게이트가 켜져 있으면 SPA 로그인 화면도 게이트 뒤에 있기 때문입니다. 대신 정적 HTML 403 페이지를 보여 리디렉트 무한 루프를 막습니다. 이 페이지에는 "다른 Google 계정으로 다시 시도" 링크(`start?prompt=select_account`)가 있습니다.

## 4. Backend API 계약

모든 경로는 Backend 기준 `/api/v1`이며, 외부에서는 `/career/api/v1`입니다. `GOOGLE_LOGIN_ENABLED=0`이면 아래 Google 엔드포인트는 모두 **404**를 반환해 기능 존재를 드러내지 않습니다.

| Method·Path | 입력 | 성공 | 실패 |
|---|---|---|---|
| `GET /auth/google/start` | query `return_to`(선택, §8.4 검증), `prompt=select_account`(선택) | 302 Google 인가 URL<br>Set-Cookie `career_g_tx` | 429 `RATE_LIMITED` (IP당 30회/15분)<br>`return_to`가 잘못되면 무시하고 `/career/` 사용 |
| `GET /auth/google/callback` | query `code`, `state` 또는 `error` | 302 §3 (a)(b)(c)(e) | 403 HTML (d)<br>tx 쿠키 없음·위조·만료·state 불일치이면 302 `/career/login?google_error=failed` |
| `GET /auth/google/pending` | 쿠키 `career_g_pending` | 200 `{email, display_name, expires_at}` | 401 `GOOGLE_SIGNUP_EXPIRED` |
| `POST /auth/google/signup` | 쿠키 `career_g_pending`<br>헤더 `X-CSRF-TOKEN: 1`<br>body `{display_name: 1..100, consents: ConsentInput[]}` (`SignupRequest`와 같은 규칙) | 201 `TokenResponse` + refresh 쿠키<br>pending 쿠키 삭제 | 401 `GOOGLE_SIGNUP_EXPIRED`<br>403 `GOOGLE_NOT_ALLOWED` (Allowlist에서 제거됨)<br>409 `GOOGLE_EMAIL_CONFLICT`<br>422 `VALIDATION_FAILED` (필수 동의 누락)<br>429 |
| `GET /auth/gate` | 쿠키 `career_gate` | 204 | 401 `EDGE_AUTH_REQUIRED` (nginx `auth_request` 전용, 본문 없음) |
| `POST /auth/logout` (기존) | 변경 없음 | 204 | — (게이트 쿠키는 유지, §7.3) |
| `GET /auth/google/signout` | — | 200 정적 "로그아웃됨" HTML(게이트 밖, 미들웨어 예외)<br>`career_gate`·refresh 쿠키 삭제, 앱 세션 revoke | — |

- 새 `ErrorCode` 4개
  - `EDGE_AUTH_REQUIRED`(401)
  - `GOOGLE_NOT_ALLOWED`(403)
  - `GOOGLE_EMAIL_CONFLICT`(409)
  - `GOOGLE_SIGNUP_EXPIRED`(401)
- callback 리디렉트의 `google_error` 값은 고정 집합 `failed | email_conflict | cancelled` 중 하나입니다. 계정 존재나 비활성 여부를 구분해 드러내지 않습니다. 비활성 계정은 `failed`를 받습니다.
- `docs/api/openapi.yaml`과 `frontend/src/api/schema.gen.ts`도 함께 갱신합니다(STEP 03).

## 5. 자동 가입·로그인 처리 로직

```python
def google_callback(code, state, tx_cookie):
    tx = verify_signed(tx_cookie, purpose="google_tx", max_age=600)    # 위조·만료 → failed
    require(compare_digest(tx.state, state))
    tokens = exchange_code(code, tx.code_verifier, redirect_uri=SETTINGS.redirect_uri)  # 10s timeout
    claims = verify_id_token(tokens.id_token, nonce=tx.nonce)          # §8.1
    email = claims.email.strip().lower()
    if not allowlist.contains(email):          # 정확 일치, 빈 목록 = 전원 거부
        return forbidden_html()                # 게이트 쿠키 발급 안 함
    gate = issue_gate_cookie(sub=claims.sub, email=email)
    identity = repo.find_identity("google", claims.sub)
    if identity:                                # 재로그인
        user = repo.get_user(identity.user_id)
        if user.status != "active":
            return redirect_login("failed", gate)
        repo.touch_last_login(user.user_id, now)
        tokens = service._start_session(user.user_id, user_agent, now)  # 기존 코드
        repo.commit()
        return redirect(f"/career/auth/google/done?next={tx.return_to}", gate, refresh=tokens)
    if repo.email_exists(canonical_email(email)):    # 로컬 계정 등 동일 이메일
        return redirect_login("email_conflict", gate)  # 자동 연결 금지
    pending = sign(purpose="google_signup", sub=claims.sub, email=email,
                   name=(claims.name or email.split("@")[0])[:100], max_age=600)
    return redirect("/career/auth/google/signup", gate, pending=pending)  # DB 쓰기 없음
```

- **최초 가입 트랜잭션** (`POST /auth/google/signup`)
  1. pending 쿠키 검증
  2. Allowlist 재확인
  3. `_validate_consents(consents)`
  4. 같은 sub의 identity가 이미 있으면(이중 제출이나 다른 탭) 그 사용자로 `_start_session` → 201로 멱등 처리
  5. `email_exists` 재확인 → 있으면 409
  6. `create_user(NewUser(provider="google", subject=sub, password_hash=None, role_code="job_seeker", consents=...))`
  7. `_start_session()` → `commit()`
  - 예외가 나면 `rollback()`합니다. 기존 `signup()`과 같은 구조입니다.
  - 동시 경쟁은 DB UNIQUE가 막습니다.
    - `users.email_canonical` 위반 → `EmailTaken` → 409
    - `(provider, subject)` 위반 → 재조회 후 멱등 로그인
- **역할:** 항상 `job_seeker`만 부여합니다. 관리자·기업 역할은 기존 관리자 기능으로만 부여합니다.
- **사용자 정보:**
  - `users.email`에는 Google이 검증한 이메일 원문(소문자)을 저장합니다.
  - `email_canonical`은 기존 `canonical_email()`로 계산합니다.
  - `display_name`은 사용자가 약관 화면에서 수정할 수 있습니다.
- **로그:**
  - 이메일과 sub 원문은 남기지 않습니다. `sub_hash=sha256(sub)[:12]`와 결과 코드만 남깁니다.
  - Client Secret, code, 토큰은 로그·예외 메시지에 넣지 않습니다.

## 6. 필수 약관 동의 처리

1. callback이 신규 사용자를 `/career/auth/google/signup`(SPA 신규 라우트 `GoogleSignupPage`)으로 보냅니다.
2. 화면이 `GET /auth/google/pending`(이메일·이름 표시용)과 `GET /consent-policies`를 호출합니다.
   - 기존 `SignupPage`의 동의 fieldset을 `ConsentFields` 컴포넌트로 분리해 재사용합니다.
   - 필수 항목은 체크하지 않으면 제출할 수 없고, 선택 항목(`llm_processing`, `behavior_tracking`)은 사용자가 고릅니다.
3. 서버는 기존 `_validate_consents()`로 현재 정책 버전과 필수 동의를 다시 검증합니다(FR-ACC-001 기준 5, FR-ACC-006).
4. **세션 유지 처리(필수 수정):** SPA 신규 라우트 `/auth/google/done`과 `/auth/google/signup` 진입 시, `AuthProvider`가 부팅 refresh 전에 `rememberSession(false)`를 호출해 `login.sessionAlive`를 설정합니다.
   - 이렇게 하지 않으면 `shouldKeepSession()`이 false가 되어 방금 받은 세션을 즉시 logout합니다.
   - 이 경로 표시는 비밀값이 아닙니다.
   - `next`는 §8.4 규칙으로 다시 검증한 뒤 이동합니다.
5. pending 쿠키는 10분 뒤 만료됩니다. 만료되면 "다시 Google로 계속" 버튼을 보여 줍니다. 그 시점까지 DB에는 아무것도 기록되지 않습니다.

## 7. 기존 계정 충돌·세션·쿠키

### 7.1 동일 이메일 충돌 정책
- Google 이메일의 `canonical_email()`이 기존 `users.email_canonical`과 같으면 **신규 생성도 연결도 하지 않습니다.**
- 사용자에게는 `/career/login?google_error=email_conflict` 화면에서 "이 이메일로 가입된 계정이 있습니다. 기존 비밀번호로 로그인하세요"라고 안내합니다.
- 게이트 쿠키는 발급하므로 로컬 로그인 화면에는 접근할 수 있습니다.
- 계정 연결은 이번 범위 밖입니다. 이후 필요하면 **로컬 로그인 상태에서 비밀번호를 다시 확인한 뒤 명시적으로 "Google 연결"**을 하는 별도 기능(`POST /me/identities/google`)으로만 제공합니다.

### 7.2 쿠키 설계
| 쿠키 | 내용 | Path(브라우저 기준) | 수명 | 속성 |
|---|---|---|---|---|
| `career_g_tx` | state, nonce, PKCE verifier, return_to | `/career/api/v1/auth/google` | 10분, 1회용 | HttpOnly, Secure, **SameSite=Lax**(Google에서 돌아오는 top-level GET에 필요), HS256 서명 |
| `career_g_pending` | purpose, sub, email, name | `/career/api/v1/auth/google` | 10분 | HttpOnly, Secure, SameSite=Strict, HS256 서명 |
| `career_gate` | purpose, sub, email, iat, exp | `/career/` | 12시간 | HttpOnly, Secure, **SameSite=Lax**, HS256 서명 |
| `refresh_token` (기존) | refresh 원문(DB에는 해시) | `/career/api/v1/auth` | 기존 14일 | 기존 HttpOnly, Secure, SameSite=Strict |

- **서명 키:** 신규 `GOOGLE_COOKIE_SECRET`을 쓰며 32바이트 이상이어야 합니다. JWT_SECRET과 분리하고 서버 `.env`에만 둡니다. 모든 서명값에 `purpose`를 넣어 쿠키 간 재사용을 막습니다.
- **쿠키 Path:**
  - Backend는 외부 접두사를 모르므로 신규 `PUBLIC_PATH_PREFIX`(Staging `/career`, 기본값 `""`)를 기준으로 Path를 만듭니다.
  - 기존 `REFRESH_COOKIE_PATH`도 이 값을 사용합니다. 그러면 PR #271 문서 §4의 공유 nginx `proxy_cookie_path` 없이도 refresh 쿠키가 `/career/api/v1/auth/*`로 전달됩니다.
  - 기본값이 `""`이므로 로컬과 기존 테스트에는 영향이 없습니다.
- **게이트 판정**(`GET /auth/gate`와 미들웨어)
  - 매 요청마다 서명, 만료, `purpose`를 검증합니다.
  - **Allowlist도 다시 확인합니다**(파일 mtime 캐시). Allowlist에서 빼면 12시간을 기다리지 않고 바로 차단됩니다.

### 7.3 로그아웃
- **기존 `POST /auth/logout`:** 앱 세션만 끝냅니다(동작 변경 없음). 게이트 쿠키는 남기므로 로그아웃 후에도 로그인 화면이 보입니다.
  - 게이트 쿠키까지 지우면 SPA가 곧바로 게이트 → Google → 자동 로그인으로 되돌아가 "로그아웃이 안 되는" 현상이 생깁니다.
- **완전 로그아웃(공용 PC 등):** `GET /auth/google/signout`이 게이트와 refresh 쿠키를 지우고 게이트 밖의 정적 페이지를 보여 줍니다.

## 8. 보안 위협과 방어

### 8.1 ID Token 검증 (PyJWT `PyJWKClient`)
- **JWKS 조회:** `https://www.googleapis.com/oauth2/v3/certs`에서 키를 받아 캐시합니다(1시간, `kid` 미스 시 재조회).
- **허용 알고리즘:** `RS256`만 허용합니다.
- **클레임 검증**
  - `iss`가 `https://accounts.google.com` 또는 `accounts.google.com`일 것
  - `aud == GOOGLE_CLIENT_ID`
  - `azp`가 있으면 `azp == GOOGLE_CLIENT_ID`
  - `exp`와 `iat` 필수, leeway 60초
  - `nonce`는 tx 쿠키 값과 `compare_digest`로 비교
  - `email_verified is True`
  - `sub`와 `email`이 str일 것
- **토큰 교환:** `https://oauth2.googleapis.com/token`에 `client_secret`과 `code_verifier`를 POST합니다(timeout 10초, 표준 라이브러리 `urllib`).
- **의존성:** `requirements.txt`에 `PyJWT[crypto]`(→ `cryptography`)를 추가해야 하며, SBOM 갱신이 필요합니다. 그 밖의 신규 라이브러리는 없습니다.
- **테스트용 엔드포인트 재정의:** 엔드포인트 URL 재정의(`GOOGLE_*_URL`)는 `APP_ENV`가 local·test일 때만 허용합니다. Staging에서 설정되어 있으면 기동을 실패시킵니다(가짜 IdP 주입 방지).

### 8.2 위협 대응표
| 위협 | 방어 |
|---|---|
| 로그인 CSRF / code 주입 | state를 tx 쿠키에 바인딩(서명), PKCE S256, 1회용 tx 쿠키 |
| ID Token 재사용·위조 | nonce 바인딩, JWKS 서명, aud·azp·iss·exp 검증 |
| 토큰·이메일 URL 노출 | 리디렉트에는 상대 경로와 고정 오류 코드만 사용, 세션은 HttpOnly 쿠키와 `/auth/refresh`로 전달, `Cache-Control: no-store`, `Referrer-Policy: no-referrer` |
| 동일 이메일 계정 탈취 | 자동 연결 금지(§7.1), sub 기준 식별 |
| Allowlist 우회 | 서버 파일 정확 일치(소문자 비교, 와일드카드·도메인 불가), 빈 파일이면 전원 거부, `GOOGLE_LOGIN_ENABLED=1`인데 파일이 없으면 기동 실패, 게이트 판정 때마다 재확인 |
| 권한 상승 | 신규 계정은 `job_seeker`만, 역할은 매 요청 DB 재조회(기존) |
| 쿠키 위조·혼용 | HS256 별도 키, `purpose` 클레임, 짧은 수명 |
| 헤더 위조(oauth2-proxy 방식의 위험) | 앱이 `X-Forwarded-Email` 같은 신원 헤더를 **전혀 신뢰하지 않음** |
| Secret 유출 | Client Secret은 서버 파일(600, 읽기 전용 마운트)에 두고 로그 금지, GitHub·이슈 금지, 유출 시 `docs/ops/SECRET_ROTATION_RUNBOOK.md` 절차 |
| 무차별 시도 | 기존 `AttemptLimiter`로 start·callback·signup에 IP별 제한 |

### 8.3 API 접근 통제와 LAN 18080 우회
- **Backend `GoogleGateMiddleware`**(`GOOGLE_GATE_ENFORCED=1`일 때)
  - `/api/v1/*` 요청에 유효한 `career_gate`가 없으면 401 JSON `{"code":"EDGE_AUTH_REQUIRED"}`를 반환합니다.
  - 예외 경로: `/api/v1/auth/google/start`, `/api/v1/auth/google/callback`, `/api/v1/auth/google/signout`, `/api/v1/auth/gate`
  - `/health`·`/version`은 `/api/v1` 밖이라 Auto-CD 헬스체크에 영향이 없습니다.
  - 게이트 검사는 기존 Bearer 인증 **앞에서** 독립적으로 수행합니다. 로컬 로그인 사용자도 게이트 쿠키가 있어야 합니다.
- **LAN 우회 1(API):**
  - LAN `<사설IP>:18080/api/...`로 직접 오면 브라우저 경로가 `/career/`가 아니어서 게이트 쿠키가 전송되지 않습니다.
  - 그래서 **fail-closed 401**이 됩니다. 로컬 회원가입·로그인 API도 게이트 뒤에 있으므로 LAN에서 계정을 만들 수 없습니다.
- **LAN 우회 2(정적 SPA 셸):**
  - 데이터 없는 HTML·JS는 LAN에서 여전히 보입니다.
  - 해결하려면 서버 base compose의 frontend 포트를 `127.0.0.1:18080:80`만 남기면 됩니다. 저장소 `poc/staging/compose.yaml`은 이미 이렇게 되어 있으므로, 서버 사본이 저장소와 다른 부분을 맞추는 작업입니다.
  - frontend 컨테이너를 다시 만들어야 하므로 **#266에서 별도 승인 후** 수행합니다.
- **참고(범위 밖, 보고만):** 서버에는 DB LAN 프록시 `ai-career-db-lan-proxy`(LAN 15432)도 떠 있습니다. 이번 인증과는 무관하지만 LAN 노출 점검 대상으로 기록합니다.

### 8.4 `return_to`·`next` 검증 (Open Redirect 방지)
- **허용 조건:** `/career/`로 시작하는 상대 경로만 허용합니다.
- **거부 대상**
  - `//`, `\`, 제어문자, `@`를 포함한 값
  - URL 디코드 후 `..` 세그먼트가 있는 값
  - `/career/api/`로 시작하는 값
  - 길이가 512자를 넘는 값
- 위반하면 `/career/`로 대체합니다.
- nginx의 `$request_uri`를 그대로 넘기므로 쿼리 파라미터가 여러 개인 딥링크는 `&` 뒤가 잘릴 수 있습니다. 허용 가능한 한계로 기록합니다.

## 9. 공유 nginx 스니펫 (적용은 #266, 별도 승인)

`/etc/nginx/snippets/ai-career-route.conf` 교체안입니다. Redmine `/`와 `/church/` 블록은 수정하지 않으며, oauth2-proxy는 필요 없습니다.

```nginx
location = /career { return 301 /career/; }

# Backend가 스스로 게이트(미들웨어)를 검사한다. callback/start는 미들웨어 예외.
location /career/api/ {
    proxy_pass http://127.0.0.1:18080/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $dbresting_forwarded_proto;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

location = /career/_gate {
    internal;
    proxy_pass http://127.0.0.1:18080/api/v1/auth/gate;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Host $host;
}

location @career_google_start {
    return 302 /career/api/v1/auth/google/start?return_to=$request_uri;
}

location /career/ {
    auth_request /career/_gate;
    error_page 401 = @career_google_start;
    proxy_pass http://127.0.0.1:18080/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $dbresting_forwarded_proto;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```
- 기존 스니펫의 `sub_filter`는 PR #271 빌드(`/career/` base)가 배포되었으므로 제거합니다.
- `proxy_cookie_path`는 `PUBLIC_PATH_PREFIX`로 대체되므로 필요하지 않습니다.
- 실제 적용 전 `/tmp` 임시 설정으로 `nginx -t`를 실행하고, 원본 백업, graceful reload(`nginx -s reload`) 순서로 진행합니다. **ngrok 재시작은 필요하지 않습니다.**

## 10. 변경 대상 파일과 예상 범위 (STEP 03, 작은 PR 3개로 분리)

| PR | 파일 | 변경 |
|---|---|---|
| **03-a Backend** (플래그 기본값 꺼짐) | `app/core/auth_config.py` | `GoogleSettings`: CLIENT_ID, CLIENT_SECRET_FILE, REDIRECT_URI, ALLOWLIST_FILE, COOKIE_SECRET, PUBLIC_PATH_PREFIX, 두 플래그, 기동 검증 |
| | `app/services/google_oauth.py` (신규, ~200줄) | 인가 URL, 코드 교환, ID Token 검증, Allowlist, 서명 쿠키 |
| | `app/services/auth.py` | `google_callback_result()`, `complete_google_signup()`, `_validate_consents()` 일반화 |
| | `app/repositories/auth.py` | `NewUser.identity_provider/subject`, `password_hash: str \| None`, `find_identity()` |
| | `app/routers/auth.py` | 엔드포인트 6개, `REFRESH_COOKIE_PATH`에 `PUBLIC_PATH_PREFIX` 반영 |
| | `app/core/google_gate.py` (신규) + `app/main.py` | 게이트 미들웨어 등록 |
| | `app/core/errors.py`, `docs/api/openapi.yaml` | 오류 코드 4개, 계약 |
| | `requirements.txt`, SBOM | `PyJWT[crypto]` |
| | `tests/test_google_oauth.py`, `tests/test_google_gate.py`, `tests/test_auth_postgres.py` 확장, 기존 fake repo 갱신 | §11 |
| **03-b Frontend** | `pages/LoginPage.tsx` | "Google로 계속" 버튼(`<a href>` 전체 페이지 이동, 클릭 시 `rememberSession(autoLogin)`), `google_error` 안내 |
| | `pages/GoogleSignupPage.tsx` (신규), `components/ConsentFields.tsx` (SignupPage에서 분리) | 최초 약관 동의 |
| | `auth/AuthContext.tsx`, `routes.tsx`, `api/auth.ts`, `mocks/handlers.ts`, `schema.gen.ts` | done/signup 라우트, 세션 유지 처리(§6.4), API |
| **03-c 배포 구성** | `poc/staging/automation/compose.release.yaml` | Google 환경변수 전달, Secret·Allowlist 파일 읽기 전용 마운트 |
| | `docs/ops/career-google-auth/`(신규 README) | 서버 적용·롤백 절차 |
| | `docs/requirements/functional/ACCOUNT.md` | FR-ACC-008 Google 로그인 추가 |

- DB 마이그레이션: **없음**
- 예상 규모: Backend 약 600줄(테스트 포함 약 1,200줄), Frontend 약 400줄(테스트 포함)

## 11. 테스트 시나리오

### 11.1 pytest (가짜 Google: 로컬 RSA 키로 JWKS를 만들고 토큰 엔드포인트는 stub)
1. **start**
   - 302 URL에 `response_type=code`, `scope=openid email profile`, `code_challenge_method=S256`, state, nonce가 있음
   - `client_secret`은 없음
   - tx 쿠키 속성(Lax, HttpOnly, Secure, Path)이 올바름
2. **callback 거부:** 다음 각각에서 세션·게이트 쿠키를 발급하지 않음
   - tx 쿠키 없음, 위조, 만료
   - state 불일치
   - `error=access_denied` → `cancelled`
3. **ID Token 거부:** 서명 키 불일치, aud·azp·iss 불일치, exp 경과, nonce 불일치, `email_verified=false`, sub 누락, alg=none·HS256
4. **Allowlist**
   - 목록 밖이면 403 HTML이고 게이트 쿠키 없음
   - 빈 파일이면 전원 거부
   - 파일이 없으면 기동 실패
   - 대소문자 무시 정확 일치, 부분 문자열·도메인 일치는 거부
5. **기존 Google 사용자:** refresh 쿠키(Path `/career/api/v1/auth`)를 받고 done으로 리디렉트, `auth_sessions` 1행 생성, 비활성 사용자는 `failed`
6. **신규 사용자:** pending 쿠키만 발급되고 DB 행이 0개
7. **동일 이메일 로컬 계정**(gmail 점·`+` 정규화 포함): `email_conflict`, identity 미생성, 로컬 비밀번호 로그인은 정상
8. **signup 완료**
   - 필수 동의 누락은 422
   - pending 만료·위조는 401
   - Allowlist에서 제거된 상태면 403
   - 성공하면 users, `auth_identities(google, sub, password_hash NULL)`, `job_seeker`, consents, 세션이 생기고 pending이 삭제됨
   - 이중 제출은 같은 사용자로 멱등 처리
   - `EmailTaken` 경쟁은 409
9. **`return_to`:** `//evil.example`, `https://evil.example`, `/career/../x`, `/\evil`, `/career/api/v1/...`는 모두 `/career/`로 대체
10. **게이트 미들웨어**
    - 켜짐: 쿠키 없음·위조·만료·Allowlist 제거면 `/api/v1/me` 401 `EDGE_AUTH_REQUIRED`
    - 예외 경로와 `/health`는 통과
    - Bearer만 있고 게이트 쿠키가 없어도 401
11. **노출 검사:** 모든 응답의 `Location` 헤더와 로그에 이메일, sub, code, 토큰이 없음
12. **회귀:** 두 플래그가 꺼지면 Google 엔드포인트는 404, 미들웨어는 비활성, 기존 테스트 스위트는 수정 없이 통과(fake repo 시그니처 갱신만)
13. **PostgreSQL 통합:** `(google, sub)` UNIQUE, `password_hash` CHECK, 사용자 삭제 시 identity cascade

### 11.2 Frontend (Vitest)
- 로그인 버튼의 href가 `/career/api/v1/auth/google/start`이고 클릭 시 `rememberSession` 호출
- `google_error` 코드별 문구
- `GoogleSignupPage`
  - 필수 동의를 하지 않으면 제출 불가
  - pending 401이면 다시 시도 안내
  - 성공하면 홈으로 이동
- done 라우트에서 refresh 후 로그아웃되지 않음(§6.4 회귀 테스트)

### 11.3 Playwright (`frontend/e2e/*.mjs`, 외부 playwright-core, 로컬 가짜 IdP)
- 신규 사용자: 게이트 → 가짜 Google → 약관 → 홈 → 새로고침해도 로그인 유지
- 재방문 사용자: 약관 없이 자동 로그인
- 동일 이메일 충돌 → 로컬 로그인 안내
- Allowlist 밖 → 403 페이지(무한 리디렉트 없음)
- 로그아웃 → 로그인 화면이 보이고 다시 "Google로 계속"
- 완전 로그아웃 → 게이트 밖 정적 페이지

### 11.4 Staging 실제 검증 (#267, 실제 Google 계정, 결과만 기록)
- 허용 계정(신규·재방문), 비허용 계정, 로컬 계정과 동일 이메일
- `curl`로 `/career/api/v1/me`를 게이트 없이 호출하면 401
- LAN `:18080`으로 직접 `/api/v1/me`를 호출하면 401
- `/`(Redmine)와 `/church/` 응답 코드, 본문 해시가 적용 전후로 같음
- ngrok 무료 경고 페이지와 Google 리디렉트 체인의 상호작용 → **NOT_VERIFIED, #267에서 확인**

## 12. Staging 적용·롤백 절차 (#266, 단계별 승인)

| 단계 | 작업 | 확인 | 롤백 |
|---|---|---|---|
| 0 | 03-a·b·c 병합 → Auto-CD 배포(플래그 꺼짐) | 기존 로그인·회원가입 회귀, `/health` | 일반 Auto-CD 롤백 |
| 1 | Backend 컨테이너의 Google 외부 HTTPS 접근 점검(읽기 전용) | token·JWKS 엔드포인트 TLS 연결 | — |
| 2 | 서버에 `secrets/google_client_secret`(600)·`google_allowlist.txt`(PM이 제공한 이메일) 배치<br>`.env`에 `GOOGLE_*` 설정, `PUBLIC_PATH_PREFIX=/career`, `GOOGLE_LOGIN_ENABLED=1` (게이트는 아직 꺼짐) | 로그인 화면 "Google로 계속" → 실제 Google 로그인 → 신규·재방문 | `GOOGLE_LOGIN_ENABLED=0` 후 backend 재생성 |
| 3 | `GOOGLE_GATE_ENFORCED=1` + 공유 nginx 스니펫 교체(백업 → `nginx -t` → reload) | 익명 `/career/` → Google, 익명 API 401, Redmine·`/church/` 동일 | 스니펫 백업 복원 → reload, 플래그 0 |
| 4 | 서버 base compose frontend 포트를 `127.0.0.1`만으로 변경 → frontend 재생성 | LAN 18080 연결 거부 | 이전 compose 사본 복원 → 재생성 |

- **DB 롤백은 필요하지 않습니다.** 기능을 꺼도 Google identity 행은 남지만, 로그인 경로가 없어 무해합니다. 삭제가 필요하면 백업 후 별도 승인을 받아 처리합니다.
- **변하지 않는 것:** Redmine, `/church/`, ngrok 프로세스(웹·5432 TCP 모두), 크롤러, Auto-CD 설정
- **비용:** 각 단계 모두 추가 비용 0원입니다. ngrok 사용량은 Dashboard 확인 전까지 NOT_VERIFIED입니다.

## 13. Issue #265 · PR #272와의 관계

- #265와 PR #272는 "**oauth2-proxy 1차 게이트 + 앱 자체 2차 수동 로그인**"을 설계했습니다.
- 이 설계는 1차 게이트와 앱 계정 로그인을 **Backend 하나로 합친 대안**입니다. 채택되면 oauth2-proxy 프로세스, 그 설정, 헤더 신뢰 문제가 모두 필요 없어집니다.
- **PR #272:** 병합하지 않고 변경하지도 않았습니다. 이 설계가 승인되면 PM이 "superseded by #328"로 닫을지 결정합니다. 재사용 가능한 항목은 nginx 우회 검토, Google Console 절차, 비용표입니다.
- **#265:** 비용과 Callback 검증 항목은 이 설계에도 그대로 적용됩니다. 종료 여부는 PM이 결정하며 이번 작업에서는 변경하지 않습니다.
- **#266(적용)·#267(E2E):** §12와 §11.4가 각각의 입력이 됩니다. 두 이슈 본문의 "2차 수동 로그인" 문구는 PM 결정 후 갱신해야 합니다.
- **#263(상위):** 인증 구조가 "1차 Google 인증 후 수동 2차 로그인"에서 "Google 인증 후 자동 가입·로그인 + 로컬 로그인 병행"으로 바뀌므로, PM 승인이 필요합니다.
