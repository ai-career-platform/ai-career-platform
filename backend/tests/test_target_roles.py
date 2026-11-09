"""T35 target-role API contract and ownership tests."""

import uuid

import pytest

from app.core.config import API_V1_PREFIX
from app.dependencies.target_roles import get_target_role_repository
from app.schemas.target_roles import JobRoleRef, TargetRole, TargetRoleItem
from tests.conftest import bearer, signup


class MemoryTargetRoleRepository:
    def __init__(self) -> None:
        self.roles = {
            uuid.UUID("11111111-1111-4111-8111-111111111111"): ("backend", "백엔드 개발자"),
            uuid.UUID("22222222-2222-4222-8222-222222222222"): ("frontend", "프론트엔드 개발자"),
            uuid.UUID("33333333-3333-4333-8333-333333333333"): ("data", "데이터 엔지니어"),
        }
        self.targets: dict[uuid.UUID, list[TargetRoleItem]] = {}
        self.replace_calls = 0

    def list_for_user(self, user_id: uuid.UUID) -> list[TargetRole]:
        return [
            TargetRole(
                job_role=JobRoleRef(job_role_id=item.job_role_id, code=self.roles[item.job_role_id][0],
                                    name=self.roles[item.job_role_id][1]),
                priority=item.priority,
            )
            for item in sorted(self.targets.get(user_id, []), key=lambda item: item.priority)
        ]

    def replace(self, user_id: uuid.UUID, items: list[TargetRoleItem]) -> list[TargetRole] | None:
        if any(item.job_role_id not in self.roles for item in items):
            return None
        self.targets[user_id] = list(items)
        self.replace_calls += 1
        return self.list_for_user(user_id)


@pytest.fixture
def target_repo(app):
    repository = MemoryTargetRoleRepository()
    app.dependency_overrides[get_target_role_repository] = lambda: repository
    yield repository
    app.dependency_overrides.pop(get_target_role_repository, None)


def access_token(client, email: str = "target@example.com") -> str:
    response = signup(client, email=email)
    assert response.status_code == 201
    return response.json()["access_token"]


def item(role_id: str, priority: int) -> dict:
    return {"job_role_id": role_id, "priority": priority}


PATH = f"{API_V1_PREFIX}/me/target-roles"
ROLE_1 = "11111111-1111-4111-8111-111111111111"
ROLE_2 = "22222222-2222-4222-8222-222222222222"
ROLE_3 = "33333333-3333-4333-8333-333333333333"


def test_authentication_is_required(client, target_repo):
    assert client.get(PATH).status_code == 401
    assert client.put(PATH, json={"items": []}).status_code == 401


def test_empty_list_and_replace_round_trip_sorted_by_priority(client, target_repo):
    headers = bearer(access_token(client))
    assert client.get(PATH, headers=headers).json() == []

    response = client.put(PATH, headers=headers, json={"items": [item(ROLE_2, 2), item(ROLE_1, 1)]})
    assert response.status_code == 200
    assert [(row["job_role"]["code"], row["priority"]) for row in response.json()] == [
        ("backend", 1), ("frontend", 2)
    ]
    assert client.get(PATH, headers=headers).json() == response.json()


def test_replacing_with_same_payload_is_idempotent(client, target_repo):
    headers = bearer(access_token(client))
    payload = {"items": [item(ROLE_1, 1)]}
    first = client.put(PATH, headers=headers, json=payload)
    second = client.put(PATH, headers=headers, json=payload)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert target_repo.replace_calls == 2


@pytest.mark.parametrize("items", [
    [item(ROLE_1, 1), item(ROLE_1, 2)],
    [item(ROLE_1, 1), item(ROLE_2, 1)],
    [item(ROLE_1, 1), item(ROLE_2, 2), item(ROLE_3, 3), item("44444444-4444-4444-8444-444444444444", 1)],
])
def test_duplicates_and_more_than_three_roles_are_rejected(client, target_repo, items):
    response = client.put(PATH, headers=bearer(access_token(client)), json={"items": items})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_unknown_job_role_is_not_saved(client, target_repo):
    headers = bearer(access_token(client))
    unknown = "99999999-9999-4999-8999-999999999999"
    response = client.put(PATH, headers=headers, json={"items": [item(unknown, 1)]})
    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert client.get(PATH, headers=headers).json() == []


def test_targets_are_isolated_by_authenticated_user(client, target_repo):
    first = bearer(access_token(client, "first@example.com"))
    second = bearer(access_token(client, "second@example.com"))
    assert client.put(PATH, headers=first, json={"items": [item(ROLE_1, 1)]}).status_code == 200
    assert client.get(PATH, headers=second).json() == []


def test_query_parameters_and_extra_fields_are_rejected(client, target_repo):
    headers = bearer(access_token(client))
    assert client.get(f"{PATH}?user_id={uuid.uuid4()}", headers=headers).status_code == 422
    response = client.put(PATH, headers=headers, json={"items": [], "user_id": str(uuid.uuid4())})
    assert response.status_code == 422
