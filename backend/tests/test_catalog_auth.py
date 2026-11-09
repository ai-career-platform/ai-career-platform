"""T17 optional auth using T15 JWT/session checks with synthetic auth storage."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import jwt
import pytest

from app.core.config import get_settings
from app.core.security import issue_access_token
from app.dependencies.auth import get_auth_repository
from app.dependencies.catalog_auth import get_optional_catalog_auth_repository
from app.main import create_app
from app.routers.catalog import get_catalog_service
from app.services.catalog import CatalogService
from tests.conftest import TEST_SECRET, signup
from tests.fakes import MemoryAuthRepository
from tests.test_catalog import MemoryCatalog

PATHS = ["/api/v1/job-roles", "/api/v1/skills?q=py",
         "/api/v1/job-roles/00000000-0000-0000-0000-000000000001"]


@pytest.fixture
def auth_case(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    auth_repo = MemoryAuthRepository()
    service = CatalogService(MemoryCatalog(), cursor_key=b"T17-auth-test-key-only-" * 2)
    app.dependency_overrides[get_catalog_service] = lambda: service
    app.dependency_overrides[get_auth_repository] = lambda: auth_repo
    app.dependency_overrides[get_optional_catalog_auth_repository] = lambda: auth_repo
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client, auth_repo
    finally:
        get_settings.cache_clear()


def new_user(client):
    response = signup(client, email="t17-auth@example.com")
    assert response.status_code == 201
    token = response.json()["access_token"]
    claims = jwt.decode(token, TEST_SECRET, algorithms=["HS256"], issuer="ai-career-platform")
    return token, UUID(claims["sub"]), UUID(claims["sid"])


@pytest.mark.parametrize("path", PATHS)
def test_public_and_logged_in_catalog_match(auth_case, path):
    client, _ = auth_case
    public = client.get(path)
    token, _, _ = new_user(client)
    authenticated = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert public.status_code == authenticated.status_code == 200
    assert public.json() == authenticated.json()


@pytest.mark.parametrize("header", ["Basic abc", "Bearer not-a-token", "Bearer "])
def test_present_bad_header_is_not_silently_anonymous(auth_case, header):
    client, _ = auth_case
    response = client.get(PATHS[0], headers={"Authorization": header})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("case,code", [
    ("expired_token", "TOKEN_EXPIRED"), ("forged", "UNAUTHENTICATED"),
    ("revoked", "UNAUTHENTICATED"), ("disabled", "UNAUTHENTICATED"),
    ("expired_session", "UNAUTHENTICATED"), ("wrong_session_owner", "UNAUTHENTICATED"),
])
def test_t15_rejections_apply_to_catalog(auth_case, case, code):
    client, repo = auth_case
    token, owner, sid = new_user(client)
    if case == "expired_token":
        token = issue_access_token(TEST_SECRET, owner, sid, [], 900,
                                   now=datetime.now(timezone.utc) - timedelta(hours=1))
    elif case == "forged":
        token = issue_access_token("wrong-test-key-01234567890123456789012345", owner, sid, [], 900)
    elif case == "revoked":
        repo.revoke_session(sid, owner, datetime.now(timezone.utc))
    elif case == "disabled":
        repo.set_status(owner, "disabled")
    elif case == "expired_session":
        repo.expire_session(sid, datetime.now(timezone.utc) - timedelta(seconds=1))
    else:
        token = issue_access_token(TEST_SECRET, uuid4(), sid, [], 900)
    for path in PATHS:
        response = client.get(path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert response.json()["code"] == code


def test_optional_auth_does_not_acquire_auth_db_for_anonymous_requests(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    try:
        app = create_app()
        service = CatalogService(MemoryCatalog(), cursor_key=b"T17-public-test-key-only-" * 2)
        app.dependency_overrides[get_catalog_service] = lambda: service
        with TestClient(app) as client:
            assert client.get(PATHS[0]).status_code == 200
            assert client.get(PATHS[0], headers={"Authorization": "Bearer malformed"}).status_code == 401
    finally:
        get_settings.cache_clear()


def test_openapi_marks_catalog_auth_as_optional(auth_case):
    client, _ = auth_case
    spec = client.get("/openapi.json").json()
    for path in ["/api/v1/job-roles", "/api/v1/skills", "/api/v1/job-roles/{job_role_id}"]:
        operation = spec["paths"][path]["get"]
        assert {} in operation["security"]
        assert {"HTTPBearer": []} in operation["security"]
        assert "401" in operation["responses"]
