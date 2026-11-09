"""T45 synthetic unit/API tests. PostgreSQL E2E remains separate."""
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.core.errors import AppError, ErrorCode
from app.repositories.recommendation_runs import Candidate, Inputs
from app.routers.recommendation_runs import get_recommendation_service
from app.schemas.job_postings import CompanyRef, JobPostingSummary, JobRoleRef
from app.schemas.recommendation_runs import ModelVersionRef, RecommendationItem, RecommendationRun
from app.services.recommendation_runs import RecommendationService
from tests.conftest import bearer, signup

NOW = datetime(2026, 11, 9, 7, tzinfo=UTC)
URL = "/api/v1/recommendation-runs"


def candidate(n, codes=("PYTHON",), role=None):
    p = JobPostingSummary(job_posting_id=UUID(int=n), title=f"공고 {n}", status="published",
        company=CompanyRef(company_id=UUID(int=500), name="합성 회사"),
        job_role=None if role is None else JobRoleRef(job_role_id=role, code="DEV", name="개발자"),
        employment_type="full_time", location_text="서울", published_at=NOW, expires_at=None)
    return Candidate(p, codes)


class MemoryRuns:
    def __init__(self, inputs=None):
        self.inputs = inputs or Inputs(("PYTHON",), {}, (candidate(1), candidate(2, ("SQL",))), frozenset())
        self.saved = {}

    def load_inputs(self, user_id, now):
        return self.inputs

    def store(self, user_id, status, ranked, now):
        run_id = uuid4()
        options = {c.posting.job_posting_id: c for c in self.inputs.candidates}
        result = RecommendationRun(recommendation_run_id=run_id, status=status,
            model_version=ModelVersionRef(model_code="skill_overlap_baseline", version="skill-overlap-draft-v2", kind="rule"),
            generated_at=now, items=[RecommendationItem(rank=i, score=score, reason=reason,
                feedback=None, job_posting=options[pid].posting) for i, (pid, score, reason) in enumerate(ranked, 1)])
        self.saved[(user_id, run_id)] = result
        return result

    def get(self, user_id, run_id):
        return self.saved.get((user_id, run_id))

    def latest(self, user_id):
        return next((run for (owner, _), run in reversed(list(self.saved.items())) if owner == user_id), None)


def test_baseline_ranks_deterministically_and_records_reason():
    repo = MemoryRuns()
    result = RecommendationService(repo, clock=lambda: NOW).create(UUID(int=99))
    assert result.status == "completed"
    assert [(i.job_posting.job_posting_id, i.score) for i in result.items] == [(UUID(int=1), 100), (UUID(int=2), 0)]
    assert all("요구 기술" in i.reason for i in result.items)
    assert result.model_version.kind == "rule"


def test_target_role_tie_and_duplicate_free():
    role = uuid4()
    repo = MemoryRuns(Inputs(("PYTHON",), {role: 1}, (candidate(9), candidate(3, role=role)), frozenset()))
    result = RecommendationService(repo, clock=lambda: NOW).create(UUID(int=99))
    assert [i.job_posting.job_posting_id for i in result.items] == [UUID(int=3), UUID(int=9)]
    assert "목표 직무" in result.items[0].reason


def test_missing_skills_fallback_and_excluded_feedback():
    repo = MemoryRuns(Inputs((), {}, (candidate(1), candidate(2)), frozenset({UUID(int=1)})))
    result = RecommendationService(repo, clock=lambda: NOW).create(UUID(int=2), limit=2)
    assert result.status == "fallback"
    assert [(i.job_posting.job_posting_id, i.score) for i in result.items] == [(UUID(int=2), None)]


def test_empty_candidate_fallback_returns_empty():
    repo = MemoryRuns(Inputs(("PYTHON",), {}, (), frozenset()))
    result = RecommendationService(repo, clock=lambda: NOW).create(UUID(int=2))
    assert result.status == "fallback" and result.items == []


