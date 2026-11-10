"""T84 운영 감사·AI 사용량 조회 — 단위·HTTP 테스트 (메모리 저장소, 실제 T15 인증 흐름).

확정 계약 동작과 PROPOSED(PM 미승인 D1~D5) 동작을 테스트 이름으로 구분한다.
PROPOSED 테스트는 `get_admin_query_policy` 를 테스트에서만 PROPOSED_POLICY 로 바꿔 실행한다 — 운영 경로는 바뀌지 않는다.
PostgreSQL 실제 SQL 검증은 tests/test_t84_admin_audit_postgres.py.
"""
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import jwt
import pytest
import yaml
from fastapi import Depends
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.repositories.admin_audit import AuditRow
from app.routers import admin_audit as admin_router
from app.schemas.admin_audit import AuditEventView
from app.services.admin_audit import (
    CONFIRMED_POLICY, PROPOSED_POLICY, AdminAuditService, AdminQueryPolicy, mask_uuid, to_view,
)
from app.services.job_postings import ListCursor, derive_cursor_key
from tests import fakes
from tests.conftest import TEST_SECRET, bearer, signup
from tests.fakes_admin_audit import MemoryAdminAuditRepository, UsageRecord

AUDIT = "/api/v1/admin/audit-events"
USAGE = "/api/v1/admin/ai-usage"
NOW = datetime(2026, 11, 10, 3, 0, tzinfo=UTC)
FROM, TO = "2026-11-01T00:00:00+09:00", "2026-11-11T00:00:00Z"
SPEC = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))


def contract(name: str) -> Draft202012Validator:
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]})


def uid(n: int) -> uuid.UUID:
    return uuid.UUID(f"00000000-0000-4000-8000-{n:012d}")


def event(n: int, at: datetime, *, actor=None, action="system.behavior.purge", rtype="behavior_purge_run",
          rid=None, req=None) -> AuditRow:
    return AuditRow(uid(n), actor, action, rtype, rid, req, at)


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def store() -> MemoryAdminAuditRepository:
    return MemoryAdminAuditRepository(NOW)


@pytest.fixture
def policy_holder():
    return {"policy": CONFIRMED_POLICY}


@pytest.fixture
def wired(app, store, policy_holder):
    def service(policy: Annotated[AdminQueryPolicy, Depends(admin_router.get_admin_query_policy)]):
        return AdminAuditService(store, ListCursor(derive_cursor_key(TEST_SECRET)), policy, app.state.attempt_limiter)

    app.dependency_overrides[admin_router.get_admin_audit_service] = service
    return app


@pytest.fixture
def proposed(wired, policy_holder):
    """PROPOSED 정책을 이 테스트에서만 켠다."""
    wired.dependency_overrides[admin_router.get_admin_query_policy] = lambda: PROPOSED_POLICY
    return wired


def new_user(client, email):
    token = signup(client, email=email).json()["access_token"]
    return token, uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"])


@pytest.fixture
def admin(client, repo, wired):
    token, user_id = new_user(client, "admin@example.com")
    repo.grant_role(user_id, "admin")
    return bearer(token), user_id


@pytest.fixture
def seeker(client, wired):
    token, user_id = new_user(client, "seeker@example.com")
    return bearer(token), user_id


def get(client, path, headers, **params):
    return client.get(path, headers=headers, params=params)


def audit(client, headers, **params):
    return get(client, AUDIT, headers, **{"from": FROM, "to": TO, **params})


# ---------------------------------------------------------------- policy wiring guard
def test_operating_route_uses_only_the_confirmed_policy(monkeypatch):
    for name in ("T84_PROPOSED", "ADMIN_QUERY_POLICY", "T84_RECORD_READS"):
        monkeypatch.setenv(name, "1")
    assert admin_router.get_admin_query_policy() is CONFIRMED_POLICY
    assert CONFIRMED_POLICY == AdminQueryPolicy()
    assert not CONFIRMED_POLICY.record_reads and CONFIRMED_POLICY.max_range_days is None


# ---------------------------------------------------------------- 1~12 audit events
def test_01_admin_lists_latest_first_in_the_confirmed_shape(client, admin, store):
    headers, _ = admin
    store.events = [event(1, NOW - timedelta(days=3)), event(2, NOW - timedelta(days=1), actor=uid(7), req="req-x-0001")]
    response = audit(client, headers)
    assert response.status_code == 200, response.text
    body = response.json()
    contract("AuditEventPage").validate(body)
    assert [i["audit_event_id"] for i in body["items"]] == [str(uid(2)), str(uid(1))]
    assert body["next_cursor"] is None
    assert store.commits == 0 and len(store.events) == 2, "confirmed policy never writes"


