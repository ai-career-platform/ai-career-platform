"""T72 behavior event API: real router + real service + in-memory repository (no DB evidence).

PostgreSQL evidence (row lock, withdrawal race, ON CONFLICT) is in test_behavior_events_postgres.py.
"""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid1, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.core.rate_limit import AttemptLimiter
from app.routers.behavior_events import get_behavior_event_service
from app.schemas.behavior_events import BehaviorEventInput, metadata_size
from app.schemas.privacy import OptionalConsentInput
from app.services.behavior_events import (
    BehaviorEventService, BehaviorEventSettings, RateLimit, storage_event_id,
)
from app.services.privacy import PrivacyService
from tests.conftest import bearer, signup

PATH = "/api/v1/me/behavior-events"
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class MemoryBehaviorRepo:
    """lock_user / latest_consent / insert_event / commit / rollback 만 흉내 낸다."""

    def __init__(self):
        self.users: dict[UUID, SimpleNamespace] = {}
        self.consents: dict[UUID, SimpleNamespace] = {}
        self.events: dict[UUID, dict] = {}
        self.pending: dict[UUID, dict] = {}
        self.calls: list[str] = []
        self.fail_insert = False

    def add_user(self, user_id, status="active"):
        self.users[user_id] = SimpleNamespace(user_id=user_id, status=status)

    def consent(self, user_id, granted, at=NOW - timedelta(days=1)):
        self.consents[user_id] = SimpleNamespace(granted=granted, recorded_at=at)

    def lock_user(self, user_id):
        self.calls.append("lock_user")
        return self.users.get(user_id)

    def latest_consent(self, user_id, code):
        assert code == "behavior_tracking"
        return self.consents.get(user_id)

    def insert_event(self, event_id, user_id, event_code, event_at, metadata):
        self.calls.append("insert_event")
        if self.fail_insert:
            raise OperationalError(None, None, RuntimeError("synthetic insert failure"))
        if event_id in self.events or event_id in self.pending:
            return False
        self.pending[event_id] = dict(user_id=user_id, event_code=event_code, event_at=event_at, metadata=metadata)
        return True

    def commit(self):
        self.calls.append("commit")
        self.events.update(self.pending)
        self.pending.clear()

    def rollback(self):
        self.calls.append("rollback")
        self.pending.clear()


@pytest.fixture
def api(app, client):
    repo = MemoryBehaviorRepo()
    state = SimpleNamespace(settings=BehaviorEventSettings(enabled=True), limiter=AttemptLimiter())
    app.dependency_overrides[get_behavior_event_service] = lambda: BehaviorEventService(
        repo, state.settings, state.limiter, clock=lambda: NOW)

    def login(email="seeker@example.com"):
        token = signup(client, email=email).json()["access_token"]
        headers = bearer(token)
        user_id = UUID(client.get("/api/v1/me", headers=headers).json()["user_id"])
        repo.add_user(user_id)
        return headers, user_id

    return SimpleNamespace(client=client, repo=repo, state=state, login=login)


def event(**overrides):
    body = {"event_id": str(uuid4()), "event_code": "posting.view",
            "event_at": (NOW - timedelta(minutes=1)).isoformat(),
            "metadata": {"job_posting_id": "jp_123", "list_position": 3}}
    body.update(overrides)
    return body


# ---------------------------------------------------------------- consent gate

def test_valid_consent_records_one_event_under_server_key(api):
    h, uid = api.login()
    api.repo.consent(uid, True)
    body = event()
    r = api.client.post(PATH, headers=h, json=body)
    assert r.status_code == 201 and r.json() == {"event_id": body["event_id"], "status": "recorded"}
    assert r.headers["cache-control"] == "no-store"
    [(key, row)] = api.repo.events.items()
    assert key == storage_event_id(uid, UUID(body["event_id"])) and key != UUID(body["event_id"])
    assert row["user_id"] == uid and row["event_code"] == "posting.view"
    assert row["metadata"] == {"job_posting_id": "jp_123", "list_position": 3}
    assert api.repo.calls == ["lock_user", "insert_event", "commit"]


