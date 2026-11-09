"""T15 인가: 익명 401 / 일반 사용자 403·404 / 관리자·소유자 200 (API_CONTRACT §1.3, NFR-SEC-002)."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import API_V1_PREFIX
from app.core.security import issue_access_token
from tests.conftest import TEST_SECRET, bearer, signup

ME = f"{API_V1_PREFIX}/me"
PROBE = f"{API_V1_PREFIX}/_probe"


def new_user(client, email):
    token = signup(client, email=email).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    return token, uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])


@pytest.fixture
def seeker(client):
    return new_user(client, "seeker@example.com")


@pytest.fixture
def admin(client, repo):
    token, user_id, sid = new_user(client, "admin@example.com")
    repo.grant_role(user_id, "admin")
    return token, user_id, sid


def assert_status(response, status, code=None):
    assert response.status_code == status, response.text
    if code:
        assert response.headers["content-type"] == "application/json"
        assert response.json()["code"] == code


# ---------------------------------------------------------------- 401 anonymous / bad token
@pytest.mark.parametrize("path", [ME, f"{ME}/permissions", f"{ME}/sessions", f"{PROBE}/admin", f"{PROBE}/audit"])
def test_anonymous_is_401(client, path):
    response = client.get(path)
    assert_status(response, 401, "UNAUTHENTICATED")
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    ["Bearer not-a-jwt", "Basic abc", "Bearer " + jwt.encode({"sub": "x"}, "wrong-secret-0123456789-0123456789")],
)
def test_malformed_or_forged_token_is_401(client, header):
    assert_status(client.get(ME, headers={"Authorization": header}), 401, "UNAUTHENTICATED")


def test_expired_token_is_401_token_expired(client, seeker):
    _, user_id, sid = seeker
    past = datetime.now(UTC) - timedelta(hours=1)
    token = issue_access_token(TEST_SECRET, user_id, sid, ["job_seeker"], 900, now=past)
    assert_status(client.get(ME, headers=bearer(token)), 401, "TOKEN_EXPIRED")


def test_token_for_other_users_session_is_401(client, seeker):
    _, _, sid = seeker
    token = issue_access_token(TEST_SECRET, uuid.uuid4(), sid, ["admin"], 900)
    assert_status(client.get(ME, headers=bearer(token)), 401, "UNAUTHENTICATED")


def test_disabled_user_token_is_401(client, repo, seeker):
    token, user_id, _ = seeker
    repo.set_status(user_id, "disabled")
    assert_status(client.get(ME, headers=bearer(token)), 401, "UNAUTHENTICATED")


# ---------------------------------------------------------------- 200 me
def test_me_returns_own_account(client, seeker):
    token, user_id, _ = seeker
    response = client.get(ME, headers=bearer(token))
    assert_status(response, 200)
    body = response.json()
    assert body["user_id"] == str(user_id)
    assert body["email"] == "seeker@example.com" and body["status"] == "active"
    assert body["profile"] == {"headline": None, "bio": None, "location_text": None}
    assert "email_canonical" not in body


def test_my_permissions(client, seeker, admin):
    seeker_body = client.get(f"{ME}/permissions", headers=bearer(seeker[0])).json()
    assert seeker_body == {"roles": ["job_seeker"], "permissions": []}
    admin_body = client.get(f"{ME}/permissions", headers=bearer(admin[0])).json()
    assert admin_body["roles"] == ["admin", "job_seeker"]
    assert admin_body["permissions"] == ["admin.audit.read", "admin.models.read"]


# ---------------------------------------------------------------- 403 role / permission
def test_seeker_is_403_on_admin_routes(client, seeker):
    assert_status(client.get(f"{PROBE}/admin", headers=bearer(seeker[0])), 403, "FORBIDDEN")
    assert_status(client.get(f"{PROBE}/audit", headers=bearer(seeker[0])), 403, "FORBIDDEN")


def test_admin_is_200_on_admin_routes(client, admin):
    assert_status(client.get(f"{PROBE}/admin", headers=bearer(admin[0])), 200)
    assert_status(client.get(f"{PROBE}/audit", headers=bearer(admin[0])), 200)


def test_roles_in_token_are_not_trusted(client, seeker):
    _, user_id, sid = seeker
    forged_roles = issue_access_token(TEST_SECRET, user_id, sid, ["admin"], 900)
    assert_status(client.get(f"{PROBE}/admin", headers=bearer(forged_roles)), 403, "FORBIDDEN")


def test_role_revocation_applies_on_next_request(client, repo, admin):
    token, user_id, _ = admin
    assert_status(client.get(f"{PROBE}/admin", headers=bearer(token)), 200)
    repo.revoke_role(user_id, "admin")
    assert_status(client.get(f"{PROBE}/admin", headers=bearer(token)), 403, "FORBIDDEN")


# ---------------------------------------------------------------- 404 ownership
def test_owner_200_other_user_404_missing_404(client, owners, seeker, admin):
    seeker_token, seeker_id, _ = seeker
    doc_id = uuid.uuid4()
    owners[doc_id] = seeker_id
    assert_status(client.get(f"{PROBE}/documents/{doc_id}", headers=bearer(seeker_token)), 200)
    # 다른 사용자(관리자라도)는 존재를 알 수 없게 404
    other = client.get(f"{PROBE}/documents/{doc_id}", headers=bearer(admin[0]))
    missing = client.get(f"{PROBE}/documents/{uuid.uuid4()}", headers=bearer(admin[0]))
    assert_status(other, 404, "NOT_FOUND")
    assert_status(missing, 404, "NOT_FOUND")
    assert other.json() == missing.json()


# ---------------------------------------------------------------- sessions
def test_session_list_marks_current_and_revoke_other_device(client, seeker):
    token, _, sid = seeker
    second = client.post(
        f"{API_V1_PREFIX}/auth/login",
        json={"email": "seeker@example.com", "password": "correct-horse-battery-1"},
        headers={"User-Agent": "second-device"},
    ).json()["access_token"]
    second_sid = jwt.decode(second, options={"verify_signature": False})["sid"]

    sessions = client.get(f"{ME}/sessions", headers=bearer(token)).json()
    assert {s["session_id"]: s["is_current"] for s in sessions} == {str(sid): True, second_sid: False}

    assert_status(client.delete(f"{ME}/sessions/{second_sid}", headers=bearer(token)), 204)
    assert_status(client.get(ME, headers=bearer(second)), 401, "UNAUTHENTICATED")
    # 이미 끝난 세션 재요청 → 404
    assert_status(client.delete(f"{ME}/sessions/{second_sid}", headers=bearer(token)), 404, "NOT_FOUND")


def test_cannot_revoke_other_users_session(client, seeker, admin):
    _, _, seeker_sid = seeker
    assert_status(client.delete(f"{ME}/sessions/{seeker_sid}", headers=bearer(admin[0])), 404, "NOT_FOUND")
    assert_status(client.get(ME, headers=bearer(seeker[0])), 200)


def test_unauthenticated_request_does_not_touch_database(client, app):
    def explode():
        raise AssertionError("repository must not be created for anonymous requests")

    from app.dependencies.auth import get_auth_repository

    app.dependency_overrides[get_auth_repository] = explode
    assert_status(client.get(ME), 401, "UNAUTHENTICATED")
