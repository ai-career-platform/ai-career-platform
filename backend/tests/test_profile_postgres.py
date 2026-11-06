"""Opt-in PostgreSQL tests; NEVER point these at a shared/user database."""

import os
import secrets
import sys
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.dependencies.profile import AuthenticatedUser, get_authenticated_user, get_profile_repository
from app.main import create_app
from app.repositories.profile import PostgresProfileRepository

pytestmark = pytest.mark.skipif(os.environ.get("T16_ISOLATED_DB_TEST") != "YES",
                                reason="requires explicit disposable PostgreSQL environment")
ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "database/model"))
import check_data_dictionary as cdd

A = UUID("00000000-0000-4000-8000-000000000001")
B = UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture
def pg_app():
    admin_url = os.environ["T16_TEST_ADMIN_URL"]
    options = conninfo_to_dict(admin_url)
    if options.get("host") not in {"127.0.0.1", "localhost"} or options.get("dbname") != "t16_profile_test":
        pytest.fail("Only loopback disposable database t16_profile_test is allowed")
    schema = "t16_" + uuid4().hex
    role = "t16_" + uuid4().hex
    password = secrets.token_urlsafe(24)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        tables = [t for t in cdd.parse(cdd.DICTIONARY.read_text(encoding="utf-8"))
                  if t.name in {"users", "user_profiles"}]
        # Exact T05 generated table/constraint definitions, test schema only.
        admin.execute(cdd.ddl(tables, schema))
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE")
                      .format(sql.Identifier(role), sql.Literal(password)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}")
                      .format(sql.Identifier(schema), sql.Identifier(role)))
        admin.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA {} TO {}")
                      .format(sql.Identifier(schema), sql.Identifier(role)))
        for user_id, name in [(A, "Synthetic A"), (B, "Synthetic B")]:
            email = name[-1].lower() + "@example.invalid"
            admin.execute("INSERT INTO users (user_id,email,email_canonical,display_name) VALUES (%s,%s,%s,%s)",
                          (user_id,email,email,name))
            admin.execute("INSERT INTO user_profiles (user_id,headline,bio) VALUES (%s,%s,%s)",
                          (user_id,"initial","keep"))
        try:
            with psycopg.connect(make_conninfo(admin_url, user=role, password=password),
                                 options=f"-csearch_path={schema}") as connection:
                app = create_app()
                app.dependency_overrides[get_authenticated_user] = lambda: AuthenticatedUser(A)
                app.dependency_overrides[get_profile_repository] = lambda: PostgresProfileRepository(connection)
                with TestClient(app) as client:
                    yield client, connection, admin
        finally:
            # Objects belong only to this random test schema in a validated test DB.
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_postgres_roundtrip_and_ownership(pg_app):
    client, connection, admin = pg_app
    # GET/auth may leave an outer read transaction open before a write.
    assert client.get("/api/v1/me").status_code == 200
    response = client.patch("/api/v1/me", json={"display_name":"Changed", "headline":None})
    assert response.status_code == 200
    assert response.json()["profile"] == {"headline":None,"bio":"keep","location_text":None}
    assert client.get("/api/v1/me").json() == response.json()
    assert admin.execute("SELECT display_name FROM users WHERE user_id=%s", (A,)).fetchone()[0] == "Changed"
    assert connection.execute("SELECT display_name FROM users WHERE user_id=%s", (B,)).fetchone()[0] == "Synthetic B"


def test_postgres_atomic_rollback(pg_app):
    client, connection, admin = pg_app
    admin.execute("""CREATE FUNCTION reject_profile() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'synthetic private failure'; END $$""")
    admin.execute("CREATE TRIGGER reject_profile BEFORE UPDATE ON user_profiles FOR EACH ROW EXECUTE FUNCTION reject_profile()")
    response = client.patch("/api/v1/me", json={"display_name":"must rollback","bio":"changed"})
    assert response.status_code == 503
    assert "synthetic private failure" not in response.text
    assert connection.execute("SELECT display_name FROM users WHERE user_id=%s", (A,)).fetchone()[0] == "Synthetic A"


def test_postgres_missing_profile_upsert(pg_app):
    client, _, admin = pg_app
    admin.execute("DELETE FROM user_profiles WHERE user_id=%s", (A,))
    assert client.get("/api/v1/me").json()["profile"]["bio"] is None
    response = client.patch("/api/v1/me", json={"bio":"new profile"})
    assert response.status_code == 200
    assert response.json()["profile"]["bio"] == "new profile"


def test_postgres_test_writer_is_not_admin(pg_app):
    _, connection, _ = pg_app
    assert connection.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone() == (False,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection.transaction():
            connection.execute("DELETE FROM users WHERE user_id=%s", (B,))


def test_postgres_invalid_and_disabled(pg_app):
    client, _, admin = pg_app
    assert client.patch("/api/v1/me", json={"email":"forbidden@example.invalid"}).status_code == 422
    admin.execute("UPDATE users SET status='disabled' WHERE user_id=%s", (A,))
    assert client.get("/api/v1/me").status_code == 404
    assert client.patch("/api/v1/me", json={"headline":"no"}).status_code == 404
