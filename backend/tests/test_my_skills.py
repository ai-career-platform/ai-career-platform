"""T33 내 보유 기술 API: GET/PUT /me/skills (openapi listMySkills·replaceMySkills, FR-PRF-001).

정상 조회·교체 / 숙련도 1~5·null / 중복 422 DUPLICATE_SKILL / 없는·폐기 기술 422 / 최대 100개 /
user_id 차단(본문·쿼리) / 401 / 사용자 간 격리 / 실패 시 롤백 / 계약 스키마 일치.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import jwt
import pytest
import yaml

from app.core.config import API_V1_PREFIX
from app.routers.my_skills import get_my_skills_repository, get_my_skills_service
from app.services.my_skills import MySkillsService
from tests.conftest import bearer, signup
from tests.fakes_my_skills import MemoryMySkillsRepository

URL = f"{API_V1_PREFIX}/me/skills"


@pytest.fixture
def skills_repo() -> MemoryMySkillsRepository:
    return MemoryMySkillsRepository()


@pytest.fixture
def api(app, client, skills_repo):
    app.dependency_overrides[get_my_skills_repository] = lambda: skills_repo
    return client


@pytest.fixture
def catalog(skills_repo):
    return {
        "python": skills_repo.add_skill("PYTHON", "Python"),
        "sql": skills_repo.add_skill("SQL", "SQL"),
        "docker": skills_repo.add_skill("DOCKER", "Docker"),
        "cobol": skills_repo.add_skill("COBOL", "COBOL", active=False),
    }


def new_user(api, email="seeker@example.com"):
    token = signup(api, email=email).json()["access_token"]
    return bearer(token), uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"])


@pytest.fixture
def seeker(api):
    return new_user(api)


def put(api, headers, *items, **extra):
    return api.put(URL, json={"items": list(items), **extra}, headers=headers)


def item(skill_id, proficiency=None):
    return {"skill_id": str(skill_id)} | ({} if proficiency is None else {"proficiency": proficiency})


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


# ---------------------------------------------------------------- 정상
def test_empty_list_for_new_user(api, seeker):
    r = api.get(URL, headers=seeker[0])
    assert r.status_code == 200 and r.json() == []


def test_replace_then_get_returns_saved_skills_sorted_by_name(api, seeker, catalog):
    headers, _ = seeker
    r = put(api, headers, item(catalog["sql"], 3), item(catalog["python"], 2), item(catalog["docker"]))
    assert r.status_code == 200, r.text
    expected = [
        {"skill": {"skill_id": str(catalog["docker"]), "code": "DOCKER", "name": "Docker"}, "proficiency": None},
        {"skill": {"skill_id": str(catalog["python"]), "code": "PYTHON", "name": "Python"}, "proficiency": 2},
        {"skill": {"skill_id": str(catalog["sql"]), "code": "SQL", "name": "SQL"}, "proficiency": 3},
    ]
    assert r.json() == expected
    assert api.get(URL, headers=headers).json() == expected


def test_replace_removes_missing_and_updates_changed(api, seeker, catalog, skills_repo):
    headers, user_id = seeker
    t0 = datetime(2026, 11, 9, tzinfo=UTC)
    service_clock = iter([t0, t0 + timedelta(hours=1)])
    api.app.dependency_overrides[get_my_skills_service] = lambda: MySkillsService(skills_repo, clock=lambda: next(service_clock))

    put(api, headers, item(catalog["python"], 2), item(catalog["sql"], 3))
    r = put(api, headers, item(catalog["python"], 4), item(catalog["docker"], 1))
    assert [(s["skill"]["code"], s["proficiency"]) for s in r.json()] == [("DOCKER", 1), ("PYTHON", 4)]

    stored = skills_repo.stored(user_id)
    assert set(stored) == {catalog["python"], catalog["docker"]}
    assert stored[catalog["python"]]["created_at"] == t0  # 남은 기술은 처음 등록 시각 유지
    assert stored[catalog["python"]]["updated_at"] == t0 + timedelta(hours=1)


def test_empty_items_clears_all(api, seeker, catalog):
    headers, _ = seeker
    put(api, headers, item(catalog["python"], 2))
    r = put(api, headers)
    assert r.status_code == 200 and r.json() == []


@pytest.mark.parametrize("level", [1, 5, None])
def test_proficiency_bounds_accepted(api, seeker, catalog, level):
    r = api.put(URL, json={"items": [{"skill_id": str(catalog["python"]), "proficiency": level}]}, headers=seeker[0])
    assert r.status_code == 200 and r.json()[0]["proficiency"] == level


def test_max_100_skills(api, seeker, skills_repo):
    ids = [skills_repo.add_skill(f"S{i:03}", f"Skill {i:03}") for i in range(101)]
    assert put(api, seeker[0], *[item(i) for i in ids[:100]]).status_code == 200
    assert_error(put(api, seeker[0], *[item(i) for i in ids]), 422, "VALIDATION_FAILED")


def test_retired_skill_already_owned_can_be_kept(api, seeker, catalog, skills_repo):
    headers, _ = seeker
    put(api, headers, item(catalog["python"], 2))
    skills_repo.retire(catalog["python"])
    r = put(api, headers, item(catalog["python"], 3))
    assert r.status_code == 200 and r.json()[0]["proficiency"] == 3


# ---------------------------------------------------------------- 거부
@pytest.mark.parametrize("level", [0, 6, -1, "3", 2.5])
def test_proficiency_out_of_range_or_type_is_422(api, seeker, catalog, level):
    body = {"items": [{"skill_id": str(catalog["python"]), "proficiency": level}]}
    assert_error(api.put(URL, json=body, headers=seeker[0]), 422, "VALIDATION_FAILED")


def test_duplicate_skill_is_422_duplicate_skill(api, seeker, catalog, skills_repo):
    headers, user_id = seeker
    r = put(api, headers, item(catalog["python"], 2), item(catalog["python"], 3))
    assert_error(r, 422, "DUPLICATE_SKILL")
    assert skills_repo.stored(user_id) == {}


@pytest.mark.parametrize("which", ["unknown", "retired"])
def test_unknown_or_retired_skill_is_422_and_nothing_changes(api, seeker, catalog, skills_repo, which):
    headers, user_id = seeker
    put(api, headers, item(catalog["sql"], 1))
    bad = uuid.uuid4() if which == "unknown" else catalog["cobol"]
    assert_error(put(api, headers, item(catalog["python"], 2), item(bad, 1)), 422, "VALIDATION_FAILED")
    assert set(skills_repo.stored(user_id)) == {catalog["sql"]}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"items": "python"},
        {"items": [{"skill_id": "not-a-uuid"}]},
        {"items": [{}]},
        {"items": [{"skill_id": str(uuid.UUID(int=1)), "level": 3}]},
        {"items": [], "user_id": str(uuid.UUID(int=2))},
    ],
)
def test_bad_body_is_422(api, seeker, body):
    assert_error(api.put(URL, json=body, headers=seeker[0]), 422, "VALIDATION_FAILED")


def test_user_id_in_query_is_rejected(api, seeker, catalog):
    other_headers, other_id = new_user(api, "other@example.com")
    put(api, other_headers, item(catalog["python"], 5))
    assert_error(api.get(URL, params={"user_id": str(other_id)}, headers=seeker[0]), 422, "VALIDATION_FAILED")
    assert_error(api.put(URL, params={"user_id": str(other_id)}, json={"items": []}, headers=seeker[0]), 422, "VALIDATION_FAILED")


def test_anonymous_is_401(api, catalog):
    assert_error(api.get(URL), 401, "UNAUTHENTICATED")
    assert_error(api.put(URL, json={"items": [item(catalog["python"], 2)]}), 401, "UNAUTHENTICATED")


def test_users_are_isolated(api, seeker, catalog, skills_repo):
    headers, user_id = seeker
    other_headers, other_id = new_user(api, "other@example.com")
    put(api, headers, item(catalog["python"], 2))
    put(api, other_headers, item(catalog["sql"], 4))
    put(api, other_headers)  # 다른 사람이 전부 지워도 내 기술은 그대로
    assert [s["skill"]["code"] for s in api.get(URL, headers=headers).json()] == ["PYTHON"]
    assert skills_repo.stored(other_id) == {} and set(skills_repo.stored(user_id)) == {catalog["python"]}


def test_commit_failure_rolls_back(api, seeker, catalog, skills_repo):
    headers, user_id = seeker
    put(api, headers, item(catalog["python"], 2))
    skills_repo.fail_commit = True
    assert_error(put(api, headers, item(catalog["sql"], 3)), 503, "DEPENDENCY_UNAVAILABLE")
    skills_repo.fail_commit = False
    assert [s["skill"]["code"] for s in api.get(URL, headers=headers).json()] == ["PYTHON"]


# ---------------------------------------------------------------- 계약
def test_responses_match_contract_schema(api, seeker, catalog):
    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
    get_schema = spec["paths"]["/me/skills"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    validator = jsonschema.Draft202012Validator({**get_schema, "components": spec["components"]})
    body = put(api, seeker[0], item(catalog["python"], 2), item(catalog["sql"])).json()
    validator.validate(body)
    validator.validate(api.get(URL, headers=seeker[0]).json())


def test_openapi_lists_my_skills_operations(api):
    paths = api.get("/openapi.json").json()["paths"]
    assert paths[URL]["get"]["operationId"] == "listMySkills"
    assert paths[URL]["put"]["operationId"] == "replaceMySkills"
    assert {"200", "401", "422"} <= set(paths[URL]["put"]["responses"])
