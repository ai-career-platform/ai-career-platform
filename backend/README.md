# AI Career Platform — Backend

정식 FastAPI Backend 애플리케이션입니다. `poc/staging/backend/main.py`(Staging PoC)와는 **별개**이며 PoC와 자동 배포 설정은 변경하지 않습니다.

> 상태: T13 골격 + T14 DB 세션 + T15 인증·인가. 나머지 `/api/v1` 서비스 API는 [API 계약](../docs/API_CONTRACT.md)·[OpenAPI](../docs/api/openapi.yaml)에 따라 기능별 일감에서 추가합니다.

## 구조

```text
backend/
├── app/
│   ├── main.py            # create_app() 팩토리, lifespan(시작/종료), 라우터 등록
│   ├── core/config.py     # 환경변수 기반 Settings(DatabaseSettings 포함)
│   ├── db.py              # SQLAlchemy 엔진·Session 팩토리·get_db 의존성
│   ├── models/            # SQLAlchemy ORM 모델(Base, auth.py: users·auth_sessions·roles 등 계정 테이블)
│   ├── core/auth_config.py # 인증 설정 (JWT 키·토큰 수명·시도 제한)
│   ├── core/security.py   # 비밀번호 해시(Argon2id)·비교용 이메일·JWT(HS256)
│   ├── core/rate_limit.py # 로그인·가입 시도 제한 (프로세스 메모리)
│   ├── dependencies/auth.py # get_current_user · require_roles · require_permissions · ensure_owner
│   ├── core/errors.py     # 에러 코드·메시지 카탈로그(ERROR_CATALOG)와 AppError
│   ├── core/exception_handlers.py  # 글로벌 예외 핸들러 → {code, status, message} 응답
│   ├── core/request_id.py # X-Request-ID 미들웨어
│   ├── routers/           # HTTP 계층 (system: /health·/version, api_v1: /api/v1 진입점)
│   ├── services/          # 업무 규칙
│   ├── repositories/      # DB 쿼리 (`get_db`의 Session으로 쿼리)
│   └── schemas/           # Pydantic DTO (base.py: ORMModel, error.py: ErrorResponse)
├── tests/test_smoke.py    # 기동·종료·OpenAPI smoke 테스트
├── tests/test_errors.py   # 공통 에러 계약 테스트
├── tests/test_auth*.py, test_authz.py, test_security.py  # T15 인증·인가 (test_auth_postgres.py는 실DB 선택 실행)
├── requirements.txt       # 실행 의존성 (PoC와 동일 버전 pin)
├── requirements-dev.txt   # + pytest, httpx
└── pytest.ini
```

요청 흐름: `routers` → `services` → `repositories` → DB. 라우터에 업무 로직이나 SQL을 직접 쓰지 않습니다.

## 실행 (Windows 11 PowerShell, Python 3.12)

```powershell
Set-Location "$HOME\projects\ai-career-platform\backend"
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

8000 포트가 사용 중이면 `--port`를 다른 값으로 바꿉니다. 다른 프로그램을 임의로 종료하지 않습니다.

확인:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/version
(Invoke-RestMethod http://127.0.0.1:8000/openapi.json).paths.PSObject.Properties.Name
Start-Process http://127.0.0.1:8000/docs
```

## 테스트

```powershell
Set-Location "$HOME\projects\ai-career-platform\backend"
.\.venv\Scripts\python.exe -m pytest -q
```

