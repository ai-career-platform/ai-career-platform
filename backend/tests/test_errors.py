"""공통 에러 계약 테스트 (docs/API_CONTRACT.md §1.4).

- 모든 오류 경로가 `{code, status, message}` 세 필드만 보내는지
- 메시지가 카탈로그 한 곳에서 오고, 계약서 표·openapi.yaml 예시와 일치하는지
"""

import logging
import re
from pathlib import Path
from typing import Annotated

import pytest
import yaml
from fastapi import APIRouter, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import API_V1_PREFIX, get_settings
from app.core.errors import ERROR_CATALOG, AppError, ErrorCode
from app.main import create_app
from app.routers.api_v1 import API_V1_RESPONSES
from app.schemas.error import ErrorResponse

REPO = Path(__file__).resolve().parents[2]
MSG = {code: spec.message for code, spec in ERROR_CATALOG.items()}


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


@probe.get("/raise/{code}")
def raise_code(code: str) -> dict:
    if code == "BOOM":
        raise RuntimeError("db password=hunter2 at /srv/app/secret.py line 42")
    if code == "RATE_LIMITED":
        raise AppError(ErrorCode.RATE_LIMITED, retry_after=30)
    if code == "DEPENDENCY_UNAVAILABLE":
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, retry_after=5)
    raise AppError(ErrorCode(code), log_detail="user_id=42 skill_id=abc already exists")


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


def assert_error(response, code: ErrorCode) -> dict:
    """오류 응답이 {code, status, message} 세 필드이고 카탈로그와 같은지 확인."""
    spec = ERROR_CATALOG[code]
    assert response.status_code == spec.status
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body == {"code": code, "status": spec.status, "message": spec.message}
    ErrorResponse.model_validate(body)
    assert re.fullmatch(r"[A-Za-z0-9._-]{8,64}", response.headers["x-request-id"])
    return body


# ---------- 형식 ----------


@pytest.mark.parametrize("code", [c for c in ErrorCode if c is not ErrorCode.INTERNAL_ERROR])
def test_every_code_is_sent_as_code_status_message(client, code):
    assert_error(client.get(f"/api/v1/_probe/raise/{code}"), code)


