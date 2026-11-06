"""PostgreSQL 통합 테스트 (선택 실행) — 공식 T05 검증용 DDL + T10 Seed 기준.

`T15_TEST_DATABASE_URL`을 지정했을 때만 실행한다. 지정한 DB의 `career` 스키마를 지우고 다시 만드므로
**일회용 로컬 DB에서만** 쓴다. 공유 Staging DB 주소를 넣지 말 것.

    docker run -d --rm --name t15-pg -e POSTGRES_PASSWORD=t15local -p 127.0.0.1:55432:5432 postgres:16
    $env:T15_TEST_DATABASE_URL = "postgresql://postgres:t15local@127.0.0.1:55432/postgres"
    .venv\\Scripts\\python.exe -m pytest tests/test_auth_postgres.py -v

DDL·Seed 파일 위치는 기본값이 저장소의 `database/schema/T05_VALIDATION_ONLY.sql`,
`database/seeds/0001_initial_seed.sql`이며 `T15_SCHEMA_SQL`, `T15_SEED_SQL`로 바꿀 수 있다.
T10 Seed에는 약관 정책(consent_policies)이 없어 테스트에서 2026-11 버전 3건을 넣는다.
DB 준비·검증 조회는 모두 앱과 같은 SQLAlchemy 엔진·ORM 모델(app/models/auth.py)로 한다.
"""

import os
import pathlib
import uuid
from datetime import UTC, datetime

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import API_V1_PREFIX, get_settings
from app.main import create_app
from app.models.auth import (
    AuthIdentity,
    AuthSession,
    ConsentPolicy,
    Role,
    User,
    UserConsent,
    UserProfile,
    UserRole,
)
from tests.conftest import PASSWORD, TEST_SECRET, bearer

REPO = pathlib.Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("T15_TEST_DATABASE_URL")
SCHEMA_SQL = pathlib.Path(os.environ.get("T15_SCHEMA_SQL", REPO / "database/schema/T05_VALIDATION_ONLY.sql"))
SEED_SQL = pathlib.Path(os.environ.get("T15_SEED_SQL", REPO / "database/seeds/0001_initial_seed.sql"))

pytestmark = [
    pytest.mark.skipif(not DB_URL, reason="T15_TEST_DATABASE_URL not set"),
    pytest.mark.skipif(not (SCHEMA_SQL.exists() and SEED_SQL.exists()), reason="T05 DDL / T10 Seed file not found"),
]

POLICY_EFFECTIVE = datetime(2026, 11, 6, tzinfo=UTC)
TEST_POLICIES = [
    ("terms", True, "https://docs.ai-career.invalid/terms/2026-11"),
    ("privacy", True, "https://docs.ai-career.invalid/privacy/2026-11"),
    ("llm_processing", False, "https://docs.ai-career.invalid/llm/2026-11"),
]
CONSENTS = [
    {"policy_code": "terms", "policy_version": "2026-11", "granted": True},
    {"policy_code": "privacy", "policy_version": "2026-11", "granted": True},
]
EMAIL = "Cras.Nec+box@gmail.com"
CANONICAL = "crasnec@gmail.com"


@pytest.fixture
def engine() -> Engine:
    # 앱(app/db.py)과 같은 SQLAlchemy + psycopg 드라이버 조합
    test_engine = create_engine(make_url(DB_URL).set(drivername="postgresql+psycopg"))
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def pg_client(monkeypatch, engine):
    # DDL·Seed 파일은 자체 BEGIN/COMMIT을 포함하므로 AUTOCOMMIT 연결에서 그대로 실행한다.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS career CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA career")
        for sql_file in (SCHEMA_SQL, SEED_SQL):
            # exec_driver_sql은 pyformat 매개변수 처리를 거치므로 SQL 안의 '%'(나머지 연산 등)를 '%%'로 이스케이프
            conn.exec_driver_sql(sql_file.read_text(encoding="utf-8").replace("%", "%%"))
    with Session(engine) as db, db.begin():
        db.add_all(
            ConsentPolicy(
                policy_code=code, version="2026-11", is_required=required,
                content_url=url, effective_at=POLICY_EFFECTIVE,
            )
            for code, required, url in TEST_POLICIES
        )
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    monkeypatch.setenv("DATABASE_URL", DB_URL)
    get_settings.cache_clear()
    try:
        with TestClient(create_app(), base_url="https://testserver") as client:
            yield client
    finally:
        get_settings.cache_clear()


def scalar(engine, stmt):
    with Session(engine) as db:
        return db.scalar(stmt)


def rows(engine, stmt):
    with Session(engine) as db:
        return db.execute(stmt).all()


def grant_role(engine, user_id, code):
    with Session(engine) as db, db.begin():
        role_id = db.scalar(select(Role.role_id).where(Role.code == code))
        db.add(UserRole(user_id=user_id, role_id=role_id))


def signup_body(email, name="통합"):
    return {"email": email, "password": PASSWORD, "display_name": name, "consents": CONSENTS}


