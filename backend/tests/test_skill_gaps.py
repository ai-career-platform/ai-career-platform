"""T43 mock integration only; does not certify T26 calculations or DB writes."""

from dataclasses import replace
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from pydantic import ValidationError
import pytest
import yaml

from app.core.errors import AppError, ErrorCode
from app.dependencies.auth import get_current_user
from app.services.auth import CurrentUser
from app.schemas.catalog import JobRoleRef, Skill
from app.main import create_app
from app.repositories.skill_gaps import GapInputSnapshot, RequiredGapSkill, RuleEvaluation
from app.routers.skill_gaps import get_skill_gap_service, router
from app.schemas.skill_gaps import (
    GapModelVersion, SkillGapHistoryQuery, SkillGapItem,
    SkillGapRequest, SkillGapSummary,
)
from app.services.skill_gaps import SkillGapService

USER = UUID(int=1)
OTHER_USER = UUID(int=2)
ROLE = UUID(int=10)
STAMP = datetime(2026, 11, 9, tzinfo=timezone.utc)
SKILL = Skill(skill_id=UUID(int=20), code="SYNTHETIC_SKILL", name="Synthetic skill")


class MemoryGapRepository:
    """Proposed port fixture. Not a DB adapter or stale-detection algorithm."""

    def __init__(self):
        self.owner = USER
        self.snapshot = GapInputSnapshot(
            role=JobRoleRef(job_role_id=ROLE, code="SYNTHETIC_ROLE", name="Synthetic role"),
            is_target_role=True,
            requirements=(RequiredGapSkill(skill=SKILL, required_level=4),),
            observed_levels={SKILL.skill_id: 2},
        )
        self.saved = {}
        self.committed = {}
        self.stale = False

    def load_inputs(self, *, user_id, job_role_id):
        assert user_id == self.owner
        return self.snapshot if job_role_id == ROLE else None

    def save(self, *, user_id, assessment):
        self.saved[(user_id, assessment.assessment_id)] = assessment.model_copy(deep=True)

    def commit(self):
        self.committed = deepcopy(self.saved)

    def rollback(self):
        self.saved = deepcopy(self.committed)

    def get_owned(self, *, user_id, assessment_id):
        saved = self.saved.get((user_id, assessment_id))
        return saved.model_copy(update={"is_stale": self.stale}, deep=True) if saved else None

    def list_owned(self, *, user_id, job_role_id, before, limit):
        self.last_history_limit = limit
        rows = [assessment for (owner, _), assessment in self.saved.items()
                if owner == user_id
                and (job_role_id is None or assessment.job_role.job_role_id == job_role_id)
                and (before is None or (assessment.evaluated_at, assessment.assessment_id) < before)]
        rows.sort(key=lambda row: (row.evaluated_at, row.assessment_id), reverse=True)
        return [SkillGapSummary(
            assessment_id=row.assessment_id, job_role=row.job_role,
            missing_skill_count=sum(item.gap > 0 for item in row.items),
            total_gap=sum(item.gap for item in row.items),
            is_stale=self.stale, evaluated_at=row.evaluated_at,
        ) for row in rows[:limit]]


class FixedRuleFixture:
    """Precomputed fixture, not the T26 implementation."""

    def __init__(self):
        self.calls = 0
        self.items = (SkillGapItem(skill=SKILL, required_level=4, observed_level=2, gap=2),)

    def evaluate(self, snapshot):
        self.calls += 1
        self.last_inputs = snapshot
        return RuleEvaluation(
            model_version=GapModelVersion(model_code="synthetic_gap_fixture", version="1", kind="rule"),
            items=self.items,
        )


@pytest.fixture
def service():
    return SkillGapService(
        MemoryGapRepository(), FixedRuleFixture(), clock=lambda: STAMP,
        new_id=lambda: UUID(int=100),
        cursor_key=b"T43-history-fixture-key-only-" * 2,
    )


@pytest.fixture
def client(service):
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(USER, UUID(int=99), frozenset(), frozenset())
    app.dependency_overrides[get_skill_gap_service] = lambda: service
    with TestClient(app) as client:
        yield client


