"""T73 actual PostgreSQL tests: quality report, retention purge, withdrawal/account deletion propagation.

Reuses the T72 `behavior_pg` fixture (T16 disposable DB, 0001 schema, synthetic users A/B, behavior_tracking v1).
Opt-in only: T16_ISOLATED_DB_TEST=YES and T16_TEST_ADMIN_URL -> loopback t16_profile_test.
"""
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg import Rollback, errors as pg_errors, sql
from sqlalchemy import event as sa_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.behavior_data import AUDIT_ACTION, purge_expired, run_quality_check
from app.core.errors import AppError
from app.repositories.privacy import SqlPrivacyRepository
from app.schemas.privacy import OptionalConsentInput
from app.services.privacy import PrivacyService
from tests.test_behavior_events_postgres import PATH, A, B, behavior_pg, body, consent, count  # noqa: F401
from tests.test_privacy_postgres import MIGRATION as MIGRATION_0002
from tests.test_profile_postgres import pg_app  # noqa: F401

AS_OF = datetime.now(UTC)


def quality(engine, as_of=None):
    with Session(engine) as db:
        return run_quality_check(db, as_of=as_of or datetime.now(UTC))


def raw_event(admin, user, code="page.view", at=None, metadata=None):
    admin.execute("INSERT INTO career.behavior_events(event_id,user_id,event_code,event_at,metadata) "
                  "VALUES(%s,%s,%s,%s,%s)",
                  (uuid4(), user, code, at or datetime.now(UTC), None if metadata is None else json.dumps(metadata)))


def errors_of(report):
    return {k: v for k, v in report.counts.items() if v and k not in ("total_events",)}


# ------------------------------------------------------------------------------- quality

def test_quality_clean_after_api_collection_and_duplicate_resend(behavior_pg):
    client, engine, admin, h = behavior_pg
    assert quality(engine).status == "PASS" and quality(engine).counts["total_events"] == 0
    consent(True, client=client, headers=h)
    payload = body()
    assert client.post(PATH, headers=h, json=payload).status_code == 201
    assert client.post(PATH, headers=h, json=payload).json()["status"] == "duplicate"
    report = quality(engine)
    assert report.status == "PASS" and report.counts["total_events"] == 1 and report.errors == 0


def test_quality_detects_each_contract_violation_without_exposing_rows(behavior_pg):
    client, engine, admin, h = behavior_pg
    consent(True, client=client, headers=h)
    time.sleep(0.01)
    now = datetime.now(UTC)
    raw_event(admin, A, "page.scroll")                                                  # unknown code
    raw_event(admin, A, "recommendation.click", metadata={"recommendation_id": "r1"})  # unapproved
    raw_event(admin, A, "search.submit", metadata={"search_type": "python backend"})   # sentence
    raw_event(admin, A, "search.submit", metadata={"query": "python"})                 # disallowed key
    raw_event(admin, A, "page.view", metadata={"page_id": {"nested": 1}})              # nested
    raw_event(admin, A, "page.view", metadata=["home"])                                 # not an object
    raw_event(admin, A, "page.view", metadata={})                                       # empty object
    raw_event(admin, A, "page.view", metadata={"page_id": "x" * 1100})                  # > 1KB (and invalid value)
    raw_event(admin, A, "page.view", metadata={f"k{i}": 1 for i in range(11)})          # > 10 keys
    raw_event(admin, A, "page.view", at=now + timedelta(hours=1))                       # future
    raw_event(admin, B, "page.view")                                                    # no consent at all
    raw_event(admin, A, "page.view", at=now - timedelta(days=30))                       # before consent
    report = quality(engine, as_of=now)
    c = report.counts
    assert c["total_events"] == 12 and report.status == "FAIL"
    assert (c["unknown_event_code"], c["unapproved_event_code"]) == (1, 1)
    assert c["metadata_value_invalid"] == 3          # sentence, nested, 1KB string
    assert c["metadata_key_not_allowed"] == 2        # query, k0..k10
    assert (c["metadata_not_object"], c["metadata_empty_object"]) == (1, 1)
    assert (c["metadata_too_large"], c["metadata_too_many_keys"]) == (1, 1)
    assert c["event_at_future"] == 1
    assert c["no_consent_at_event_time"] == 2        # B, A 30 days before consent (page.scroll is not tracking)
    assert c["retained_without_current_consent"] == 1   # B only
    assert (c["duplicate_storage_key"], c["missing_required"], c["orphan_user"]) == (0, 0, 0)
    text = report.to_json()
    assert str(A) not in text and str(B) not in text and "python" not in text and "nested" not in text


