"""SQL execution tests on isolated SQLite; PostgreSQL still needs verification."""

from uuid import UUID

import pytest
from sqlalchemy import (
    Boolean, Column, Integer, MetaData, String, Table, Uuid, create_engine, insert,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.repositories.catalog_sqlalchemy import SQLAlchemyCatalogRepository
from app.schemas.catalog import JobRoleQuery
from app.services.catalog import CatalogService


@pytest.fixture
def repository():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    roles = Table("job_roles", metadata,
        Column("job_role_id", Uuid, primary_key=True), Column("code", String),
        Column("name", String), Column("description", String), Column("is_active", Boolean))
    skills = Table("skills", metadata,
        Column("skill_id", Uuid, primary_key=True), Column("code", String),
        Column("name", String), Column("is_active", Boolean))
    links = Table("job_role_skills", metadata,
        Column("job_role_id", Uuid, primary_key=True),
        Column("skill_id", Uuid, primary_key=True), Column("required_level", Integer))
    metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(insert(roles), [
            dict(job_role_id=UUID(int=i), code=f"synthetic-{i}", name=name,
                 description=None, is_active=active)
            for i, name, active in [(1, "Backend", True), (2, "Backend", True),
                                    (3, "Frontend", True), (4, "Retired", False)]
        ])
        session.execute(insert(skills), [
            dict(skill_id=UUID(int=i), code=f"synthetic-skill-{i}", name=name, is_active=active)
            for i, name, active in [(1, "CPython", True), (2, "Python", True),
                (3, "100% SQL", True), (4, "100X SQL", True),
                (5, "under_score", True), (6, "underXscore", True), (7, "Python old", False)]
        ])
        session.execute(insert(links), [dict(job_role_id=UUID(int=1), skill_id=UUID(int=2), required_level=4)])
        yield SQLAlchemyCatalogRepository(session, schema=None)
    engine.dispose()


def test_sql_paging_active_filter_and_ties(repository):
    service = CatalogService(repository, cursor_key=b"synthetic-sql-test-key" * 2)
    ids, cursor = [], None
    for _ in range(3):
        page = service.list_job_roles(JobRoleQuery(limit=1, cursor=cursor))
        ids.extend(r.job_role_id.int for r in page.items)
        cursor = page.next_cursor
    assert ids == [1, 2, 3]
    assert cursor is None
    assert [r.job_role_id.int for r in repository.list_job_roles(q="BACK", after=None, limit=100)] == [1, 2]


def test_sql_detail_relationship_empty_and_missing(repository):
    role = repository.get_job_role(UUID(int=1))
    assert role.required_skills[0].skill.name == "Python"
    assert role.required_skills[0].required_level == 4
    assert repository.get_job_role(UUID(int=2)).required_skills == []
    assert repository.get_job_role(UUID(int=99)) is None


def test_sql_skill_ranking_limit_and_literal_search(repository):
    assert [s.name for s in repository.search_skills(q="PY", limit=20)] == ["Python", "CPython"]
    assert len(repository.search_skills(q="py", limit=1)) == 1
    assert [s.name for s in repository.search_skills(q="0%", limit=20)] == ["100% SQL"]
    assert [s.name for s in repository.search_skills(q="_", limit=20)] == ["under_score"]
    assert repository.search_skills(q="' OR 1=1 --", limit=20) == []


def test_postgres_parameterization_and_schema():
    class Capture:
        def execute(self, statement):
            self.compiled = statement.compile(dialect=postgresql.dialect())
            class Empty:
                def mappings(self):
                    return []
            return Empty()
    session = Capture()
    repo = SQLAlchemyCatalogRepository(session)
    hostile = "' OR 1=1 --"
    repo.list_job_roles(q=hostile, after=("Backend", UUID(int=1)), limit=2)
    sql = str(session.compiled)
    assert "career.job_roles" in sql
    assert hostile not in sql
    assert any(hostile in str(value) for value in session.compiled.params.values())
    assert "LIMIT" in sql
