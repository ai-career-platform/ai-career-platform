"""T43 with real T15 JWT/session checks; auth storage and T26/Gap DB are fakes.

get_current_user and get_skill_gap_user_id are never overridden here.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import jwt
import pytest

from app.core.config import get_settings
from app.core.security import issue_access_token
from app.main import create_app
from app.routers.skill_gaps import get_skill_gap_service, router
from app.services.skill_gaps import SkillGapService
from tests.fakes import MemoryAuthRepository, override_auth_repository
from tests.test_skill_gaps import FixedRuleFixture, MemoryGapRepository, ROLE, STAMP

JWT_TEST_KEY = "T43-test-only-jwt-signature-key-not-a-secret-123"
CONSENTS = [
    {"policy_code": "terms", "policy_version": "2026-11", "granted": True},
    {"policy_code": "privacy", "policy_version": "2026-11", "granted": True},
    {"policy_code": "llm_processing", "policy_version": "2026-11", "granted": False},
]


@pytest.fixture
def auth_case(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", JWT_TEST_KEY)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    get_settings.cache_clear()
    application = create_app()
    application.include_router(router, prefix="/api/v1")
    auth_repo = MemoryAuthRepository()
    gap_repo = MemoryGapRepository()
    service = SkillGapService(
        gap_repo, FixedRuleFixture(), clock=lambda: STAMP,
        new_id=uuid4, cursor_key=b"T43-auth-test-cursor-key-only-" * 2,
    )
    override_auth_repository(application, auth_repo)
    application.dependency_overrides[get_skill_gap_service] = lambda: service
    try:
        with TestClient(application, base_url="https://testserver") as client:
            yield client, auth_repo, gap_repo, service
    finally:
        get_settings.cache_clear()


def signup_user(client, email):
    response = client.post("/api/v1/auth/signup", json={
        "email": email, "password": "T43-synthetic-password-only-123",
        "display_name": "Synthetic T43 user", "consents": CONSENTS,
    })
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    claims = jwt.decode(token, JWT_TEST_KEY, algorithms=["HS256"], issuer="ai-career-platform")
    return token, UUID(claims["sub"]), UUID(claims["sid"])


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_real_auth_identity_used_for_creation_and_history(auth_case):
    client, _, gap_repo, _ = auth_case
    token, owner, _ = signup_user(client, "t43-owner@example.com")
    gap_repo.owner = owner
    headers = bearer(token)
    response = client.post("/api/v1/skill-gaps", headers=headers, json={"job_role_id": str(ROLE)})
    assert response.status_code == 201
    assessment_id = UUID(response.json()["assessment_id"])
    assert (owner, assessment_id) in gap_repo.saved
    assert client.get(response.headers["location"], headers=headers).status_code == 200
    history = client.get("/api/v1/skill-gaps", headers=headers)
    assert [row["assessment_id"] for row in history.json()["items"]] == [str(assessment_id)]


def test_other_real_user_cannot_read_owner_result(auth_case):
    client, _, gap_repo, _ = auth_case
    owner_token, owner, _ = signup_user(client, "t43-owner@example.com")
    gap_repo.owner = owner
    created = client.post("/api/v1/skill-gaps", headers=bearer(owner_token), json={"job_role_id": str(ROLE)})
    other_token, _, _ = signup_user(client, "t43-other@example.com")
    foreign = client.get(created.headers["location"], headers=bearer(other_token))
    missing = client.get(f"/api/v1/skill-gaps/{uuid4()}", headers=bearer(other_token))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert client.get("/api/v1/skill-gaps", headers=bearer(other_token)).json() == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("authorization", [None, "Basic abc", "Bearer not-a-jwt"])
def test_bad_auth_rejected_before_gap_service(auth_case, authorization):
    client, _, _, service = auth_case
    headers = {"Authorization": authorization} if authorization else {}
    headers["X-User-ID"] = str(uuid4())
    response = client.post("/api/v1/skill-gaps", headers=headers, json={"job_role_id": str(ROLE)})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert response.headers["www-authenticate"] == "Bearer"
    assert service.evaluator.calls == 0


@pytest.mark.parametrize("case,code", [
    ("expired_token", "TOKEN_EXPIRED"), ("forged_token", "UNAUTHENTICATED"),
    ("expired_session", "UNAUTHENTICATED"), ("revoked_session", "UNAUTHENTICATED"),
    ("disabled_user", "UNAUTHENTICATED"), ("mismatched_session", "UNAUTHENTICATED"),
])
def test_real_auth_rejection_on_t43(auth_case, case, code):
    client, repo, gap_repo, service = auth_case
    token, owner, sid = signup_user(client, "t43-owner@example.com")
    gap_repo.owner = owner
    if case == "expired_token":
        token = issue_access_token(JWT_TEST_KEY, owner, sid, ["job_seeker"], 900,
                                   now=datetime.now(timezone.utc) - timedelta(hours=1))
    elif case == "forged_token":
        token = issue_access_token("wrong-test-signature-key-1234567890123456", owner, sid, ["job_seeker"], 900)
    elif case == "expired_session":
        repo.expire_session(sid, datetime.now(timezone.utc) - timedelta(seconds=1))
    elif case == "revoked_session":
        repo.revoke_session(sid, owner, datetime.now(timezone.utc))
    elif case == "disabled_user":
        repo.set_status(owner, "disabled")
    else:
        token = issue_access_token(JWT_TEST_KEY, uuid4(), sid, ["job_seeker"], 900)
    response = client.post("/api/v1/skill-gaps", headers=bearer(token), json={"job_role_id": str(ROLE)})
    assert response.status_code == 401
    assert response.json()["code"] == code
    assert service.evaluator.calls == 0
    assert not gap_repo.saved


def test_logout_invalidates_t43_access(auth_case):
    client, _, gap_repo, _ = auth_case
    token, owner, _ = signup_user(client, "t43-owner@example.com")
    gap_repo.owner = owner
    assert client.get("/api/v1/skill-gaps", headers=bearer(token)).status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/skill-gaps", headers=bearer(token)).status_code == 401


def test_real_principal_cannot_be_overridden_by_body(auth_case):
    client, _, gap_repo, service = auth_case
    token, owner, _ = signup_user(client, "t43-owner@example.com")
    gap_repo.owner = owner
    response = client.post("/api/v1/skill-gaps", headers=bearer(token), json={
        "job_role_id": str(ROLE), "user_id": str(uuid4()),
    })
    assert response.status_code == 422
    assert service.evaluator.calls == 0


def test_real_user_cannot_reuse_other_users_history_cursor(auth_case):
    client, _, gap_repo, _ = auth_case
    owner_token, owner, _ = signup_user(client, "t43-owner@example.com")
    gap_repo.owner = owner
    for _ in range(2):
        assert client.post("/api/v1/skill-gaps", headers=bearer(owner_token), json={"job_role_id": str(ROLE)}).status_code == 201
    cursor = client.get("/api/v1/skill-gaps?limit=1", headers=bearer(owner_token)).json()["next_cursor"]
    other_token, _, _ = signup_user(client, "t43-other@example.com")
    response = client.get("/api/v1/skill-gaps", params={"cursor": cursor}, headers=bearer(other_token))
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_CURSOR"