def test_old_valid_events_are_not_flagged_by_the_collection_window(behavior_pg):
    _, engine, admin, _ = behavior_pg
    old = datetime.now(UTC) - timedelta(days=60)
    admin.execute("INSERT INTO career.user_consents(user_id,policy_code,policy_version,granted,recorded_at) "
                  "VALUES(%s,'behavior_tracking','v1',true,%s)", (A, old - timedelta(days=1)))
    raw_event(admin, A, "page.view", at=old, metadata={"page_id": "home"})
    report = quality(engine)
    assert report.status == "PASS" and report.counts["total_events"] == 1


@pytest.mark.parametrize("stmt,params,error", [
    ("INSERT INTO career.behavior_events(event_id,user_id,event_code,event_at) VALUES(%s,%s,NULL,now())",
     lambda: (uuid4(), A), pg_errors.NotNullViolation),
    ("INSERT INTO career.behavior_events(event_id,user_id,event_code,event_at) VALUES(%s,NULL,'page.view',now())",
     lambda: (uuid4(),), pg_errors.NotNullViolation),
    ("INSERT INTO career.behavior_events(event_id,user_id,event_code,event_at) VALUES(%s,%s,'page.view',now())",
     lambda: (uuid4(), uuid4()), pg_errors.ForeignKeyViolation),
])
def test_missing_and_orphan_rows_are_rejected_by_the_database(behavior_pg, stmt, params, error):
    _, engine, admin, _ = behavior_pg
    with pytest.raises(error):
        admin.execute(stmt, params())
    assert quality(engine).counts["total_events"] == 0


def test_duplicate_storage_key_is_rejected_by_primary_key(behavior_pg):
    _, engine, admin, _ = behavior_pg
    key = uuid4()
    admin.execute("INSERT INTO career.behavior_events(event_id,user_id,event_code,event_at) VALUES(%s,%s,'page.view',now())", (key, A))
    with pytest.raises(pg_errors.UniqueViolation):
        admin.execute("INSERT INTO career.behavior_events(event_id,user_id,event_code,event_at) VALUES(%s,%s,'page.view',now())", (key, A))
    assert quality(engine).counts["duplicate_storage_key"] == 0


def test_quality_check_is_read_only(behavior_pg):
    _, engine, admin, _ = behavior_pg
    raw_event(admin, B, "page.view")
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().split()[0].upper())
    sa_event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as db:
            run_quality_check(db, as_of=AS_OF)
            assert not db.in_transaction()
    finally:
        sa_event.remove(engine, "before_cursor_execute", record)
    assert statements[0] == "SET" and not {"INSERT", "UPDATE", "DELETE"} & set(statements)
    assert count(admin, B) == 1


# ------------------------------------------------------------------------------- retention

def audit_rows(admin):
    return admin.execute("SELECT resource_id, request_id FROM career.audit_events WHERE action_code=%s ORDER BY occurred_at",
                         (AUDIT_ACTION,)).fetchall()


@pytest.fixture
def retention_rows(behavior_pg):
    _, engine, admin, _ = behavior_pg
    as_of = datetime.now(UTC)
    cutoff = as_of - timedelta(days=187)
    raw_event(admin, A, at=cutoff - timedelta(seconds=1), metadata={"page_id": "expired_a"})
    raw_event(admin, B, at=cutoff - timedelta(days=10), metadata={"page_id": "expired_b"})
    raw_event(admin, A, at=cutoff + timedelta(seconds=1), metadata={"page_id": "kept_boundary"})
    raw_event(admin, A, at=as_of - timedelta(days=1), metadata={"page_id": "recent"})
    return engine, admin, as_of


