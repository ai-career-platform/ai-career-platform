"""Profile contracts exercised with T14 SQLAlchemy Session on disposable PostgreSQL."""

import json
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from app.core.errors import AppError, ErrorCode
from app.dependencies.auth import CurrentUser as AuthenticatedUser
from app.dependencies.auth import get_current_user as get_authenticated_user
from app.main import create_app
from app.repositories.auth import SqlAuthRepository
from app.repositories.profile import PostgresProfileRepository
from app.routers.me import get_profile_service
from app.services.profile import ProfileService
from tests.fakes import override_auth_repository

ALICE = UUID("00000000-0000-4000-8000-000000000001")
BOB = UUID("00000000-0000-4000-8000-000000000002")
MISSING = UUID("00000000-0000-4000-8000-000000000099")


from sqlalchemy.orm import Session
from tests.test_profile_postgres import pg_app


class PostgresTestConnection:
    def __init__(self, admin):
        self.admin = admin
        self.db = self
    def execute(self, query, params=()):
        query = query.replace(" users", " career.users").replace(" user_profiles", " career.user_profiles")
        return self.admin.execute(query, params)
    def commit(self): pass  # setup connection is autocommit


@pytest.fixture
def fixture_app(pg_app):
    _, engine, admin, _ = pg_app
    for user_id in [ALICE, BOB]:
        admin.execute("UPDATE career.user_profiles SET headline='original headline', bio='original bio', location_text='original location' WHERE user_id=%s", (user_id,))
    connection = PostgresTestConnection(admin)
    with Session(engine) as session:
        repository = PostgresProfileRepository(session)
        app = create_app()
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(ALICE, ALICE, frozenset(), frozenset())
        app.dependency_overrides[get_profile_service] = lambda: ProfileService(repository)
        override_auth_repository(app, SqlAuthRepository(session))
        with TestClient(app) as client:
            yield app, client, connection, repository


def problem(response, status, code):
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert body["status"] == status and body["code"] == code
    assert response.headers["x-request-id"].startswith("req-")
    assert response.headers["cache-control"] == "no-store"
    return body


def test_read_own_profile_only(fixture_app):
    _, client, _, _ = fixture_app
    response = client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["user_id"] == str(ALICE)
    assert body["email"] == "a@example.invalid"
    assert "email_canonical" not in response.text
    assert body["profile"]["bio"] == "original bio"
    assert str(BOB) not in response.text


def test_patch_preserves_omitted_and_other_user(fixture_app):
    _, client, _, repository = fixture_app
    before_bob = repository.get(BOB)
    result = client.patch("/api/v1/me", json={"display_name": "Changed", "headline": "new headline"})
    assert result.status_code == 200
    assert result.json()["display_name"] == "Changed"
    assert result.json()["profile"] == {"headline": "new headline", "bio": "original bio",
                                        "location_text": "original location"}
    assert client.get("/api/v1/me").json() == result.json()
    assert repository.get(BOB) == before_bob


def test_email_is_read_only_original_not_canonical(fixture_app):
    _, client, connection, _ = fixture_app
    original = "Synthetic.A+tag@example.invalid"
    connection.execute("UPDATE users SET email=%s WHERE user_id=%s", (original, str(ALICE)))
    connection.db.commit()
    assert client.get("/api/v1/me").json()["email"] == original
    assert client.patch("/api/v1/me", json={"email": "b@example.invalid"}).status_code == 422
    assert client.get("/api/v1/me").json()["email"] == original


@pytest.mark.parametrize("value", [None, ""])
@pytest.mark.parametrize("field", ["headline", "bio", "location_text"])
def test_clear_only_selected_field(fixture_app, field, value):
    _, client, _, _ = fixture_app
    response = client.patch("/api/v1/me", json={field: value})
    assert response.status_code == 200
    assert response.json()["profile"][field] == value
    assert response.json()["display_name"] == "Synthetic A"
    for other in {"headline", "bio", "location_text"} - {field}:
        assert response.json()["profile"][other].startswith("original")


@pytest.mark.parametrize("payload", [
    {}, {"display_name": None}, {"display_name": ""}, {"display_name": "x" * 101},
    {"headline": "x" * 201}, {"bio": "x" * 5001}, {"location_text": "x" * 121},
    {"headline": 123}, {"bio": []}, {"location_text": True},
    {"email": "b@example.invalid"}, {"visibility": "public"}, {"user_id": str(BOB)},
    {"profile": {"bio": "nested is not the PATCH contract"}}, {"status": "disabled"},
    {"display_name": "Would change", "unexpected": "do not echo"},
])
def test_invalid_patch_is_atomic_and_redacted(fixture_app, payload):
    _, client, _, _ = fixture_app
    before = client.get("/api/v1/me").json()
    response = client.patch("/api/v1/me", json=payload)
    body = problem(response, 422, "VALIDATION_FAILED")
    assert body["message"]
    assert "do not echo" not in response.text
    assert "b@example.invalid" not in response.text
    assert client.get("/api/v1/me").json() == before


@pytest.mark.parametrize("field,length", [("display_name",100),("headline",200),("bio",5000),("location_text",120)])
def test_maximum_length_accepted(fixture_app, field, length):
    _, client, _, _ = fixture_app
    response = client.patch("/api/v1/me", json={field: "가" * length})
    assert response.status_code == 200