## 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `APP_ENV` | `local-dev` | `/version`의 environment |
| `APP_VERSION` | `0.1.0` | `/version`의 version, OpenAPI 버전 |
| `DATABASE_URL` | 미설정 | PostgreSQL 앱 계정 URL. 미설정 시 DB 경로는 503을 반환합니다. |
| `DB_POOL_SIZE` | `5` | 프로세스당 최대 연결 수 (1–100) |
| `DB_TIMEOUT_SECONDS` | `5` | 풀 대기 및 접속 시간 제한(초, 1–60) |
| `JWT_SECRET` | 미설정 | access token(HS256) 서명 키, 32자 이상. local-dev/test에서 없으면 프로세스마다 임의 키(재시작 시 로그인 풀림), 그 외 환경은 기동 실패 |
| `ACCESS_TOKEN_TTL_SECONDS` | `900` | access token 수명 (60–3600) |
| `REFRESH_TOKEN_TTL_SECONDS` | `1209600` | refresh token·세션 수명, 14일 |
| `AUTH_COOKIE_SECURE` | `true` | refresh 쿠키 `Secure`. http 로컬 확인 때만 `false` |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCK_SECONDS` | `5` / `900` | 같은 계정 연속 실패 5회 → 15분 잠금 (429 + `Retry-After`) |
| `LOGIN_IP_MAX_ATTEMPTS` | `30` | 같은 IP 로그인 시도 한도 / `AUTH_RATE_WINDOW_SECONDS`(900초) |
| `SIGNUP_IP_MAX_ATTEMPTS` | `10` | 같은 IP 가입 시도 한도 / 1시간 |

`.env` 파일은 자동으로 읽지 않습니다. 실행 환경에서 변수를 설정하세요. 앱에는 최소권한 계정을 사용하고 Migration에는 별도의 계정을 사용합니다. DB 접근은 SQLAlchemy 2.x(psycopg 3 드라이버)를 사용합니다. `app.db.get_db`는 요청마다 `Session` 하나를 제공하고, 요청이 끝나면 남은 트랜잭션을 롤백한 뒤 연결을 풀에 반환합니다. 쓰기 호출자가 성공 시 `session.commit()`을 명시적으로 호출합니다. ORM 모델은 `app.models.Base`를 상속하고, 응답 스키마는 `app.schemas.base.ORMModel`(`from_attributes=True`)을 상속합니다.

## 현재 API

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 앱 상태 `{"status":"ok","service":"ai-career-backend"}` |
| GET | `/health/db` | PostgreSQL에서 `SELECT 1` 실행. 접속 실패 시 503 `DEPENDENCY_UNAVAILABLE` |
| GET | `/version` | 애플리케이션·환경·버전 |
| GET | `/openapi.json`, `/docs` | OpenAPI / Swagger UI |
| POST | `/api/v1/auth/signup` | 가입 + 필수 약관 동의 → 201 access token + refresh 쿠키 |
| POST | `/api/v1/auth/login` | 로그인(비교용 이메일) → 200, 실패 401, 반복 실패 429 |
| POST | `/api/v1/auth/refresh` | refresh 쿠키 회전 → 새 access token. 이전 refresh 즉시 무효 |
| POST | `/api/v1/auth/logout` | 현재 세션 폐기 + 쿠키 삭제 → 204 |
| GET | `/api/v1/consent-policies` | 시행 중 약관 목록 (비로그인) |
| GET | `/api/v1/me`, `/api/v1/me/permissions` | 내 계정·역할·권한 |
| GET/DELETE | `/api/v1/me/sessions[/{session_id}]` | 로그인 기기 목록·다른 기기 로그아웃 |
| GET | `/api/v1/me/target-roles` | 내 목표 직무를 우선순위 순으로 조회 |
| PUT | `/api/v1/me/target-roles` | 목표 직무를 최대 3개까지 전체 교체 |

## 인증·인가 사용법 (T15)

새 기능 라우터는 아래 의존성만 쓰면 됩니다. 사용자는 항상 토큰의 `sub`로 정하고, 경로·본문으로 user_id를 받지 않습니다.

```python
from fastapi import Depends
from app.dependencies.auth import CurrentUserDep, ensure_owner, require_permissions, require_roles

@router.get("/me/documents")                                         # 토큰 없음·만료·폐기 → 401
def list_docs(user: CurrentUserDep): ...

@router.get("/admin/audit", dependencies=[Depends(require_roles("admin"))])  # 역할 없음 → 403
def audit(): ...

@router.get("/documents/{document_id}")
def get_doc(document_id: UUID, user: CurrentUserDep):
    doc = repo.get_document(document_id)
    ensure_owner(doc.owner_user_id if doc else None, user)           # 남의 것·없음 → 404