def test_create_snapshot_and_owned_get_without_recalculation(service):
    result = service.create(user_id=USER, job_role_id=ROLE)
    assert result.evaluated_at == STAMP
    assert result.items[0].gap == 2
    service.repository.snapshot = replace(service.repository.snapshot, observed_levels={SKILL.skill_id: 5})
    service.repository.stale = True
    historical = service.get(user_id=USER, assessment_id=result.assessment_id)
    assert historical.is_stale is True
    assert historical.items[0].observed_level == 2
    assert service.evaluator.calls == 1


def test_foreign_and_missing_results_indistinguishable(service):
    result = service.create(user_id=USER, job_role_id=ROLE)
    for user, assessment in [(OTHER_USER, result.assessment_id), (USER, UUID(int=999))]:
        with pytest.raises(AppError) as exc:
            service.get(user_id=user, assessment_id=assessment)
        assert exc.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize("case,code", [
    ("missing_role", ErrorCode.NOT_FOUND),
    ("not_target", ErrorCode.NOT_A_TARGET_ROLE),
    ("no_skills", ErrorCode.NO_USER_SKILLS),
])
def test_create_preconditions_do_not_evaluate_or_save(service, case, code):
    role = ROLE
    if case == "missing_role":
        role = UUID(int=999)
    elif case == "not_target":
        service.repository.snapshot = replace(service.repository.snapshot, is_target_role=False)
    else:
        service.repository.snapshot = replace(service.repository.snapshot, observed_levels={})
    with pytest.raises(AppError) as exc:
        service.create(user_id=USER, job_role_id=role)
    assert exc.value.code == code
    assert service.evaluator.calls == 0
    assert not service.repository.saved


def test_unknown_proficiency_passed_to_t26_without_rewriting(service):
    service.repository.snapshot = replace(service.repository.snapshot, observed_levels={SKILL.skill_id: None})
    service.evaluator.items = (SkillGapItem(skill=SKILL, required_level=4, observed_level=0, gap=4),)
    assert service.create(user_id=USER, job_role_id=ROLE).items[0].observed_level == 0
    assert service.evaluator.last_inputs.observed_levels[SKILL.skill_id] is None


def test_duplicate_rule_result_rejected_before_save(service):
    service.evaluator.items = service.evaluator.items * 2
    with pytest.raises(AppError) as exc:
        service.create(user_id=USER, job_role_id=ROLE)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not service.repository.saved


def test_result_order_and_fixed_input_reproducibility(service):
    other_skill = Skill(skill_id=UUID(int=21), code="SECOND_SYNTHETIC", name="Another skill")
    service.repository.snapshot = replace(service.repository.snapshot, requirements=(
        *service.repository.snapshot.requirements,
        RequiredGapSkill(skill=other_skill, required_level=5),
    ))
    service.evaluator.items = (
        SkillGapItem(skill=SKILL, required_level=4, observed_level=2, gap=2),
        SkillGapItem(skill=other_skill, required_level=5, observed_level=0, gap=5),
    )
    first = service.create(user_id=USER, job_role_id=ROLE)
    second = service.create(user_id=USER, job_role_id=ROLE)
    assert first == second
    assert [item.gap for item in first.items] == [5, 2]


def test_empty_rule_result_is_preserved(service):
    service.evaluator.items = ()
    assert service.create(user_id=USER, job_role_id=ROLE).items == []


def test_http_create_location_and_get_match_contract(client):
    response = client.post("/api/v1/skill-gaps", json={"job_role_id": str(ROLE)})
    assert response.status_code == 201
    location = response.headers["location"]
    assert location == "/api/v1/skill-gaps/00000000-0000-0000-0000-000000000064"
    result = client.get(location)
    assert result.status_code == 200
    assert result.json() == response.json()
    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    Draft202012Validator({
        "$ref": "#/components/schemas/SkillGap", "components": spec["components"],
    }).validate(response.json())


