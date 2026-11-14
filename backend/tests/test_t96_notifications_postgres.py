"""T96 알림 outbox — 일회용 PostgreSQL 18 + migration 0005(T96·T97) + 최소 권한 앱 역할.

실제 메일 공급자·외부 호출 없음(Mock 공급자). 공유 Staging DB 에는 적용하지 않습니다.
"""
import json
import os
import threading
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import create_engine

from app.db import sqlalchemy_url
from sqlalchemy.orm import sessionmaker

from app.repositories.notifications import SqlNotificationOutbox, SqlRecipientDirectory
from app.services.notifications import (
    BACKOFF,
    LEASE,
    SPECS,
    MockNotificationProvider,
    NotificationDispatcher,
    NotificationEvent,
    NotificationWorker,
)
from tests.security.security_pg import ROOT, USER_A, USER_B, disposable_pg, requires_pg
from tests.test_t96_notifications import APPROVED, DAY, KST, VARS, Clock

pytestmark = requires_pg
DDL = (ROOT / "database/migrations/0005_notifications.sql").read_text(encoding="utf-8")
# 제안 동의 코드는 이 일회용 DB 에만 넣음(Seed 미변경)
POLICIES = ("INSERT INTO career.consent_policies(policy_code, version, is_required, content_url, effective_at) "
            "SELECT c, 'proposal-1', false, 'https://example.invalid/policy', now() "
            "FROM unnest(ARRAY['service_updates','recommendation_alerts','marketing_notification']) c")
EMAIL_A = "t86-a@example.invalid"


@pytest.fixture
def pg(monkeypatch):
    for ctx in disposable_pg(monkeypatch, write_tables=("notification_deliveries",), extra_sql=(DDL, POLICIES)):
        engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]), pool_size=10)
        try:
            yield ctx, sessionmaker(engine)
        finally:
            engine.dispose()


def wire(factory, clock, script=()):
    session = factory()
    outbox, directory = SqlNotificationOutbox(session), SqlRecipientDirectory(session)
    provider = MockNotificationProvider(list(script))
    return (NotificationDispatcher(outbox, directory, APPROVED, clock),
            NotificationWorker(outbox, directory, provider, APPROVED, clock), provider, session)


def consent(admin, user, code, granted):
    admin.execute("INSERT INTO career.user_consents(user_id, policy_code, policy_version, granted, recorded_at) "
                  "VALUES (%s, %s, 'proposal-1', %s, clock_timestamp())", (user, code, granted))


def rows(admin):
    return admin.execute("SELECT notification_type, status, attempts, last_error_code, user_id "
                         "FROM career.notification_deliveries ORDER BY created_at, notification_type").fetchall()


def test_ddl_constraints_and_app_role_privileges(pg):
    ctx, factory = pg
    admin = ctx.db
    bad = [("status", "'done'"), ("channel", "'sms'"), ("attempts", "11"), ("variables", "'[]'")]
    for column, value in bad:
        with pytest.raises(psycopg.errors.CheckViolation):
            admin.execute(f"INSERT INTO career.notification_deliveries(notification_type, dedupe_key, template_code, "
                          f"template_version, {column}) VALUES ('x', repeat('a', 64), 'x', '1', {value})")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin.execute("INSERT INTO career.notification_deliveries(notification_type, dedupe_key, template_code, "
                      "template_version) VALUES ('x', repeat('A', 64), 'x', '1')")
    with pytest.raises(psycopg.errors.CheckViolation):    # sent 인데 sent_at 없음
        admin.execute("INSERT INTO career.notification_deliveries(notification_type, dedupe_key, template_code, "
                      "template_version, status) VALUES ('x', repeat('a', 64), 'x', '1', 'sent')")
    with factory() as s, pytest.raises(Exception, match="permission denied"):   # 앱 역할은 users 를 못 바꿈
        s.execute(__import__("sqlalchemy").text("UPDATE career.users SET status='disabled'"))


def test_end_to_end_consent_latest_row_retry_and_success(pg):
    ctx, factory = pg
    clock = Clock(DAY)
    dispatcher, worker, provider, _ = wire(factory, clock, ["transient"])
    assert dispatcher.enqueue(NotificationEvent(USER_A, "marketing.newsletter", "", VARS["marketing.newsletter"])) == \
        "blocked_consent"                                                      # 기본 끔
    consent(ctx.db, USER_A, "marketing_notification", True)
    assert dispatcher.enqueue(NotificationEvent(USER_A, "marketing.newsletter", "", VARS["marketing.newsletter"])) == "queued"
    consent(ctx.db, USER_A, "marketing_notification", False)               # 최신 행 = 철회
    assert dispatcher.enqueue(NotificationEvent(USER_A, "marketing.newsletter", "n2", VARS["marketing.newsletter"])) == \
        "blocked_consent"
    assert worker.run().cancelled == 1                                         # 대기열도 발송 직전 취소 (T95 §3-2)

    assert dispatcher.enqueue(NotificationEvent(USER_A, "security.password_changed", "", VARS["security.password_changed"])) == \
        "queued"                                                              # 필수 — 마케팅 철회와 무관
    assert worker.run().retried == 1
    clock.at = DAY + BACKOFF[0]
    assert worker.run().sent == 1
    assert [r[:4] for r in rows(ctx.db)] == [("marketing.newsletter", "cancelled", 0, "consent_withdrawn"),
                                                ("security.password_changed", "sent", 2, None)]
    assert provider.sent[0].to == EMAIL_A


