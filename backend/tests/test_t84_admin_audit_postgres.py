"""T84 실제 PostgreSQL 18 통합 테스트 — FastAPI → SQLAlchemy → PostgreSQL (일회용 DB 전용).

T16 가드와 같은 조건에서만 실행한다: T16_ISOLATED_DB_TEST=YES, loopback, DB 이름 t16_profile_test.
- 0001 Migration + 0001 Seed(역할·권한) 를 그대로 적용하고, 합성 사용자·감사 행·사용량 행만 넣는다.
- 앱은 **최소 권한 역할**로 접속: 인증 6개 표 SELECT, audit_events SELECT·INSERT, ai_usage_records SELECT.
  UPDATE·DELETE 권한이 없음을 확인한다. 끝나면 스키마와 역할을 지운다.
- 비용 NULL 허용(D2-A)은 이 일회용 DB 안에서만 ALTER 로 흉내 낸다 — 실제 Migration 아님.
Staging·공유 DB에는 절대 연결하지 않는다.
"""
import os
import secrets
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL
from sqlalchemy.orm import Session

from app.core.config import DatabaseSettings, get_settings
from app.core.security import issue_access_token
from app.db import create_db_engine
from app.main import create_app
from app.repositories.admin_audit import SqlAdminAuditRepository
from app.routers import admin_audit as admin_router
from app.services.admin_audit import PROPOSED_POLICY, AdminAuditService, AdminQueryPolicy
from app.services.job_postings import ListCursor, derive_cursor_key
from tests.conftest import TEST_SECRET, bearer

pytestmark = pytest.mark.skipif(os.environ.get("T16_ISOLATED_DB_TEST") != "YES",
                                reason="requires disposable loopback PostgreSQL")
ROOT = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((ROOT / "docs/api/openapi.yaml").read_text(encoding="utf-8"))
AUDIT, USAGE = "/api/v1/admin/audit-events", "/api/v1/admin/ai-usage"
ADMIN, SEEKER = UUID("00000000-0000-4000-8000-000000000841"), UUID("00000000-0000-4000-8000-000000000842")
# user_profiles: User ORM 이 LEFT JOIN 으로 함께 읽는다 (인증 경로가 실제로 요구함 — 최소 권한 시험에서 확인)
AUTH_TABLES = ("users", "user_profiles", "auth_sessions", "user_roles", "roles", "role_permissions", "permissions")


def contract(name):
    return Draft202012Validator({"$ref": f"#/components/schemas/{name}", "components": SPEC["components"]})


class PG:
    def __init__(self, client, engine, admin, headers, role):
        self.client, self.engine, self.db, self.h, self.role = client, engine, admin, headers, role

    def q(self, query, *args):
        return self.db.execute(query, args).fetchall()

    def count(self, where="TRUE", *args):
        return self.db.execute(f"SELECT count(*) FROM career.audit_events WHERE {where}", args).fetchone()[0]