def test_body_user_id_cannot_select_owner(client):
    response = client.post("/api/v1/skill-gaps", json={
        "job_role_id": str(ROLE), "user_id": str(OTHER_USER),
    })
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_http_other_owner_receives_404(client):
    response = client.post("/api/v1/skill-gaps", json={"job_role_id": str(ROLE)})
    client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(OTHER_USER, UUID(int=99), frozenset(), frozenset())
    assert client.get(response.headers["location"]).status_code == 404


def test_authentication_not_implemented_fails_closed():
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        response = client.post("/api/v1/skill-gaps", json={"job_role_id": str(ROLE)},
                               headers={"Authorization": "Bearer untrusted"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_missing_service_adapter_returns_503():
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(USER, UUID(int=99), frozenset(), frozenset())
    with TestClient(app) as client:
        assert client.post("/api/v1/skill-gaps", json={"job_role_id": str(ROLE)}).status_code == 503


@pytest.mark.parametrize("required,observed,gap", [(0, 0, 0), (6, 0, 5), (4, -1, 5), (4, 6, 0), (4, 2, 3)])
def test_invalid_gap_dto(required, observed, gap):
    with pytest.raises(ValidationError):
        SkillGapItem(skill=SKILL, required_level=required, observed_level=observed, gap=gap)


def test_request_requires_valid_role_id():
    with pytest.raises(ValidationError):
        SkillGapRequest(job_role_id="invalid")


def populate_history(service):
    template = service.create(user_id=USER, job_role_id=ROLE)
    service.repository.saved.clear()
    other_role = JobRoleRef(job_role_id=UUID(int=11), code="OTHER_ROLE", name="Other role")
    for owner, ident, days, role in [
        (USER, 101, 0, template.job_role), (USER, 102, 0, template.job_role),
        (USER, 103, 1, other_role), (OTHER_USER, 999, 10, template.job_role),
    ]:
        service.repository.save(user_id=owner, assessment=template.model_copy(update={
            "assessment_id": UUID(int=ident), "evaluated_at": STAMP + timedelta(days=days),
            "job_role": role,
        }))


def test_history_keyset_ties_and_owner_scope(service):
    populate_history(service)
    ids, cursor = [], None
    for _ in range(3):
        page = service.list_history(user_id=USER, query=SkillGapHistoryQuery(limit=1, cursor=cursor))
        ids.extend(row.assessment_id.int for row in page.items)
        cursor = page.next_cursor
    assert ids == [103, 102, 101]
    assert cursor is None
    assert service.repository.last_history_limit == 2
    assert len(set(ids)) == 3


def test_history_role_filter_summaries_and_empty(service):
    populate_history(service)
    service.repository.stale = True
    page = service.list_history(user_id=USER, query=SkillGapHistoryQuery(job_role_id=ROLE))
    assert [row.assessment_id.int for row in page.items] == [102, 101]
    assert all(row.missing_skill_count == 1 and row.total_gap == 2 and row.is_stale for row in page.items)
    empty = service.list_history(user_id=USER, query=SkillGapHistoryQuery(job_role_id=UUID(int=999)))
    assert empty.model_dump() == {"items": [], "next_cursor": None}


def test_history_cursor_rejects_owner_filter_tampering_and_key_change(service):
    populate_history(service)
    token = service.list_history(user_id=USER, query=SkillGapHistoryQuery(limit=1)).next_cursor
    assert len(token) <= 500
    altered = ("A" if token[0] != "A" else "B") + token[1:]
    for user, query in [
        (OTHER_USER, SkillGapHistoryQuery(cursor=token)),
        (USER, SkillGapHistoryQuery(job_role_id=ROLE, cursor=token)),
        (USER, SkillGapHistoryQuery(cursor=altered)),
    ]:
        with pytest.raises(AppError) as exc:
            service.list_history(user_id=user, query=query)
        assert exc.value.code == ErrorCode.INVALID_CURSOR
    other = SkillGapService(service.repository, service.evaluator, cursor_key=b"different-history-test-key" * 2)
    with pytest.raises(AppError) as exc:
        other.list_history(user_id=USER, query=SkillGapHistoryQuery(cursor=token))
    assert exc.value.code == ErrorCode.INVALID_CURSOR


@pytest.mark.parametrize("token", ["", "bad!", "a", "e30"])
def test_malformed_history_cursor(service, token):
    with pytest.raises(AppError) as exc:
        service.list_history(user_id=USER, query=SkillGapHistoryQuery(cursor=token))
    assert exc.value.code == ErrorCode.INVALID_CURSOR


def test_history_requires_configured_key(service):
    unconfigured = SkillGapService(service.repository, service.evaluator)
    with pytest.raises(AppError) as exc:
        unconfigured.list_history(user_id=USER, query=SkillGapHistoryQuery())
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_new_history_during_paging_does_not_repeat_newer_rows(service):
    populate_history(service)
    first = service.list_history(user_id=USER, query=SkillGapHistoryQuery(limit=1))
    newest = service.repository.saved[(USER, UUID(int=103))]
    service.repository.save(user_id=USER, assessment=newest.model_copy(update={
        "assessment_id": UUID(int=104), "evaluated_at": STAMP + timedelta(days=2),
    }))
    next_page = service.list_history(user_id=USER, query=SkillGapHistoryQuery(cursor=first.next_cursor))
    assert [row.assessment_id.int for row in next_page.items] == [102, 101]


def test_http_history_contract_and_filter(client, service):
    populate_history(service)
    response = client.get("/api/v1/skill-gaps", params={"job_role_id": str(ROLE), "limit": 1})
    assert response.status_code == 200
    assert response.json()["items"][0]["assessment_id"] == str(UUID(int=102))
    next_page = client.get("/api/v1/skill-gaps", params={
        "job_role_id": str(ROLE), "limit": 1, "cursor": response.json()["next_cursor"],
    })
    assert next_page.json()["items"][0]["assessment_id"] == str(UUID(int=101))
    assert next_page.json()["next_cursor"] is None
    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    Draft202012Validator({
        "$ref": "#/components/schemas/SkillGapSummaryPage", "components": spec["components"],
    }).validate(response.json())


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 101}, {"limit": "bad"}, {"limit": 1.5},
    {"job_role_id": "bad"}, {"cursor": "a" * 501},
])
def test_http_history_invalid_query(client, params):
    assert client.get("/api/v1/skill-gaps", params=params).status_code == 422


