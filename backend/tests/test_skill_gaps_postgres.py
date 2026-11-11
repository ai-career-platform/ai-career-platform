"""Opt-in T43 persistence tests on a separately provisioned T09 local DB.

Never creates/drops schema. Per-test changes use an outer transaction and
savepoints, including service commit/rollback, and are rolled back on teardown.
A separate durability test commits its own generated rows and removes them
in teardown. Two cases use the actual merged T26 calculator. Stale policy
and approved test-model rows are still synthetic test dependencies.
"""

import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.core.errors import AppError, ErrorCode
from app.repositories.skill_gaps import RuleEvaluation, SqlSkillGapRepository
from app.schemas.skill_gaps import GapModelVersion, SkillGap, SkillGapHistoryQuery, SkillGapItem
from app.services.skill_gaps import SkillGapService
from app.services.skill_gap_evaluator import T26SkillGapEvaluator
from tests.test_skill_gaps import STAMP

DB_URL = os.environ.get("T43_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="T43 dedicated local T09 database not configured")


class SeedRuleFixture:
    """Precomputed T10 BACKEND_ENGINEER fixture, not a T26 replacement."""

    VALUES = {
        "PYTHON": (5, 4, 1), "FASTAPI": (4, 3, 1), "POSTGRESQL": (3, 2, 1),
        "REST_API": (2, 0, 2), "DOCKER": (1, 0, 1),
    }

    def __init__(self, model):
        self.model = model

    def evaluate(self, snapshot):
        return RuleEvaluation(model_version=self.model, items=tuple(
            SkillGapItem(skill=item.skill, required_level=self.VALUES[item.skill.code][0],
                         observed_level=self.VALUES[item.skill.code][1], gap=self.VALUES[item.skill.code][2])
            for item in snapshot.requirements
        ))


@pytest.fixture
def case():
    parsed = make_url(DB_URL)
    assert parsed.host in {"127.0.0.1", "localhost"}
    assert parsed.port == 25437 and parsed.database.startswith("t43_local_")
    engine = create_engine(parsed.set(drivername="postgresql+psycopg"))
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            assert connection.scalar(text("SELECT count(*) FROM career_migration.schema_migrations WHERE version='0001'")) == 1
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                owner = session.scalar(text("SELECT user_id FROM career.users WHERE email='seed-user-01@example.com'"))
                other = session.scalar(text("SELECT user_id FROM career.users WHERE email='seed-user-02@example.com'"))
                role = session.scalar(text("SELECT job_role_id FROM career.job_roles WHERE code='BACKEND_ENGINEER'"))
                model_id = uuid4()
                model = GapModelVersion(model_code="t43_synthetic_" + model_id.hex, version="1", kind="rule")
                session.execute(text("INSERT INTO career.model_versions (model_version_id,model_code,version,kind,approved_at) VALUES (:id,:code,'1','rule',:approved)"),
                                {"id": model_id, "code": model.model_code, "approved": STAMP})
                session.execute(text("INSERT INTO career.user_target_roles (user_id,job_role_id,priority) VALUES (:owner,:role,1)"),
                                {"owner": owner, "role": role})
                # T10 assigns roles by its own ordering. Explicitly prepare
                # this test's backend levels instead of assuming that order.
                session.execute(text("DELETE FROM career.user_skills WHERE user_id=:owner"), {"owner": owner})
                for code, proficiency in [("PYTHON", 4), ("FASTAPI", 3), ("POSTGRESQL", 2)]:
                    session.execute(text("INSERT INTO career.user_skills (user_id,skill_id,proficiency) SELECT :owner,skill_id,:level FROM career.skills WHERE code=:code"),
                                    {"owner": owner, "level": proficiency, "code": code})
                session.commit()
                state = {"stale": False}
                repository = SqlSkillGapRepository(session, stale_checker=lambda *_: state["stale"])
                service = SkillGapService(repository, SeedRuleFixture(model), clock=lambda: STAMP,
                                          cursor_key=b"T43-postgres-test-key-only-" * 2)
                yield SimpleNamespace(session=session, repository=repository, service=service,
                                      owner=owner, other=other, role=role, model_id=model_id, state=state)
            transaction.rollback()
    finally:
        engine.dispose()


def test_single_statement_input_snapshot_and_owner_filter(case):
    statements = []
    connection = case.session.connection()
    def record(*args):
        statements.append(args[2])
    event.listen(connection, "before_cursor_execute", record)
    try:
        snapshot = case.repository.load_inputs(user_id=case.owner, job_role_id=case.role)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert len(statements) == 1
    assert snapshot.is_target_role
    assert len(snapshot.requirements) == 5
    assert len(snapshot.observed_levels) == 3
    assert not case.repository.load_inputs(user_id=case.other, job_role_id=case.role).is_target_role
    assert case.repository.load_inputs(user_id=case.owner, job_role_id=UUID(int=0)) is None


@pytest.mark.parametrize("null_proficiency", [False, True])
def test_real_t26_sql_save_and_history(case, null_proficiency):
    if null_proficiency:
        case.session.execute(text("UPDATE career.user_skills SET proficiency=NULL WHERE user_id=:owner AND skill_id=(SELECT skill_id FROM career.skills WHERE code='PYTHON')"), {"owner": case.owner})
    model = case.service.evaluator.model
    service = SkillGapService(case.repository, T26SkillGapEvaluator.from_t26(model),
                             clock=lambda: STAMP, cursor_key=b"T43-real-T26-local-test-only-" * 2)
    result = service.create(user_id=case.owner, job_role_id=case.role)
    levels = {item.skill.code: (item.required_level, item.observed_level, item.gap) for item in result.items}
    assert levels["PYTHON"] == ((5, 0, 5) if null_proficiency else (5, 4, 1))
    assert levels["REST_API"] == (2, 0, 2)  # absent skill also becomes numeric zero
    assert service.get(user_id=case.owner, assessment_id=result.assessment_id).items == result.items
    page = service.list_history(user_id=case.owner, query=SkillGapHistoryQuery(limit=1))
    assert page.items[0].total_gap == sum(item.gap for item in result.items)
    assert page.items[0].assessment_id == result.assessment_id
    if null_proficiency:
        assert case.session.scalar(text("SELECT proficiency FROM career.user_skills WHERE user_id=:owner AND skill_id=(SELECT skill_id FROM career.skills WHERE code='PYTHON')"), {"owner": case.owner}) is None


def test_http_real_calculator_and_database_with_injected_identity(case, monkeypatch):
    """Real HTTP/DTO/calculation/DB; identity and stale policy remain test doubles."""
    from app.core.config import get_settings
    from app.dependencies.auth import get_current_user
    from app.main import create_app
    from app.routers.skill_gaps import get_skill_gap_service, router
    from app.services.auth import CurrentUser

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", "T43-http-db-test-only-signature-key-123456789")
    get_settings.cache_clear()
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    identity = {"user": case.owner}
    service = SkillGapService(case.repository,
        T26SkillGapEvaluator.from_t26(case.service.evaluator.model),
        clock=lambda: STAMP, cursor_key=b"T43-http-database-test-key-only-" * 2)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=identity["user"], session_id=uuid4(), roles=frozenset(), permissions=frozenset())
    app.dependency_overrides[get_skill_gap_service] = lambda: service
    try:
        with TestClient(app, base_url="https://testserver") as client:
            response = client.post("/api/v1/skill-gaps", json={"job_role_id": str(case.role)})
            assert response.status_code == 201, response.text
            created = response.json()
            assert next(item for item in created["items"] if item["skill"]["code"] == "PYTHON")["gap"] == 1
            detail = client.get(response.headers["location"])
            assert detail.status_code == 200
            # PostgreSQL can serialize the same instant in its session timezone.
            assert SkillGap.model_validate(detail.json()) == SkillGap.model_validate(created)
            history = client.get("/api/v1/skill-gaps", params={"job_role_id": str(case.role), "limit": 1})
            assert history.status_code == 200
            assert history.json()["items"][0]["assessment_id"] == created["assessment_id"]
            assert history.json()["items"][0]["total_gap"] == 6
            invalid = client.get("/api/v1/skill-gaps", params={"cursor": ""})
            assert invalid.status_code == 400 and invalid.json()["code"] == "INVALID_CURSOR"
            identity["user"] = case.other
            assert client.get(response.headers["location"]).status_code == 404
            assert client.get("/api/v1/skill-gaps").json() == {"items": [], "next_cursor": None}
    finally:
        get_settings.cache_clear()


