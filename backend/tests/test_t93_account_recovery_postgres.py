"""T93 비밀번호 재설정 — 실제 PostgreSQL 18 일회용 DB + FastAPI TestClient (메일은 메모리 outbox, 실제 발송 없음)."""
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL

from app.core.config import get_settings
from app.core.security import hash_password, issue_access_token
from app.main import create_app
from app.routers.account_recovery import get_mail_sender
from app.services.account_recovery import token_hash
from app.services.mail import MemoryMailSender
from tests.conftest import TEST_SECRET, bearer
from tests.security.security_pg import ROOT, USER_A, USER_B, SecurityPG, requires_pg

pytestmark = requires_pg
OLD, NEW = "old-correct-horse-93", "new-correct-horse-93"
EMAIL_A = "t86-a@example.invalid"      # security_pg 의 합성 사용자 A
WRITES = ("password_reset_tokens", "auth_identities", "auth_sessions", "audit_events", "users")


@pytest.fixture
def pg(monkeypatch):
    """T86 sec_pg 와 같은 가드·최소 권한 일회용 DB. 쓰기는 WRITES 표에만.
    (T87 PR #189 의 공용 disposable_pg 가 병합되면 그것으로 바꿀 수 있음 — 미병합 코드에 의존하지 않으려고 여기 둠)"""
    options = conninfo_to_dict(os.environ["T16_TEST_ADMIN_URL"])
    if options.get("host") not in {"127.0.0.1", "localhost"} or options.get("dbname") != "t16_profile_test":
        pytest.fail("Only loopback disposable t16_profile_test is allowed")
    role, password = "t93_" + uuid4().hex, secrets.token_urlsafe(24)
    ident = sql.Identifier(role)
    with psycopg.connect(os.environ["T16_TEST_ADMIN_URL"], autocommit=True) as admin:
        admin.execute("DROP SCHEMA IF EXISTS career CASCADE")
        admin.execute("CREATE SCHEMA career")
        admin.execute((ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8"))
        admin.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(ident, sql.Literal(password)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA career TO {}").format(ident))
        admin.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA career TO {}").format(ident))
        for table in WRITES:
            admin.execute(sql.SQL("GRANT INSERT, UPDATE ON career.{} TO {}").format(sql.Identifier(table), ident))
        headers = {}
        for uid, email in [(USER_A, EMAIL_A), (USER_B, "t86-b@example.invalid")]:
            admin.execute("INSERT INTO career.users(user_id,email,email_canonical,display_name) VALUES(%s,%s,%s,%s)",
                          (uid, email, email, "합성 사용자"))
            sid = uuid4()
            admin.execute("INSERT INTO career.auth_sessions(session_id,user_id,refresh_token_hash,expires_at) VALUES(%s,%s,%s,%s)",
                          (sid, uid, uid.hex * 2, datetime.now(UTC) + timedelta(hours=1)))
            headers[uid] = bearer(issue_access_token(TEST_SECRET, uid, sid, [], 3600))
        admin.execute("INSERT INTO career.auth_identities (user_id, provider, subject, password_hash) VALUES (%s,'local',%s,%s)",
                      (USER_A, EMAIL_A, hash_password(OLD)))
        url = URL.create("postgresql", username=role, password=password, host=options["host"],
                         port=int(options.get("port", 5432)), database=options["dbname"])
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
        monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
        get_settings.cache_clear()
        try:
            with TestClient(create_app(), base_url="https://testserver", headers={"X-CSRF-TOKEN": "1"},
                            raise_server_exceptions=False) as client:
                yield SecurityPG(client, admin, headers, role)
                client.app.dependency_overrides.clear()
        finally:
            get_settings.cache_clear()
            admin.execute("DROP SCHEMA career CASCADE")
            admin.execute(sql.SQL("DROP OWNED BY {}").format(ident))
            admin.execute(sql.SQL("DROP ROLE {}").format(ident))


def with_mail(pg, **kw) -> MemoryMailSender:
    mail = MemoryMailSender(**kw)
    pg.client.app.dependency_overrides[get_mail_sender] = lambda: mail
    return mail


def request(pg, email):
    return pg.client.post("/api/v1/auth/password-reset-requests", json={"email": email})


def reset(pg, token, password=NEW):
    return pg.client.post("/api/v1/auth/password-resets", json={"token": token, "new_password": password})


def test_default_without_mail_provider_is_the_same_503_for_everyone(pg):
    responses = [request(pg, EMAIL_A), request(pg, "nobody@example.invalid")]
    assert {r.status_code for r in responses} == {503}
    assert responses[0].json() == responses[1].json() | {"request_id": responses[0].json().get("request_id")} or \
        responses[0].json()["code"] == responses[1].json()["code"]
    assert pg.scalar("SELECT count(*) FROM career.password_reset_tokens") == 0


def test_full_reset_flow_on_real_postgres(pg, caplog):
    mail = with_mail(pg)
    with caplog.at_level(logging.DEBUG):
        known, unknown = request(pg, EMAIL_A), request(pg, "nobody@example.invalid")
        assert known.status_code == unknown.status_code == 202 and known.content == unknown.content == b""
        assert len(mail.outbox) == 1
        raw = mail.outbox[0].link.split("token=", 1)[1]
        stored = pg.scalar("SELECT token_hash FROM career.password_reset_tokens WHERE user_id=%s", USER_A)
        assert stored == token_hash(raw) and raw not in stored
        assert pg.scalar("SELECT expires_at - created_at FROM career.password_reset_tokens WHERE user_id=%s", USER_A) == timedelta(minutes=30)

        assert pg.client.get("/api/v1/me", headers=pg.h[USER_A]).status_code == 200
        done = reset(pg, raw)
        assert done.status_code == 204
        request_id = done.headers["x-request-id"]
    assert pg.client.get("/api/v1/me", headers=pg.h[USER_A]).status_code == 401, "all sessions revoked"
    assert pg.client.get("/api/v1/me", headers=pg.h[USER_B]).status_code == 200, "other users untouched"
    assert pg.scalar("SELECT count(*) FROM career.auth_sessions WHERE user_id=%s AND revoked_at IS NULL", USER_A) == 0
    assert pg.scalar("SELECT count(*) FROM career.password_reset_tokens WHERE user_id=%s AND used_at IS NULL", USER_A) == 0
    audit = pg.db.execute("SELECT actor_user_id, resource_type, request_id FROM career.audit_events "
                          "WHERE action_code='auth.password.reset'").fetchall()
    assert audit == [(USER_A, "user", request_id)]
    login_new = pg.client.post("/api/v1/auth/login", json={"email": EMAIL_A, "password": NEW})
    login_old = pg.client.post("/api/v1/auth/login", json={"email": EMAIL_A, "password": OLD})
    assert login_new.status_code == 200 and login_old.status_code == 401
    assert reset(pg, raw, "third-correct-horse-93").json()["code"] == "INVALID_RESET_TOKEN", "single use"
    server_logs = " | ".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    for secret in (raw, NEW, OLD, EMAIL_A):
        assert secret not in server_logs


def test_expired_and_forged_tokens_are_the_same_400(pg):
    with_mail(pg)
    created = datetime.now(UTC) - timedelta(hours=1)
    pg.db.execute("INSERT INTO career.password_reset_tokens (user_id, token_hash, created_at, expires_at) VALUES (%s,%s,%s,%s)",
                  (USER_A, token_hash("expired-token-0123456789-abcdef"), created, created + timedelta(minutes=30)))
    bodies = [reset(pg, "expired-token-0123456789-abcdef").json(), reset(pg, "forged-token-0123456789-abcdef").json()]
    assert {(b["status"], b["code"]) for b in bodies} == {(400, "INVALID_RESET_TOKEN")}
    assert pg.client.get("/api/v1/me", headers=pg.h[USER_A]).status_code == 200, "nothing changed"


def test_database_rejects_tokens_longer_than_30_minutes(pg):
    now = datetime.now(UTC)
    with pytest.raises(Exception):
        pg.db.execute("INSERT INTO career.password_reset_tokens (user_id, token_hash, created_at, expires_at) VALUES (%s,%s,%s,%s)",
                      (USER_A, "a" * 64, now, now + timedelta(minutes=31)))


def test_mail_failure_after_retries_leaves_no_token(pg):
    mail = with_mail(pg, fail_times=5)
    assert request(pg, EMAIL_A).status_code == 202
    assert mail.attempts == 3 and mail.outbox == []
    assert pg.scalar("SELECT count(*) FROM career.password_reset_tokens") == 0
