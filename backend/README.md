# AI Career Platform — Backend (T13 골격)

정식 FastAPI Backend 애플리케이션입니다. `poc/staging/backend/main.py`(Staging PoC)와는 **별개**이며 PoC와 자동 배포 설정은 변경하지 않습니다.

> 상태: T13 골격 + T16 내 프로필 조회·부분수정 후보 구현. T14 DB 연결과 T15 인증이 main에 없어 T16 실연동은 대기 중입니다. 기본 앱은 미인증 401, 인증/저장소 미연동 503으로 차단하며 테스트용 인증을 운영에 제공하지 않습니다. [T16 구현·검증](../docs/work-orders/initial-30/T16_IMPLEMENTATION.md)을 참조하세요.

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

`.env` 파일은 자동으로 읽지 않습니다. DB 접속 설정과 `/health/db`는 T14(DB 연결·세션 수명주기)에서 추가합니다.

## 현재 API

| Method | Path | 설명 |
|---|---|---|
| GET | `/health` | 앱 상태 `{"status":"ok","service":"ai-career-backend"}` |
| GET | `/version` | 애플리케이션·환경·버전 |
| GET/PATCH | `/api/v1/me` | 내 프로필 조회·부분수정 (T14/T15 실연동 전 차단) |
| GET | `/openapi.json`, `/docs` | OpenAPI / Swagger UI |

## 기능 추가 방법

1. `app/schemas/<기능>.py`에 요청·응답 DTO
2. `app/repositories/<기능>.py`에 DB 쿼리
3. `app/services/<기능>.py`에 업무 규칙
4. `app/routers/<기능>.py`에 `APIRouter`를 만들고 `app/routers/api_v1.py`에서 `api_router.include_router(...)`
5. `tests/`에 정상·예외(401/403/404/422 등) 테스트