def test_save_numeric_snapshot_and_read_without_recalculation(case):
    result = case.service.create(user_id=case.owner, job_role_id=case.role)
    assert len(result.items) == 5
    case.session.execute(text("UPDATE career.user_skills SET proficiency=5 WHERE user_id=:owner"), {"owner": case.owner})
    case.state["stale"] = True  # Policy is a deliberate test double, not a DB stale algorithm.
    historical = case.service.get(user_id=case.owner, assessment_id=result.assessment_id)
    assert historical.items == result.items
    assert historical.is_stale
    assert historical.model_version == result.model_version


def test_other_owner_and_missing_results_are_not_disclosed(case):
    result = case.service.create(user_id=case.owner, job_role_id=case.role)
    assert case.repository.get_owned(user_id=case.other, assessment_id=result.assessment_id) is None
    assert case.repository.get_owned(user_id=case.owner, assessment_id=uuid4()) is None
    assert case.repository.list_owned(user_id=case.other, job_role_id=None, before=None, limit=20) == []


@pytest.mark.parametrize("limit", [1, 2, 20, 100])
def test_sql_history_summaries_and_keyset_ties(case, limit):
    results = [case.service.create(user_id=case.owner, job_role_id=case.role) for _ in range(3)]
    seen, cursor = [], None
    for _ in range(4):
        page = case.service.list_history(user_id=case.owner, query=SkillGapHistoryQuery(
            limit=limit, job_role_id=case.role, cursor=cursor,
        ))
        for row in page.items:
            assert row.missing_skill_count == 5 and row.total_gap == 6
        seen.extend(row.assessment_id for row in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == sorted([row.assessment_id for row in results], reverse=True)
    assert len(seen) == len(set(seen)) == 3
    assert cursor is None
    assert case.service.list_history(user_id=case.owner, query=SkillGapHistoryQuery(job_role_id=uuid4())).items == []


@pytest.mark.parametrize("mode", ["unapproved", "unknown_version"])
def test_unapproved_or_unknown_model_not_saved(case, mode):
    if mode == "unapproved":
        case.session.execute(text("UPDATE career.model_versions SET approved_at=NULL WHERE model_version_id=:id"), {"id": case.model_id})
        case.session.commit()
    else:
        case.service.evaluator.model = case.service.evaluator.model.model_copy(update={"version": "missing"})
    with pytest.raises(AppError) as exc:
        case.service.create(user_id=case.owner, job_role_id=case.role)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert case.session.scalar(text("SELECT count(*) FROM career.skill_gap_assessments WHERE user_id=:owner"), {"owner": case.owner}) == 0


def test_partial_item_failure_rolls_back_assessment(case):
    save = case.repository.save
    def save_then_fail(**kwargs):
        save(**kwargs)
        case.session.execute(text("INSERT INTO career.skill_gap_items (assessment_id,skill_id,required_level,observed_level,gap) VALUES (:id,:missing,1,0,1)"),
                             {"id": kwargs["assessment"].assessment_id, "missing": uuid4()})
    case.repository.save = save_then_fail
    with pytest.raises(IntegrityError):
        case.service.create(user_id=case.owner, job_role_id=case.role)
    assert case.session.scalar(text("SELECT count(*) FROM career.skill_gap_assessments WHERE user_id=:owner"), {"owner": case.owner}) == 0
    assert case.session.scalar(text("SELECT count(*) FROM career.skill_gap_items")) == 0


def test_empty_result_still_has_zero_summary(case):
    case.service.evaluator.evaluate = lambda snapshot: RuleEvaluation(case.service.evaluator.model, ())
    result = case.service.create(user_id=case.owner, job_role_id=case.role)
    assert case.service.get(user_id=case.owner, assessment_id=result.assessment_id).items == []
    summary = case.service.list_history(user_id=case.owner, query=SkillGapHistoryQuery()).items[0]
    assert summary.total_gap == summary.missing_skill_count == 0


def test_unknown_stale_policy_result_fails_closed(case):
    result = case.service.create(user_id=case.owner, job_role_id=case.role)
    case.repository.stale_checker = lambda *_: None
    with pytest.raises(AppError) as exc:
        case.service.get(user_id=case.owner, assessment_id=result.assessment_id)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_source_null_and_missing_levels_are_not_conflated(case):
    case.session.execute(text("UPDATE career.user_skills SET proficiency=NULL WHERE user_id=:owner AND skill_id=(SELECT skill_id FROM career.skills WHERE code='PYTHON')"), {"owner": case.owner})
    snapshot = case.repository.load_inputs(user_id=case.owner, job_role_id=case.role)
    by_code = {item.skill.code: item.skill.skill_id for item in snapshot.requirements}
    assert snapshot.observed_levels[by_code["PYTHON"]] is None
    assert by_code["DOCKER"] not in snapshot.observed_levels


def test_committed_assessment_visible_in_new_session(case):
    """Separate real transaction verifies durable commit, then deletes own rows."""
    template = case.service.create(user_id=case.owner, job_role_id=case.role)
    identifier, model_id = uuid4(), uuid4()
    model = template.model_version.model_copy(update={"model_code": "t43_commit_fixture_" + model_id.hex})
    assessment = template.model_copy(update={"assessment_id": identifier, "model_version": model})
    engine = create_engine(make_url(DB_URL).set(drivername="postgresql+psycopg"))
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO career.model_versions (model_version_id,model_code,version,kind,approved_at) VALUES (:id,:code,'1','rule',:approved)"),
                               {"id": model_id, "code": model.model_code, "approved": STAMP})
        with Session(engine) as writer:
            repository = SqlSkillGapRepository(writer, stale_checker=lambda *_: False)
            repository.save(user_id=case.owner, assessment=assessment)
            repository.commit()
        with Session(engine) as reader:
            read = SqlSkillGapRepository(reader, stale_checker=lambda *_: False).get_owned(
                user_id=case.owner, assessment_id=identifier,
            )
            assert read == assessment
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM career.skill_gap_assessments WHERE assessment_id=:id"), {"id": identifier})
            connection.execute(text("DELETE FROM career.model_versions WHERE model_version_id=:id"), {"id": model_id})
        engine.dispose()
