"""T86 인증 회귀 게이트 — **모든** 비공개 경로가 토큰 없음·만료·위변조에 401 을 돌려주는지 (DB 없음, T15 메모리 인증).

경로 목록은 실제 등록된 라우터에서 읽으므로, 인증을 빠뜨린 새 경로가 생기면 CI 가 실패합니다.
기존 tests/test_authz.py 는 대표 경로만 보므로, 여기서는 전 경로 × 토큰 변형을 확인합니다.
"""
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
import yaml
from pathlib import Path

from app.core.security import issue_access_token
from tests.conftest import TEST_SECRET, bearer, signup
from tests.security.security_inventory import COOKIE_AUTH_ROUTES, PUBLIC_ROUTES, inventory, protected

PROTECTED = protected()
SPEC = yaml.safe_load((Path(__file__).resolve().parents[3] / "docs/api/openapi.yaml").read_text(encoding="utf-8"))


def call(client, route, headers=None):
    return client.request(route.method, route.url(), headers=headers or {})


def assert_401(response, route, code=("UNAUTHENTICATED",)):
    assert response.status_code == 401, f"{route}: {response.status_code} {response.text[:120]}"
    assert response.json()["code"] in code, route
    assert response.headers.get("www-authenticate") == "Bearer", route


# ---------------------------------------------------------------- failure scenario 1: 인증 없이 200
@pytest.mark.parametrize("route", PROTECTED, ids=str)
def test_every_protected_route_rejects_missing_token(client, route):
    assert_401(call(client, route), route)


FORGED = {
    "wrong-secret": lambda uid, sid: jwt.encode({"sub": str(uid), "sid": str(sid), "exp": 9_999_999_999},
                                                "attacker-secret-0123456789-abcdefghij", algorithm="HS256"),
    "alg-none": lambda uid, sid: jwt.encode({"sub": str(uid), "sid": str(sid), "exp": 9_999_999_999}, None, algorithm="none"),
    "garbage": lambda uid, sid: "not-a-jwt",
    "tampered-payload": lambda uid, sid: _tamper(issue_access_token(TEST_SECRET, uid, sid, ["admin"], 900)),
}


def _tamper(token: str) -> str:
    head, payload, sig = token.split(".")
    return ".".join([head, payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB"), sig])


@pytest.mark.parametrize("variant", sorted(FORGED))
@pytest.mark.parametrize("route", PROTECTED, ids=str)
def test_every_protected_route_rejects_forged_tokens(client, route, variant):
    token = FORGED[variant](uuid.uuid4(), uuid.uuid4())
    assert_401(call(client, route, bearer(token)), route)


@pytest.mark.parametrize("route", PROTECTED, ids=str)
def test_every_protected_route_rejects_expired_token(client, route):
    token = issue_access_token(TEST_SECRET, uuid.uuid4(), uuid.uuid4(), ["admin"], 900,
                               now=datetime.now(UTC) - timedelta(hours=2))
    assert_401(call(client, route, bearer(token)), route, ("TOKEN_EXPIRED",))


@pytest.mark.parametrize("route", PROTECTED, ids=str)
def test_every_protected_route_rejects_validly_signed_token_without_a_live_session(client, route):
    """서명은 맞지만 서버에 없는(또는 폐기된) 세션 → 401. 토큰 안의 roles 는 신뢰하지 않음."""
    token = issue_access_token(TEST_SECRET, uuid.uuid4(), uuid.uuid4(), ["admin"], 900)
    assert_401(call(client, route, bearer(token)), route)


def test_logged_out_session_token_is_rejected_on_every_protected_route(client):
    response = signup(client, email="t86-logout@example.com")
    token = response.json()["access_token"]
    assert client.get("/api/v1/me", headers=bearer(token)).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=bearer(token)).status_code in (200, 204)
    for route in PROTECTED:
        assert_401(call(client, route, bearer(token)), route)


# ---------------------------------------------------------------- gate: 공개 경로 목록 = 실제 = 계약
def test_unauthenticated_reachable_routes_are_exactly_the_reviewed_list(client):
    reachable = {r.key for r in inventory() if call(client, r).status_code != 401}
    assert reachable == PUBLIC_ROUTES, "새 공개 경로는 보안 검토 후 PUBLIC_ROUTES 에 추가"


@pytest.mark.parametrize("key", sorted(COOKIE_AUTH_ROUTES))
def test_cookie_authenticated_routes_reject_missing_or_forged_refresh_cookie(client, key):
    method, path = key
    assert_401(client.request(method, path), key)
    client.cookies.set("refresh_token", "forged-refresh-value", domain="testserver", path="/api/v1/auth")
    assert_401(client.request(method, path), key)


def test_public_api_routes_are_public_in_the_confirmed_contract():
    contract_public = set()
    for path, item in SPEC["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict):
                security = op.get("security", SPEC.get("security"))
                if not security or {} in security:
                    contract_public.add((method.upper(), "/api/v1" + path))
    app_public = {k for k in PUBLIC_ROUTES if k[1].startswith("/api/v1/")}
    assert app_public <= contract_public, app_public - contract_public
    assert not COOKIE_AUTH_ROUTES & contract_public, "refresh/logout 은 계약상 공개 경로가 아님"


def test_inventory_matches_the_running_app(app):
    running = {r.key for r in inventory(app) if not r.path.startswith("/api/v1/_probe")}  # conftest 전용 시험 경로 제외
    assert running == {r.key for r in inventory()}
