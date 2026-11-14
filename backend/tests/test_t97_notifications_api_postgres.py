"""T97 알림함·수신 설정 API — 일회용 PostgreSQL 18 + migration 0005 + 최소 권한 앱 역할 + 실제 FastAPI(NOTIFICATIONS_API=true).

합성 사용자 A·B(security_pg)만 씁니다. 알림 행은 관리자 연결로 직접 넣습니다(실제 발송 없음). 공유 Staging DB 는 쓰지 않습니다.
"""
import logging
from uuid import uuid4

import psycopg
import pytest

from app.services.notifications import DEFAULT_TEMPLATES, SPECS
from tests.security.security_pg import ROOT, USER_A, USER_B, disposable_pg, requires_pg

pytestmark = requires_pg
DDL = (ROOT / "database/migrations/0005_notifications.sql").read_text(encoding="utf-8")
INBOX = "/api/v1/me/notifications"
PREFS = "/api/v1/me/notification-preferences"
SECRET_VAR = "합성-점검-문구-T97"


@pytest.fixture
def pg(monkeypatch):
    monkeypatch.setenv("NOTIFICATIONS_API", "true")
    yield from disposable_pg(monkeypatch, write_tables=("notification_deliveries", "notification_preferences"),
                             extra_sql=(DDL,))


def insert(pg, user, type_="service.maintenance", *, channel="in_app", status="sent", minutes_ago=10,
           variables='{"window_kst": "02:00~04:00"}'):
    delivery_id = uuid4()
    sent = "now() - make_interval(mins => %s)" if status == "sent" else "NULL"
    args = [delivery_id, user, type_, channel, status, uuid4().hex * 2, type_, variables, minutes_ago]
    if status == "sent":
        args.append(minutes_ago)
    pg.db.execute(
        "INSERT INTO career.notification_deliveries (delivery_id, user_id, notification_type, channel, status, "
        "dedupe_key, template_code, template_version, variables, created_at, sent_at) "
        f"VALUES (%s, %s, %s, %s, %s, %s, %s, 'draft-1', %s::jsonb, now() - make_interval(mins => %s), {sent})", args)
    return str(delivery_id)


def test_inbox_own_rows_newest_first_and_mark_read(pg):
    old = insert(pg, USER_A, minutes_ago=60)
    new = insert(pg, USER_A, "service.policy_change", minutes_ago=5, variables='{"effective_date": "12월 1일"}')
    insert(pg, USER_A, channel="email")                     # 이메일 기록은 알림함에 없음
    insert(pg, USER_A, status="queued")                     # 아직 전달 전
    theirs = insert(pg, USER_B)
    r = pg.client.get(INBOX, headers=pg.h[USER_A])
    assert r.status_code == 200, r.text
    page = r.json()
    assert [i["notification_id"] for i in page["items"]] == [new, old] and page["unread_count"] == 2
    assert page["items"][0]["title"] == DEFAULT_TEMPLATES["service.policy_change"].subject
    assert page["items"][0]["read_at"] is None
    one = pg.client.post(f"{INBOX}/{new}/read", headers=pg.h[USER_A])
    assert one.status_code == 200 and one.json()["read_at"] is not None
    again = pg.client.post(f"{INBOX}/{new}/read", headers=pg.h[USER_A])
    assert again.json()["read_at"] == one.json()["read_at"]                       # 멱등
    assert pg.client.get(INBOX, headers=pg.h[USER_A]).json()["unread_count"] == 1
    assert pg.client.post(f"{INBOX}/read-all", headers=pg.h[USER_A]).json() == {"updated": 1}
    assert pg.client.post(f"{INBOX}/read-all", headers=pg.h[USER_A]).json() == {"updated": 0}
    assert pg.scalar("SELECT read_at IS NULL FROM career.notification_deliveries WHERE delivery_id = %s", theirs)