```

- 매 요청 DB에서 세션(폐기·만료)·계정 상태·역할을 다시 읽습니다. 로그아웃·역할 회수·정지는 다음 요청부터 반영되며 토큰 안의 `roles`는 신뢰하지 않습니다.
- 토큰이 없거나 틀린 요청은 DB 연결 전에 401로 끝납니다.
- 실DB 통합 테스트: `tests/test_auth_postgres.py` 상단 주석 참고 (`T15_TEST_DATABASE_URL`, 일회용 DB 전용, T05 DDL + T10 Seed 사용).

## 공통 에러 처리

모든 오류는 `code`, `status`, `message` 세 필드만 보냅니다 (`application/json`). 계약: [API_CONTRACT.md §1.4](../docs/API_CONTRACT.md#14-오류).

```json
{"code": "EMAIL_TAKEN", "status": 409, "message": "이미 가입된 이메일입니다."}
```

### 서비스·라우터에서 오류 내기

`HTTPException`을 쓰지 말고 코드만 골라 `AppError`를 raise 합니다. 상태와 메시지는 카탈로그에서 정해집니다.

```python
from app.core.errors import AppError, ErrorCode

raise AppError(ErrorCode.EMAIL_TAKEN)                                  # 409 이미 가입된 이메일입니다.
raise AppError(ErrorCode.NOT_FOUND)                                    # 404 (다른 사람 소유도 404)
raise AppError(ErrorCode.RATE_LIMITED, retry_after=30)                 # 429 + Retry-After: 30
raise AppError(ErrorCode.DUPLICATE_SKILL, log_detail=f"skill_id={sid}") # 422, log_detail은 로그에만
```

### 오류 메시지 관리 규칙

- 메시지는 [`app/core/errors.py`](app/core/errors.py)의 `ERROR_CATALOG` **한 곳**에만 있습니다. 문구를 바꿀 때는 여기만 고칩니다.
- 호출하는 쪽에서 메시지 문자열을 직접 쓰지 않습니다. 다른 문구가 필요하면 새 `ErrorCode`를 추가합니다.
- 메시지는 사용자에게 그대로 보여 줄 문장입니다. 내부 정보(경로, SQL, 예외 내용, 입력값)는 넣지 않습니다.
- 개발자용 원인은 `log_detail=`로 넘깁니다. 응답에는 나가지 않고 `X-Request-ID`와 함께 로그에 남습니다.
- 코드를 추가·변경하면 [API_CONTRACT.md §1.4](../docs/API_CONTRACT.md#14-오류) 표와 `openapi.yaml` 예시도 맞춥니다. `tests/test_errors.py`가 셋이 다르면 실패합니다.

### 핸들러가 자동으로 바꾸는 오류

| 상황 | 응답 code | 로그에 남는 것 |
|---|---|---|
| `AppError` | 예외의 code | code, request_id, log_detail |
| Pydantic 요청 검증 실패 (본문·쿼리·경로) | 422 `VALIDATION_FAILED` | 틀린 필드 위치와 종류 (입력값은 남기지 않음) |
| 깨진 JSON 본문 | 400 `MALFORMED_JSON` | |
| 없는 경로 / 허용 안 된 메서드 | 404 `NOT_FOUND` / 405 `METHOD_NOT_ALLOWED` | |
| 그 밖의 모든 예외 | 500 `INTERNAL_ERROR` | 스택트레이스 |

401은 `WWW-Authenticate: Bearer`가 자동으로 붙습니다. 모든 응답(성공 포함)에 `X-Request-ID` 헤더가 붙고, 오류 화면은 이 값을 문의용 요청 번호로 보여 줍니다. `/api/v1` 라우터는 OpenAPI에 422·500의 `ErrorResponse`를 자동으로 표시합니다.

## 기능 추가 방법

1. `app/schemas/<기능>.py`에 요청·응답 DTO
2. `app/repositories/<기능>.py`에 DB 쿼리
3. `app/services/<기능>.py`에 업무 규칙
4. `app/routers/<기능>.py`에 `APIRouter`를 만들고 `app/routers/api_v1.py`에서 `api_router.include_router(...)`
5. 오류는 `raise AppError(ErrorCode.XXX)` (위 [공통 에러 처리](#공통-에러-처리))
6. `tests/`에 정상·예외(401/403/404/422 등) 테스트 — 응답 형식은 `tests/test_errors.py`의 `assert_error` 참고