def test_http_history_cursor_rejection(client, service):
    populate_history(service)
    assert client.get("/api/v1/skill-gaps?cursor=bad").status_code == 400
    token = client.get("/api/v1/skill-gaps?limit=1").json()["next_cursor"]
    client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(OTHER_USER, UUID(int=99), frozenset(), frozenset())
    response = client.get("/api/v1/skill-gaps", params={"cursor": token})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CURSOR"


def test_http_history_another_user_id_query_cannot_override_principal(client, service):
    populate_history(service)
    response = client.get("/api/v1/skill-gaps", params={"user_id": str(OTHER_USER)})
    assert [UUID(row["assessment_id"]).int for row in response.json()["items"]] == [103, 102, 101]


def test_save_failure_is_not_reported_as_created(client, service):
    def fail_save(**kwargs):
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
    service.repository.save = fail_save
    response = client.post("/api/v1/skill-gaps", json={"job_role_id": str(ROLE)})
    assert response.status_code == 503
    assert "location" not in response.headers
    assert not service.repository.saved


@pytest.mark.parametrize("observed", [-1, 0, 6, True, "3"])
def test_invalid_source_proficiency_rejected_before_evaluation(service, observed):
    service.repository.snapshot = replace(service.repository.snapshot, observed_levels={SKILL.skill_id: observed})
    with pytest.raises(AppError) as exc:
        service.create(user_id=USER, job_role_id=ROLE)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert service.evaluator.calls == 0
    assert not service.repository.saved


def test_rule_cannot_change_source_levels(service):
    service.evaluator.items = (SkillGapItem(skill=SKILL, required_level=5, observed_level=2, gap=3),)
    with pytest.raises(AppError) as exc:
        service.create(user_id=USER, job_role_id=ROLE)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert not service.repository.saved