def test_other_users_notifications_are_404_and_untouched(pg):
    theirs = insert(pg, USER_B)
    email = insert(pg, USER_A, channel="email")
    for target in (theirs, email, str(uuid4())):
        assert pg.client.post(f"{INBOX}/{target}/read", headers=pg.h[USER_A]).status_code == 404
    assert pg.client.get(INBOX, headers=pg.h[USER_A]).json() == {"items": [], "unread_count": 0}
    assert pg.scalar("SELECT count(*) FROM career.notification_deliveries WHERE read_at IS NOT NULL") == 0
    assert pg.client.get(INBOX).status_code == 401


def test_preferences_defaults_update_isolation_and_required_rejected(pg):
    r = pg.client.get(PREFS, headers=pg.h[USER_A])
    assert r.status_code == 200, r.text
    items = {p["type"]: p for p in r.json()["items"]}
    assert list(items) == list(SPECS)
    assert items["marketing.newsletter"]["enabled"] is False and items["service.maintenance"]["enabled"] is True
    bad = pg.client.put(PREFS, headers=pg.h[USER_A], json={"items": [
        {"type": "marketing.newsletter", "enabled": True}, {"type": "security.password_reset", "enabled": False}]})
    assert bad.status_code == 422
    assert pg.scalar("SELECT count(*) FROM career.notification_preferences") == 0       # 일부만 저장되지 않음
    for enabled in (True, False, True):                                                  # upsert
        ok = pg.client.put(PREFS, headers=pg.h[USER_A], json={"items": [
            {"type": "marketing.newsletter", "enabled": enabled}, {"type": "service.maintenance", "enabled": False}]})
        assert ok.status_code == 200, ok.text
    mine = {p["type"]: p["enabled"] for p in pg.client.get(PREFS, headers=pg.h[USER_A]).json()["items"]}
    assert mine["marketing.newsletter"] is True and mine["service.maintenance"] is False
    theirs = {p["type"]: p["enabled"] for p in pg.client.get(PREFS, headers=pg.h[USER_B]).json()["items"]}
    assert theirs["marketing.newsletter"] is False and theirs["service.maintenance"] is True
    assert pg.scalar("SELECT count(*) FROM career.notification_preferences WHERE user_id = %s", USER_A) == 2


def test_schema_constraints_and_account_deletion(pg):
    email = insert(pg, USER_A, channel="email")
    with pytest.raises(psycopg.errors.CheckViolation):                   # read_at 은 in_app·sent 만
        pg.db.execute("UPDATE career.notification_deliveries SET read_at = now() WHERE delivery_id = %s", (email,))
    with pytest.raises(psycopg.errors.CheckViolation):
        pg.db.execute("INSERT INTO career.notification_preferences (user_id, notification_type, channel, enabled) "
                      "VALUES (%s, 'marketing.newsletter', 'sms', true)", (USER_A,))
    kept = insert(pg, USER_A)
    pg.client.put(PREFS, headers=pg.h[USER_A], json={"items": [{"type": "marketing.newsletter", "enabled": True}]})
    pg.db.execute("DELETE FROM career.users WHERE user_id = %s", (USER_A,))     # 일회용 DB 의 합성 사용자
    assert pg.scalar("SELECT count(*) FROM career.notification_preferences") == 0          # CASCADE
    assert pg.scalar("SELECT user_id IS NULL FROM career.notification_deliveries WHERE delivery_id = %s", kept)


def test_logs_do_not_contain_notification_variables(pg, caplog):
    nid = insert(pg, USER_A, variables='{"window_kst": "%s"}' % SECRET_VAR)
    with caplog.at_level(logging.DEBUG):
        page = pg.client.get(INBOX, headers=pg.h[USER_A]).json()
        assert SECRET_VAR in page["items"][0]["summary"]                  # 응답에는 본인에게만
        pg.client.post(f"{INBOX}/{nid}/read", headers=pg.h[USER_A])
        pg.client.post(f"{INBOX}/{uuid4()}/read", headers=pg.h[USER_B])
    assert SECRET_VAR not in caplog.text
