"""T17 공개 조회: Authorization 헤더와 무관하게 같은 결과, 인증 DB 조회 없음, 키 설정 불필요."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.security import derive_key, issue_access_token
from app.db import get_db
from app.dependencies.auth import get_auth_repository
from app.main import create_app
from app.routers.catalog import get_catalog_service
from app.services.catalog import CURSOR_KEY_PURPOSE, CatalogService
from tests.conftest import TEST_SECRET
from tests.test_catalog import MemoryCatalog

PATHS = ["/api/v1/job-roles", "/api/v1/skills?q=py",
         "/api/v1/job-roles/00000000-0000-0000-0000-000000000001"]
EXPIRED = issue_access_token(TEST_SECRET, uuid4(), uuid4(), [], 900, now=datetime.now(UTC) - timedelta(hours=1))
FORGED = issue_access_token("wrong-test-key-01234567890123456789012345", uuid4(), uuid4(), [], 900)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    app = create_app()
    service = CatalogService(MemoryCatalog(), cursor_key=derive_key(TEST_SECRET, CURSOR_KEY_PURPOSE))
    app.dependency_overrides[get_catalog_service] = lambda: service
    # 카탈로그가 인증 저장소를 건드리면 바로 실패하게 한다.
    app.dependency_overrides[get_auth_repository] = lambda: pytest.fail("catalog must not load auth state")
    try:
        with TestClient(app, base_url="https://testserver") as c:
            yield c
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("header", [
    None, "Basic abc", "Bearer not-a-token", "Bearer ", f"Bearer {EXPIRED}", f"Bearer {FORGED}",
])
def test_any_authorization_header_gets_the_public_response(client, path, header):
    anonymous = client.get(path)
    response = client.get(path, headers={"Authorization": header} if header else {})
    assert response.status_code == anonymous.status_code == 200
    assert response.json() == anonymous.json()


def test_service_uses_shared_db_session_and_jwt_derived_key(monkeypatch):
    """T17 전용 세션·키 설정 없이 T14 `get_db`와 `JWT_SECRET`만으로 서비스가 만들어진다."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("T17_CURSOR_KEY", raising=False)
    get_settings.cache_clear()

    class EmptySession:
        def execute(self, _statement):
            return self

        def mappings(self):
            return []

    try:
        app = create_app()
        app.dependency_overrides[get_db] = EmptySession
        with TestClient(app) as c:
            for path in ["/api/v1/job-roles", "/api/v1/skills?q=py"]:
                response = c.get(path)
                assert response.status_code == 200, response.text
    finally:
        get_settings.cache_clear()


def test_openapi_marks_auth_optional_exactly_once(client):
    spec = client.get("/openapi.json").json()
    for path in ["/api/v1/job-roles", "/api/v1/skills", "/api/v1/job-roles/{job_role_id}"]:
        operation = spec["paths"][path]["get"]
        assert operation["security"] == [{}, {"HTTPBearer": []}]
        assert "401" not in operation["responses"]
        assert "503" in operation["responses"]
