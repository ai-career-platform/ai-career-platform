"""T17 PostgreSQL 통합 테스트 (선택 실행) — T05 스키마 + T10 Seed가 적용된 **로컬 일회용 DB** 기준.

`T17_TEST_DATABASE_URL`(postgresql://...)을 지정했을 때만 실행하고, 호스트가 localhost가 아니면 거부한다.
테스트 데이터 변경은 트랜잭션 롤백 또는 finally 정리로 되돌린다. 준비 절차: backend/tests/T17_RUNTIME_SETUP.md
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.main import create_app
from app.core.security import issue_access_token
from app.core.config import get_settings
from app.repositories.catalog import SqlCatalogRepository
from app.routers.catalog import get_catalog_service
from app.schemas.catalog import JobRoleQuery, SkillQuery
from app.core.errors import AppError, ErrorCode
from app.services.catalog import CatalogService

DB_URL = os.environ.get("T17_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DB_URL, reason="T17_TEST_DATABASE_URL not set")
if DB_URL and make_url(DB_URL).host not in {"localhost", "127.0.0.1", "::1"}:
    raise RuntimeError("T17 Postgres tests run only against a local disposable DB")
SQLA_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def session():
    engine = create_engine(SQLA_URL)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                yield session
            transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def service(session):
    return CatalogService(SqlCatalogRepository(session), cursor_key=b"postgres-local-test-only-" * 2)


@pytest.mark.parametrize("limit", [1, 7, 9, 20, 100])
def test_seed_full_pagination_and_unicode_search(service, limit):
    ids, cursor = [], None
    for _ in range(31):
        page = service.list_job_roles(JobRoleQuery(limit=limit, cursor=cursor))
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
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    monkeypatch.delenv("T17_CURSOR_KEY", raising=False)
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
        assert app.state.db_session_factory is None
    finally:
        get_settings.cache_clear()


def test_postgres_renamed_anchor_rejected(session, service):
    first = service.list_job_roles(JobRoleQuery(limit=1))
    session.execute(text("UPDATE career.job_roles SET name=:name WHERE job_role_id=:id"),
                    {"name": "Zzz renamed anchor", "id": first.items[0].job_role_id})
    with pytest.raises(AppError) as exc:
        service.list_job_roles(JobRoleQuery(cursor=first.next_cursor))
    assert exc.value.code == ErrorCode.INVALID_CURSOR


def test_logged_in_request_uses_one_connection_and_same_response(monkeypatch):
    """토큰이 있어도 카탈로그는 인증 DB 조회를 하지 않으므로 풀 크기 1에서도 막히지 않는다."""
    url = DB_URL
    engine = create_engine(SQLA_URL)
    sid = uuid4()
    key = "T17-local-postgres-auth-test-key-only-0123456"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DB_POOL_SIZE", "1")
    monkeypatch.setenv("DB_TIMEOUT_SECONDS", "1")
    monkeypatch.setenv("JWT_SECRET", key)
    get_settings.cache_clear()
    try:
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            owner = connection.scalar(text("SELECT user_id FROM career.users WHERE status='active' ORDER BY user_id LIMIT 1"))
            assert owner is not None
            connection.execute(text(
                "INSERT INTO career.auth_sessions "
                "(session_id,user_id,refresh_token_hash,created_at,expires_at) "
                "VALUES (:sid,:owner,:hash,:now,:expires)"
            ), {"sid": sid, "owner": owner, "hash": "test-only-" + sid.hex,
                "now": now, "expires": now + timedelta(hours=1)})
        token = issue_access_token(key, owner, sid, [], 900)
        app = create_app()
        with TestClient(app) as client:
            for path in ["/api/v1/job-roles?limit=1", "/api/v1/skills?q=python"]:
                response = client.get(path, headers={"Authorization": f"Bearer {token}"})
                assert response.status_code == 200, response.text
                assert response.json() == client.get(path).json()
            role_id = client.get("/api/v1/job-roles?limit=1").json()["items"][0]["job_role_id"]
            assert client.get(f"/api/v1/job-roles/{role_id}", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    finally:
        try:
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM career.auth_sessions WHERE session_id=:sid"), {"sid": sid})
        finally:
            engine.dispose()
            get_settings.cache_clear()