def test_full_flow_against_postgres(pg_client, engine):
    auth = f"{API_V1_PREFIX}/auth"
    signup = pg_client.post(f"{auth}/signup", json=signup_body(EMAIL))
    assert signup.status_code == 201, signup.text
    token = signup.json()["access_token"]
    user_id = uuid.UUID(jwt.decode(token, options={"verify_signature": False})["sub"])

    # 저장 내용: 원래 이메일 + 비교용 이메일, argon2id 해시, refresh 토큰은 해시만
    assert rows(engine, select(User.email, User.email_canonical).where(User.user_id == user_id)) == [(EMAIL, CANONICAL)]
    pw_hash = scalar(engine, select(AuthIdentity.password_hash).where(AuthIdentity.user_id == user_id))
    assert pw_hash.startswith("$argon2id$")
    refresh = pg_client.cookies.get("refresh_token")
    hashes = [h for (h,) in rows(engine, select(AuthSession.refresh_token_hash).where(AuthSession.user_id == user_id))]
    assert len(hashes) == 1 and refresh not in hashes and len(hashes[0]) == 64
    assert scalar(engine, select(func.count()).select_from(UserConsent).where(UserConsent.user_id == user_id)) == 2
    assert scalar(engine, select(func.count()).select_from(UserProfile).where(UserProfile.user_id == user_id)) == 1

    # 중복(비교용 이메일 기준)
    dup = pg_client.post(f"{auth}/signup", json=signup_body("crasnec@googlemail.com", "중복"))
    assert dup.status_code == 409 and dup.json()["code"] == "EMAIL_TAKEN"

    # /me, 권한, 역할 부여 즉시 반영 (Seed의 admin 역할·권한 사용)
    me = pg_client.get(f"{API_V1_PREFIX}/me", headers=bearer(token))
    assert me.status_code == 200 and me.json()["user_id"] == str(user_id)
    assert pg_client.get(f"{API_V1_PREFIX}/me/permissions", headers=bearer(token)).json() == {
        "roles": ["job_seeker"], "permissions": [],
    }
    grant_role(engine, user_id, "admin")
    assert pg_client.get(f"{API_V1_PREFIX}/me/permissions", headers=bearer(token)).json()["permissions"] == [
        "admin.audit.read", "admin.models.read",
    ]

    # 로그인(비교용 이메일) → 세션 2개, refresh 회전, 다른 기기 로그아웃
    login = pg_client.post(f"{auth}/login", json={"email": CANONICAL, "password": PASSWORD})
    assert login.status_code == 200
    second = login.json()["access_token"]
    second_sid = jwt.decode(second, options={"verify_signature": False})["sid"]
    assert scalar(engine, select(User.last_login_at).where(User.user_id == user_id)) is not None

    old_refresh = pg_client.cookies.get("refresh_token")
    assert pg_client.post(f"{auth}/refresh").status_code == 200
    pg_client.cookies.clear()
    pg_client.cookies.set("refresh_token", old_refresh)
    assert pg_client.post(f"{auth}/refresh").status_code == 401

    sessions = pg_client.get(f"{API_V1_PREFIX}/me/sessions", headers=bearer(token)).json()
    assert len(sessions) == 2
    assert pg_client.delete(f"{API_V1_PREFIX}/me/sessions/{second_sid}", headers=bearer(token)).status_code == 204
    assert pg_client.get(f"{API_V1_PREFIX}/me", headers=bearer(second)).status_code == 401
    assert pg_client.delete(f"{API_V1_PREFIX}/me/sessions/{second_sid}", headers=bearer(token)).status_code == 404

    bad = pg_client.post(f"{auth}/login", json={"email": CANONICAL, "password": "wrong-password-1"})
    assert bad.status_code == 401 and bad.json()["code"] == "INVALID_CREDENTIALS"


def test_seed_user_without_password_cannot_log_in(pg_client):
    # T10 Seed 사용자는 auth_identities가 없으므로 어떤 비밀번호로도 로그인되지 않는다.
    response = pg_client.post(
        f"{API_V1_PREFIX}/auth/login", json={"email": "seed-user-01@example.com", "password": PASSWORD}
    )
    assert response.status_code == 401 and response.json()["code"] == "INVALID_CREDENTIALS"


def test_signup_rolls_back_when_role_seed_missing(pg_client, engine):
    with Session(engine) as db, db.begin():
        role_id = db.scalar(select(Role.role_id).where(Role.code == "job_seeker"))
        db.execute(delete(UserRole).where(UserRole.role_id == role_id))
        db.execute(delete(Role).where(Role.role_id == role_id))
    # 운영에서는 500 INTERNAL_ERROR 응답. TestClient는 처리되지 않은 서버 예외를 그대로 다시 던진다.
    with pytest.raises(RuntimeError, match="not seeded"):
        pg_client.post(f"{API_V1_PREFIX}/auth/signup", json=signup_body("rollback@example.com", "롤백"))
    assert scalar(engine, select(func.count()).select_from(User).where(User.email_canonical == "rollback@example.com")) == 0
