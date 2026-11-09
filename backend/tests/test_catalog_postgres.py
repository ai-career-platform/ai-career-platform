"""Opt-in integration tests for the dedicated T17 temporary local cluster.

Set T17_LOCAL_POSTGRES=1 only after provisioning 127.0.0.1:25437 with
user t17_test, T05 validation schema and T10 Seed. Never points to staging.
"""

import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.main import create_app
from app.core.config import get_settings
from app.repositories.catalog import SqlCatalogRepository
from app.routers.catalog import get_catalog_service
from app.schemas.catalog import JobRoleQuery, SkillQuery
from app.core.errors import AppError, ErrorCode
from app.services.catalog import CatalogService

pytestmark = pytest.mark.skipif(
    os.environ.get("T17_LOCAL_POSTGRES") != "1",
    reason="Dedicated temporary PostgreSQL test cluster is opt-in",
)


@pytest.fixture
def session():
    engine = create_engine("postgresql+psycopg://t17_test@127.0.0.1:25437/postgres")
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            assert connection.scalar(text("SELECT current_user")) == "t17_test"
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                yield session
            transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def service(session):
    return CatalogService(
        SqlCatalogRepository(session), cursor_key=b"postgres-local-test-only-" * 2
    )


def test_seed_full_pagination_and_unicode_search(service):
    ids, cursor = [], None
    for _ in range(20):
        page = service.list_job_roles(JobRoleQuery(limit=7, cursor=cursor))
        ids.extend(r.job_role_id for r in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(ids) == len(set(ids)) == 30
    assert cursor is None
    page = service.list_job_roles(JobRoleQuery(q="백엔드"))
    assert [r.code for r in page.items] == ["BACKEND_ENGINEER"]
    assert service.search_skills(SkillQuery(q="pYtHoN")).items[0].code == "PYTHON"


def test_seed_detail_relationship_and_missing(service):
    role = service.list_job_roles(JobRoleQuery(q="백엔드")).items[0]
    detail = service.get_job_role(role.job_role_id)
    assert len(detail.required_skills) == 5
    levels = {s.skill.code: s.required_level for s in detail.required_skills}
    assert levels["PYTHON"] == 5
    assert levels["DOCKER"] == 1
    with pytest.raises(AppError) as exc:
        service.get_job_role(UUID(int=0))
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_active_filters_literal_wildcards_and_empty_relationship(session, service):
    role = service.list_job_roles(JobRoleQuery(q="백엔드")).items[0]
    session.execute(text("UPDATE career.job_roles SET is_active=false WHERE job_role_id=:id"),
                    {"id": role.job_role_id})
    assert service.list_job_roles(JobRoleQuery(q="백엔드")).items == []
    session.execute(text("UPDATE career.skills SET is_active=false WHERE code='PYTHON'"))
    assert service.search_skills(SkillQuery(q="python")).items == []
    for query in ["%_", "' OR 1=1 --", "미존재기술"]:
        assert service.search_skills(SkillQuery(q=query)).items == []
    session.execute(text("DELETE FROM career.job_role_skills WHERE job_role_id=:id"),
                    {"id": role.job_role_id})
    assert service.get_job_role(role.job_role_id).required_skills == []


def test_http_with_real_repository(service):
    app = create_app()
    app.dependency_overrides[get_catalog_service] = lambda: service
    with TestClient(app) as client:
        response = client.get("/api/v1/job-roles", params={"q": "백엔드"})
        assert response.status_code == 200
        assert response.json()["items"][0]["code"] == "BACKEND_ENGINEER"
        missing = client.get("/api/v1/job-roles/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404
        assert missing.json()["code"] == "NOT_FOUND"
        assert client.get("/api/v1/job-roles?cursor=broken").status_code == 400
        assert client.get("/api/v1/skills?q=a").status_code == 422


def test_t14_runtime_provider_without_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://t17_test@127.0.0.1:25437/postgres")
    monkeypatch.setenv("T17_CURSOR_KEY", "dedicated-local-test-key-not-for-deployment-123")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as client:
            assert app.dependency_overrides == {}
            assert client.get("/health/db").status_code == 200
            first = client.get("/api/v1/job-roles?limit=1")
            assert first.status_code == 200
            page = first.json()
            second = client.get("/api/v1/job-roles", params={
                "limit": 1, "cursor": page["next_cursor"],
            })
            assert second.status_code == 200
            assert second.json()["items"][0]["job_role_id"] != page["items"][0]["job_role_id"]
            detail = client.get("/api/v1/job-roles/" + page["items"][0]["job_role_id"])
            assert detail.status_code == 200
            assert len(detail.json()["required_skills"]) == 5
            assert client.get("/api/v1/skills?q=python").json()["items"][0]["code"] == "PYTHON"
            assert client.get("/api/v1/job-roles?cursor=broken").status_code == 400
            assert client.get("/api/v1/skills?q=a").status_code == 422
            assert client.get("/api/v1/job-roles/00000000-0000-0000-0000-000000000000").status_code == 404
            monkeypatch.delenv("T17_CURSOR_KEY")
            assert client.get("/api/v1/job-roles").status_code == 503
        assert app.state.db_session_factory is None
    finally:
        get_settings.cache_clear()
