"""공통 에러 계약 테스트 (docs/API_CONTRACT.md §1.4).

테스트 전용 라우트를 붙인 앱으로 모든 오류 경로가 같은 형식인지 확인합니다.
"""

import re
from typing import Annotated

import pytest
from fastapi import APIRouter, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import API_V1_PREFIX, get_settings
from app.core.errors import (
    BadRequestError,
    ConflictError,
    DependencyUnavailableError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthorizedError,
    ValidationFailedError,
)
from app.main import create_app
from app.routers.api_v1 import API_V1_RESPONSES
from app.schemas.error import ProblemDetail

PROBLEM_JSON = "application/problem+json"


class SkillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    proficiency: int | None = Field(default=None, ge=1, le=5)


class SkillsReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SkillItem] = Field(max_length=3)


class Signup(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=10)


probe = APIRouter(prefix="/_probe")


@probe.post("/skills")
def replace_skills(body: SkillsReplace) -> dict:
    return {"count": len(body.items)}


@probe.post("/signup")
def signup(body: Signup) -> dict:
    return {"ok": True}


@probe.get("/list")
def listing(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> dict:
    return {"limit": limit}


@probe.get("/raise/{kind}")
def raise_kind(kind: str) -> dict:
    match kind:
        case "bad":
            raise BadRequestError(ErrorCode.NO_USER_SKILLS)
        case "unauth":
            raise UnauthorizedError(ErrorCode.TOKEN_EXPIRED)
        case "forbidden":
            raise ForbiddenError(ErrorCode.CONSENT_REQUIRED, detail="AI 처리 동의가 필요합니다.")
        case "notfound":
            raise NotFoundError()
        case "conflict":
            raise ConflictError(ErrorCode.EMAIL_TAKEN)
        case "dup":
            raise ValidationFailedError(ErrorCode.DUPLICATE_SKILL, errors=[{"field": "items[1].skill_id", "code": "DUPLICATE"}])
        case "rate":
            raise RateLimitedError(retry_after=30)
        case "dep":
            raise DependencyUnavailableError(retry_after=5)
        case "boom":
            raise RuntimeError("db password=hunter2 at /srv/app/secret.py line 42")
    return {"ok": True}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    app = create_app()
    # 기능 라우터와 같은 방식으로 /api/v1 아래에 붙인다 (공통 responses 상속 확인용)
    v1 = APIRouter(prefix=API_V1_PREFIX, responses=API_V1_RESPONSES)
    v1.include_router(probe)
    app.include_router(v1)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    get_settings.cache_clear()


def assert_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM_JSON)
    body = response.json()
    ProblemDetail.model_validate(body)  # 형식 자체가 DTO와 일치
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"].endswith("/" + code.lower().replace("_", "-"))
    assert body["request_id"] == response.headers["x-request-id"]
    return body


@pytest.mark.parametrize(
    ("kind", "status", "code"),
    [
        ("bad", 400, "NO_USER_SKILLS"),
        ("unauth", 401, "TOKEN_EXPIRED"),
        ("forbidden", 403, "CONSENT_REQUIRED"),
        ("notfound", 404, "NOT_FOUND"),
        ("conflict", 409, "EMAIL_TAKEN"),
        ("rate", 429, "RATE_LIMITED"),
        ("dep", 503, "DEPENDENCY_UNAVAILABLE"),
    ],
)
def test_app_errors_use_problem_format(client, kind, status, code):
    assert_problem(client.get(f"/api/v1/_probe/raise/{kind}"), status, code)


def test_unauthorized_sends_www_authenticate(client):
    r = client.get("/api/v1/_probe/raise/unauth")
    assert r.headers["www-authenticate"] == "Bearer"


def test_retry_after_header(client):
    assert client.get("/api/v1/_probe/raise/rate").headers["retry-after"] == "30"
    assert client.get("/api/v1/_probe/raise/dep").headers["retry-after"] == "5"


def test_detail_is_optional_and_passed_through(client):
    body = assert_problem(client.get("/api/v1/_probe/raise/forbidden"), 403, "CONSENT_REQUIRED")
    assert body["detail"] == "AI 처리 동의가 필요합니다."
    body = assert_problem(client.get("/api/v1/_probe/raise/notfound"), 404, "NOT_FOUND")
    assert "detail" not in body and "errors" not in body


