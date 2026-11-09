"""T15 인증 API: 가입·로그인·갱신·로그아웃·세션 (FR-ACC-001~003, NFR-SEC-001)."""

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import API_V1_PREFIX
from app.core.security import hash_token
from tests.conftest import CONSENTS, PASSWORD, TEST_SECRET, bearer, signup

AUTH = f"{API_V1_PREFIX}/auth"


def login(client, email="seeker@example.com", password=PASSWORD, **headers):
    return client.post(f"{AUTH}/login", json={"email": email, "password": password}, headers=headers)


def assert_problem(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    assert set(body) == {"code", "status", "message"}
    assert body["code"] == code and body["status"] == status
    assert response.headers["x-request-id"]
    return body


# ---------------------------------------------------------------- signup
def test_signup_returns_token_cookie_and_stores_only_hashes(client, repo):
    response = signup(client, email="  Seeker+box@Example.com ")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"access_token", "token_type", "expires_in"}
    assert body["token_type"] == "Bearer" and body["expires_in"] == 900

    cookie = response.headers["set-cookie"]
    for attr in ("refresh_token=", "HttpOnly", "Secure", "SameSite=strict", f"Path={AUTH}", "Max-Age=1209600"):
        assert attr.lower() in cookie.lower()
    refresh = client.cookies.get("refresh_token")

    stored = repo.stored()
    (canonical, identity), = stored["identities"].items()
    assert canonical == "seeker@example.com"  # 비교용 이메일
    user = stored["users"][identity["user_id"]]
    assert user.email == "Seeker+box@Example.com"  # 입력값(앞뒤 공백만 제거) 보존
    assert identity["password_hash"].startswith("$argon2id$")
    dump = json.dumps({k: str(v) for k, v in stored.items()})
    assert PASSWORD not in dump and refresh not in dump
    assert any(s["hash"] == hash_token(refresh) for s in stored["sessions"].values())
    assert stored["roles"][identity["user_id"]] == {"job_seeker"}
    assert len(stored["consents"]) == 3


def test_signup_access_token_claims(client):
    token = signup(client).json()["access_token"]
    claims = jwt.decode(token, TEST_SECRET, algorithms=["HS256"], issuer="ai-career-platform")
    assert claims["roles"] == ["job_seeker"] and claims["typ"] == "access"
    assert uuid.UUID(claims["sub"]) and uuid.UUID(claims["sid"])
    assert claims["exp"] - claims["iat"] == 900


def test_signup_duplicate_canonical_email_is_409(client):
    assert signup(client, email="cras.nec+a@gmail.com").status_code == 201
    assert_problem(signup(client, email="CrasNec@googlemail.com"), 409, "EMAIL_TAKEN")


def test_signup_requires_required_consents(client, repo):
    consents = [c | {"granted": False} if c["policy_code"] == "privacy" else c for c in CONSENTS]
    assert_problem(signup(client, consents=consents), 422, "VALIDATION_FAILED")
    assert repo.stored()["users"] == {}


def test_signup_rejects_unknown_policy_version(client):
    consents = [*CONSENTS[:1], {"policy_code": "privacy", "policy_version": "1999-01", "granted": True}]
    assert_problem(signup(client, consents=consents), 422, "VALIDATION_FAILED")


def test_signup_validation_error_does_not_echo_password(client):
    response = signup(client, password="short")
    assert_problem(response, 422, "VALIDATION_FAILED")
    assert "short" not in response.text


def test_signup_is_rate_limited_per_ip(client, app):
    app.state.auth_settings = replace(app.state.auth_settings, signup_ip_max_attempts=2)
    assert signup(client, email="a@example.com").status_code == 201
    response = signup(client, email="b@example.com")
    assert_problem(response, 429, "RATE_LIMITED")
    assert int(response.headers["retry-after"]) > 0