@pytest.fixture
def pg(monkeypatch):
    options = conninfo_to_dict(os.environ["T16_TEST_ADMIN_URL"])
    if options.get("host") not in {"127.0.0.1", "localhost"} or options.get("dbname") != "t16_profile_test":
        pytest.fail("Only loopback disposable t16_profile_test is allowed")
    role, password = "t84_" + uuid4().hex, secrets.token_urlsafe(24)
    with psycopg.connect(os.environ["T16_TEST_ADMIN_URL"], autocommit=True) as admin:
        assert 180000 <= admin.info.server_version < 190000
        admin.execute("DROP SCHEMA IF EXISTS career CASCADE")
        admin.execute("CREATE SCHEMA career")
        admin.execute((ROOT / "database/migrations/0001_initial_schema.sql").read_text(encoding="utf-8"))
        admin.execute((ROOT / "database/seeds/0001_initial_seed.sql").read_text(encoding="utf-8"))
        ident = sql.Identifier(role)
        admin.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
            ident, sql.Literal(password)))
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA career TO {}").format(ident))
        for table in AUTH_TABLES + ("ai_usage_records",):
            admin.execute(sql.SQL("GRANT SELECT ON career.{} TO {}").format(sql.Identifier(table), ident))
        admin.execute(sql.SQL("GRANT SELECT, INSERT ON career.audit_events TO {}").format(ident))
        sessions = {}
        for uid, email, role_code in [(ADMIN, "t84-admin@example.invalid", "admin"),
                                      (SEEKER, "t84-seeker@example.invalid", "job_seeker")]:
            admin.execute("INSERT INTO career.users(user_id,email,email_canonical,display_name) VALUES(%s,%s,%s,%s)",
                          (uid, email, email, "합성 사용자"))
            admin.execute("INSERT INTO career.user_roles(user_id, role_id) SELECT %s, role_id FROM career.roles "
                          "WHERE code=%s", (uid, role_code))
            sessions[uid] = uuid4()
            admin.execute("INSERT INTO career.auth_sessions(session_id,user_id,refresh_token_hash,expires_at) "
                          "VALUES(%s,%s,%s,%s)", (sessions[uid], uid, uid.hex * 2, datetime.now(UTC) + timedelta(hours=1)))
        url = URL.create("postgresql+psycopg", username=role, password=password, host=options["host"],
                         port=int(options.get("port", 5432)), database=options["dbname"])
        runtime = create_db_engine(DatabaseSettings(url=url.render_as_string(hide_password=False), pool_size=3,
                                                    timeout=5))
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
        monkeypatch.setenv("DATABASE_URL", url.set(drivername="postgresql").render_as_string(hide_password=False))
        get_settings.cache_clear()
        app = create_app()
        try:
            with TestClient(app, base_url="https://testserver") as client:
                headers = {uid: bearer(issue_access_token(TEST_SECRET, uid, sid, [], 3600))
                           for uid, sid in sessions.items()}
                pg = PG(client, runtime, admin, headers, role)
                pg.app = app
                yield pg
        finally:
            runtime.dispose()
            get_settings.cache_clear()
            admin.execute("DROP SCHEMA career CASCADE")
            admin.execute(sql.SQL("DROP OWNED BY {}").format(ident))
            admin.execute(sql.SQL("DROP ROLE {}").format(ident))


