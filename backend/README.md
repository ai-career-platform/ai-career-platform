# AI Career Platform — Backend (T13 골격)

정식 FastAPI Backend 애플리케이션입니다. `poc/staging/backend/main.py`(Staging PoC)와는 **별개**이며 PoC와 자동 배포 설정은 변경하지 않습니다.

> 상태: 골격만 구현. `/api/v1` 서비스 API는 [API 계약 초안](../docs/API_CONTRACT.md) 확정(T06) 후 기능별 일감에서 추가합니다.

## 구조

```text
backend/
├── app/
│   ├── main.py            # create_app() 팩토리, lifespan(시작/종료), 라우터 등록
│   ├── core/config.py     # 환경변수 기반 Settings
│   ├── routers/           # HTTP 계층 (system: /health·/version, api_v1: /api/v1 진입점)
│   ├── services/          # 업무 규칙
│   ├── repositories/      # DB 쿼리 (T14에서 DB 연결과 함께 추가)
│   └── schemas/           # Pydantic DTO
├── tests/test_smoke.py    # 기동·종료·OpenAPI smoke 테스트
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

`.env` 파일은 자동으로 읽지 않습니다. 실행 환경에서 변수를 설정하세요. 앱에는 최소권한 계정을 사용하고 Migration에는 별도의 계정을 사용합니다. DB 접근은 SQLAlchemy 2.x(psycopg 3 드라이버)를 사용합니다. `app.db.get_db`는 요청마다 `Session` 하나를 제공하고, 요청이 끝나면 남은 트랜잭션을 롤백한 뒤 연결을 풀에 반환합니다. 쓰기 호출자가 성공 시 `session.commit()`을 명시적으로 호출합니다. ORM 모델은 `app.models.Base`를 상속하고, 응답 스키마는 `app.schemas.base.ORMModel`(`from_attributes=True`)을 상속합니다.

## 현재 API

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 앱 상태 `{"status":"ok","service":"ai-career-backend"}` |
| GET | `/health/db` | PostgreSQL에서 `SELECT 1` 실행. 접속 실패 시 503 |
| GET | `/version` | 애플리케이션·환경·버전 |
| GET | `/openapi.json`, `/docs` | OpenAPI / Swagger UI |

## 기능 추가 방법

1. `app/schemas/<기능>.py`에 요청·응답 DTO
2. `app/repositories/<기능>.py`에 DB 쿼리
3. `app/services/<기능>.py`에 업무 규칙
4. `app/routers/<기능>.py`에 `APIRouter`를 만들고 `app/routers/api_v1.py`에서 `api_router.include_router(...)`
5. `tests/`에 정상·예외(401/403/404/422 등) 테스트