def test_concurrent_enqueue_of_the_same_event_creates_one_row(pg):
    ctx, factory = pg
    clock, barrier, results = Clock(DAY), threading.Barrier(8), []

    def go():
        dispatcher, *_ , session = wire(factory, clock)
        barrier.wait()
        results.append(dispatcher.enqueue(NotificationEvent(USER_A, "security.new_login", "login-1",
                                                             VARS["security.new_login"])))
        session.close()

    threads = [threading.Thread(target=go) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["duplicate"] * 7 + ["queued"]
    assert len(rows(ctx.db)) == 1


def test_concurrent_workers_never_claim_the_same_row(pg):
    ctx, factory = pg
    clock = Clock(DAY)
    dispatcher, *_ = wire(factory, clock)
    for i in range(40):
        user = USER_A if i % 2 else USER_B
        assert dispatcher.enqueue(NotificationEvent(user, "security.new_login", f"l{i}", VARS["security.new_login"])) == "queued"
    barrier, sent = threading.Barrier(4), []

    def go():
        _, worker, provider, session = wire(factory, clock)
        worker.batch = 15
        barrier.wait()
        worker.run()
        sent.extend(m.delivery_id for m in provider.sent)
        session.close()

    threads = [threading.Thread(target=go) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sent) == len(set(sent)) == 40
    assert {r[1] for r in rows(ctx.db)} == {"sent"}


def test_crash_recovery_quiet_hours_and_deleted_user(pg):
    ctx, factory = pg
    night = DAY.replace(hour=23)
    clock = Clock(night)
    consent(ctx.db, USER_B, "service_updates", True)
    dispatcher, worker, provider, session = wire(factory, clock)
    dispatcher.enqueue(NotificationEvent(USER_A, "security.new_login", "", VARS["security.new_login"]))
    dispatcher.enqueue(NotificationEvent(USER_B, "service.maintenance", "", VARS["service.maintenance"]))
    morning = (night + timedelta(days=1)).replace(hour=8)
    assert ctx.db.execute("SELECT next_attempt_at FROM career.notification_deliveries "
                             "WHERE notification_type='service.maintenance'").fetchone()[0] == morning

    claimed = SqlNotificationOutbox(session).claim_due(night, 10, night + LEASE)      # 꺼낸 뒤 중단
    assert [c.type for c in claimed] == ["security.new_login"]
    assert worker.run().sent == 0
    clock.at = night + LEASE
    assert worker.run().sent == 1                                                     # 점유 만료 후 회수

    ctx.db.execute("DELETE FROM career.users WHERE user_id = %s", (USER_B,))      # 일회용 DB 의 합성 사용자
    assert [r[4] for r in rows(ctx.db)] == [USER_A, None]                             # B 행은 SET NULL (ANONYMIZE)
    clock.at = morning
    assert worker.run().cancelled == 1 and len(provider.sent) == 1


def test_stored_rows_hold_no_address_link_or_body(pg):
    ctx, factory = pg
    dispatcher, worker, provider, _ = wire(factory, Clock(DAY))
    dispatcher.enqueue(NotificationEvent(USER_A, "security.password_changed", "", VARS["security.password_changed"]))
    worker.run()
    dump = json.dumps([list(map(str, r)) for r in ctx.db.execute(
        "SELECT * FROM career.notification_deliveries").fetchall()], ensure_ascii=False)
    body = provider.sent[0].body
    assert EMAIL_A not in dump and "t86-a" not in dump and body not in dump and "http" not in dump


def test_purge_by_retention_only_touches_finished_rows(pg):
    ctx, factory = pg
    clock = Clock(DAY)
    consent(ctx.db, USER_A, "marketing_notification", True)
    dispatcher, worker, _, session = wire(factory, clock)
    dispatcher.enqueue(NotificationEvent(USER_A, "marketing.newsletter", "", VARS["marketing.newsletter"]))
    dispatcher.enqueue(NotificationEvent(USER_A, "security.password_changed", "", VARS["security.password_changed"]))
    worker.run()
    dispatcher.enqueue(NotificationEvent(USER_A, "service.policy_change", "", VARS["service.policy_change"]))
    removed = SqlNotificationOutbox(session).purge_expired(DAY + timedelta(days=91),
                                                           {k: s.retention for k, s in SPECS.items()})
    assert removed == 1
    assert sorted(r[0] for r in rows(ctx.db)) == ["security.password_changed", "service.policy_change"]