def test_02_anonymous_is_401_before_any_validation(client, wired):
    assert client.get(AUDIT).status_code == 401
    assert client.get(AUDIT).json()["code"] == "UNAUTHENTICATED"
    assert client.get(USAGE).status_code == 401


def test_03_job_seeker_is_403(client, seeker):
    headers, _ = seeker
    assert audit(client, headers).json()["code"] == "FORBIDDEN"
    assert get(client, USAGE, headers, **{"from": "2026-11-01", "to": "2026-11-02"}).status_code == 403


def test_04_revoked_admin_and_admin_without_permission_are_403(client, repo, admin, monkeypatch):
    headers, user_id = admin
    monkeypatch.setitem(fakes.ROLE_PERMISSIONS, "admin", {"admin.models.read"})
    assert audit(client, headers).status_code == 403, "admin role without admin.audit.read"
    monkeypatch.setitem(fakes.ROLE_PERMISSIONS, "admin", {"admin.audit.read"})
    assert audit(client, headers).status_code == 200
    repo.revoke_role(user_id, "admin")
    assert audit(client, headers).status_code == 403, "role revocation applies on the next request"


@pytest.mark.parametrize("params", [
    {"from": None}, {"to": None},
    {"from": "2026-11-01T00:00:00"},                       # no UTC offset (RFC 3339 requires one)
    {"from": TO, "to": FROM},                              # reversed
    {"from": TO},                                          # empty range
    {"limit": 0}, {"limit": 101}, {"actor_user_id": "not-a-uuid"}, {"action_code": "a" * 101},
])
def test_05_invalid_period_and_filters_are_422(client, admin, params):
    headers, _ = admin
    query = {"from": FROM, "to": TO, **params}
    response = client.get(AUDIT, headers=headers, params={k: v for k, v in query.items() if v is not None})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"


def test_05_long_period_allowed_by_confirmed_contract_but_rejected_by_proposed_d5(client, admin, wired):
    headers, _ = admin
    long = {"from": "2026-01-01T00:00:00Z", "to": "2026-11-10T00:00:00Z"}
    assert get(client, AUDIT, headers, **long).status_code == 200
    wired.dependency_overrides[admin_router.get_admin_query_policy] = lambda: PROPOSED_POLICY
    assert get(client, AUDIT, headers, **long).status_code == 422          # PROPOSED D5
    ninety = {"from": "2026-08-12T00:00:00Z", "to": "2026-11-10T00:00:00Z"}
    assert get(client, AUDIT, headers, **ninety).status_code == 200        # exactly 90 days


