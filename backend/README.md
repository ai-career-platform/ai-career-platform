# AI Career Platform — Backend (T13 골격)

정식 FastAPI Backend 애플리케이션입니다. `poc/staging/backend/main.py`(Staging PoC)와는 **별개**이며 PoC와 자동 배포 설정은 변경하지 않습니다.

> 상태: 골격만 구현. `/api/v1` 서비스 API는 [API 계약 초안](../docs/API_CONTRACT.md) 확정(T06) 후 기능별 일감에서 추가합니다.

## 구조

```text
backend/
├── app/
│   ├── main.py            # create_app() 팩토리, lifespan(시작/종료), 라우터 등록
│   ├── core/config.py     # 환경변수 기반 Settings
│   ├── core/errors.py     # 공통 에러 코드(ErrorCode)와 앱 예외(AppError 하위 클래스)
│   ├── core/exception_handlers.py  # 글로벌 예외 핸들러 → ProblemDetail 응답
│   ├── core/request_id.py # X-Request-ID 미들웨어
│   ├── routers/           # HTTP 계층 (system: /health·/version, api_v1: /api/v1 진입점)
│   ├── services/          # 업무 규칙
│   ├── repositories/      # DB 쿼리 (T14에서 DB 연결과 함께 추가)
│   └── schemas/           # Pydantic DTO (error.py: ProblemDetail·FieldError)
├── tests/test_smoke.py    # 기동·종료·OpenAPI smoke 테스트
├── tests/test_errors.py   # 공통 에러 계약 테스트
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

`.env` 파일은 자동으로 읽지 않습니다. DB 접속 설정과 `/health/db`는 T14(DB 연결·세션 수명주기)에서 추가합니다.

## 현재 API

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 앱 상태 `{"status":"ok","service":"ai-career-backend"}` |
| GET | `/version` | 애플리케이션·환경·버전 |
| GET | `/openapi.json`, `/docs` | OpenAPI / Swagger UI |

## 공통 에러 처리

모든 오류는 `application/problem+json` 형식의 `ProblemDetail`로 응답합니다. 계약: [API_CONTRACT.md §1.4](../docs/API_CONTRACT.md#14-오류).

```json
{"type": "https://docs.ai-career.invalid/problems/email-taken", "title": "Email already registered",
 "status": 409, "code": "EMAIL_TAKEN", "request_id": "req-3f9a1c0b7d2e4a61"}
```

### 서비스·라우터에서 오류 내기

`HTTPException`을 쓰지 말고 `app.core.errors`의 예외를 raise 합니다. 응답 변환은 글로벌 핸들러가 합니다.

```python
from app.core.errors import ConflictError, ErrorCode, NotFoundError, ValidationFailedError

raise ConflictError(ErrorCode.EMAIL_TAKEN)                     # 409
raise NotFoundError()                                          # 404 NOT_FOUND (다른 사람 소유도 404)
raise ValidationFailedError(ErrorCode.DUPLICATE_SKILL,         # 422 + errors
                            errors=[{"field": "items[1].skill_id", "code": "DUPLICATE"}])
raise RateLimitedError(retry_after=30)                         # 429 + Retry-After
```

| 예외 | 상태 | 기본 code |
|---|---|---|
| `BadRequestError` | 400 | `BAD_REQUEST` |
| `UnauthorizedError` | 401 (+ `WWW-Authenticate: Bearer`) | `UNAUTHENTICATED` |
| `ForbiddenError` | 403 | `FORBIDDEN` |
| `NotFoundError` | 404 | `NOT_FOUND` |
| `ConflictError` | 409 | `CONFLICT` |
| `PayloadTooLargeError` / `UnsupportedMediaTypeError` | 413 / 415 | `FILE_TOO_LARGE` / `UNSUPPORTED_FILE_TYPE` |
| `ValidationFailedError` | 422 | `VALIDATION_FAILED` |
| `RateLimitedError` | 429 (+ `Retry-After`) | `RATE_LIMITED` |
| `DependencyUnavailableError` / `DependencyTimeoutError` | 503 / 504 | `DEPENDENCY_UNAVAILABLE` / `DEPENDENCY_TIMEOUT` |

새 `code`가 필요하면 `ErrorCode`와 `DEFAULT_TITLES`, 그리고 API_CONTRACT.md §1.4 표에 함께 추가합니다(테스트가 제목 누락을 잡습니다).

### 핸들러가 자동으로 바꾸는 오류

| 상황 | 응답 |
|---|---|
| Pydantic 요청 검증 실패 (본문·쿼리·경로) | 422 `VALIDATION_FAILED` + `errors[{field, code}]`. 입력값은 넣지 않음 |
| 깨진 JSON 본문 | 400 `MALFORMED_JSON` |
| 없는 경로 / 허용 안 된 메서드 | 404 `NOT_FOUND` / 405 `METHOD_NOT_ALLOWED` |
| 그 밖의 모든 예외 | 500 `INTERNAL_ERROR`. 고정 문구만 보내고 원인은 로그(`request_id`)에만 |

모든 응답(성공 포함)에 `X-Request-ID` 헤더가 붙습니다. `/api/v1` 라우터는 OpenAPI에 422·500의 `ProblemDetail` 응답을 자동으로 표시합니다.

## 기능 추가 방법

1. `app/schemas/<기능>.py`에 요청·응답 DTO
2. `app/repositories/<기능>.py`에 DB 쿼리
3. `app/services/<기능>.py`에 업무 규칙
4. `app/routers/<기능>.py`에 `APIRouter`를 만들고 `app/routers/api_v1.py`에서 `api_router.include_router(...)`
5. 오류는 `app.core.errors` 예외로 raise (위 [공통 에러 처리](#공통-에러-처리))
6. `tests/`에 정상·예외(401/403/404/422 등) 테스트 — 응답 형식은 `tests/test_errors.py`의 `assert_problem` 참고
