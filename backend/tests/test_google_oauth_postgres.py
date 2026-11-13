"""#328 Google 계정 생성·로그인 PostgreSQL 통합 시험 (선택 실행, tests/test_auth_postgres.py 와 같은 조건).

`T15_TEST_DATABASE_URL` 이 있을 때만 돈다. 지정한 DB 의 `career` 스키마를 지우고 다시 만드므로 **일회용 DB 에서만** 쓴다.
실제 Google 대신 tests/google_idp.py 가짜 IdP 를 쓴다. DB 스키마는 바꾸지 않는다(기존 auth_identities 그대로).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app
from app.models.auth import AuthIdentity, AuthSession, ConsentPolicy, Role, User, UserConsent, UserRole
from app.repositories.auth import EmailTaken, IdentityTaken, NewUser, SqlAuthRepository
from app.services.google_oauth import GoogleOAuthClient
from tests.conftest import PASSWORD
from tests.google_idp import FakeGoogle
from tests.test_auth_postgres import CONSENTS, DB_URL, POLICY_EFFECTIVE, SCHEMA_SQL, SEED_SQL, TEST_POLICIES, engine  # noqa: F401
from tests.test_google_oauth import ALLOWED, CALLBACK, START, google_env

pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="T15_TEST_DATABASE_URL not set"),
    pytest.mark.skipif(not (SCHEMA_SQL.exists() and SEED_SQL.exists()), reason="T05 DDL / T10 Seed file not found"),
]
AUTH = f"{API_V1_PREFIX}/auth"


def reset_schema(engine) -> None:  # noqa: F811 (fixture 이름과 같은 인자)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS career CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA career")
        for sql_file in (SCHEMA_SQL, SEED_SQL):
            conn.exec_driver_sql(sql_file.read_text(encoding="utf-8").replace("%", "%%"))
    with Session(engine) as db, db.begin():
        db.add_all(
            ConsentPolicy(policy_code=code, version="2026-11", is_required=required, content_url=url,
                          effective_at=POLICY_EFFECTIVE)
            for code, required, url in TEST_POLICIES
        )


@pytest.fixture
def pg_google(monkeypatch, engine, tmp_path):  # noqa: F811
    reset_schema(engine)
    secret = tmp_path / "secret"
    secret.write_text("t328-synthetic-client-secret", encoding="utf-8")
    allow = tmp_path / "allow"
    allow.write_text(f"{ALLOWED}\ncrasnec@gmail.com\n", encoding="utf-8")
    google_env(monkeypatch, {"secret": secret, "allow": allow})
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()
    idp = FakeGoogle()
    application = create_app()
    runtime = application.state.google
    runtime.client = GoogleOAuthClient(runtime.settings, transport=idp.transport, key_resolver=idp.key_resolver)
    try:
        with TestClient(application, base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"}) as client:
            yield client, idp
    finally:
        get_settings.cache_clear()


def login(client, idp, email=ALLOWED, sub="pg-google-sub"):
    start = client.get(START, follow_redirects=False)
    code, state = idp.authorize(start.headers["location"], sub=sub, email=email)
    return client.get(CALLBACK, params={"code": code, "state": state}, follow_redirects=False)


def count(engine, model, *where):  # noqa: F811
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(model).where(*where))


def test_google_signup_and_return_login_against_postgres(pg_google, engine):  # noqa: F811
    client, idp = pg_google
    seeded = count(engine, User)  # T10 Seed 사용자
    assert login(client, idp).headers["location"] == "/auth/google/signup"
    assert count(engine, User) == seeded  # pending 단계에서는 DB 쓰기 없음
    response = client.post(f"{AUTH}/google/signup", json={"display_name": "구글PG", "consents": CONSENTS})
    assert response.status_code == 201, response.text
    user_id = uuid.UUID(jwt.decode(response.json()["access_token"], options={"verify_signature": False})["sub"])
    with Session(engine) as db:
        identity = db.execute(select(AuthIdentity.provider, AuthIdentity.subject, AuthIdentity.password_hash)
                              .where(AuthIdentity.user_id == user_id)).all()
        assert identity == [("google", "pg-google-sub", None)]
        assert db.scalar(select(User.email_canonical).where(User.user_id == user_id)) == ALLOWED
        roles = db.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.role_id)
                           .where(UserRole.user_id == user_id)).all()
        assert roles == ["job_seeker"]
    assert count(engine, UserConsent, UserConsent.user_id == user_id) == 2
    assert count(engine, AuthSession, AuthSession.user_id == user_id) == 1

    client.cookies.clear()
    returning = login(client, idp)
    assert returning.headers["location"] == "/auth/google/done?next=%2F"
    assert count(engine, User) == seeded + 1 and count(engine, AuthSession, AuthSession.user_id == user_id) == 2
    assert client.post(f"{AUTH}/refresh").status_code == 200


def test_same_email_local_account_is_not_linked_against_postgres(pg_google, engine):  # noqa: F811
    client, idp = pg_google
    seeded = count(engine, User)
    local = client.post(f"{AUTH}/signup", json={"email": "Cras.Nec+box@gmail.com", "password": PASSWORD,
                                                "display_name": "로컬", "consents": CONSENTS})
    assert local.status_code == 201
    response = login(client, idp, email="crasnec@gmail.com", sub="other-google-sub")
    assert response.headers["location"] == "/login?google_error=email_conflict"
    assert count(engine, AuthIdentity, AuthIdentity.provider == "google") == 0
    assert count(engine, User) == seeded + 1


def test_repository_unique_constraints_against_postgres(engine):  # noqa: F811
    reset_schema(engine)
    seeded_users, seeded_identities = count(engine, User), count(engine, AuthIdentity)
    now = datetime.now(UTC)
    google = NewUser(email="g@gmail.com", email_canonical="g@gmail.com", display_name="g", password_hash=None,
                     consents=[], role_code="job_seeker", identity_provider="google", identity_subject="dup-sub")
    with Session(engine) as db:
        repo = SqlAuthRepository(db)
        user_id = repo.create_user(google, now)
        repo.commit()
        assert repo.find_identity("google", "dup-sub") == user_id
        assert repo.find_identity("google", "missing") is None
        assert repo.find_identity("local", "g@gmail.com") is None  # local identity 를 만들지 않음
        with pytest.raises(IdentityTaken):
            repo.create_user(NewUser(**{**google.__dict__, "email": "h@gmail.com", "email_canonical": "h@gmail.com"}),
                             now)
        with pytest.raises(EmailTaken):
            repo.create_user(NewUser(**{**google.__dict__, "identity_subject": "another"}), now)
        # 롤백 뒤에도 세션은 계속 쓸 수 있고, 남은 행은 처음 1명뿐
        assert repo.email_exists("g@gmail.com")
    assert count(engine, User) == seeded_users + 1 and count(engine, AuthIdentity) == seeded_identities + 1
    with Session(engine) as db:
        with pytest.raises(ValueError):
            SqlAuthRepository(db).create_user(
                NewUser(**{**google.__dict__, "email": "x@gmail.com", "email_canonical": "x@gmail.com",
                           "identity_subject": "x", "password_hash": "$argon2id$not-allowed"}), now)