# ---------------------------------------------------------------- login
def test_login_success_with_canonical_email(client, repo):
    signup(client, email="cras.nec+box@gmail.com")
    response = login(client, email="crasnec@gmail.com", **{"User-Agent": "pytest-device"})
    assert response.status_code == 200
    assert "refresh_token=" in response.headers["set-cookie"]
    assert response.headers["cache-control"] == "no-store"
    agents = [s["record"].user_agent for s in repo.stored()["sessions"].values()]
    assert "pytest-device" in agents


def test_login_failure_does_not_reveal_account_existence(client):
    signup(client)
    wrong_password = assert_problem(login(client, password="wrong-password-1"), 401, "INVALID_CREDENTIALS")
    no_account = assert_problem(login(client, email="nobody@example.com"), 401, "INVALID_CREDENTIALS")
    assert wrong_password == no_account


def test_login_disabled_account_gets_same_401(client, repo):
    user_id = jwt.decode(signup(client).json()["access_token"], options={"verify_signature": False})["sub"]
    repo.set_status(uuid.UUID(user_id), "disabled")
    assert_problem(login(client), 401, "INVALID_CREDENTIALS")


def test_login_locks_account_after_repeated_failures(client):
    signup(client)
    for _ in range(4):
        assert_problem(login(client, password="wrong-password-1"), 401, "INVALID_CREDENTIALS")
    locked = login(client, password="wrong-password-1")
    assert_problem(locked, 429, "RATE_LIMITED")
    assert int(locked.headers["retry-after"]) == 900
    # 잠긴 동안은 올바른 비밀번호도 거부
    assert_problem(login(client), 429, "RATE_LIMITED")


def test_successful_login_resets_failure_count(client):
    signup(client)
    for _ in range(4):
        login(client, password="wrong-password-1")
    assert login(client).status_code == 200
    for _ in range(4):
        assert_problem(login(client, password="wrong-password-1"), 401, "INVALID_CREDENTIALS")


# ---------------------------------------------------------------- refresh / logout
def test_refresh_rotates_token_and_old_token_is_rejected(client):
    signup(client)
    old_refresh = client.cookies.get("refresh_token")
    response = client.post(f"{AUTH}/refresh")
    assert response.status_code == 200
    new_refresh = client.cookies.get("refresh_token")
    assert new_refresh and new_refresh != old_refresh

    client.cookies.clear()
    client.cookies.set("refresh_token", old_refresh)
    assert_problem(client.post(f"{AUTH}/refresh"), 401, "UNAUTHENTICATED")


def test_refresh_without_cookie_is_401(client):
    assert_problem(client.post(f"{AUTH}/refresh"), 401, "UNAUTHENTICATED")


def test_logout_revokes_session_and_clears_cookie(client):
    token = signup(client).json()["access_token"]
    refresh = client.cookies.get("refresh_token")
    response = client.post(f"{AUTH}/logout")
    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()

    assert_problem(client.get(f"{API_V1_PREFIX}/me", headers=bearer(token)), 401, "UNAUTHENTICATED")
    client.cookies.set("refresh_token", refresh)
    assert_problem(client.post(f"{AUTH}/refresh"), 401, "UNAUTHENTICATED")


def test_logout_without_cookie_is_401(client):
    assert_problem(client.post(f"{AUTH}/logout"), 401, "UNAUTHENTICATED")


def test_expired_refresh_session_is_401(client, repo):
    token = signup(client).json()["access_token"]
    sid = uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sid"])
    repo.expire_session(sid, datetime.now(UTC) - timedelta(seconds=1))
    assert_problem(client.post(f"{AUTH}/refresh"), 401, "UNAUTHENTICATED")


# ---------------------------------------------------------------- consent policies
def test_consent_policies_is_public(client):
    response = client.get(f"{API_V1_PREFIX}/consent-policies")
    assert response.status_code == 200
    codes = {p["policy_code"]: p["is_required"] for p in response.json()}
    assert codes == {"terms": True, "privacy": True, "llm_processing": False}