def remaining_pages(admin):
    return sorted(r[0] for r in admin.execute("SELECT metadata->>'page_id' FROM career.behavior_events").fetchall())


def test_retention_dry_run_deletes_nothing_and_writes_no_audit(retention_rows):
    engine, admin, as_of = retention_rows
    with Session(engine) as db:
        result = purge_expired(db, as_of=as_of, retention_days=180)
    assert (result.dry_run, result.target, result.deleted, result.status) == (True, 2, 0, "PASS")
    assert len(remaining_pages(admin)) == 4 and audit_rows(admin) == []


def test_retention_purge_deletes_only_expired_is_audited_and_idempotent(retention_rows):
    engine, admin, as_of = retention_rows
    with Session(engine) as db:
        first = purge_expired(db, as_of=as_of, retention_days=180, dry_run=False)
    assert (first.target, first.deleted, first.remaining_expired, first.status, first.audit_recorded) == (2, 2, 0, "PASS", True)
    assert remaining_pages(admin) == ["kept_boundary", "recent"]
    assert [str(r[0]) for r in audit_rows(admin)] == [first.run_id]
    with Session(engine) as db:
        again = purge_expired(db, as_of=as_of, retention_days=180, dry_run=False)
    assert (again.target, again.deleted, again.status) == (0, 0, "PASS")
    assert remaining_pages(admin) == ["kept_boundary", "recent"] and len(audit_rows(admin)) == 2
    assert engine.pool.checkedout() == 0


def test_retention_audit_failure_rolls_back_the_delete(retention_rows):
    engine, admin, as_of = retention_rows
    admin.execute(sql.SQL("REVOKE INSERT ON career.audit_events FROM {}").format(sql.Identifier(engine.url.username)))
    with Session(engine) as db:
        result = purge_expired(db, as_of=as_of, retention_days=180, dry_run=False)
    assert (result.status, result.deleted, result.audit_recorded) == ("FAIL", 0, False)
    assert result.reason_code.startswith("PURGE_FAILED_") and result.remaining_expired == 2
    assert len(remaining_pages(admin)) == 4 and audit_rows(admin) == []


def test_retention_delete_failure_rolls_back(retention_rows):
    engine, admin, as_of = retention_rows

    def fail_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM career.behavior_events"):
            raise IntegrityError(statement, parameters, RuntimeError("synthetic delete failure"))
    sa_event.listen(engine, "before_cursor_execute", fail_delete)
    try:
        with Session(engine) as db:
            result = purge_expired(db, as_of=as_of, retention_days=180, dry_run=False)
    finally:
        sa_event.remove(engine, "before_cursor_execute", fail_delete)
    assert (result.status, result.deleted) == ("FAIL", 0) and len(remaining_pages(admin)) == 4


# ------------------------------------------------------------------------------- withdrawal (T72/T31 path)