def test_global_tie_break_is_deterministic_across_batches_and_input_order():
    # 120 equal-score candidates span three T27 batches of 50; order must be global by ID.
    cands = tuple(candidate(n) for n in range(120, 0, -1))
    runs = [RecommendationService(MemoryRuns(Inputs(("PYTHON",), {}, order, frozenset())),
                                  clock=lambda: NOW).create(UUID(int=7), limit=50)
            for order in (cands, tuple(reversed(cands)))]
    ids = [[i.job_posting.job_posting_id for i in run.items] for run in runs]
    assert ids[0] == ids[1] == [UUID(int=n) for n in range(1, 51)]
    assert [i.rank for i in runs[0].items] == list(range(1, 51))
    assert len(set(ids[0])) == 50


def test_skills_without_comparable_postings_fall_back_to_latest():
    repo = MemoryRuns(Inputs(("PYTHON",), {}, (candidate(5, ()), candidate(4, ())), frozenset()))
    result = RecommendationService(repo, clock=lambda: NOW).create(UUID(int=2), limit=1)
    assert result.status == "fallback"
    assert [(i.job_posting.job_posting_id, i.score) for i in result.items] == [(UUID(int=5), None)]
    assert "최신 공고" in result.items[0].reason


def test_not_interested_excluded_from_scored_ranking():
    repo = MemoryRuns(Inputs(("PYTHON",), {}, (candidate(1), candidate(2)), frozenset({UUID(int=1)})))
    result = RecommendationService(repo, clock=lambda: NOW).create(UUID(int=2))
    assert result.status == "completed"
    assert [i.job_posting.job_posting_id for i in result.items] == [UUID(int=2)]


@pytest.mark.parametrize("limit", [0, 51, True, 1.2])
def test_invalid_service_limits(limit):
    with pytest.raises(AppError) as err:
        RecommendationService(MemoryRuns(), clock=lambda: NOW).create(UUID(int=3), limit=limit)
    assert err.value.code == ErrorCode.VALIDATION_FAILED


def test_owner_isolation_and_read_only_get():
    repo = MemoryRuns()
    service = RecommendationService(repo, clock=lambda: NOW)
    owner, other = uuid4(), uuid4()
    run = service.create(owner)
    assert service.get(owner, run.recommendation_run_id) == run
    assert service.latest(owner) == run
    assert len(repo.saved) == 1
    for load in (lambda: service.get(other, run.recommendation_run_id), lambda: service.latest(other)):
        with pytest.raises(AppError) as err:
            load()
        assert err.value.code == ErrorCode.NOT_FOUND
    assert len(repo.saved) == 1


@pytest.fixture
def api(app, client):
    repo = MemoryRuns()
    app.dependency_overrides[get_recommendation_service] = lambda: RecommendationService(repo, clock=lambda: NOW)
    return client


def test_api_auth_contract_and_run_retrieval(api):
    assert api.post(URL).status_code == 401
    assert api.get(URL + "/latest").status_code == 401
    assert api.get(URL + "/" + str(uuid4())).status_code == 401
    h = bearer(signup(api).json()["access_token"])
    assert api.get(URL + "/latest", headers=h).status_code == 404
    response = api.post(URL, headers=h, json={"limit": 1})
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["items"]) == 1 and body["status"] == "completed"
    assert response.headers["location"] == URL + "/" + body["recommendation_run_id"]
    assert api.get(URL + "/latest", headers=h).json() == body
    assert api.get(response.headers["location"], headers=h).json() == body
    assert api.get(URL + "/" + str(uuid4()), headers=h).status_code == 404
    for bad in (0, 51, True, "3"):
        assert api.post(URL, headers=h, json={"limit": bad}).status_code == 422
    assert api.post(URL, headers=h, json={"limit": 1, "user_id": str(uuid4())}).status_code == 422


def test_swagger_has_t06_operation_ids(api):
    paths = api.get("/openapi.json").json()["paths"]
    assert paths[URL]["post"]["operationId"] == "createRecommendationRun"
    assert paths[URL + "/latest"]["get"]["operationId"] == "getLatestRecommendationRun"
    assert paths[URL + "/{recommendation_run_id}"]["get"]["operationId"] == "getRecommendationRun"
