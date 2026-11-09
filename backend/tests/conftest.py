import uuid

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.core.config import API_V1_PREFIX, get_settings
from app.dependencies.auth import (
    CurrentUserDep,
    ensure_owner,
    require_permissions,
    require_roles,
)
from app.main import create_app
from tests.fakes import MemoryAuthRepository, override_auth_repository

TEST_SECRET = "t15-test-secret-0123456789-abcdefghij"
PASSWORD = "correct-horse-battery-1"
CONSENTS = [
    {"policy_code": "terms", "policy_version": "2026-11", "granted": True},
    {"policy_code": "privacy", "policy_version": "2026-11", "granted": True},
    {"policy_code": "llm_processing", "policy_version": "2026-11", "granted": False},
]


def build_probe_router(owners: dict[uuid.UUID, uuid.UUID]) -> APIRouter:
    """기능 라우터가 인가 의존성을 쓰는 방식을 흉내 낸 테스트 전용 경로."""
    router = APIRouter(prefix="/_probe")

    @router.get("/admin", dependencies=[Depends(require_roles("admin"))])
    def admin_only() -> dict:
        return {"ok": True}

    @router.get("/audit", dependencies=[Depends(require_permissions("admin.audit.read"))])
    def audit_only() -> dict:
        return {"ok": True}

    @router.get("/documents/{document_id}")
    def owned_document(document_id: uuid.UUID, user: CurrentUserDep) -> dict:
        ensure_owner(owners.get(document_id), user)
        return {"document_id": str(document_id)}

    return router


@pytest.fixture
def repo() -> MemoryAuthRepository:
    return MemoryAuthRepository()


@pytest.fixture
def owners() -> dict[uuid.UUID, uuid.UUID]:
    return {}


@pytest.fixture
def app(monkeypatch, repo, owners):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.include_router(build_probe_router(owners), prefix=API_V1_PREFIX)
    override_auth_repository(application, repo)
    yield application
    get_settings.cache_clear()


@pytest.fixture
def client(app):
    # refresh 쿠키가 Secure이므로 https 기준 주소를 쓴다.
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def signup(client: TestClient, email: str = "seeker@example.com", **overrides):
    body = {"email": email, "password": PASSWORD, "display_name": "김구직", "consents": CONSENTS, **overrides}
    return client.post(f"{API_V1_PREFIX}/auth/signup", json=body)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