@pytest.mark.parametrize("consent", [None, False])
def test_no_consent_or_withdrawn_stores_nothing(api, consent):
    h, uid = api.login()
    if consent is not None:
        api.repo.consent(uid, consent)
    r = api.client.post(PATH, headers=h, json=event())
    assert r.status_code == 200 and r.json()["status"] == "blocked_no_consent"
    assert api.repo.events == {} and "insert_event" not in api.repo.calls


def test_event_before_current_consent_is_not_restored(api):
    """철회(삭제) 후 재동의해도 그 이전에 일어난 이벤트는 다시 저장하지 않는다."""
    h, uid = api.login()
    api.repo.consent(uid, True, at=NOW - timedelta(minutes=5))
    r = api.client.post(PATH, headers=h, json=event(event_at=(NOW - timedelta(minutes=10)).isoformat()))
    assert r.json()["status"] == "blocked_no_consent" and api.repo.events == {}


@pytest.mark.parametrize("code,metadata", [
    ("posting.bookmark", {"job_posting_id": "jp_1"}),
    ("recommendation.click", {"recommendation_id": "rec_1", "rank": 1}),
    ("recommendation.dismiss", {"recommendation_id": "rec_1", "reason_code": "not_relevant"}),
])
def test_unapproved_personalization_events_are_never_stored(api, code, metadata):
    h, uid = api.login()
    api.repo.consent(uid, True)
    r = api.client.post(PATH, headers=h, json=event(event_code=code, metadata=metadata))
    assert r.status_code == 200 and r.json()["status"] == "blocked_policy_pending"
    assert api.repo.events == {} and api.repo.calls == []


def test_collection_disabled_by_default_touches_nothing(api):
    h, uid = api.login()
    api.repo.consent(uid, True)
    api.state.settings = BehaviorEventSettings()
    assert BehaviorEventSettings.from_env({}) == BehaviorEventSettings(enabled=False, rate_limit=None)
    r = api.client.post(PATH, headers=h, json=event())
    assert r.status_code == 200 and r.json()["status"] == "collection_disabled"
    assert api.repo.calls == []


# ---------------------------------------------------------------- duplicates and ownership