def insert_events(pg, rows):
    """rows: (audit_event_id, actor, action, resource_type, resource_id, request_id, occurred_at)"""
    with pg.db.cursor() as cur:
        cur.executemany("INSERT INTO career.audit_events(audit_event_id, actor_user_id, action_code, resource_type, "
                        "resource_id, request_id, occurred_at) VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)


def nid(n):
    return UUID(f"00000000-0000-4000-9000-{n:012d}")


def get(pg, path, who=ADMIN, **params):
    return pg.client.get(path, headers=pg.h[who], params=params)


# cursor 는 검색 조건에 묶이므로 조회 기간은 한 번만 정한다.
WINDOW = {"from": (datetime.now(UTC) - timedelta(days=30)).isoformat(),
          "to": (datetime.now(UTC) + timedelta(days=1)).isoformat()}


def audit(pg, who=ADMIN, **params):
    return get(pg, AUDIT, who, **{**WINDOW, **params})


# ---------------------------------------------------------------- audit events
def test_pg_least_privilege_runtime_role(pg):
    grants = {r[0] for r in pg.q("SELECT privilege_type FROM information_schema.role_table_grants "
                                 "WHERE grantee=%s AND table_name='audit_events'", pg.role)}
    assert grants == {"SELECT", "INSERT"}
    assert not pg.q("SELECT 1 FROM pg_roles WHERE rolname=%s AND (rolsuper OR rolcreaterole)", pg.role)
    with Session(pg.engine) as db:
        assert db.connection().exec_driver_sql("SELECT current_user").scalar() == pg.role


def test_pg_admin_reads_real_rows_in_the_confirmed_shape_without_writing(pg):
    t = datetime.now(UTC) - timedelta(hours=1)
    insert_events(pg, [(nid(1), ADMIN, "admin.role.grant", "user", SEEKER, "req-t84-0001", t),
                       (nid(2), None, "system.behavior.purge", "behavior_purge_run", nid(50), "req-t84-0002",
                        t - timedelta(minutes=1))])
    before = pg.count()
    response = audit(pg)
    assert response.status_code == 200, response.text
    contract("AuditEventPage").validate(response.json())
    assert [i["audit_event_id"] for i in response.json()["items"]] == [str(nid(1)), str(nid(2))]
    assert "example.invalid" not in response.text and "합성 사용자" not in response.text
    assert pg.count() == before, "confirmed policy writes nothing"


def test_pg_authorization_boundaries(pg):
    assert pg.client.get(AUDIT).status_code == 401
    assert audit(pg, SEEKER).json()["code"] == "FORBIDDEN"
    assert get(pg, USAGE, SEEKER, **{"from": "2026-11-01", "to": "2026-11-02"}).status_code == 403
    pg.db.execute("DELETE FROM career.role_permissions WHERE permission_id = "
                  "(SELECT permission_id FROM career.permissions WHERE code='admin.audit.read')")
    assert audit(pg).status_code == 403, "admin role without admin.audit.read"
    assert get(pg, USAGE, **{"from": "2026-11-01", "to": "2026-11-02"}).status_code == 200, "confirmed: admin role"
    pg.db.execute("DELETE FROM career.user_roles WHERE user_id=%s", (ADMIN,))
    assert get(pg, USAGE, **{"from": "2026-11-01", "to": "2026-11-02"}).status_code == 403, "revoked admin"


def test_pg_cursor_walk_over_identical_timestamps_and_filters(pg):
    t = datetime.now(UTC).replace(microsecond=123456) - timedelta(hours=2)
    insert_events(pg, [(nid(n), ADMIN if n % 2 else None, "admin.role.grant" if n % 3 else "admin.role.revoke",
                        "user", None, None, t) for n in range(1, 251)])
    seen, cursor = [], None
    while True:
        body = audit(pg, limit=100, **({"cursor": cursor} if cursor else {})).json()
        seen += [i["audit_event_id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == 250 and len(set(seen)) == 250
    assert seen == [str(nid(n)) for n in range(250, 0, -1)], "uuid order is PostgreSQL byte order"
    by_actor = audit(pg, actor_user_id=str(ADMIN), action_code="admin.role.revoke", limit=100).json()["items"]
    assert {i["audit_event_id"] for i in by_actor} == {str(nid(n)) for n in range(1, 251) if n % 2 and not n % 3}


def test_pg_cursor_and_validation_errors(pg):
    insert_events(pg, [(nid(n), None, "system.x.y", "r", None, None, datetime.now(UTC) - timedelta(minutes=n))
                       for n in range(1, 4)])
    cursor = audit(pg, limit=1).json()["next_cursor"]
    bad = audit(pg, limit=1, cursor=cursor[:-3] + ("AAA" if cursor[-3:] != "AAA" else "BBB"))
    assert bad.status_code == 400 and bad.json()["code"] == "INVALID_CURSOR"
    assert audit(pg, limit=1, cursor=cursor, action_code="system.x.y").status_code == 400
    assert audit(pg, **{"from": "2026-11-01T00:00:00"}).status_code == 422
    assert audit(pg, limit=101).status_code == 422


def test_pg_rows_newer_than_the_first_page_never_join_the_walk(pg):
    base = datetime.now(UTC) - timedelta(hours=1)
    insert_events(pg, [(nid(n), None, "system.x.y", "r", None, None, base - timedelta(minutes=n)) for n in range(1, 5)])
    first = audit(pg, limit=2).json()
    insert_events(pg, [(nid(99), None, "system.x.y", "r", None, None, datetime.now(UTC))])
    second = audit(pg, limit=2, cursor=first["next_cursor"]).json()
    ids = [i["audit_event_id"] for i in first["items"] + second["items"]]
    assert ids == [str(nid(n)) for n in range(1, 5)] and second["next_cursor"] is None


# ---------------------------------------------------------------- D4 / limits (PROPOSED, test-only policy)
def test_pg_d4_read_event_committed_excluded_and_written_once_proposed(pg):
    pg.app.dependency_overrides[admin_router.get_admin_query_policy] = lambda: PROPOSED_POLICY
    insert_events(pg, [(nid(n), None, "system.x.y", "r", None, None, datetime.now(UTC) - timedelta(minutes=n))
                       for n in range(1, 4)])
    first = audit(pg, limit=2, actor_user_id=str(SEEKER))
    first = audit(pg, limit=2)
    assert first.status_code == 200
    reads = pg.q("SELECT audit_event_id, actor_user_id, resource_type, resource_id, request_id FROM "
                 "career.audit_events WHERE action_code='admin.audit.view' ORDER BY occurred_at")
    assert len(reads) == 2, "one per first page; committed (seen from another connection)"
    last = reads[-1]
    assert last[1] == ADMIN and last[2] == "audit_events" and last[3] is None
    assert last[4] == first.headers["x-request-id"]
    assert str(last[0]) not in first.text
    assert all(str(SEEKER) not in str(r) for r in reads), "filter values are not stored"
    second = audit(pg, limit=2, cursor=first.json()["next_cursor"])
    assert pg.count("action_code='admin.audit.view'") == 2 and str(last[0]) not in second.text


def test_pg_d4_fail_closed_when_insert_is_not_allowed_proposed(pg):
    insert_events(pg, [(nid(1), None, "system.x.y", "r", None, None, datetime.now(UTC) - timedelta(minutes=1))])
    pg.db.execute(sql.SQL("REVOKE INSERT ON career.audit_events FROM {}").format(sql.Identifier(pg.role)))
    assert audit(pg).status_code == 200, "confirmed policy needs SELECT only"
    pg.app.dependency_overrides[admin_router.get_admin_query_policy] = lambda: PROPOSED_POLICY
    response = audit(pg)
    assert response.status_code == 503 and "items" not in response.json()
    assert pg.count() == 1


def test_pg_statement_timeout_is_503_proposed(pg):
    pg.app.dependency_overrides[admin_router.get_admin_query_policy] = lambda: AdminQueryPolicy(statement_timeout_ms=200)
    locker = psycopg.connect(os.environ["T16_TEST_ADMIN_URL"])
    try:
        locker.execute("LOCK TABLE career.audit_events IN ACCESS EXCLUSIVE MODE")
        started = time.monotonic()
        response = audit(pg)
        assert response.status_code == 503 and response.json()["code"] == "DEPENDENCY_UNAVAILABLE"
        assert time.monotonic() - started < 4
    finally:
        locker.rollback()
        locker.close()


def test_pg_missing_select_privilege_is_a_server_error_without_details(pg):
    pg.db.execute(sql.SQL("REVOKE SELECT ON career.audit_events FROM {}").format(sql.Identifier(pg.role)))
    client = TestClient(pg.app, base_url="https://testserver", raise_server_exceptions=False)
    response = client.get(AUDIT, headers=pg.h[ADMIN], params=WINDOW)
    assert response.status_code == 500 and response.json()["code"] == "INTERNAL_ERROR"
    assert "permission" not in response.text.lower() and "audit_events" not in response.text


# ---------------------------------------------------------------- AI usage
def usage_rows(pg, rows):
    """rows: (occurred_at, user_id, feature, model, in, out, cost)"""
    with pg.db.cursor() as cur:
        cur.executemany("INSERT INTO career.ai_usage_records(occurred_at, user_id, feature_code, provider_model, "
                        "input_tokens, output_tokens, estimated_cost_usd) VALUES (%s,%s,%s,%s,%s,%s,%s)", rows)


def kst(day, hour, minute=0, micro=0):
    return datetime(2026, 11, day, hour, minute, 0, micro, tzinfo=UTC) - timedelta(hours=9)


def test_pg_usage_empty_and_header(pg):
    response = get(pg, USAGE, **{"from": "2026-11-01", "to": "2026-11-07"})
    assert response.status_code == 200 and response.json() == []
    assert response.headers["x-ai-cost-status"] == "unverified"


def test_pg_usage_sql_aggregation_kst_boundaries_and_withdrawn_users(pg):
    usage_rows(pg, [
        (kst(1, 0), ADMIN, "document_analysis", "model-a", 100, 10, "0.100000"),
        (kst(1, 23, 59, 999999), None, "rag_answer", "model-a", 200, 20, "0.200000"),   # withdrawn user
        (kst(2, 0), SEEKER, "rag_answer", "model-b", 300, 30, "0.300001"),
        (kst(7, 23, 59), None, "agent", "model-b", 400, 40, "0.000000"),
        (kst(8, 0), ADMIN, "agent", "model-b", 999, 999, "9.000000"),                    # outside
        (kst(1, 0) - timedelta(microseconds=1), ADMIN, "agent", "model-b", 999, 999, "9.000000"),  # outside
    ])
    params = {"from": "2026-11-01", "to": "2026-11-07"}
    day = get(pg, USAGE, **params).json()
    for b in day:
        contract("AiUsageBucket").validate(b)
    assert [(b["key"], b["request_count"], b["input_tokens"]) for b in day] == [
        ("2026-11-01", 2, 300), ("2026-11-02", 1, 300), ("2026-11-07", 1, 400)]
    feature = {b["key"]: b for b in get(pg, USAGE, group_by="feature_code", **params).json()}
    assert feature["rag_answer"]["estimated_cost_usd"] == 0.500001 and feature["rag_answer"]["output_tokens"] == 50
    model = {b["key"]: b["request_count"] for b in get(pg, USAGE, group_by="provider_model", **params).json()}
    assert model == {"model-a": 2, "model-b": 2}
    response = get(pg, USAGE, group_by="feature_code", **params)
    assert str(ADMIN) not in response.text and str(SEEKER) not in response.text
    assert get(pg, USAGE, **{"from": "2026-11-08", "to": "2026-11-07"}).status_code == 422


def test_pg_d2_zero_and_null_distinguished_on_a_simulated_nullable_column_proposed(pg):
    # 일회용 DB 안에서만 D2-A 를 흉내 낸다 (실제 Migration 아님).
    pg.db.execute("ALTER TABLE career.ai_usage_records ALTER COLUMN estimated_cost_usd DROP NOT NULL, "
                  "ALTER COLUMN estimated_cost_usd DROP DEFAULT")
    boundary = kst(3, 0)
    usage_rows(pg, [
        (kst(2, 12), None, "agent", "m", 1, 1, "0.000000"),      # before boundary → unknown, not free
        (kst(3, 12), None, "agent", "m", 1, 1, "0.000000"),      # recorded free
        (kst(4, 12), None, "agent", "m", 1, 1, None),            # unrecorded
        (kst(5, 12), None, "agent", "m", 1, 1, "0.250000"),
    ])
    with Session(pg.engine) as db:
        service = AdminAuditService(SqlAdminAuditRepository(db), ListCursor(derive_cursor_key(TEST_SECRET)),
                                    PROPOSED_POLICY)
        report = service.usage_report_proposed(ADMIN, date(2026, 11, 1), date(2026, 11, 7), "day", boundary)
        no_d2 = service.usage_report_proposed(ADMIN, date(2026, 11, 1), date(2026, 11, 7), "day")
    assert report.totals.request_count == 4 and report.totals.unpriced_request_count == 2
    assert report.totals.estimated_cost_usd == 0.25
    by_day = {b.key: (b.estimated_cost_usd, b.unpriced_request_count) for b in report.buckets}
    assert by_day == {"2026-11-02": (None, 1), "2026-11-03": (0.0, 0), "2026-11-04": (None, 1),
                      "2026-11-05": (0.25, 0)}
    assert no_d2.totals.estimated_cost_usd is None and no_d2.totals.unpriced_request_count == 4
    confirmed = get(pg, USAGE, **{"from": "2026-11-01", "to": "2026-11-07"})
    assert confirmed.status_code == 500, "confirmed contract cannot carry NULL cost; never shown as 0"


def test_pg_usage_requires_no_write_privilege(pg):
    grants = {r[0] for r in pg.q("SELECT privilege_type FROM information_schema.role_table_grants "
                                 "WHERE grantee=%s AND table_name='ai_usage_records'", pg.role)}
    assert grants == {"SELECT"}
