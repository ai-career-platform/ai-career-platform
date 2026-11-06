"""글로벌 예외 핸들러. 모든 오류를 ProblemDetail(`application/problem+json`)로 바꿉니다.

| 들어오는 예외 | 응답 |
|---|---|
| AppError 하위 클래스 | 예외의 status / code / title / detail / headers |
| RequestValidationError (Pydantic 요청 검증) | 422 VALIDATION_FAILED + errors[{field, code}] (입력값은 넣지 않음) |
| 잘못된 JSON 본문 | 400 MALFORMED_JSON |
| Starlette HTTPException (없는 경로, 허용 안 된 메서드 등) | 404 NOT_FOUND / 405 METHOD_NOT_ALLOWED / 그 외 상태별 기본 코드 |
| 그 밖의 모든 예외 | 500 INTERNAL_ERROR. 내부 정보는 응답에 넣지 않고 서버 로그에만 남김 |
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import DEFAULT_TITLES, AppError, ErrorCode
from app.core.request_id import REQUEST_ID_HEADER, new_request_id
from app.schemas.error import FieldError, ProblemDetail

logger = logging.getLogger("app.errors")

PROBLEM_JSON = "application/problem+json"
PROBLEM_TYPE_BASE = "https://docs.ai-career.invalid/problems/"

# Starlette/FastAPI가 직접 내는 HTTP 오류의 상태 → 코드
_STATUS_CODES: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.FILE_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_FILE_TYPE,
    422: ErrorCode.VALIDATION_FAILED,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.DEPENDENCY_UNAVAILABLE,
    504: ErrorCode.DEPENDENCY_TIMEOUT,
}

# Pydantic v2 오류 type → 계약의 필드 오류 코드
_FIELD_CODES: dict[str, str] = {
    "missing": "REQUIRED",
    "extra_forbidden": "UNKNOWN_FIELD",
    "string_too_short": "TOO_SHORT",
    "string_too_long": "TOO_LONG",
    "too_short": "TOO_SHORT",
    "too_long": "TOO_LONG",
    "greater_than": "OUT_OF_RANGE",
    "greater_than_equal": "OUT_OF_RANGE",
    "less_than": "OUT_OF_RANGE",
    "less_than_equal": "OUT_OF_RANGE",
    "string_pattern_mismatch": "INVALID_FORMAT",
    "value_error": "INVALID_FORMAT",
    "uuid_parsing": "INVALID_FORMAT",
    "uuid_type": "INVALID_FORMAT",
    "date_from_datetime_parsing": "INVALID_FORMAT",
    "date_parsing": "INVALID_FORMAT",
    "datetime_parsing": "INVALID_FORMAT",
    "datetime_from_date_parsing": "INVALID_FORMAT",
    "enum": "INVALID_CHOICE",
    "literal_error": "INVALID_CHOICE",
    "int_parsing": "INVALID_TYPE",
    "int_type": "INVALID_TYPE",
    "float_parsing": "INVALID_TYPE",
    "bool_parsing": "INVALID_TYPE",
    "string_type": "INVALID_TYPE",
    "list_type": "INVALID_TYPE",
    "dict_type": "INVALID_TYPE",
    "model_type": "INVALID_TYPE",
    "json_invalid": "INVALID_JSON",
}


def problem_type(code: ErrorCode | str) -> str:
    return PROBLEM_TYPE_BASE + str(code).lower().replace("_", "-")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or new_request_id()


def problem_response(
    request: Request,
    status: int,
    code: ErrorCode,
    *,
    title: str | None = None,
    detail: str | None = None,
    errors: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    body = ProblemDetail(
        type=problem_type(code),
        title=title or DEFAULT_TITLES[code],
        status=status,
        code=code,
        detail=detail,
        request_id=request_id,
        errors=errors,
    )
    # 500은 RequestIdMiddleware 바깥(ServerErrorMiddleware)에서 응답되므로 헤더를 여기서도 넣는다
    return JSONResponse(
        status_code=status,
        content=body.model_dump(exclude_none=True),
        media_type=PROBLEM_JSON,
        headers={**(headers or {}), REQUEST_ID_HEADER: request_id},
    )


def _field_path(loc: tuple[Any, ...]) -> str:
    """('body', 'items', 0, 'proficiency') → 'items[0].proficiency'. 위치 접두사(body/query/path)는 뺀다."""
    parts = list(loc[1:] if loc and loc[0] in ("body", "query", "path", "header", "cookie") else loc)
    out = ""
    for part in parts:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out or str(loc[0] if loc else "")


async def _app_error(request: Request, exc: AppError) -> JSONResponse:
    errors = [FieldError(**e) for e in exc.errors] if exc.errors else None
    if exc.status >= 500:
        logger.error("app error %s request_id=%s", exc.code, _request_id(request))
    return problem_response(
        request, exc.status, exc.code, title=exc.title, detail=exc.detail, errors=errors, headers=exc.headers
    )


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    raw = exc.errors()
    if any(e.get("type") == "json_invalid" for e in raw):
        return problem_response(request, 400, ErrorCode.MALFORMED_JSON)
    errors = [
        FieldError(field=_field_path(tuple(e.get("loc", ()))), code=_FIELD_CODES.get(e.get("type", ""), "INVALID"))
        for e in raw
    ]
    return problem_response(request, 422, ErrorCode.VALIDATION_FAILED, errors=errors)


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST)
    headers = dict(exc.headers or {})
    if exc.status_code == 401:
        headers.setdefault("WWW-Authenticate", "Bearer")
    return problem_response(request, exc.status_code, code, headers=headers or None)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error request_id=%s", _request_id(request))
    return problem_response(request, 500, ErrorCode.INTERNAL_ERROR)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
    install_problem_openapi(app)


# ---------- OpenAPI ----------
# "model=" 을 쓰면 FastAPI가 application/json으로 표시하므로, problem+json 아래에
# components 참조를 직접 넣고, 스키마는 install_problem_openapi()가 components에 등록한다.
_PROBLEM_REF = {"$ref": "#/components/schemas/ProblemDetail"}


def problem_responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """라우터 responses= 에 넣는 공통 오류 응답 정의."""
    return {s: {"description": "Problem details", "content": {PROBLEM_JSON: {"schema": _PROBLEM_REF}}} for s in statuses}


def install_problem_openapi(app: FastAPI) -> None:
    """생성되는 OpenAPI의 components.schemas에 ProblemDetail·FieldError를 넣는다."""
    original = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        spec = original()
        schema = ProblemDetail.model_json_schema(ref_template="#/components/schemas/{model}")
        components = spec.setdefault("components", {}).setdefault("schemas", {})
        components.update(schema.pop("$defs", {}))
        components["ProblemDetail"] = schema
        app.openapi_schema = spec
        return spec

    app.openapi = openapi  # type: ignore[method-assign]
