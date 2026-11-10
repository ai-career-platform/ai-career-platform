"""T86 관리자 감사·AI 비용 API 공통 보안 시나리오 — T84 시험(tests/test_t84_admin_audit*.py)에 없는 것만.

T84 가 이미 다루는 것(중복 안 함): 401·403·권한 회수, cursor 변조·조건 변경, 개인정보 키, 비용 미확인 헤더 기본 동작.
여기서 추가: 악성 입력 매트릭스(관리자·일반 사용자), 인가가 입력 검증보다 먼저인지, 다른 관리자의 cursor 재사용,
오류 응답의 비용 헤더·내부 정보.
"""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends

from app.routers import admin_audit as admin_router
from app.services.admin_audit import AdminAuditService, AdminQueryPolicy
from app.services.job_postings import ListCursor, derive_cursor_key
from tests.conftest import TEST_SECRET, bearer, signup
from tests.fakes_admin_audit import MemoryAdminAuditRepository
from tests.test_t84_admin_audit import NOW, event
import jwt

AUDIT, USAGE = "/api/v1/admin/audit-events", "/api/v1/admin/ai-usage"
WINDOW = {"from": "2026-11-01T00:00:00Z", "to": "2026-11-11T00:00:00Z"}
MALICIOUS_AUDIT = [
    {"action_code": "' OR '1'='1"}, {"action_code": "admin.role.grant; DROP TABLE x"}, {"action_code": "A" * 101},
    {"actor_user_id": "' OR 1=1 --"}, {"actor_user_id": "../../etc/passwd"},
    {"from": "'; SELECT 1 --"}, {"to": "9999999999"}, {"limit": "-1"}, {"limit": "100000000000"},
    {"limit": "1 OR 1=1"},
]
MALICIOUS_USAGE = [{"group_by": "user_id"}, {"group_by": "day; DROP TABLE x"}, {"from": "2026-13-45"},
                   {"to": "' OR '1'='1"}]


@pytest.fixture
def store():
    s = MemoryAdminAuditRepository(NOW)
    s.events = [event(n, NOW - timedelta(minutes=n), actor=uuid.UUID(int=7)) for n in range(1, 4)]
    return s


@pytest.fixture
def wired(app, store):
    def service(policy: Annotated[AdminQueryPolicy, Depends(admin_router.get_admin_query_policy)]):
        return AdminAuditService(store, ListCursor(derive_cursor_key(TEST_SECRET)), policy, app.state.attempt_limiter)
    app.dependency_overrides[admin_router.get_admin_audit_service] = service
    return app


def user(client, repo, email, admin=False):
    token = signup(client, email=email).json()["access_token"]
    if admin:
        repo.grant_role(uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"]), "admin")
    return bearer(token)


@pytest.mark.parametrize("params", MALICIOUS_AUDIT)
def test_malicious_audit_filters_are_safe_for_admin_and_403_for_seeker(client, repo, wired, params):
    admin = user(client, repo, f"a-{uuid.uuid4().hex[:6]}@example.com", admin=True)
    seeker = user(client, repo, f"s-{uuid.uuid4().hex[:6]}@example.com")
    as_admin = client.get(AUDIT, headers=admin, params={**WINDOW, **params})
    # 확정 계약의 action_code 는 길이 제한만 있어 문자열 그대로 바인딩된다 → 일치하는 행 없음(200, 빈 목록) 또는 형식 오류 422
    assert as_admin.status_code in (200, 422), params
    if as_admin.status_code == 200:
        assert as_admin.json()["items"] == [] or "action_code" not in params, params
    else:
        assert as_admin.json()["code"] == "VALIDATION_FAILED"
    assert "DROP" not in as_admin.text and "passwd" not in as_admin.text, "input is not echoed"
    as_seeker = client.get(AUDIT, headers=seeker, params={**WINDOW, **params})
    assert as_seeker.status_code == 403, "authorization runs before input validation"


@pytest.mark.parametrize("params", MALICIOUS_USAGE)
def test_malicious_usage_params_are_422_without_cost_header(client, repo, wired, params):
    admin = user(client, repo, f"u-{uuid.uuid4().hex[:6]}@example.com", admin=True)
    response = client.get(USAGE, headers=admin, params={"from": "2026-11-01", "to": "2026-11-07", **params})
    assert response.status_code == 422
    assert "x-ai-cost-status" not in response.headers


def test_cursor_is_not_a_bearer_credential(client, repo, wired):
    admin_a = user(client, repo, "t86-cur-a@example.com", admin=True)
    admin_b = user(client, repo, "t86-cur-b@example.com", admin=True)
    seeker = user(client, repo, "t86-cur-s@example.com")
    cursor = client.get(AUDIT, headers=admin_a, params={**WINDOW, "limit": 1}).json()["next_cursor"]
    assert cursor
    assert client.get(AUDIT, headers=seeker, params={**WINDOW, "limit": 1, "cursor": cursor}).status_code == 403
    assert client.get(AUDIT, params={**WINDOW, "limit": 1, "cursor": cursor}).status_code == 401
    # 같은 권한의 다른 관리자는 이어서 볼 수 있다(cursor 는 사용자에 묶이지 않음) — 권한 상승이 아니므로 허용, 보고서에 기록
    assert client.get(AUDIT, headers=admin_b, params={**WINDOW, "limit": 1, "cursor": cursor}).status_code == 200


def test_error_responses_carry_no_cost_header_or_internal_detail(client, repo, wired, store):
    admin = user(client, repo, "t86-err@example.com", admin=True)
    assert "x-ai-cost-status" not in client.get(USAGE).headers
    store.fail.add("usage")
    failed = client.get(USAGE, headers=admin, params={"from": "2026-11-01", "to": "2026-11-07"})
    assert failed.status_code == 503 and "x-ai-cost-status" not in failed.headers
    assert "synthetic" not in failed.text and "SELECT" not in failed.text
    store.fail.clear()
    ok_store = client.get(USAGE, headers=admin, params={"from": "2026-11-01", "to": "2026-11-07"})
    assert ok_store.headers["x-ai-cost-status"] == "unverified"


def test_audit_response_stays_within_admin_scope(client, repo, wired):
    admin = user(client, repo, "t86-scope@example.com", admin=True)
    body = client.get(AUDIT, headers=admin, params=WINDOW).json()
    assert {k for item in body["items"] for k in item} <= {
        "audit_event_id", "actor_user_id", "action_code", "resource_type", "resource_id", "request_id", "occurred_at"}
    assert "@" not in str(body)
