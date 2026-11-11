"""T142 제안 DDL을 일회용 PostgreSQL에 적용해 제약을 확인한다(승인 전 migration 아님).

`T142_ADMIN_URL`(관리자 접속, 예: postgresql://user@127.0.0.1:55496/postgres)이 있을 때만 실행.
매번 `t142_ddl_<임의>` DB를 새로 만들고 끝나면 지운다. 공유·Staging DB에는 접속하지 않는다.
"""

import os
import secrets
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")
ADMIN_URL = os.environ.get("T142_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="T142_ADMIN_URL not set (disposable PostgreSQL only)")
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ["0001_initial_schema.sql", "0002_deletion_request_unscheduled.sql",
              "0003_market_metric_skill_dimension.sql"]


@pytest.fixture
def db():
    host = ADMIN_URL.split("@", 1)[-1].split("/", 1)[0]
    assert host.split(":")[0] in {"127.0.0.1", "localhost"}, "loopback only"
    name = f"t142_ddl_{secrets.token_hex(4)}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = ADMIN_URL.rsplit("/", 1)[0] + "/" + name
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE SCHEMA career")
            for m in MIGRATIONS:
                conn.execute((ROOT / "database" / "migrations" / m).read_text(encoding="utf-8"))
            conn.execute((ROOT / "database" / "proposed" / "T142_personal_data_requests.sql").read_text(encoding="utf-8"))
            yield conn
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def user(conn, n):
    uid = uuid.uuid4()
    conn.execute("INSERT INTO career.users (user_id, email, email_canonical, display_name) VALUES (%s, %s, %s, 'u')",
                 (uid, f"synthetic{n}@example.com", f"synthetic{n}@example.com"))
    return uid


def req(conn, uid, status="received", **extra):
    cols = {"user_id": uid, "request_type": "export", "status": status, **extra}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return conn.execute(f"INSERT INTO career.data_subject_requests ({names}) VALUES ({marks}) RETURNING request_id",
                        list(cols.values())).fetchone()[0]


def rejects(conn, sql, params=()):
    with pytest.raises(psycopg.errors.IntegrityError):
        with conn.transaction():
            conn.execute(sql, params)


def test_one_open_request_per_type(db):
    uid = user(db, 1)
    req(db, uid)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            req(db, uid)
    req(db, uid, request_type="erasure")                                   # 다른 유형은 허용
    db.execute("UPDATE career.data_subject_requests SET status='cancelled' WHERE request_type='export'")
    req(db, uid)                                                           # 닫힌 뒤 새 요청 허용


def test_reason_required_and_officer_not_requester(db):
    uid = user(db, 2)
    rejects(db, "INSERT INTO career.data_subject_requests (user_id, request_type, status) VALUES (%s,'export','failed')",
            (uid,))
    rejects(db, "INSERT INTO career.data_subject_requests (user_id, request_type, status, reason_code, handled_by) "
                "VALUES (%s,'export','rejected','legal_hold',%s)", (uid, uid))
    rejects(db, "INSERT INTO career.data_subject_requests (user_id, request_type, status) VALUES (%s,'bogus','received')",
            (uid,))
    rejects(db, "INSERT INTO career.data_subject_requests (user_id, request_type, status, attempts) "
                "VALUES (%s,'export','received',4)", (uid,))


def test_completed_export_must_expire_within_24h(db):
    uid = user(db, 3)
    rejects(db, "INSERT INTO career.data_subject_requests (user_id, request_type, status, completed_at) "
                "VALUES (%s,'export','completed',now())", (uid,))
    rejects(db, "INSERT INTO career.data_subject_requests (user_id, request_type, status, completed_at, expires_at) "
                "VALUES (%s,'export','completed',now(),now()+interval '25 hours')", (uid,))
    req(db, uid, status="completed", completed_at="2026-11-11T00:00:00Z", expires_at="2026-11-12T00:00:00Z")


def test_tokens_are_hashes_short_lived_and_one_live_link(db):
    uid = user(db, 4)
    sid = db.execute("INSERT INTO career.auth_sessions (user_id, refresh_token_hash, expires_at) "
                     "VALUES (%s, %s, now()+interval '1 day') RETURNING session_id", (uid, "e" * 64)).fetchone()[0]
    rejects(db, "INSERT INTO career.data_reauth_grants (token_hash, user_id, session_id, expires_at) "
                "VALUES ('plain-token', %s, %s, now()+interval '5 minutes')", (uid, sid))
    rejects(db, "INSERT INTO career.data_reauth_grants (token_hash, user_id, session_id, expires_at) "
                "VALUES (%s, %s, %s, now()+interval '11 minutes')", ("1" * 64, uid, sid))
    db.execute("INSERT INTO career.data_reauth_grants (token_hash, user_id, session_id, expires_at) "
               "VALUES (%s, %s, %s, now()+interval '10 minutes')", ("1" * 64, uid, sid))
    rid = req(db, uid, status="completed", completed_at="2026-11-11T00:00:00Z", expires_at="2026-11-12T00:00:00Z")
    db.execute("INSERT INTO career.data_export_downloads (token_hash, request_id, expires_at) "
               "VALUES (%s, %s, now()+interval '10 minutes')", ("2" * 64, rid))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            db.execute("INSERT INTO career.data_export_downloads (token_hash, request_id, expires_at) "
                       "VALUES (%s, %s, now()+interval '10 minutes')", ("3" * 64, rid))
    # 세션 폐기(삭제) → 재인증 허가도 사라진다
    db.execute("DELETE FROM career.auth_sessions WHERE session_id = %s", (sid,))
    assert db.execute("SELECT count(*) FROM career.data_reauth_grants").fetchone()[0] == 0


def test_user_deletion_anonymizes_request_history(db):
    uid = user(db, 5)
    rid = req(db, uid, status="cancelled")
    db.execute("DELETE FROM career.users WHERE user_id = %s", (uid,))
    row = db.execute("SELECT user_id, status FROM career.data_subject_requests WHERE request_id = %s", (rid,)).fetchone()
    assert row == (None, "cancelled")
