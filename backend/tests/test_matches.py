"""T41 적합도 API: POST /matches, GET /matches/{match_id} (openapi createMatch·getMatch, FR-ANL-001).

정상 / 400 보유 기술 없음 / 401 / 404(없음·초안·비활성·남의 결과) / 422 / 503 계산 기준 없음.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import API_V1_PREFIX
from app.routers.matches import get_match_service
from app.services import match_rule
from app.services.matching import MatchService
from tests.conftest import bearer, signup
from tests.fakes_matching import MemoryMatchRepository

MATCHES = f"{API_V1_PREFIX}/matches"
S = [uuid.UUID(int=i) for i in range(1, 10)]


@pytest.fixture
def match_repo() -> MemoryMatchRepository:
    return MemoryMatchRepository()


@pytest.fixture
def api(app, client, match_repo):
    app.dependency_overrides[get_match_service] = lambda: MatchService(match_repo)
    return client


def new_user(api, email="seeker@example.com"):
    token = signup(api, email=email).json()["access_token"]
    return bearer(token), uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"])


@pytest.fixture
def seeker(api, match_repo):
    headers, user_id = new_user(api)
    match_repo.skills[user_id] = {S[0]: 4, S[1]: 2}
    return headers, user_id


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


# ---------------------------------------------------------------- 정상
def test_posting_match_is_created_and_saved(api, match_repo, seeker):
    headers, user_id = seeker
    role = match_repo.add_role({S[2]: 2})
    # S[2]는 공고에 수준이 없어 직무 기본값 2 사용
    posting = match_repo.add_posting(role, [(S[0], 4, True), (S[1], 3, True), (S[2], None, True)])

    r = api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers)
    assert r.status_code == 201, r.text
    body = r.json()
    assert r.headers["location"] == f"{MATCHES}/{body['match_id']}"
    assert body["target"] == {"job_posting_id": str(posting), "job_role_id": None}
    assert body["status"] == "completed"
    assert body["score"] == 55.56  # tests/test_match_rule.py 첫 Golden과 같은 입력
    assert body["score_is_probability"] is False
    assert (body["matched_skill_count"], body["missing_skill_count"]) == (1, 2)
    assert body["model_version"] == {"model_code": "match_rule", "version": "1", "kind": "rule"}
    assert body["limitations"] == [match_rule.LIMIT_BASE]

    stored = match_repo.matches[uuid.UUID(body["match_id"])]
    assert stored.user_id == user_id and stored.model_version.model_code == "match_rule"
    assert match_repo.commits == 1


def test_role_match_uses_role_skills(api, match_repo, seeker):
    headers, _ = seeker
    role = match_repo.add_role({S[0]: 4, S[1]: 4})
    body = api.post(MATCHES, json={"job_role_id": str(role)}, headers=headers).json()
    assert body["target"] == {"job_posting_id": None, "job_role_id": str(role)}
    assert body["score"] == 75.0 and (body["matched_skill_count"], body["missing_skill_count"]) == (1, 1)


def test_same_input_same_score(api, match_repo, seeker):
    headers, _ = seeker
    posting = match_repo.add_posting(None, [(S[0], 5, True), (S[1], 3, False)])
    scores = {api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers).json()["score"] for _ in range(3)}
    assert len(scores) == 1


def test_get_returns_own_result(api, match_repo, seeker):
    headers, _ = seeker
    posting = match_repo.add_posting(None, [(S[0], 4, True)])
    created = api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers).json()
    got = api.get(f"{MATCHES}/{created['match_id']}", headers=headers)
    assert got.status_code == 200 and got.json() == created


@pytest.mark.parametrize("status, expires_in", [("closed", None), ("published", timedelta(days=-1))])
def test_closed_or_expired_posting_is_scored_with_notice(api, match_repo, seeker, status, expires_in):
    headers, _ = seeker
    expires = datetime.now(UTC) + expires_in if expires_in else None
    posting = match_repo.add_posting(None, [(S[0], 4, True)], status=status, expires_at=expires)
    body = api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers).json()
    assert body["status"] == "completed" and match_rule.LIMIT_CLOSED in body["limitations"]


def test_posting_without_skills_is_failed_result(api, match_repo, seeker):
    headers, _ = seeker
    posting = match_repo.add_posting(None, [])
    r = api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers)
    assert r.status_code == 201
    body = r.json()
    assert (body["status"], body["score"], body["matched_skill_count"]) == ("failed", None, None)
    assert match_rule.LIMIT_NO_REQUIREMENTS in body["limitations"]


# ---------------------------------------------------------------- 거부
def test_no_user_skills_is_400(api, match_repo):
    headers, _ = new_user(api)
    posting = match_repo.add_posting(None, [(S[0], 4, True)])
    assert_error(api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers), 400, "NO_USER_SKILLS")
    assert match_repo.matches == {}


def test_anonymous_is_401(api, match_repo):
    posting = match_repo.add_posting(None, [(S[0], 4, True)])
    assert_error(api.post(MATCHES, json={"job_posting_id": str(posting)}), 401, "UNAUTHENTICATED")
    assert_error(api.get(f"{MATCHES}/{uuid.uuid4()}"), 401, "UNAUTHENTICATED")


@pytest.mark.parametrize("kind", ["missing_posting", "draft_posting", "missing_role", "inactive_role"])
def test_unknown_or_hidden_target_is_404(api, match_repo, seeker, kind):
    headers, _ = seeker
    body = {
        "missing_posting": lambda: {"job_posting_id": str(uuid.uuid4())},
        "draft_posting": lambda: {"job_posting_id": str(match_repo.add_posting(None, [(S[0], 1, True)], status="draft"))},
        "missing_role": lambda: {"job_role_id": str(uuid.uuid4())},
        "inactive_role": lambda: {"job_role_id": str(match_repo.add_role({S[0]: 1}, active=False))},
    }[kind]()
    assert_error(api.post(MATCHES, json=body, headers=headers), 404, "NOT_FOUND")


def test_other_users_result_is_404(api, match_repo, seeker):
    headers, _ = seeker
    posting = match_repo.add_posting(None, [(S[0], 4, True)])
    match_id = api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers).json()["match_id"]
    other, _ = new_user(api, "other@example.com")
    assert_error(api.get(f"{MATCHES}/{match_id}", headers=other), 404, "NOT_FOUND")
    assert_error(api.get(f"{MATCHES}/{uuid.uuid4()}", headers=headers), 404, "NOT_FOUND")


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"job_posting_id": str(uuid.UUID(int=1)), "job_role_id": str(uuid.UUID(int=2))},
        {"job_posting_id": "not-a-uuid"},
        {"job_posting_id": str(uuid.UUID(int=1)), "user_id": str(uuid.UUID(int=3))},
    ],
)
def test_bad_request_body_is_422(api, seeker, body):
    headers, _ = seeker
    assert_error(api.post(MATCHES, json=body, headers=headers), 422, "VALIDATION_FAILED")


def test_bad_match_id_is_422(api, seeker):
    headers, _ = seeker
    assert_error(api.get(f"{MATCHES}/not-a-uuid", headers=headers), 422, "VALIDATION_FAILED")


def test_missing_approved_rule_is_503_and_nothing_saved(api, match_repo, seeker):
    headers, _ = seeker
    match_repo.model_versions.clear()
    posting = match_repo.add_posting(None, [(S[0], 4, True)])
    assert_error(api.post(MATCHES, json={"job_posting_id": str(posting)}, headers=headers), 503, "DEPENDENCY_UNAVAILABLE")
    assert match_repo.matches == {}


# ---------------------------------------------------------------- OpenAPI
def test_openapi_lists_contract_responses(api):
    paths = api.get("/openapi.json").json()["paths"]
    post = paths[MATCHES]["post"]
    assert {"201", "400", "401", "404", "422", "503"} <= set(post["responses"])
    assert {"200", "401", "404"} <= set(paths[f"{MATCHES}/{{match_id}}"]["get"]["responses"])


def test_responses_match_contract_schema(api, match_repo, seeker):
    """응답이 docs/api/openapi.yaml 의 Match 스키마(T06 계약)를 그대로 만족하는지."""
    from pathlib import Path

    import jsonschema
    import yaml

    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        {"$ref": "#/components/schemas/Match", "components": spec["components"]},
        format_checker=jsonschema.FormatChecker(),
    )
    headers, _ = seeker
    ok = match_repo.add_posting(None, [(S[0], 4, True), (S[5], 2, False)])
    empty = match_repo.add_posting(None, [], status="closed")
    for target in (ok, empty):
        body = api.post(MATCHES, json={"job_posting_id": str(target)}, headers=headers).json()
        validator.validate(body)
        assert body["evaluated_at"].endswith("Z") or body["evaluated_at"].endswith("+00:00")