def test_log_detail_stays_in_server_log(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.errors"):
        r = client.get("/api/v1/_probe/raise/DUPLICATE_SKILL")
    assert "user_id=42" not in r.text
    assert "user_id=42" in caplog.text and r.headers["x-request-id"] in caplog.text


def test_unauthorized_sends_www_authenticate(client):
    for code in ("UNAUTHENTICATED", "TOKEN_EXPIRED", "INVALID_CREDENTIALS"):
        assert client.get(f"/api/v1/_probe/raise/{code}").headers["www-authenticate"] == "Bearer"


def test_retry_after_header(client):
    assert client.get("/api/v1/_probe/raise/RATE_LIMITED").headers["retry-after"] == "30"
    assert client.get("/api/v1/_probe/raise/DEPENDENCY_UNAVAILABLE").headers["retry-after"] == "5"


# ---------- 핸들러가 바꾸는 오류 ----------


def test_request_validation_is_422_without_field_details(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.errors"):
        r = client.post(
            "/api/v1/_probe/skills",
            json={"items": [{"skill_id": "6b1d0b1c-7e2a-4f1b-9d3c-2a1b0c9d8e7f", "proficiency": 9}, {}], "extra": 1},
        )
    assert_error(r, ErrorCode.VALIDATION_FAILED)
    assert "proficiency" not in r.text
    # 어떤 필드가 틀렸는지는 로그에서 찾는다
    assert "body.items[0].proficiency:less_than_equal" in caplog.text
    assert "body.extra:extra_forbidden" in caplog.text


def test_query_validation_is_422(client):
    assert_error(client.get("/api/v1/_probe/list?limit=500"), ErrorCode.VALIDATION_FAILED)


def test_validation_never_echoes_input_even_in_logs(client, caplog):
    with caplog.at_level(logging.INFO, logger="app.errors"):
        r = client.post("/api/v1/_probe/signup", json={"email": "seeker@example.com", "password": "pw9Xq!"})
    assert_error(r, ErrorCode.VALIDATION_FAILED)
    for secret in ("pw9Xq!", "seeker@example.com"):
        assert secret not in r.text and secret not in caplog.text


def test_malformed_json_is_400(client):
    r = client.post("/api/v1/_probe/signup", content=b'{"email": ', headers={"content-type": "application/json"})
    assert_error(r, ErrorCode.MALFORMED_JSON)


def test_unknown_route_404(client):
    assert_error(client.get("/api/v1/no-such-route"), ErrorCode.NOT_FOUND)


def test_wrong_method_405(client):
    r = client.delete("/health")
    assert_error(r, ErrorCode.METHOD_NOT_ALLOWED)
    assert "GET" in r.headers.get("allow", "")


def test_unhandled_exception_hides_internals(client):
    r = client.get("/api/v1/_probe/raise/BOOM")
    assert_error(r, ErrorCode.INTERNAL_ERROR)
    for leaked in ("hunter2", "secret.py", "RuntimeError", "Traceback"):
        assert leaked not in r.text


# ---------- 요청 번호 ----------


def test_request_id_is_reused_when_safe(client):
    r = client.get("/api/v1/_probe/raise/NOT_FOUND", headers={"X-Request-ID": "nginx-7f3a9c21"})
    assert r.headers["x-request-id"] == "nginx-7f3a9c21"
    assert "nginx-7f3a9c21" not in r.text  # 본문에는 넣지 않음


def test_request_id_is_replaced_when_unsafe(client):
    r = client.get("/api/v1/_probe/raise/NOT_FOUND", headers={"X-Request-ID": "<script>alert(1)</script>"})
    assert re.fullmatch(r"req-[0-9a-f]{16}", r.headers["x-request-id"])


def test_success_responses_also_carry_request_id(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert re.fullmatch(r"req-[0-9a-f]{16}", r.headers["x-request-id"])


# ---------- OpenAPI ----------


def test_openapi_documents_error_response_for_api_v1(client):
    spec = client.get("/openapi.json").json()
    responses = spec["paths"]["/api/v1/_probe/skills"]["post"]["responses"]
    assert responses["422"]["content"] == {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}
    schema = spec["components"]["schemas"]["ErrorResponse"]
    assert set(schema["properties"]) == set(schema["required"]) == {"code", "status", "message"}
    assert "HTTPValidationError" not in str(responses)


def test_generated_openapi_is_valid(client):
    from openapi_spec_validator import validate

    validate(client.get("/openapi.json").json())


# ---------- 메시지 카탈로그 관리 ----------


def test_catalog_covers_every_code_with_matching_status_range():
    assert set(ERROR_CATALOG) == set(ErrorCode)
    for code, spec in ERROR_CATALOG.items():
        assert 400 <= spec.status <= 599, code
        assert spec.message.strip() and spec.message.endswith("."), code
        # 사용자 문구에 내부 정보처럼 보이는 것이 섞이지 않게
        assert not re.search(r"[{}<>_/\\]|Exception|Error|SQL|null", spec.message), code


def test_default_code_per_status_is_the_generic_one():
    from app.core.exception_handlers import _STATUS_CODES

    assert _STATUS_CODES[400] is ErrorCode.BAD_REQUEST
    assert _STATUS_CODES[401] is ErrorCode.UNAUTHENTICATED
    assert _STATUS_CODES[409] is ErrorCode.CONFLICT
    assert _STATUS_CODES[422] is ErrorCode.VALIDATION_FAILED


def test_contract_table_matches_catalog():
    """docs/API_CONTRACT.md §1.4 code 목록 표 = ERROR_CATALOG."""
    text = (REPO / "docs" / "API_CONTRACT.md").read_text(encoding="utf-8")
    section = text.split("### 1.4 오류", 1)[1].split("\n### ", 1)[0]
    rows = re.findall(r"^\| (\d{3}) \| `([A-Z_]+)` \| ([^|]+?) \|", section, re.M)
    documented = {code: (int(status), message) for status, code, message in rows}
    expected = {str(code): (spec.status, spec.message) for code, spec in ERROR_CATALOG.items()}
    assert documented == expected


def test_openapi_examples_match_catalog():
    """docs/api/openapi.yaml 의 모든 오류 예시 message = 카탈로그 문구."""
    spec = yaml.safe_load((REPO / "docs" / "api" / "openapi.yaml").read_text(encoding="utf-8"))
    examples = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("schema") == {"$ref": "#/components/schemas/ErrorResponse"} and "example" in node:
                examples.append(node["example"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(spec)
    assert examples
    for ex in examples:
        spec_ = ERROR_CATALOG[ErrorCode(ex["code"])]
        assert ex == {"code": ex["code"], "status": spec_.status, "message": spec_.message}
