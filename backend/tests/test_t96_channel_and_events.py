"""T96 후속 — 채널 구분(in_app 행은 메일 공급자에 절대 가지 않음)과 업무 이벤트 in_app 알림 연결 (메모리, 발송 없음).

in_app 유형은 T95 매트릭스에 아직 없으므로 시험 전용 spec(채널만 in_app 으로 바꾼 사본)으로 경로를 검증합니다.
"""
import logging
from dataclasses import replace
from uuid import uuid4

from app.repositories.notifications import SqlNotificationOutbox
from app.schemas.job_applications import JobApplicationCreate, JobApplicationUpdate
from app.services.job_applications import JobApplicationService
from app.services.job_postings import ListCursor
from app.services.notification_events import EVENT_NOTIFICATIONS_ENABLED, EVENT_TYPES, EventNotifier, EventType
from app.services.notification_inbox import MemoryNotificationInboxRepository
from app.services.notifications import (
    DEFAULT_TEMPLATES,
    SPECS,
    Delivery,
    MemoryOutbox,
    MemoryRecipientDirectory,
    MockNotificationProvider,
    NotificationDispatcher,
    NotificationEvent,
    NotificationWorker,
    Recipient,
    dedupe_key,
)
from tests.test_t102_job_applications import NOW, POSTING, MemoryRepo
from tests.test_t96_notifications import APPROVED, DAY, EMAIL, NIGHT, ROOT, U, VARS, Clock

IN_APP_SPECS = {**SPECS, "service.maintenance": replace(SPECS["service.maintenance"], channel="in_app"),
                "service.policy_change": replace(SPECS["service.policy_change"], channel="in_app")}


class Env:
    def __init__(self, *, consents=None, at=DAY, specs=IN_APP_SPECS, prefs=None):
        self.clock = Clock(at)
        self.dir = MemoryRecipientDirectory({U: Recipient(U, EMAIL, True, consents or {})})
        self.outbox = MemoryOutbox()
        self.prefs = prefs
        self.provider = MockNotificationProvider()
        self.dispatcher = NotificationDispatcher(self.outbox, self.dir, APPROVED, self.clock, specs=specs,
                                                 preferences=prefs)
        self.worker = NotificationWorker(self.outbox, self.dir, self.provider, APPROVED, self.clock, specs=specs)

    def enqueue(self, type_, subject=""):
        return self.dispatcher.enqueue(NotificationEvent(U, type_, subject, VARS[type_]))


def test_in_app_event_is_stored_as_delivered_inbox_item_and_never_reaches_the_mail_sender():
    env = Env(at=NIGHT)                                               # 조용한 시간이어도 알림함은 바로
    assert env.enqueue("service.maintenance") == "delivered"
    (row,) = env.outbox.rows.values()
    assert (row.channel, row.status, row.sent_at, row.next_attempt_at, row.attempts) == ("in_app", "sent", NIGHT, NIGHT, 0)
    for _ in range(3):
        summary = env.worker.run()
        assert (summary.sent, summary.cancelled, summary.deferred) == (0, 0, 0)
    assert env.provider.calls == 0 and env.provider.sent == []
    assert env.outbox.rows[row.delivery_id] == row                    # worker 가 손대지 않음


def test_email_and_in_app_rows_side_by_side_only_email_is_mailed():
    env = Env()
    assert env.enqueue("service.maintenance") == "delivered"         # in_app (시험 spec)
    assert env.enqueue("security.new_login") == "queued"             # email
    assert env.worker.run().sent == 1
    assert [m.subject for m in env.provider.sent] == [APPROVED["security.new_login"].subject]
    assert {r.channel: r.status for r in env.outbox.rows.values()} == {"in_app": "sent", "email": "sent"}


def test_queued_or_stale_in_app_rows_are_never_claimed():
    """예전 코드·수동 입력으로 queued/sending 상태인 in_app 행이 있어도 꺼내지 않음."""
    env = Env(specs=SPECS)
    for status in ("queued", "sending"):
        d = Delivery(uuid4(), U, "service.maintenance", "in_app", status, 0, dedupe_key(U, "x", status),
                     "service.maintenance", "test-1", VARS["service.maintenance"], DAY, DAY)
        env.outbox.rows[d.delivery_id] = d
        env.outbox.locked[d.delivery_id] = DAY
    assert env.outbox.claim_due(DAY, 100, DAY) == []
    env.worker.run()
    assert env.provider.calls == 0


def test_worker_guard_cancels_a_non_email_row_without_calling_the_provider():
    class LeakyOutbox(MemoryOutbox):                                  # 잘못된 저장소 구현을 흉내
        def claim_due(self, now, limit, lease_until):
            return [replace(r, status="sending") for r in self.rows.values()]

    env = Env(specs=SPECS)
    env.outbox = LeakyOutbox()
    env.worker.outbox = env.outbox
    d = Delivery(uuid4(), U, "service.maintenance", "in_app", "queued", 0, dedupe_key(U, "x", ""),
                 "service.maintenance", "test-1", VARS["service.maintenance"], DAY, DAY)
    env.outbox.rows[d.delivery_id] = d
    assert env.worker.run().cancelled == 1
    assert env.provider.calls == 0
    assert env.outbox.rows[d.delivery_id].last_error_code == "channel_not_email"


def test_in_app_dedupe_uses_the_existing_dedupe_key():
    env = Env()
    assert env.enqueue("service.maintenance", "m-1") == "delivered"
    assert env.enqueue("service.maintenance", "m-1") == "duplicate"
    assert env.enqueue("service.maintenance", "m-2") == "delivered"
    assert len(env.outbox.rows) == 2


