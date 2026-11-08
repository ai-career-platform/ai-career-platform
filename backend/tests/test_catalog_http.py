"""HTTP tests in an isolated app; shared main/router files stay untouched."""

import pytest
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml
from openapi_spec_validator import validate
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.errors import ERROR_CATALOG, ErrorCode
from app.routers.catalog import get_catalog_service
from app.services.catalog import CatalogService
from test_catalog import MemoryCatalog


@pytest.fixture
def client():
    app = create_app()
    service = CatalogService(MemoryCatalog(), cursor_key=b"http-tests-only-key-" * 2)
    app.dependency_overrides[get_catalog_service] = lambda: service
    with TestClient(app) as client:
        yield client


def assert_problem(response, status, code):
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"code", "status", "message"}
    assert body["status"] == status
    assert body["code"] == code
    assert body["message"] == ERROR_CATALOG[ErrorCode(code)].message
    assert response.headers["X-Request-ID"]
    return body


def test_http_paging_and_dto(client):
    first = client.get("/api/v1/job-roles", params={"q": "back", "limit": 1})
    assert first.status_code == 200
    body = first.json()
    assert set(body) == {"items", "next_cursor"}
    assert set(body["items"][0]) == {"job_role_id", "code", "name"}
    second = client.get("/api/v1/job-roles", params={
        "q": "back", "limit": 1, "cursor": body["next_cursor"],
    }).json()
    assert second["items"][0]["job_role_id"] != body["items"][0]["job_role_id"]
    assert second["next_cursor"] is None


def test_detail_and_missing(client):
    response = client.get("/api/v1/job-roles/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 200
    assert response.json()["required_skills"] == []
    assert response.json()["description"] is None
    assert_problem(client.get(
        "/api/v1/job-roles/00000000-0000-0000-0000-000000000099"
    ), 404, "NOT_FOUND")


def test_skills_and_empty(client):
    response = client.get("/api/v1/skills", params={"q": "py"})
    assert response.status_code == 200
    assert [s["name"] for s in response.json()["items"]] == ["Python", "CPython"]
    assert client.get("/api/v1/skills?q=missing").json() == {"items": []}
    assert client.get("/api/v1/job-roles?q=missing").json() == {
        "items": [], "next_cursor": None,
    }


@pytest.mark.parametrize("path,params", [
    ("/skills", {}), ("/skills", {"q": "a"}),
    ("/skills", {"q": "a" * 61}), ("/skills", {"q": "py", "limit": 101}),
    ("/job-roles", {"q": ""}), ("/job-roles", {"q": "a" * 101}),
    ("/job-roles", {"limit": 0}), ("/job-roles", {"limit": "abc"}),
    ("/job-roles", {"cursor": "a" * 501}),
    ("/job-roles/not-a-uuid", {}),
])
def test_http_validation(client, path, params):
    body = assert_problem(client.get("/api/v1" + path, params=params),
                          422, "VALIDATION_FAILED")


def test_cursor_rejection(client):
    assert_problem(client.get("/api/v1/job-roles?cursor=bad"), 400, "INVALID_CURSOR")
    token = client.get("/api/v1/job-roles?limit=1").json()["next_cursor"]
    assert_problem(client.get("/api/v1/job-roles", params={"q": "changed", "cursor": token}),
                   400, "INVALID_CURSOR")


def test_no_input_leak_and_unique_request_ids(client):
    rejected = "private@example.test-" * 10
    first = client.get("/api/v1/job-roles", params={"limit": rejected})
    second = client.get("/api/v1/job-roles", params={"limit": rejected})
    assert rejected not in first.text
    assert first.headers["X-Request-ID"] != second.headers["X-Request-ID"]


def test_unconfigured_provider_returns_503():
    app = create_app()
    with TestClient(app) as client:
        assert_problem(client.get("/api/v1/job-roles"), 503, "DEPENDENCY_UNAVAILABLE")


def test_openapi_catalog_contract(client):
    spec = client.get("/openapi.json").json()
    validate(spec)
    assert set(spec["paths"]) == {
        "/health", "/health/db", "/version",
        "/api/v1/job-roles", "/api/v1/job-roles/{job_role_id}", "/api/v1/skills"
    }
    operation = spec["paths"]["/api/v1/job-roles"]["get"]
    parameters = {p["name"]: p for p in operation["parameters"]}
    assert parameters["limit"]["schema"]["maximum"] == 100
    assert parameters["limit"]["schema"]["default"] == 20
    for status in ["400", "422", "503"]:
        content = operation["responses"][status]["content"]
        assert set(content) == {"application/json"}
    skills = spec["paths"]["/api/v1/skills"]["get"]
    q = next(p for p in skills["parameters"] if p["name"] == "q")
    assert q["required"] is True
    assert q["schema"]["minLength"] == 2


@pytest.mark.parametrize("path,schema_name", [
    ("/api/v1/job-roles?limit=1", "JobRolePage"),
    ("/api/v1/job-roles/00000000-0000-0000-0000-000000000001", "JobRoleDetail"),
    ("/api/v1/job-roles?cursor=broken", "ErrorResponse"),
    ("/api/v1/skills?q=a", "ErrorResponse"),
    ("/api/v1/job-roles/00000000-0000-0000-0000-000000000099", "ErrorResponse"),
])
def test_response_matches_team_contract(client, path, schema_name):
    spec_path = Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    schema = {
        "$ref": f"#/components/schemas/{schema_name}",
        "components": spec["components"],
    }
    Draft202012Validator(schema).validate(client.get(path).json())


def test_skill_response_matches_team_contract(client):
    spec_path = Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    response_schema = spec["paths"]["/skills"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    Draft202012Validator({**response_schema, "components": spec["components"]}).validate(
        client.get("/api/v1/skills?q=py").json()
    )