def test_business_validation_error_lists_fields(client):
    body = assert_problem(client.get("/api/v1/_probe/raise/dup"), 422, "DUPLICATE_SKILL")
    assert body["errors"] == [{"field": "items[1].skill_id", "code": "DUPLICATE"}]


def test_request_validation_422_with_field_paths(client):
    r = client.post(
        "/api/v1/_probe/skills",
        json={"items": [{"skill_id": "6b1d0b1c-7e2a-4f1b-9d3c-2a1b0c9d8e7f", "proficiency": 9}, {"proficiency": 2}], "extra": 1},
    )
    body = assert_problem(r, 422, "VALIDATION_FAILED")
    assert {"field": "items[0].proficiency", "code": "OUT_OF_RANGE"} in body["errors"]
    assert {"field": "items[1].skill_id", "code": "REQUIRED"} in body["errors"]
    assert {"field": "extra", "code": "UNKNOWN_FIELD"} in body["errors"]


def test_query_validation_422(client):
    body = assert_problem(client.get("/api/v1/_probe/list?limit=500"), 422, "VALIDATION_FAILED")
    assert body["errors"] == [{"field": "limit", "code": "OUT_OF_RANGE"}]


def test_validation_error_never_echoes_input(client):
    r = client.post("/api/v1/_probe/signup", json={"email": "seeker@example.com", "password": "short"})
    body = assert_problem(r, 422, "VALIDATION_FAILED")
    assert "short" not in r.text and "seeker@example.com" not in r.text
    assert body["errors"] == [{"field": "password", "code": "TOO_SHORT"}]


def test_malformed_json_is_400(client):
    r = client.post("/api/v1/_probe/signup", content=b'{"email": ', headers={"content-type": "application/json"})
    assert_problem(r, 400, "MALFORMED_JSON")


def test_unknown_route_404(client):
    assert_problem(client.get("/api/v1/no-such-route"), 404, "NOT_FOUND")


def test_wrong_method_405(client):
    r = client.delete("/health")
    assert_problem(r, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in r.headers.get("allow", "")


def test_unhandled_exception_hides_internals(client):
    r = client.get("/api/v1/_probe/raise/boom")
    body = assert_problem(r, 500, "INTERNAL_ERROR")
    assert body["title"] == "Internal server error"
    for leaked in ("hunter2", "secret.py", "RuntimeError", "Traceback"):
        assert leaked not in r.text


def test_request_id_is_reused_when_safe(client):
    r = client.get("/api/v1/_probe/raise/notfound", headers={"X-Request-ID": "nginx-7f3a9c21"})
    assert r.headers["x-request-id"] == "nginx-7f3a9c21"
    assert r.json()["request_id"] == "nginx-7f3a9c21"


def test_request_id_is_replaced_when_unsafe(client):
    r = client.get("/api/v1/_probe/raise/notfound", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert re.fullmatch(r"req-[0-9a-f]{16}", r.headers["x-request-id"])


def test_success_responses_also_carry_request_id(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert re.fullmatch(r"req-[0-9a-f]{16}", r.headers["x-request-id"])


def test_openapi_documents_problem_for_api_v1(client):
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/api/v1/_probe/skills"]["post"]["responses"]
    assert "application/problem+json" in responses["422"]["content"]
    assert set(responses["422"]["content"]) == {"application/problem+json"}
    assert responses["422"]["content"]["application/problem+json"]["schema"] == {"$ref": "#/components/schemas/ProblemDetail"}
    problem = spec["components"]["schemas"]["ProblemDetail"]
    assert set(problem["required"]) == {"type", "title", "status", "code", "request_id"}
    assert "FieldError" in spec["components"]["schemas"]
    assert "HTTPValidationError" not in str(responses)


def test_generated_openapi_is_valid(client):
    from openapi_spec_validator import validate

    validate(client.get("/openapi.json").json())


def test_every_error_code_has_a_title():
    from app.core.errors import DEFAULT_TITLES

    assert set(DEFAULT_TITLES) == set(ErrorCode)