def test_user_preferences_apply_to_optional_types_only():
    prefs = MemoryNotificationInboxRepository()
    env = Env(prefs=prefs)
    prefs.set_preferences(U, [("service.maintenance", "in_app", False), ("service.policy_change", "in_app", False)], DAY)
    assert env.enqueue("service.maintenance") == "blocked_preference"     # 선택 — 사용자가 끔
    assert env.enqueue("service.policy_change") == "delivered"            # 필수 — 설정과 무관
    prefs.set_preferences(U, [("service.maintenance", "in_app", True)], DAY)
    assert env.enqueue("service.maintenance") == "delivered"
    # 켜 둔 설정이 동의 부재를 덮지 않음 (recommendation.new_results 기본 끔, 동의 없음)
    prefs.set_preferences(U, [("recommendation.new_results", "email", True)], DAY)
    assert env.enqueue("recommendation.new_results") == "blocked_consent"


def test_email_preference_off_blocks_email_without_touching_other_channels():
    prefs = MemoryNotificationInboxRepository()
    env = Env(consents={"marketing_notification": True}, prefs=prefs)
    prefs.set_preferences(U, [("marketing.newsletter", "email", False)], DAY)
    assert env.enqueue("marketing.newsletter") == "blocked_preference"
    assert env.outbox.rows == {}


# ---------------------------------------------------------------- 업무 이벤트 연결

class Spy:
    def __init__(self, result="delivered", exc=None):
        self.calls, self.result, self.exc = [], result, exc

    def enqueue(self, event):
        self.calls.append(event)
        if self.exc:
            raise self.exc
        return self.result


def test_event_switch_is_off_and_stage_change_type_is_blocked_by_template_approval():
    assert EVENT_NOTIFICATIONS_ENABLED is False
    entry = EVENT_TYPES["application.stage_changed"]
    assert entry.approved is False and "BLOCKED" in entry.note
    assert "application.stage_changed" not in SPECS and "application.stage_changed" not in DEFAULT_TEMPLATES
    built = []
    assert EventNotifier(lambda: built.append(1)).notify(U, "application.stage_changed", "x") == "disabled"
    assert EventNotifier(lambda: built.append(1), enabled=True).notify(U, "application.stage_changed", "x") == \
        "blocked_unapproved"
    assert built == []                                                    # dispatcher(=DB) 를 만들지도 않음
    assert EventNotifier(lambda: built.append(1), enabled=True).notify(U, "no.such", "x") == "unknown_event"


def test_event_notifier_only_dispatches_approved_in_app_types_with_empty_variables():
    spy = Spy()
    registry = {"service.maintenance": EventType("service.maintenance", "test", True, "test only"),
                "service.policy_change": EventType("service.policy_change", "test", True, "test only")}
    notifier = EventNotifier(lambda: spy, enabled=True, registry=registry, specs=IN_APP_SPECS)
    assert notifier.notify(U, "service.maintenance", "ref-1") == "delivered"
    assert spy.calls == [NotificationEvent(U, "service.maintenance", "ref-1", {})]
    email_only = EventNotifier(lambda: spy, enabled=True, registry=registry, specs=SPECS)
    assert email_only.notify(U, "service.maintenance", "ref-2") == "blocked_unapproved"   # in_app 이 아니면 안 보냄
    assert len(spy.calls) == 1


def test_event_notifier_swallows_template_and_unexpected_errors(caplog):
    registry = {"service.maintenance": EventType("service.maintenance", "test", True, "test only")}
    env = Env()                                         # 실제 dispatcher — 변수 불일치 → ValueError
    real = EventNotifier(lambda: env.dispatcher, enabled=True, registry=registry, specs=IN_APP_SPECS)
    assert real.notify(U, "service.maintenance", "r") == "blocked_template"
    caplog.set_level(logging.INFO)
    boom = EventNotifier(lambda: Spy(exc=RuntimeError(EMAIL)), enabled=True, registry=registry, specs=IN_APP_SPECS)
    assert boom.notify(U, "service.maintenance", "r") == "error"
    assert EMAIL not in caplog.text and str(U) not in caplog.text


def test_self_initiated_stage_change_never_notifies(monkeypatch):
    """PM 결정 2026-11-14: 본인이 바꾼 지원 단계는 알림을 만들지 않음 — dispatcher·outbox·notifier 를 전혀 부르지 않음."""
    calls = []

    def trap(name):
        return lambda *a, **k: calls.append(name)

    monkeypatch.setattr(NotificationDispatcher, "enqueue", trap("dispatcher"))
    monkeypatch.setattr(EventNotifier, "notify", trap("notifier"))
    monkeypatch.setattr(MemoryOutbox, "enqueue", trap("memory_outbox"))
    monkeypatch.setattr(SqlNotificationOutbox, "enqueue", trap("sql_outbox"))
    svc = JobApplicationService(MemoryRepo(), ListCursor(b"k" * 32), clock=lambda: NOW)
    a = svc.create(U, JobApplicationCreate(job_posting_id=POSTING, memo="비공개 메모"))
    for stage in ("applied", "interviewing", "offered", "withdrawn"):
        a = svc.update(U, a.application_id, JobApplicationUpdate(version=a.version, stage=stage))
    assert a.stage == "withdrawn" and calls == []


def test_job_application_code_has_no_notification_wiring():
    for path in ("app/services/job_applications.py", "app/routers/job_applications.py"):
        source = (ROOT / "backend" / path).read_text(encoding="utf-8")
        imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
        assert not [line for line in imports if "notification" in line], path
        assert "NotificationDispatcher" not in source and "EventNotifier" not in source, path