def test_withdrawal_delete_failure_rolls_back_the_consent_change(behavior_pg):
    client, engine, admin, h = behavior_pg
    consent(True, client=client, headers=h)
    assert client.post(PATH, headers=h, json=body()).status_code == 201

    def fail_delete(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("DELETE FROM career.behavior_events"):
            raise IntegrityError(statement, parameters, RuntimeError("synthetic withdrawal delete failure"))
    sa_event.listen(engine, "before_cursor_execute", fail_delete)
    try:
        with Session(engine) as db, pytest.raises(AppError) as exc:
            PrivacyService(SqlPrivacyRepository(db)).record_consent(
                A, OptionalConsentInput(policy_code="behavior_tracking", policy_version="v1", granted=False))
    finally:
        sa_event.remove(engine, "before_cursor_execute", fail_delete)
    assert exc.value.status == 503
    latest = admin.execute("SELECT granted FROM career.user_consents WHERE user_id=%s AND policy_code='behavior_tracking' "
                           "ORDER BY recorded_at DESC LIMIT 1", (A,)).fetchone()[0]
    assert latest is True and count(admin) == 1      # 동의 변경과 삭제가 함께 롤백


def test_repeated_withdrawal_leaves_zero_even_for_rows_written_around_the_api(behavior_pg):
    client, engine, admin, h = behavior_pg
    consent(True, client=client, headers=h)
    assert client.post(PATH, headers=h, json=body()).status_code == 201
    consent(False, client=client, headers=h)
    assert count(admin) == 0
    raw_event(admin, A, "page.view")                 # 앱을 우회해 남은 행 가정
    assert quality(engine).counts["retained_without_current_consent"] == 1
    consent(False, client=client, headers=h)         # 같은 철회 반복 → 이력은 그대로, 잔존 행 삭제
    assert count(admin) == 0
    assert admin.execute("SELECT count(*) FROM career.user_consents WHERE user_id=%s AND granted=false", (A,)).fetchone()[0] == 1
    assert quality(engine).status == "PASS"


def test_withdrawal_and_reconsent_flow_keeps_other_users_and_blocks_replay(behavior_pg):
    client, engine, admin, h = behavior_pg
    assert client.post(PATH, headers=h, json=body()).json()["status"] == "blocked_no_consent" and count(admin) == 0
    consent(True, client=client, headers=h)
    consent(True, user=B, engine=engine)
    old = body()
    assert client.post(PATH, headers=h, json=old).status_code == 201
    raw_event(admin, B, "page.view", metadata={"page_id": "b"})
    consent(False, client=client, headers=h)
    assert (count(admin), count(admin, B)) == (0, 1)
    assert client.post(PATH, headers=h, json=body()).json()["status"] == "blocked_no_consent"
    time.sleep(0.05)
    consent(True, client=client, headers=h)
    assert client.post(PATH, headers=h, json=old).json()["status"] == "blocked_no_consent"
    assert client.post(PATH, headers=h, json=body()).status_code == 201
    assert (count(admin), count(admin, B)) == (1, 1)
    assert quality(engine).status == "PASS"


# ------------------------------------------------------------------------------- account deletion

def test_deletion_request_disables_account_and_blocks_new_events(behavior_pg):
    client, engine, admin, h = behavior_pg
    admin.execute(MIGRATION_0002.read_text(encoding="utf-8"))   # T31 탈퇴 접수 전제 (test_privacy_postgres와 동일)
    consent(True, client=client, headers=h)
    assert client.post(PATH, headers=h, json=body()).status_code == 201
    r = client.post("/api/v1/me/deletion-request", headers=h, json={"confirmation": "DELETE"})
    assert r.status_code == 202
    assert admin.execute("SELECT status FROM career.users WHERE user_id=%s", (A,)).fetchone()[0] == "disabled"
    assert client.post(PATH, headers=h, json=body()).status_code == 401
    # 탈퇴 요청은 비활성화일 뿐 물리 삭제가 아니다: 기존 이벤트는 물리 삭제(D-06, 미확정) 때까지 남는다
    assert count(admin) == 1


def test_physical_user_delete_cascades_events_and_consents_only_for_that_user(behavior_pg):
    client, engine, admin, h = behavior_pg
    consent(True, client=client, headers=h)
    consent(True, user=B, engine=engine)
    assert client.post(PATH, headers=h, json=body()).status_code == 201
    raw_event(admin, B, "page.view", metadata={"page_id": "b"})
    with admin.transaction():                         # 실패해 롤백된 물리 삭제는 아무것도 지우지 않는다
        admin.execute("DELETE FROM career.users WHERE user_id=%s", (A,))
        assert count(admin) == 0
        raise Rollback()
    assert count(admin) == 1
    admin.execute("DELETE FROM career.users WHERE user_id=%s", (A,))
    assert count(admin) == 0
    assert admin.execute("SELECT count(*) FROM career.user_consents WHERE user_id=%s", (A,)).fetchone()[0] == 0
    assert (count(admin, B), admin.execute("SELECT count(*) FROM career.user_consents WHERE user_id=%s", (B,)).fetchone()[0]) == (1, 1)
    assert quality(engine).status == "PASS"
