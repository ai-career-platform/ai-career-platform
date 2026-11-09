import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    get_settings.cache_clear()
    yield create_app()
    get_settings.cache_clear()


def test_app_startup_and_shutdown(app):
    assert app.state.ready is False
    with TestClient(app):
        assert app.state.ready is True
    assert app.state.ready is False


def test_health(app):
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ai-career-backend"}


def test_version_reads_environment(app):
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {
        "application": "ai-career-platform",
        "environment": "test",
        "version": "9.9.9",
    }


def test_openapi_lists_system_routes(app):
    with TestClient(app) as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "ai-career-platform"
    assert spec["info"]["version"] == "9.9.9"
    assert {
        "/health", "/health/db", "/version", "/api/v1/job-roles",
        "/api/v1/job-roles/{job_role_id}", "/api/v1/skills",
    } <= set(spec["paths"])


def test_docs_page_served(app):
    with TestClient(app) as client:
        response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_unimplemented_api_v1_route_returns_404(app):
    with TestClient(app) as client:
        response = client.get("/api/v1/unimplemented-smoke-test")
    assert response.status_code == 404


def test_settings_defaults_without_environment(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("APP_VERSION", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.app_env == "local-dev"
        assert settings.app_version == "0.1.0"
    finally:
        get_settings.cache_clear()