def walk(client, headers, limit, **params):
    seen, cursor, pages = [], None, 0
    while True:
        query = {"limit": limit, **params, **({"cursor": cursor} if cursor else {})}
        body = audit(client, headers, **query).json()
        seen += [i["audit_event_id"] for i in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            return seen, pages


def test_06_identical_timestamps_page_without_duplicates_or_gaps(client, admin, store):
    headers, _ = admin
    same = NOW - timedelta(hours=1)
    store.events = [event(n, same) for n in range(1, 251)] + [event(900, same - timedelta(microseconds=1))]
    seen, pages = walk(client, headers, 100)
    assert pages == 3 and len(seen) == 251 and len(set(seen)) == 251
    assert seen[:250] == [str(uid(n)) for n in range(250, 0, -1)] and seen[-1] == str(uid(900))


def test_06_events_created_during_the_walk_do_not_shift_pages(client, admin, store):
    headers, _ = admin
    store.events = [event(n, NOW - timedelta(minutes=n)) for n in range(1, 6)]
    first = audit(client, headers, limit=2).json()
    store.events.append(event(99, NOW + timedelta(seconds=1)))           # newer than as_of
    store.current = NOW + timedelta(minutes=5)
    second = audit(client, headers, limit=2, cursor=first["next_cursor"]).json()
    third = audit(client, headers, limit=2, cursor=second["next_cursor"]).json()
    ids = [i["audit_event_id"] for p in (first, second, third) for i in p["items"]]
    assert ids == [str(uid(n)) for n in range(1, 6)], "upper bound fixed at the first page's as_of"


@pytest.mark.parametrize("mutate", [
    lambda c: c[:-2] + ("A" if c[-2] != "A" else "B") + c[-1],
    lambda c: "x" + c, lambda c: "not-base64!!", lambda c: c[: len(c) // 2],
])
def test_07_tampered_cursor_is_400(client, admin, store, mutate):
    headers, _ = admin
    store.events = [event(n, NOW - timedelta(minutes=n)) for n in range(1, 4)]
    cursor = audit(client, headers, limit=1).json()["next_cursor"]
    response = audit(client, headers, limit=1, cursor=mutate(cursor))
    assert response.status_code == 400 and response.json()["code"] == "INVALID_CURSOR"


def test_07_cursor_is_bound_to_the_filters(client, admin, store):
    headers, _ = admin
    store.events = [event(n, NOW - timedelta(minutes=n), action="admin.role.grant") for n in range(1, 4)]
    cursor = audit(client, headers, limit=1).json()["next_cursor"]
    assert audit(client, headers, limit=1, cursor=cursor, action_code="admin.role.grant").status_code == 400
    assert audit(client, headers, limit=1, cursor=cursor, to="2026-11-12T00:00:00Z").status_code == 400
    assert audit(client, headers, limit=50, cursor=cursor).status_code == 200, "limit is not bound"


def test_08_filter_combinations(client, admin, store):
    headers, _ = admin
    t = NOW - timedelta(hours=2)
    store.events = [event(1, t, actor=uid(7), action="admin.role.grant"),
                    event(2, t, actor=uid(7), action="admin.role.revoke"),
                    event(3, t, actor=uid(8), action="admin.role.grant"),
                    event(4, t, actor=None, action="system.behavior.purge")]

    def ids(**p):
        return {i["audit_event_id"] for i in audit(client, headers, **p).json()["items"]}

    assert ids(actor_user_id=str(uid(7))) == {str(uid(1)), str(uid(2))}
    assert ids(action_code="admin.role.grant") == {str(uid(1)), str(uid(3))}
    assert ids(actor_user_id=str(uid(7)), action_code="admin.role.grant") == {str(uid(1))}
    assert ids(actor_user_id=str(uid(9))) == set()


def test_09_response_contains_only_the_seven_columns_and_no_personal_data(client, admin, store):
    headers, _ = admin
    store.events = [event(1, NOW - timedelta(hours=1), actor=uid(7), rtype="user", rid=uid(8), req="req-x-0002")]
    response = audit(client, headers)
    item = response.json()["items"][0]
    assert set(item) == {"audit_event_id", "actor_user_id", "action_code", "resource_type", "resource_id",
                         "request_id", "occurred_at"}
    text = response.text
    for forbidden in ("@example.com", "display_name", "email", "password", "token", "ip"):
        assert forbidden not in text.replace("next_cursor", "")


def test_09_masking_serialization_proposed_d3():
    raw = uuid.UUID("0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0")
    assert mask_uuid(raw) == "0f1e2d3c-****-****-****-********e1f0"
    assert mask_uuid(None) is None
    view = to_view(event(1, NOW, actor=raw, rtype="user", rid=raw))
    dumped = view.model_dump(mode="json")
    assert str(raw) not in json.dumps(dumped)
    assert dumped["actor_user_id_masked"] == dumped["resource_id"] == mask_uuid(raw)
    assert dumped["resource_id_masked"] is True
    other = to_view(event(2, NOW, actor=None, rtype="behavior_purge_run", rid=raw)).model_dump(mode="json")
    assert other["resource_id"] == str(raw) and other["resource_id_masked"] is False
    assert other["actor_user_id_masked"] is None
    with pytest.raises(ValidationError):
        AuditEventView(**{**dumped, "actor_user_id_masked": str(raw)})


def test_10_empty_result(client, admin):
    headers, _ = admin
    assert audit(client, headers).json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("op", ["now", "list"])
def test_11_database_error_is_503_without_details(client, admin, store, op):
    headers, _ = admin
    store.fail.add(op)
    response = audit(client, headers)
    assert response.status_code == 503 and response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
    assert "synthetic" not in response.text and "SELECT" not in response.text


def test_12_scope_is_the_half_open_range_and_never_beyond_as_of(client, admin, store):
    headers, _ = admin
    start = datetime(2026, 11, 1, tzinfo=UTC)
    store.events = [event(1, start - timedelta(microseconds=1)), event(2, start),
                    event(3, NOW - timedelta(microseconds=1)), event(4, NOW), event(5, NOW + timedelta(days=1))]
    body = audit(client, headers, **{"from": "2026-11-01T00:00:00Z", "to": "2026-11-30T00:00:00Z"}).json()
    assert [i["audit_event_id"] for i in body["items"]] == [str(uid(3)), str(uid(2))]


# ---------------------------------------------------------------- D4 audit-read event (PROPOSED)
def test_d4_first_page_records_one_read_event_excluded_from_its_own_result(client, admin, store, proposed):
    headers, user_id = admin
    store.events = [event(n, NOW - timedelta(minutes=n)) for n in range(1, 4)]
    first = audit(client, headers, limit=2)
    assert first.status_code == 200
    reads = [e for e in store.events if e.action_code == "admin.audit.view"]
    assert len(reads) == 1 and store.commits == 1
    read = reads[0]
    assert read.actor_user_id == user_id and read.resource_type == "audit_events" and read.resource_id is None
    assert read.request_id == first.headers["x-request-id"]
    assert str(read.audit_event_id) not in first.text
    second = audit(client, headers, limit=2, cursor=first.json()["next_cursor"])
    assert len([e for e in store.events if e.action_code == "admin.audit.view"]) == 1, "no event for page 2"
    assert str(read.audit_event_id) not in second.text


def test_d4_read_event_stores_no_filter_values(client, admin, store, proposed):
    headers, _ = admin
    audit(client, headers, actor_user_id=str(uid(7)), action_code="admin.role.grant")
    read = next(e for e in store.events if e.action_code == "admin.audit.view")
    assert uid(7) not in (read.actor_user_id, read.resource_id)
    assert "admin.role.grant" not in {read.action_code, read.resource_type, read.request_id}


@pytest.mark.parametrize("op", ["record", "list", "commit"])
def test_d4_fail_closed_returns_no_rows_proposed(client, admin, store, proposed, op):
    headers, _ = admin
    store.events = [event(1, NOW - timedelta(minutes=1))]
    store.fail.add(op)
    response = audit(client, headers)
    assert response.status_code == 503 and "items" not in response.json()
    assert [e.action_code for e in store.events] == ["system.behavior.purge"]


def test_d4_disabled_under_confirmed_policy(client, admin, store):
    headers, _ = admin
    audit(client, headers)
    assert store.events == [] and store.commits == 0


def test_query_limit_rate_and_timeout_proposed(client, admin, store, proposed):
    headers, _ = admin
    for _ in range(60):
        assert audit(client, headers).status_code == 200
    blocked = audit(client, headers)
    assert blocked.status_code == 429 and blocked.json()["code"] == "RATE_LIMITED"
    assert int(blocked.headers["retry-after"]) > 0
    assert store.timeouts and set(store.timeouts) == {5000}


def test_confirmed_policy_sets_no_new_limits(client, admin, store):
    headers, _ = admin
    for _ in range(70):
        assert audit(client, headers).status_code == 200
    assert store.timeouts == []


# ---------------------------------------------------------------- 13~24 AI usage
def usage(client, headers, **params):
    return get(client, USAGE, headers, **{"from": "2026-11-01", "to": "2026-11-07", **params})


def rec(at, feature="document_analysis", model="model-a", i=10, o=5, cost="0.010000"):
    return UsageRecord(at, feature, model, i, o, None if cost is None else Decimal(cost))


@pytest.fixture
def usage_data(store):
    kst = lambda d, h, m=0: datetime(2026, 11, d, h, m, tzinfo=UTC) - timedelta(hours=9)  # noqa: E731
    store.usage_records = [
        rec(kst(1, 0), i=100, o=10, cost="0.100000"),
        rec(kst(1, 23, 59), feature="rag_answer", i=200, o=20, cost="0.200000"),
        rec(kst(2, 0), feature="rag_answer", model="model-b", i=300, o=30, cost="0.300000"),
        rec(kst(7, 23, 59), feature="agent", model="model-b", i=400, o=40, cost="0.000000"),
        rec(kst(8, 0), i=999, o=999, cost="9.000000"),                       # outside (to + 1 day)
        rec(kst(1, 0) - timedelta(microseconds=1), i=999, o=999, cost="9.000000"),  # outside (before from)
    ]
    return store


def test_13_empty_usage_is_an_empty_list_marked_unverified(client, admin):
    headers, _ = admin
    response = usage(client, headers)
    assert response.status_code == 200 and response.json() == []
    assert response.headers["x-ai-cost-status"] == "unverified"


def test_14_daily_buckets_follow_kst_dates(client, admin, usage_data):
    headers, _ = admin
    body = usage(client, headers).json()
    for bucket in body:
        contract("AiUsageBucket").validate(bucket)
    assert [(b["key"], b["request_count"]) for b in body] == [("2026-11-01", 2), ("2026-11-02", 1), ("2026-11-07", 1)]


def test_15_feature_buckets(client, admin, usage_data):
    headers, _ = admin
    body = {b["key"]: b for b in usage(client, headers, group_by="feature_code").json()}
    assert {k: v["request_count"] for k, v in body.items()} == {"agent": 1, "document_analysis": 1, "rag_answer": 2}


def test_16_model_buckets(client, admin, usage_data):
    headers, _ = admin
    body = {b["key"]: b["request_count"] for b in usage(client, headers, group_by="provider_model").json()}
    assert body == {"model-a": 2, "model-b": 2}


def test_17_18_token_sums(client, admin, usage_data):
    headers, _ = admin
    body = {b["key"]: b for b in usage(client, headers, group_by="provider_model").json()}
    assert (body["model-a"]["input_tokens"], body["model-a"]["output_tokens"]) == (300, 30)
    assert (body["model-b"]["input_tokens"], body["model-b"]["output_tokens"]) == (700, 70)


def test_19_confirmed_cost_is_the_stored_sum_and_is_marked_unverified(client, admin, usage_data):
    headers, _ = admin
    response = usage(client, headers, group_by="feature_code")
    body = {b["key"]: b["estimated_cost_usd"] for b in response.json()}
    assert body == {"agent": 0.0, "document_analysis": 0.1, "rag_answer": 0.5}
    assert response.headers["x-ai-cost-status"] == "unverified", "0.0 is not asserted to be free"


def test_19_proposed_report_without_d2_marks_every_cost_unknown(admin, usage_data):
    _, user_id = admin
    service = AdminAuditService(usage_data, ListCursor(derive_cursor_key(TEST_SECRET)), PROPOSED_POLICY)
    report = service.usage_report_proposed(user_id, date(2026, 11, 1), date(2026, 11, 7), "feature_code")
    assert all(b.estimated_cost_usd is None and b.unpriced_request_count == b.request_count for b in report.buckets)
    assert report.totals.estimated_cost_usd is None and report.totals.unpriced_request_count == 4
    assert report.model_dump(by_alias=True, mode="json")["from"] == "2026-11-01"


def test_20_zero_and_null_are_distinguished_after_d2_proposed(admin, store):
    _, user_id = admin
    boundary = datetime(2026, 11, 3, tzinfo=UTC)
    store.usage_records = [
        rec(boundary - timedelta(days=1), cost="0.000000"),        # pre-D2 zero → unknown, not free
        rec(boundary + timedelta(hours=1), cost="0.000000"),       # recorded free
        rec(boundary + timedelta(hours=2), cost=None),             # unrecorded
        rec(boundary + timedelta(hours=3), cost="0.250000"),
    ]
    service = AdminAuditService(store, ListCursor(derive_cursor_key(TEST_SECRET)), PROPOSED_POLICY)
    report = service.usage_report_proposed(user_id, date(2026, 11, 1), date(2026, 11, 7), "feature_code", boundary)
    assert report.totals.request_count == 4
    assert report.totals.estimated_cost_usd == 0.25 and report.totals.unpriced_request_count == 2
    only_free = [r for r in store.usage_records if r.estimated_cost_usd == 0 and r.occurred_at > boundary]
    store.usage_records = only_free
    free = service.usage_report_proposed(user_id, date(2026, 11, 1), date(2026, 11, 7), "day", boundary)
    assert free.totals.estimated_cost_usd == 0.0 and free.totals.unpriced_request_count == 0


def test_20_confirmed_contract_refuses_to_turn_null_cost_into_zero(client, admin, store):
    headers, _ = admin
    store.usage_records = [rec(datetime(2026, 11, 2, tzinfo=UTC), cost=None)]
    response = usage(client, headers)
    assert response.status_code == 500 and "0.0" not in response.text


def test_21_kst_day_boundary(client, admin, store):
    headers, _ = admin
    store.usage_records = [rec(datetime(2026, 11, 1, 14, 59, 59, 999999, tzinfo=UTC)),
                           rec(datetime(2026, 11, 1, 15, 0, tzinfo=UTC))]
    body = get(client, USAGE, headers, **{"from": "2026-11-01", "to": "2026-11-02"}).json()
    assert [b["key"] for b in body] == ["2026-11-01", "2026-11-02"]
    one = get(client, USAGE, headers, **{"from": "2026-11-02", "to": "2026-11-02"}).json()
    assert [b["key"] for b in one] == ["2026-11-02"], "to is inclusive, from starts at 00:00 KST"


@pytest.mark.parametrize("params", [{"from": "2026-11-08", "to": "2026-11-07"}, {"from": "2026-13-01"},
                                    {"group_by": "user_id"}, {"to": None}])
def test_22_period_errors_are_422(client, admin, params):
    headers, _ = admin
    query = {k: v for k, v in {"from": "2026-11-01", "to": "2026-11-07", **params}.items() if v is not None}
    response = client.get(USAGE, headers=headers, params=query)
    assert response.status_code == 422 and response.json()["code"] == "VALIDATION_FAILED"


def test_22_usage_range_limit_is_proposed_d5(client, admin, wired):
    headers, _ = admin
    long = {"from": "2026-01-01", "to": "2026-11-07"}
    assert get(client, USAGE, headers, **long).status_code == 200
    wired.dependency_overrides[admin_router.get_admin_query_policy] = lambda: PROPOSED_POLICY
    assert get(client, USAGE, headers, **long).status_code == 422
    assert get(client, USAGE, headers, **{"from": "2026-08-10", "to": "2026-11-07"}).status_code == 200  # 90 days


def test_23_usage_permission_confirmed_role_and_proposed_d1(client, admin, monkeypatch, wired):
    headers, _ = admin
    monkeypatch.setitem(fakes.ROLE_PERMISSIONS, "admin", set())
    assert usage(client, headers).status_code == 200, "confirmed contract: admin role"
    wired.dependency_overrides[admin_router.get_admin_query_policy] = lambda: PROPOSED_POLICY
    assert usage(client, headers).json()["code"] == "FORBIDDEN"            # PROPOSED D1


def test_24_totals_are_consistent_across_groupings(client, admin, usage_data):
    headers, _ = admin
    totals = []
    for group in ("day", "feature_code", "provider_model"):
        body = usage(client, headers, group_by=group).json()
        totals.append(tuple(round(sum(b[k] for b in body), 6)
                            for k in ("request_count", "input_tokens", "output_tokens", "estimated_cost_usd")))
    assert totals[0] == totals[1] == totals[2] == (4, 1000, 100, 0.6)


def test_usage_never_exposes_user_ids(client, admin, store):
    headers, _ = admin
    store.usage_records = [UsageRecord(datetime(2026, 11, 2, tzinfo=UTC), "agent", "m", 1, 1, Decimal("0"), uid(7)),
                           UsageRecord(datetime(2026, 11, 2, tzinfo=UTC), "agent", "m", 1, 1, Decimal("0"), None)]
    response = usage(client, headers, group_by="feature_code")
    assert response.json()[0]["request_count"] == 2, "withdrawn users (NULL) included"
    assert str(uid(7)) not in response.text


# ---------------------------------------------------------------- confirmed contract conformance
@pytest.mark.parametrize("path", ["/admin/audit-events", "/admin/ai-usage"])
def test_generated_operation_matches_the_confirmed_openapi(app, path):
    generated = app.openapi()["paths"][f"/api/v1{path}"]["get"]
    confirmed = SPEC["paths"][path]["get"]

    def names(params):
        out = set()
        for p in params:
            if "$ref" in p:
                p = SPEC["components"]["parameters"][p["$ref"].rsplit("/", 1)[1]]
            out.add((p["name"], bool(p.get("required"))))
        return out

    assert generated["operationId"] == confirmed["operationId"]
    assert names(generated["parameters"]) == names(confirmed["parameters"])
    assert set(confirmed["responses"]) <= set(generated["responses"])
    assert "/api/v1/admin/audit" not in app.openapi()["paths"], "no alias path"
