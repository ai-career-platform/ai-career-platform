"""T86 인가 회귀 게이트 — **모든** /api/v1/admin/* 경로 (DB 없음, T15 메모리 인증).

실패 시나리오 2(일반 사용자가 관리자 데이터 조회)·4(권한 회수 후 기존 토큰으로 접근)를 전 경로에서 막는지 확인합니다.
"""
import uuid

import jwt
import pytest

from app.core.security import issue_access_token
from tests import fakes
from tests.conftest import TEST_SECRET, bearer, signup
from tests.security.security_inventory import admin_routes

ADMIN = admin_routes()


def new_user(client, email):
    token = signup(client, email=email).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    return token, uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])


def call(client, route, token):
    return client.request(route.method, route.url(), headers=bearer(token))


def test_admin_inventory_is_not_empty_and_includes_t84():
    paths = {r.path for r in ADMIN}
    assert {"/api/v1/admin/audit-events", "/api/v1/admin/ai-usage"} <= paths
    assert len(ADMIN) >= 8


@pytest.mark.parametrize("route", ADMIN, ids=str)
def test_job_seeker_is_403_on_every_admin_route(client, route):
    token, _, _ = new_user(client, f"seeker-{uuid.uuid4().hex[:6]}@example.com")
    response = call(client, route, token)
    assert response.status_code == 403 and response.json()["code"] == "FORBIDDEN", f"{route}: {response.text[:120]}"


@pytest.mark.parametrize("route", ADMIN, ids=str)
def test_admin_claim_inside_the_token_is_not_trusted(client, route):
    _, user_id, sid = new_user(client, f"claim-{uuid.uuid4().hex[:6]}@example.com")
    forged_roles = issue_access_token(TEST_SECRET, user_id, sid, ["admin", "job_seeker"], 900)
    assert call(client, route, forged_roles).status_code == 403, route


def test_role_revocation_applies_to_the_same_token_on_every_admin_route(client, repo):
    token, user_id, _ = new_user(client, "t86-admin@example.com")
    repo.grant_role(user_id, "admin")
    before = {str(r): call(client, r, token).status_code for r in ADMIN}
    assert all(code not in (401, 403) for code in before.values()), before
    repo.revoke_role(user_id, "admin")
    after = {str(r): call(client, r, token).status_code for r in ADMIN}
    assert set(after.values()) == {403}, after
    repo.grant_role(user_id, "admin")
    assert all(call(client, r, token).status_code not in (401, 403) for r in ADMIN)


def test_admin_without_audit_permission_is_403_on_audit_events_only(client, repo, monkeypatch):
    token, user_id, _ = new_user(client, "t86-admin-noperm@example.com")
    repo.grant_role(user_id, "admin")
    monkeypatch.setitem(fakes.ROLE_PERMISSIONS, "admin", set())
    codes = {r.path: call(client, r, token).status_code for r in ADMIN}
    assert codes.pop("/api/v1/admin/audit-events") == 403
    # 그 밖의 admin 경로는 확정 계약상 역할(admin)만 요구 — 권한 코드 미적용이 의도임을 고정 (T84 D1 미승인)
    assert all(code not in (401, 403) for code in codes.values()), codes


def test_disabled_admin_is_401_everywhere(client, repo):
    token, user_id, _ = new_user(client, "t86-disabled@example.com")
    repo.grant_role(user_id, "admin")
    repo.set_status(user_id, "disabled")
    assert {call(client, r, token).status_code for r in ADMIN} == {401}
