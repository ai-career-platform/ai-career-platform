# Google SSO Staging 적용·롤백 절차 (#328 STEP 03-c → #266, 검증은 #267)

- 대상: `https://sulfite-footbath-next.ngrok-free.dev/career/`만입니다. Redmine(`/`), `/church/`, ngrok 프로세스(웹·5432 TCP)는 바꾸지 않습니다.
- 코드
  - Backend: PR #330 (`GOOGLE_*` 플래그 기본 OFF)
  - Frontend: STEP 03-b PR
  - 설계: PR #329 `docs/security/GOOGLE_SSO_AUTO_SIGNUP_DESIGN.md`
- 이 문서와 `poc/staging/automation/compose.release.yaml` 변경만으로는 서버가 바뀌지 않습니다. 아래 단계는 운영자가 승인을 받은 뒤 순서대로 실행합니다.
- 비밀값(Client Secret, 쿠키 키, Allowlist 이메일)은 서버 파일과 서버의 비공개 `.env`에만 둡니다. Git·이슈·로그·이미지에는 넣지 않습니다.

## 0. 2026-11-13 읽기 전용 점검 결과 (변경 없음)

| 항목 | 상태 |
|---|---|
| 배포 SHA | `82ca9e4` = main, `/api/version` 확인 |
| Health | `/api/health` 200, `/api/health/db` 200 |
| `/`·`/church/`·`/career/`·`/career/login` | 모두 200 |
| Google 엔드포인트 | `/api/v1/auth/gate` 404 (현재 이미지에 기능 없음) |
| Backend 외부 HTTPS | Google JWKS 200, token endpoint 도달(400 응답이 정상) |
| Backend 프로세스 | `uvicorn main:app` 단일 프로세스(`--workers` 없음). `OneTimeUse` 메모리 1회용 전제가 성립하며, 컨테이너 사용자는 root |
| 진입점 | `poc/staging/backend/main.py`가 `app.main.create_app()`을 써서 Google 라우터·미들웨어가 그대로 포함됨 |
| 공유 nginx 스니펫 | `/etc/nginx/snippets/ai-career-route.conf` (md5 `35096002…`), PR #271 §4 `proxy_cookie_path` 적용본, `sub_filter` 없음 |
| frontend 포트 | **`127.0.0.1:18080`과 LAN IP `:18080`에 함께 바인딩.** 서버 base `compose.yaml`에만 있는 차이(저장소는 loopback만) |
| Auto-CD | `automation/config.json`이 base `compose.yaml` sha256(`1cb3bcdc…`)을 고정하고 있어 compose를 바꾸면 `COMPOSE_BASELINE_MISMATCH`로 HOLD |
| 서버 `compose.release.yaml` | 저장소 사본과 다름(서버에는 `CRAWLER_NIGHT_POLICY_FILE`과 `crawler-policy` 볼륨이 있음). **서버 사본에 아래 §2 줄만 추가하고 통째로 덮어쓰지 않음** |
| `.env`의 Google 키 | 없음 |
| AI Career Google Client Secret | **서버에 없음.** `~/Downloads`에 다른(예전 Redmine) Client의 secret JSON이 있으나 사용하지 않음. 권한이 `0664`이므로 소유자가 정리할 것을 권고 |

## 1. 선행 조건 (모두 충족해야 진행)

1. PR #330(Backend)과 STEP 03-b(Frontend)가 독립 리뷰 승인 후 main에 병합되었고, Auto-CD가 그 SHA를 배포해 `/api/version` = main인 상태
2. **PM이 서버에 Client Secret 파일을 배치함**
   - Google Cloud Console에서 기존 "AI Career Google Login" Client의 secret을 받아 둡니다. 새로 만들지 않습니다.
   - 에이전트는 secret 값을 만들거나 추측하지 않습니다.
3. PM이 허용 이메일 목록을 확정함(11~30명, 정확한 주소)
   - 실제 로그인할 계정은 **Google Auth Platform 테스트 사용자이면서 Backend Allowlist에도 있어야** 합니다. 둘은 별개입니다.
4. ngrok 요금제·당월 사용량이 무료 한도 안임을 Dashboard에서 확인(그 전까지 비용은 NOT_VERIFIED)

## 2. 설정 준비 (기능 OFF 유지)

```bash
cd /home/kant/ai-career-staging-poc
TS=$(date -u +%Y%m%dT%H%M%SZ)
cp -p automation/compose.release.yaml automation/compose.release.yaml.bak-google-$TS
cp -p .env .env.bak-google-$TS                       # 내용은 출력하지 않음
install -d -m 700 google-auth
install -m 600 /dev/null google-auth/allowlist.txt   # 빈 파일 = 전원 거부(fail closed)
# PM: google-auth/client_secret 에 Client Secret '값' 한 줄만 저장(권한 600). JSON 파일이면 client_secret 값만 옮긴다.
# PM: google-auth/allowlist.txt 에 허용 이메일을 한 줄에 하나씩(와일드카드·도메인 금지)
```

서버 `automation/compose.release.yaml`의 backend `environment:`와 `volumes:`에 저장소 PR의 Google 줄을 **추가**합니다(기존 crawler 줄은 유지). 서버 `.env`에는 아래 키를 추가합니다(값은 출력하지 않음).

```text
PUBLIC_PATH_PREFIX=/career
GOOGLE_LOGIN_ENABLED=0
GOOGLE_GATE_ENFORCED=0
GOOGLE_CLIENT_ID=<AI Career Google Login 의 Client ID>
GOOGLE_CLIENT_SECRET_FILE=/run/google-auth/client_secret
GOOGLE_REDIRECT_URI=https://sulfite-footbath-next.ngrok-free.dev/career/api/v1/auth/google/callback
GOOGLE_ALLOWLIST_FILE=/run/google-auth/allowlist.txt
GOOGLE_COOKIE_SECRET=<새 임의값 48자 이상, JWT_SECRET 과 다르게: python3 -c "import secrets;print(secrets.token_urlsafe(48))">
```

