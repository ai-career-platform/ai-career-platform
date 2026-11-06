"""글로벌 예외 핸들러. 모든 오류를 `{code, status, message}` 응답으로 바꿉니다.

| 들어오는 예외 | 응답 code |
|---|---|
| AppError | 예외의 code (상태·메시지는 ERROR_CATALOG) |
| RequestValidationError (Pydantic 요청 검증) | 422 VALIDATION_FAILED |
| 잘못된 JSON 본문 | 400 MALFORMED_JSON |
| Starlette HTTPException (없는 경로, 허용 안 된 메서드 등) | 404 NOT_FOUND / 405 METHOD_NOT_ALLOWED / 그 외 상태별 기본 코드 |
| 그 밖의 모든 예외 | 500 INTERNAL_ERROR |

응답에는 카탈로그 메시지만 나갑니다. 원인(필드 위치, log_detail, 스택트레이스)은 request_id와 함께 서버 로그에만 남깁니다.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import ERROR_CATALOG, AppError, ErrorCode
from app.core.request_id import REQUEST_ID_HEADER, new_request_id
from app.schemas.error import ErrorResponse

logger = logging.getLogger("app.errors")

# Starlette/FastAPI가 직접 내는 HTTP 오류의 상태 → 코드
_STATUS_CODES: dict[int, ErrorCode] = {
    spec.status: code
    for code, spec in reversed(ERROR_CATALOG.items())  # 상태별 첫 코드(기본 코드)가 남도록 역순
}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or new_request_id()


def error_response(request: Request, code: ErrorCode, headers: dict[str, str] | None = None) -> JSONResponse:
    spec = ERROR_CATALOG[code]
    body = ErrorResponse(code=code, status=spec.status, message=spec.message)
    # 500은 RequestIdMiddleware 바깥(ServerErrorMiddleware)에서 응답되므로 헤더를 여기서도 넣는다
    return JSONResponse(
        status_code=spec.status,
        content=body.model_dump(),
        headers={**(headers or {}), REQUEST_ID_HEADER: _request_id(request)},
    )


def _field_path(loc: tuple[Any, ...]) -> str:
    """('body', 'items', 0, 'proficiency') → 'body.items[0].proficiency' (로그용)."""
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else ("." if out else "") + str(part)
    return out


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    level = logging.ERROR if exc.status >= 500 else logging.INFO
    logger.log(level, "%s %s request_id=%s detail=%s", exc.status, exc.code, _request_id(request), exc.log_detail)
    return error_response(request, exc.code, exc.headers)


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    raw = exc.errors()
    code = ErrorCode.MALFORMED_JSON if any(e.get("type") == "json_invalid" for e in raw) else ErrorCode.VALIDATION_FAILED
    # 어떤 필드가 왜 틀렸는지는 로그에만 (입력값 e["input"]은 남기지 않음)
    fields = [f"{_field_path(tuple(e.get('loc', ())))}:{e.get('type')}" for e in raw]
    logger.info("%s request_id=%s fields=%s", code, _request_id(request), fields)
    return error_response(request, code)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST)
    headers = dict(exc.headers or {})
    if exc.status_code == 401:
        headers.setdefault("WWW-Authenticate", "Bearer")
    return error_response(request, code, headers)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error request_id=%s", _request_id(request))
    return error_response(request, ErrorCode.INTERNAL_ERROR)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
    install_error_openapi(app)


# ---------- OpenAPI ----------
_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}


def error_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """라우터 responses= 에 넣는 공통 오류 응답 정의 (FastAPI 기본 HTTPValidationError 대신)."""
    return {s: {"description": "Error", "content": {"application/json": {"schema": _ERROR_REF}}} for s in statuses}


def install_error_openapi(app: FastAPI) -> None:
    """생성되는 OpenAPI의 components.schemas에 ErrorResponse를 넣는다."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        spec = original()
        spec.setdefault("components", {}).setdefault("schemas", {})["ErrorResponse"] = ErrorResponse.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        app.openapi_schema = spec
        return spec

    app.openapi = openapi  # type: ignore[method-assign]
