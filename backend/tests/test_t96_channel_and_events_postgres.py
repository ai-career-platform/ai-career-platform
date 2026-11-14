"""T96 후속 — in_app 행은 메일 worker 가 꺼내지 않고 바로 알림함에 보임 (일회용 PostgreSQL 18 + migration 0005).

실제 메일 공급자·외부 호출 없음(Mock 공급자). 공유 Staging DB 에는 적용하지 않습니다.
in_app 유형은 T95 매트릭스에 아직 없으므로 시험 전용 spec(채널만 in_app)으로 검증합니다.
"""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import sqlalchemy_url
from app.repositories.notification_inbox import SqlNotificationInboxRepository
from app.repositories.notifications import SqlNotificationOutbox, SqlRecipientDirectory
from app.services.notification_inbox import TYPES
from app.services.notifications import (
    LEASE,
    MockNotificationProvider,
    NotificationDispatcher,
    NotificationEvent,
    NotificationWorker,
)
from tests.security.security_pg import ROOT, USER_A, disposable_pg, requires_pg
from tests.test_t96_channel_and_events import IN_APP_SPECS
from tests.test_t96_notifications import APPROVED, DAY, VARS, Clock

pytestmark = requires_pg
DDL = (ROOT / "database/migrations/0005_notifications.sql").read_text(encoding="utf-8")


@pytest.fixture
def pg(monkeypatch):
    for ctx in disposable_pg(monkeypatch, write_tables=("notification_deliveries", "notification_preferences"),
                             extra_sql=(DDL,)):
        engine = create_engine(sqlalchemy_url(os.environ["DATABASE_URL"]))
        try:
            yield ctx, sessionmaker(engine)
        finally:
            engine.dispose()


def test_in_app_rows_go_straight_to_the_inbox_and_are_never_mailed(pg):
    ctx, factory = pg
    night = DAY.replace(hour=23)
    clock = Clock(night)
    session = factory()
    outbox, directory, inbox = SqlNotificationOutbox(session), SqlRecipientDirectory(session), \
        SqlNotificationInboxRepository(session)
    provider = MockNotificationProvider()
    dispatcher = NotificationDispatcher(outbox, directory, APPROVED, clock, specs=IN_APP_SPECS, preferences=inbox)
    worker = NotificationWorker(outbox, directory, provider, APPROVED, clock, specs=IN_APP_SPECS)

    event = NotificationEvent(USER_A, "service.maintenance", "m-1", VARS["service.maintenance"])
    assert dispatcher.enqueue(event) == "delivered"
    assert dispatcher.enqueue(event) == "duplicate"                      # 기존 dedupe_key 로 1건
    # 예전 코드·수동 입력으로 남은 queued in_app 행 (메일 worker 가 꺼내면 안 됨)
    legacy = uuid4()
    ctx.db.execute("INSERT INTO career.notification_deliveries (delivery_id, user_id, notification_type, channel, "
                   "status, dedupe_key, template_code, template_version, variables, next_attempt_at) "
                   "VALUES (%s, %s, 'service.maintenance', 'in_app', 'queued', %s, 'service.maintenance', 'test-1', "
                   "'{\"window_kst\": \"02:00~04:00\"}'::jsonb, now() - interval '1 day')",
                   (legacy, USER_A, uuid4().hex * 2))
    assert dispatcher.enqueue(NotificationEvent(USER_A, "security.new_login", "", VARS["security.new_login"])) == "queued"

    assert [d.channel for d in outbox.claim_due(night, 100, night + LEASE)] == ["email"]   # 꺼낸 뒤 중단
    clock.at = night + LEASE
    assert worker.run().sent == 1
    clock.at = night + 2 * LEASE
    worker.run()
    assert provider.calls == 1 and [m.subject for m in provider.sent] == [APPROVED["security.new_login"].subject]

    rows = ctx.db.execute("SELECT channel, status, sent_at IS NOT NULL, attempts, delivery_id = %s "
                          "FROM career.notification_deliveries ORDER BY channel, status", (legacy,)).fetchall()
    assert rows == [("email", "sent", True, 1, False), ("in_app", "queued", False, 0, True),
                    ("in_app", "sent", True, 0, False)]
    items, unread = inbox.list_inbox(USER_A, TYPES, 10)
    assert [i.type for i in items] == ["service.maintenance"] and unread == 1   # 바로 알림함에 보임

    inbox.set_preferences(USER_A, [("service.maintenance", "in_app", False)], night)
    assert dispatcher.enqueue(NotificationEvent(USER_A, "service.maintenance", "m-2", VARS["service.maintenance"])) == \
        "blocked_preference"
    session.close()