def test_same_event_id_is_stored_once(api):
    h, uid = api.login()
    api.repo.consent(uid, True)
    body = event()
    first = api.client.post(PATH, headers=h, json=body)
    again = api.client.post(PATH, headers=h, json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json() == {"event_id": body["event_id"], "status": "duplicate"}
    assert len(api.repo.events) == 1


def test_same_client_event_id_for_two_users_stays_separate(api):
    ha, a = api.login("a@example.com")
    hb, b = api.login("b@example.com")
    api.repo.consent(a, True)
    api.repo.consent(b, True)
    body = event()
    assert api.client.post(PATH, headers=ha, json=body).json()["status"] == "recorded"
    assert api.client.post(PATH, headers=hb, json=body).json()["status"] == "recorded"
    owners = sorted(str(row["user_id"]) for row in api.repo.events.values())
    assert owners == sorted([str(a), str(b)]) and len(set(api.repo.events)) == 2


def test_user_id_cannot_be_forged_in_body_or_query(api):
    ha, a = api.login("a@example.com")
    _, b = api.login("b@example.com")
    api.repo.consent(a, True)
    api.repo.consent(b, True)
    assert api.client.post(PATH, headers=ha, json=event(user_id=str(b))).status_code == 422
    assert api.client.post(f"{PATH}?user_id={b}", headers=ha, json=event()).status_code == 422
    assert api.client.post(PATH, headers=ha, json=event()).status_code == 201
    assert [row["user_id"] for row in api.repo.events.values()] == [a]


# ---------------------------------------------------------------- payload validation

@pytest.mark.parametrize("overrides", [
    {"event_code": "page.scroll"},
    {"event_code": "PAGE.VIEW"},
    {"metadata": {"job_posting_id": "jp_1", "email": "x"}},
    {"metadata": {"job_posting_id": "개발자 신입 서울"}},
    {"event_code": "search.submit", "metadata": {"search_type": "python backend"}},
    {"event_code": "search.submit", "metadata": {"query": "python"}},
    {"metadata": {"job_posting_id": {"id": "jp_1"}}},
    {"metadata": {"job_posting_id": ["jp_1"]}},
    {"metadata": {"job_posting_id": None}},
    {"metadata": {"job_posting_id": "a" * 65}},
    {"metadata": {f"k{i}": 1 for i in range(11)}},
    {"metadata": "jp_1"},
    {"metadata": ["jp_1"]},
    {"event_at": "2026-11-10T11:59:00"},
    {"event_at": "not-a-date"},
    {"event_at": None},
    {"event_id": "123"},
    {"event_id": "00000000-0000-0000-0000-000000000000"},
    {"event_id": str(uuid1())},
    {"event_id": None},
])
def test_contract_violations_are_rejected_before_storage(api, overrides):
    h, uid = api.login()
    api.repo.consent(uid, True)
    body = {k: v for k, v in event(**overrides).items() if v is not None or k == "metadata"}
    r = api.client.post(PATH, headers=h, json=body)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_FAILED"
    assert api.repo.calls == []


@pytest.mark.parametrize("delta,ok", [
    (timedelta(minutes=5), True), (timedelta(minutes=5, seconds=1), False),
    (-timedelta(days=7), True), (-timedelta(days=7, seconds=1), False),
])
def test_event_time_window_boundaries(api, delta, ok):
    h, uid = api.login()
    api.repo.consent(uid, True, at=NOW - timedelta(days=30))
    r = api.client.post(PATH, headers=h, json=event(event_at=(NOW + delta).isoformat()))
    assert r.status_code == (201 if ok else 422)
    assert len(api.repo.events) == (1 if ok else 0)


def test_other_timezone_is_accepted_as_same_instant(api):
    h, uid = api.login()
    api.repo.consent(uid, True)
    r = api.client.post(PATH, headers=h, json=event(event_at="2026-11-10T20:59:00+09:00"))
    assert r.status_code == 201
    [row] = api.repo.events.values()
    assert row["event_at"] == NOW - timedelta(minutes=1)


def test_empty_metadata_is_stored_as_null(api):
    h, uid = api.login()
    api.repo.consent(uid, True)
    assert api.client.post(PATH, headers=h, json=event(event_code="page.view", metadata={})).status_code == 201
    assert [row["metadata"] for row in api.repo.events.values()] == [None]


def test_malformed_json_is_400(api):
    h, _ = api.login()
    r = api.client.post(PATH, headers={**h, "Content-Type": "application/json"}, content=b'{"event_id": ')
    assert r.status_code == 400 and r.json()["code"] == "MALFORMED_JSON"
    assert api.repo.calls == []


def test_metadata_size_matches_postgres_text_and_1kb_limit():
    assert metadata_size({"a": 1, "b": "x"}) == len('{"a": 1, "b": "x"}')
    with pytest.raises(ValidationError):
        BehaviorEventInput.model_validate(event(metadata={f"k{i}": "v" * 64 for i in range(10)}))


# ---------------------------------------------------------------- auth, account state, rate limit, rollback

def test_unauthenticated_request_is_401_without_service(app, client):
    service = Mock()
    app.dependency_overrides[get_behavior_event_service] = lambda: service
    for headers in ({}, {"Authorization": "Bearer not-a-token"}):
        r = client.post(PATH, headers=headers, json=event())
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    service.record.assert_not_called()


def test_disabled_account_found_under_lock_is_401_and_rolled_back(api):
    h, uid = api.login()
    api.repo.consent(uid, True)
    api.repo.users[uid].status = "disabled"
    r = api.client.post(PATH, headers=h, json=event())
    assert r.status_code == 401 and api.repo.events == {}
    assert api.repo.calls == ["lock_user", "rollback"]


def test_rate_limit_blocks_after_limit_per_user(api):
    ha, a = api.login("a@example.com")
    hb, b = api.login("b@example.com")
    api.repo.consent(a, True)
    api.repo.consent(b, True)
    api.state.settings = BehaviorEventSettings(enabled=True, rate_limit=RateLimit(2, 60))
    codes = [api.client.post(PATH, headers=ha, json=event()).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    blocked = api.client.post(PATH, headers=ha, json=event())
    assert blocked.status_code == 429 and blocked.json()["code"] == "RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) > 0
    assert api.client.post(PATH, headers=hb, json=event()).status_code == 201
    assert len(api.repo.events) == 3


def test_rate_limit_does_not_replace_consent_gate(api):
    h, uid = api.login()
    api.state.settings = BehaviorEventSettings(enabled=True, rate_limit=RateLimit(100, 60))
    assert api.client.post(PATH, headers=h, json=event()).json()["status"] == "blocked_no_consent"
    assert api.repo.events == {}


@pytest.mark.parametrize("raw", ["60", "0/60", "60/0", "a/b", "-1/60"])
def test_invalid_rate_limit_setting_fails_fast(raw):
    with pytest.raises(ValueError):
        BehaviorEventSettings.from_env({"BEHAVIOR_EVENTS_RATE_LIMIT": raw})
    assert BehaviorEventSettings.from_env(
        {"BEHAVIOR_EVENTS_ENABLED": "true", "BEHAVIOR_EVENTS_RATE_LIMIT": "60/60"}
    ) == BehaviorEventSettings(enabled=True, rate_limit=RateLimit(60, 60))


def test_storage_error_rolls_back_and_is_503(api):
    h, uid = api.login()
    api.repo.consent(uid, True)
    api.repo.fail_insert = True
    r = api.client.post(PATH, headers=h, json=event())
    assert r.status_code == 503 and r.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert api.repo.events == {} and api.repo.calls[-1] == "rollback" and "commit" not in api.repo.calls


# ---------------------------------------------------------------- T31 withdrawal hook and contract

@pytest.mark.parametrize("code,granted,deletes", [
    ("behavior_tracking", False, True), ("behavior_tracking", True, False), ("llm_processing", False, False),
])
def test_withdrawal_deletes_tracking_events_inside_the_locked_transaction(code, granted, deletes):
    repo = Mock()
    repo.lock_user.return_value = SimpleNamespace(status="active")
    repo.current_policy.return_value = SimpleNamespace(version="v1", is_required=False)
    repo.latest_consent.return_value = None
    PrivacyService(repo).record_consent(uuid4(), OptionalConsentInput(policy_code=code, policy_version="v1", granted=granted))
    names = [c[0] for c in repo.method_calls]
    if deletes:
        assert names.index("lock_user") < names.index("delete_behavior_events") < names.index("commit")
        codes = repo.delete_behavior_events.call_args.args[1]
        assert set(codes) == {"page.view", "search.submit", "posting.view", "role.view", "skill_gap.view"}
    else:
        assert "delete_behavior_events" not in names


def test_openapi_declares_behavior_event_operation(client):
    spec = client.get("/openapi.json").json()
    op = spec["paths"][PATH]["post"]
    assert op["operationId"] == "recordMyBehaviorEvent"
    assert {"200", "201", "400", "401", "422", "429", "503"} <= set(op["responses"])
    props = spec["components"]["schemas"]["BehaviorEventInput"]["properties"]
    assert "user_id" not in props and set(props) == {"event_id", "event_code", "event_at", "metadata"}