값 없이 형식만 확인합니다.
- `python -m app.core.env_contract --target staging`을 backend 컨테이너 안에서 실행해 결과를 확인합니다.
- `stat -c '%a' google-auth/*`가 600인지 확인합니다.

## 3. 기능 OFF 상태로 재기동 (F-02)

- 다음 Auto-CD 배포에서 반영되며, 수동으로 반영할 때도 Auto-CD와 같은 명령만 씁니다(`up -d --no-build --no-deps --pull never frontend backend`, `down`·`-v` 금지).
- 확인 항목
  - `/api/health` 200
  - 로컬 로그인·회원가입·refresh 회귀
  - `/api/v1/auth/gate` 404
  - `/`·`/church/` 200

## 4. Google 로그인만 켜기 (F-03, 게이트 OFF)

1. `.env`에 `GOOGLE_LOGIN_ENABLED=1`을 넣고 backend를 재생성합니다.
   - 설정이 틀리면 기동이 거부되며(fail closed) Health가 실패하면 즉시 §7 롤백입니다.
2. `/api/v1/auth/gate`가 401로 바뀌면 기능이 켜진 것입니다. 로그인 화면에 "Google로 계속하기"가 보입니다.
3. **PM이 일반 브라우저에서 Google 로그인을 직접 완료**합니다. 에이전트는 비밀번호·2FA를 다루지 않습니다.
   - 최초 사용: 약관 화면 → 가입 → 홈 화면
   - 재방문: 약관 화면 없이 로그인
4. DB 확인(건수만): `auth_identities provider='google'` 1건, `password_hash IS NULL`, `job_seeker`, 동의·세션 행
5. 로컬 로그인 회귀를 확인합니다.

## 5. 게이트 켜기 (F-04) — §4가 실제로 성공한 뒤에만

```bash
sudo cp -p /etc/nginx/snippets/ai-career-route.conf /etc/nginx/snippets/ai-career-route.conf.bak-google-$TS
sudo install -m 644 docs/ops/google-sso/ai-career-route.gate.conf /etc/nginx/snippets/ai-career-route.conf
sudo nginx -t && sudo systemctl reload nginx          # 실패하면 백업 복원. ngrok 재시작 없음
# .env: GOOGLE_GATE_ENFORCED=1 → backend 재생성
```

- 익명으로 `/career/`에 들어가면 Google로 이동하고, 익명 `/career/api/v1/me`는 401 `EDGE_AUTH_REQUIRED`입니다.
- `/`와 `/church/`는 이전과 같은 응답이어야 합니다.
- 스니펫은 `nginx -t`(Staging nginx, `/tmp` 임시 설정)로 문법 검증을 마쳤습니다(2026-11-13).

## 6. LAN 18080 축소 (F-05)

```bash
cp -p compose.yaml compose.yaml.bak-google-$TS
cp -p automation/config.json automation/config.json.bak-google-$TS
# compose.yaml 의 frontend ports 에서 '<LAN IP>:18080:80' 한 줄만 지운다(저장소 사본과 같아짐)
python3 - <<'PY'   # Auto-CD 기준 해시 갱신(없으면 COMPOSE_BASELINE_MISMATCH 로 HOLD)
import hashlib, json, pathlib
c = pathlib.Path('automation/config.json'); d = json.loads(c.read_text())
d['compose_sha256'] = hashlib.sha256(pathlib.Path('compose.yaml').read_bytes()).hexdigest()
c.write_text(json.dumps(d, indent=2) + '\n')
PY
# frontend 만 재생성(현재 배포 이미지 그대로): Auto-CD 와 같은 compose 인자 + FRONTEND_IMAGE/BACKEND_IMAGE/DEPLOY_SHA
ss -ltn | grep 18080       # 127.0.0.1:18080 만 남아야 함
```

## 7. 롤백

| 단계 | 롤백 |
|---|---|
| §5 게이트 | 스니펫 백업 복원 → `nginx -t` → reload, `.env` `GOOGLE_GATE_ENFORCED=0` → backend 재생성 |
| §4 로그인 | `.env` `GOOGLE_LOGIN_ENABLED=0` → backend 재생성(Google 경로 404) |
| §6 포트 | `compose.yaml`·`config.json` 백업 복원 → frontend 재생성 |
| 코드 | 이전 main SHA로 Auto-CD 정상 경로 사용(직접 이미지 교체 금지) |

- DB 롤백은 필요 없습니다. Google identity 행은 남지만 로그인 경로가 없어 무해합니다. 삭제가 필요하면 백업 후 별도 승인을 받습니다.
- 금지: DB 초기화, `docker compose down -v`, ngrok 재시작, Redmine·`/church/` 설정 변경

## 8. 실제 E2E (#267)

로컬 브라우저 E2E는 가짜 IdP로 같은 시나리오를 먼저 확인했습니다(`scripts/e2e/google_sso/README.md`, 10/10). Staging에서는 아래 Case를 PM 계정으로 실제 실행하고, 결과는 PASS·FAIL·BLOCKED·NOT_RUN 가운데 하나로 기록합니다.

| Case | 내용 |
|---|---|
| 01 | 신규 사용자 |
| 02 | 재방문 사용자 |
| 03 | 미허용 계정 |
| 04 | 로컬 계정과 이메일 충돌 |
| 05 | 세션 유지 |
| 06 | 로그아웃 |
| 07 | 직접 API 접근과 LAN 우회 |
| 08 | `/`·`/church/` 회귀 |