@pytest.mark.parametrize("method", ["get", "patch"])
def test_no_user_id_from_query(fixture_app, method):
    _, client, _, _ = fixture_app
    kwargs = {"json": {"headline": "attempt"}} if method == "patch" else {}
    response = getattr(client, method)("/api/v1/me?user_id=" + str(BOB), **kwargs)
    problem(response, 422, "VALIDATION_FAILED")


def test_no_public_profile_creation_or_deletion(fixture_app):
    _, client, _, _ = fixture_app
    assert client.get("/api/v1/users/" + str(BOB)).status_code == 404
    assert client.get("/api/v1/me/" + str(BOB)).status_code == 404
    for method in ["post", "put", "delete"]:
        assert getattr(client, method)("/api/v1/me").status_code == 405


@pytest.mark.parametrize("method", ["get", "patch"])
@pytest.mark.parametrize("disabled", [False, True])
def test_missing_or_disabled_user_is_404(fixture_app, method, disabled):
    app, client, connection, _ = fixture_app
    if disabled:
        connection.execute("UPDATE users SET status = 'disabled' WHERE user_id = %s", (str(ALICE),))
        connection.db.commit()
    else:
        app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(MISSING, MISSING, frozenset(), frozenset())
    kwargs = {"json": {"bio": "updated"}} if method == "patch" else {}
    problem(getattr(client, method)("/api/v1/me", **kwargs), 404, "NOT_FOUND")


def test_missing_profile_row_can_be_initialized_by_patch(fixture_app):
    _, client, connection, _ = fixture_app
    connection.execute("DELETE FROM user_profiles WHERE user_id = %s", (str(ALICE),))
    connection.db.commit()
    assert client.get("/api/v1/me").json()["profile"] == {
        "headline": None, "bio": None, "location_text": None}
    response = client.patch("/api/v1/me", json={"headline": "first"})
    assert response.status_code == 200
    assert response.json()["profile"] == {"headline": "first", "bio": None, "location_text": None}


def test_atomic_rollback_when_profile_write_fails(fixture_app):
    _, client, connection, _ = fixture_app
    connection.db.execute("""CREATE FUNCTION career.fail_patch() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic private database error'; END $$""")
    connection.db.execute("CREATE TRIGGER fail_patch BEFORE UPDATE ON career.user_profiles FOR EACH ROW EXECUTE FUNCTION career.fail_patch()")
    connection.db.commit()
    response = client.patch("/api/v1/me", json={"display_name": "must rollback", "bio": "changed"})
    problem(response, 503, "DEPENDENCY_UNAVAILABLE")
    assert "private database error" not in response.text
    assert client.get("/api/v1/me").json()["display_name"] == "Synthetic A"
    assert client.get("/api/v1/me").json()["profile"]["bio"] == "original bio"


def test_sql_values_are_parameters(fixture_app):
    _, client, _, _ = fixture_app
    injection = "Robert'); DROP TABLE users;--"
    assert client.patch("/api/v1/me", json={"display_name": injection}).status_code == 200
    assert client.get("/api/v1/me").json()["display_name"] == injection


@pytest.mark.parametrize("header", [None, "Basic ignored", "Bearer unsigned.synthetic.token"])
def test_production_default_never_authenticates_unverified_input(header):
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/me", headers={"Authorization":header} if header else {})
    problem(response, 401, "UNAUTHENTICATED")
    assert "unsigned.synthetic.token" not in response.text


def test_storage_not_bound_fails_closed():
    app = create_app()
    app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(ALICE, ALICE, frozenset(), frozenset())
    with TestClient(app) as client:
        problem(client.get("/api/v1/me"), 503, "DEPENDENCY_UNAVAILABLE")


def test_malformed_json_never_echoes_body(fixture_app):
    _, client, _, _ = fixture_app
    response = client.patch("/api/v1/me", content='{"bio":"secret', headers={"Content-Type":"application/json"})
    problem(response, 400, "MALFORMED_JSON")
    assert "secret" not in response.text


def test_responses_validate_against_t06_contract(fixture_app):
    _, client, _, _ = fixture_app
    spec = yaml.safe_load((Path(__file__).parents[2]/"docs/api/openapi.yaml").read_text(encoding="utf-8"))
    def validator(name):
        return Draft202012Validator({"$ref":f"#/components/schemas/{name}",
                                      "components":spec["components"]}, format_checker=FormatChecker())
    for response in [client.get("/api/v1/me"), client.patch("/api/v1/me", json={"bio":None})]:
        validator("Me").validate(response.json())
    assert client.patch("/api/v1/me", json={}).json()["code"] == "VALIDATION_FAILED"
    schema = client.get("/openapi.json").json()
    request = schema["components"]["schemas"]["MePatch"]
    assert request["additionalProperties"] is False
    assert request["minProperties"] == 1
    assert request["properties"]["display_name"]["type"] == "string"
    assert set(schema["paths"]["/api/v1/me"]) == {"get", "patch"}
    for method in ["get", "patch"]:
        for status in ["401", "404", "422", "503"]:
            assert set(schema["paths"]["/api/v1/me"][method]["responses"][status]["content"]) == {"application/json"}


def test_unhandled_profile_error_is_redacted_and_not_cached():
    class BrokenRepository:
        def get_user(self, _):
            raise RuntimeError("synthetic internal detail")
    app = create_app()
    app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(ALICE, ALICE, frozenset(), frozenset())
    override_auth_repository(app, BrokenRepository())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/me")
    problem(response, 500, "INTERNAL_ERROR")
    assert "synthetic internal detail" not in response.text