def test_source_duplicate_requirement_rejected(service):
    service.repository.snapshot = replace(service.repository.snapshot,
        requirements=service.repository.snapshot.requirements * 2)
    with pytest.raises(AppError) as exc:
        service.create(user_id=USER, job_role_id=ROLE)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert service.evaluator.calls == 0


def test_rule_cannot_return_another_skill(service):
    other_skill = SKILL.model_copy(update={"skill_id": UUID(int=999)})
    service.evaluator.items = (SkillGapItem(skill=other_skill, required_level=4, observed_level=2, gap=2),)
    with pytest.raises(AppError) as exc:
        service.create(user_id=USER, job_role_id=ROLE)
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE


def test_t43_test_app_openapi_and_operations(client):
    spec = client.get("/openapi.json").json()
    validate(spec)
    collection = spec["paths"]["/api/v1/skill-gaps"]
    assert collection["get"]["operationId"] == "listMySkillGaps"
    assert collection["post"]["operationId"] == "createSkillGap"
    assert "201" in collection["post"]["responses"]
    assert "400" in collection["get"]["responses"]
    assert spec["paths"]["/api/v1/skill-gaps/{assessment_id}"]["get"]["operationId"] == "getSkillGap"


@pytest.mark.parametrize("operation", ["load_inputs", "save", "get_owned", "list_owned", "commit"])
def test_sql_repository_maps_failures_to_common_error_without_raw_details(service, operation):
    from sqlalchemy.exc import SQLAlchemyError
    from app.repositories.skill_gaps import SqlSkillGapRepository

    class BrokenSession:
        rollbacks = 0

        def execute(self, *args, **kwargs):
            raise SQLAlchemyError("synthetic private database details")

        scalar = execute
        commit = execute

        def rollback(self):
            self.rollbacks += 1

    session = BrokenSession()
    repository = SqlSkillGapRepository(session, stale_checker=lambda *_: False)
    assessment = service.create(user_id=USER, job_role_id=ROLE)
    kwargs = {
        "load_inputs": {"user_id": USER, "job_role_id": ROLE},
        "save": {"user_id": USER, "assessment": assessment},
        "get_owned": {"user_id": USER, "assessment_id": assessment.assessment_id},
        "list_owned": {"user_id": USER, "job_role_id": ROLE, "before": None, "limit": 20},
        "commit": {},
    }
    with pytest.raises(AppError) as error:
        getattr(repository, operation)(**kwargs[operation])
    assert error.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert error.value.log_detail == "SQLAlchemyError"
    assert session.rollbacks == 1


@pytest.mark.parametrize("timestamp", [None, "invalid", "2026-11-09T00:00:00"])
def test_signed_common_cursor_still_requires_an_aware_timestamp(service, timestamp):
    from app.services.job_postings import ListCursor

    token = ListCursor(b"T43-history-fixture-key-only-" * 2).encode(
        "skill-gaps", {"owner": str(USER), "job_role_id": None}, UUID(int=100), timestamp,
    )
    with pytest.raises(AppError) as error:
        service.list_history(user_id=USER, query=SkillGapHistoryQuery(cursor=token))
    assert error.value.code == ErrorCode.INVALID_CURSOR


@pytest.mark.parametrize("path", ["/api/v1/skill-gaps", "/api/v1/skill-gaps/00000000-0000-0000-0000-000000000064"])
def test_unconnected_read_routes_require_authentication(path):
    app = create_app()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        response = client.get(path, headers={"Authorization": "Bearer invented-token", "X-User-ID": str(USER)})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


def test_no_default_app_registration():
    spec = create_app().openapi()
    assert "/api/v1/skill-gaps" not in spec["paths"]


@pytest.mark.parametrize("body", [{}, {"job_role_id": "invalid"}, {"job_role_id": None}])
def test_invalid_create_request_does_not_call_calculator(client, service, body):
    response = client.post("/api/v1/skill-gaps", json=body)
    assert response.status_code == 422
    assert service.evaluator.calls == 0
    assert not service.repository.saved
