"""T96 알림 발송 모듈 단위 시험 (메모리 outbox·Mock 공급자, 실제 발송·외부 호출 없음)."""
import logging
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.notifications import (
    BACKOFF,
    DEFAULT_TEMPLATES,
    KST,
    LEASE,
    SPECS,
    MemoryOutbox,
    MemoryRecipientDirectory,
    MockNotificationProvider,
    NotificationDispatcher,
    NotificationEvent,
    NotificationWorker,
    Recipient,
    RenderedMessage,
    UnavailableNotificationProvider,
    WorkerSummary,
    mask_email,
    release_time,
)

ROOT = Path(__file__).resolve().parents[2]
EMAIL = "gildong.hong@example.invalid"
U = uuid4()
DAY = datetime(2026, 11, 11, 14, 0, tzinfo=KST)
NIGHT = datetime(2026, 11, 11, 23, 0, tzinfo=KST)
# 시험 전용 '승인' 템플릿 — 비밀 변수 없는 유형만 (운영 DEFAULT_TEMPLATES 는 전부 미승인)
APPROVED = {k: replace(t, approved=True, version="test-1") for k, t in DEFAULT_TEMPLATES.items() if not t.has_secret}
VARS = {"security.password_changed": {"changed_at_kst": "2026-11-11 14:00"},
        "security.new_login": {"login_at_kst": "2026-11-11 14:00"},
        "account.recovery_notice": {},
        "account.deletion_receipt": {"requested_at_kst": "2026-11-11 14:00"},
        "service.policy_change": {"effective_date": "2026-12-01"},
        "service.maintenance": {"window_kst": "02:00~04:00"},
        "recommendation.new_results": {"count": "3"},
        "marketing.newsletter": {"headline": "11월 소식"}}


class Clock:
    def __init__(self, at):
        self.at = at

    def __call__(self):
        return self.at


class Env:
    def __init__(self, *, consents=None, active=True, script=(), at=DAY):
        self.clock = Clock(at)
        self.dir = MemoryRecipientDirectory({U: Recipient(U, EMAIL, active, consents or {})})
        self.outbox = MemoryOutbox()
        self.provider = MockNotificationProvider(list(script))
        self.dispatcher = NotificationDispatcher(self.outbox, self.dir, APPROVED, self.clock)
        self.worker = NotificationWorker(self.outbox, self.dir, self.provider, APPROVED, self.clock)

    def enqueue(self, type_, subject=""):
        return self.dispatcher.enqueue(NotificationEvent(U, type_, subject, VARS[type_]))

    def only(self):
        (row,) = self.outbox.rows.values()
        return row


def parse_matrix():
    text = (ROOT / "docs/notifications/T95_PREFERENCE_MATRIX.md").read_text(encoding="utf-8")
    section = text.split("## 알림 유형", 1)[1].split("\n## ", 1)[0]
    rows = [r for r in section.splitlines() if r.startswith("| ") and not r.startswith("| type") and "---" not in r]
    return {c[0]: c for c in ([x.strip() for x in r.strip("|").split("|")] for r in rows)}


def window(text):
    n, unit = re.fullmatch(r"(\d+)(분|시간|일)", text).groups()
    return {"분": timedelta(minutes=1), "시간": timedelta(hours=1), "일": timedelta(days=1)}[unit] * int(n)


def test_specs_match_the_t95_matrix_row_by_row():
    matrix = parse_matrix()
    assert set(matrix) == set(SPECS) == set(DEFAULT_TEMPLATES)
    for name, (_, _, required, consent, default, _, channel, quiet, dedupe, retries, retention, approval) in matrix.items():
        spec = SPECS[name]
        assert spec.required == (required == "예"), name
        assert spec.consent == (None if consent == "-" else consent), name
        assert spec.default_on == (default == "켬"), name
        assert spec.channel == channel and spec.quiet_hours == (quiet == "적용"), name
        assert spec.dedupe_window == window(dedupe) and spec.max_attempts == int(retries), name
        assert spec.retention == window(retention.replace("1년", "365일")), name
        assert approval == "미승인" and not DEFAULT_TEMPLATES[name].approved, name


def test_production_defaults_send_nothing():
    env = Env()
    dispatcher = NotificationDispatcher(env.outbox, env.dir, clock=env.clock)          # DEFAULT_TEMPLATES
    with pytest.raises(ValueError, match="not approved"):
        dispatcher.enqueue(NotificationEvent(U, "service.policy_change", "", VARS["service.policy_change"]))
    assert env.enqueue("service.policy_change") == "queued"
    summary = NotificationWorker(env.outbox, env.dir, UnavailableNotificationProvider(), APPROVED, env.clock).run()
    assert summary.sent == 0 and env.only().status == "queued" and env.provider.calls == 0


def test_secret_templates_are_never_queued_and_variables_must_match():
    env = Env()
    approved = {**APPROVED, "security.password_reset": replace(DEFAULT_TEMPLATES["security.password_reset"], approved=True)}
    dispatcher = NotificationDispatcher(env.outbox, env.dir, approved, env.clock)
    with pytest.raises(ValueError, match="secret"):
        dispatcher.enqueue(NotificationEvent(U, "security.password_reset", "", {"reset_link": "https://x/?t=SECRET"}))
    with pytest.raises(ValueError, match="expects variables"):
        dispatcher.enqueue(NotificationEvent(U, "marketing.newsletter", "", {"headline": "x", "email": EMAIL}))
    with pytest.raises(ValueError, match="unknown"):
        dispatcher.enqueue(NotificationEvent(U, "sms.promo"))
    assert env.outbox.rows == {}


@pytest.mark.parametrize(("type_", "consents", "expected"), [
    ("marketing.newsletter", {"marketing_notification": False}, "blocked_consent"),           # S1
    ("marketing.newsletter", {}, "blocked_consent"),                                          # 기본 끔
    ("marketing.newsletter", {"marketing_notification": True}, "queued"),
    ("security.password_changed", {"marketing_notification": False}, "queued"),               # S2 필수
    ("recommendation.new_results", {}, "blocked_consent"),                                    # S3 기본 끔
    ("service.maintenance", {}, "queued"),                                                    # 기본 켬
    ("service.maintenance", {"service_updates": False}, "blocked_consent"),
])
def test_consent_rules(type_, consents, expected):
    assert Env(consents=consents).enqueue(type_) == expected


def test_inactive_account_gets_only_the_deletion_receipt():   # S6
    env = Env(active=False, consents={"marketing_notification": True})
    assert [env.enqueue(t) for t in ("service.policy_change", "marketing.newsletter", "security.new_login")] == [
        "blocked_inactive"] * 3
    assert env.enqueue("account.deletion_receipt") == "queued"
    assert Env().dispatcher.enqueue(NotificationEvent(uuid4(), "account.recovery_notice")) == "unknown_recipient"


def test_duplicates_inside_the_window_are_blocked_and_reopen_after_it():   # S7
    env = Env()
    assert env.enqueue("security.password_changed", "s1") == "queued"
    assert env.enqueue("security.password_changed", "s1") == "duplicate"        # 대기 중
    assert env.enqueue("security.password_changed", "s2") == "queued"           # 다른 대상
    env.worker.run()
    env.clock.at += timedelta(minutes=4)
    assert env.enqueue("security.password_changed", "s1") == "duplicate"        # 보낸 뒤 창 안
    env.clock.at += timedelta(minutes=2)
    assert env.enqueue("security.password_changed", "s1") == "queued"           # 창 밖
    assert len(env.outbox.rows) == 3 and env.provider.calls == 2


def test_quiet_hours_defer_optional_types_but_not_security():   # S4, S5
    env = Env(consents={"marketing_notification": True}, at=NIGHT)
    env.enqueue("marketing.newsletter")
    env.enqueue("security.new_login")
    morning = datetime(2026, 11, 12, 8, 0, tzinfo=KST)
    news = next(r for r in env.outbox.rows.values() if r.type == "marketing.newsletter")
    assert news.next_attempt_at == morning
    assert env.worker.run().sent == 1 and env.provider.sent[0].subject == APPROVED["security.new_login"].subject
    env.clock.at = morning - timedelta(seconds=1)
    assert env.worker.run().sent == 0
    env.clock.at = morning
    assert env.worker.run().sent == 1
    assert release_time(SPECS["marketing.newsletter"], datetime(2026, 11, 12, 7, 59, tzinfo=KST)) == morning
    assert release_time(SPECS["marketing.newsletter"], DAY) == DAY


def test_transient_failures_back_off_then_succeed():
    env = Env(script=["transient", "transient"])
    env.enqueue("security.password_changed")
    assert env.worker.run().retried == 1
    row = env.only()
    assert (row.status, row.attempts, row.next_attempt_at, row.last_error_code) == (
        "queued", 1, DAY + BACKOFF[0], "transient")
    assert env.worker.run().sent == 0                                     # 백오프 전에는 꺼내지 않음
    env.clock.at = DAY + BACKOFF[0]
    env.worker.run()
    assert env.only().next_attempt_at == env.clock.at + BACKOFF[1]
    env.clock.at = env.only().next_attempt_at
    assert env.worker.run().sent == 1
    row = env.only()
    assert (row.status, row.attempts, row.sent_at) == ("sent", 3, env.clock.at)
    assert len(env.provider.sent) == 1


def test_max_attempts_and_permanent_failures_stop_retrying():   # S9
    env = Env(consents={"marketing_notification": True}, script=["transient"] * 5)
    env.enqueue("marketing.newsletter")       # 최대 2회
    env.worker.run()
    env.clock.at += BACKOFF[0]
    assert env.worker.run().failed == 1 and (env.only().status, env.only().attempts) == ("failed", 2)
    env.clock.at += timedelta(days=1)
    assert env.worker.run() == WorkerSummary() and env.provider.calls == 2

    env = Env(script=["permanent"])
    env.enqueue("security.password_changed")
    assert env.worker.run().failed_permanent == 1
    env.clock.at += timedelta(days=1)
    env.worker.run()
    assert (env.only().status, env.only().attempts, env.provider.calls) == ("failed_permanent", 1, 1)


def test_rechecks_before_sending_cancel_withdrawn_consent_and_disabled_accounts():
    env = Env(consents={"recommendation_alerts": True})
    env.enqueue("recommendation.new_results", "run-1")
    env.dir.recipients[U] = Recipient(U, EMAIL, True, {"recommendation_alerts": False})
    assert env.worker.run().cancelled == 1 and env.only().last_error_code == "consent_withdrawn"

    env = Env()
    env.enqueue("service.policy_change")
    env.dir.recipients[U] = Recipient(U, EMAIL, False, {})
    assert env.worker.run().cancelled == 1 and env.only().last_error_code == "recipient_inactive"
    assert env.provider.calls == 0


def test_template_revoked_or_changed_after_queueing_is_not_sent():
    env = Env()
    env.enqueue("service.policy_change")
    env.worker.templates = {**APPROVED, "service.policy_change": replace(APPROVED["service.policy_change"], version="test-2")}
    assert env.worker.run().failed_permanent == 1 and env.only().last_error_code == "template_unapproved"
    assert env.provider.calls == 0


def test_crashed_worker_lease_is_recovered():
    env = Env()
    env.enqueue("security.new_login")
    assert len(env.outbox.claim_due(DAY, 10, DAY + LEASE)) == 1           # 꺼낸 뒤 중단(finish 없음)
    assert env.worker.run().sent == 0                                      # 점유 중
    env.clock.at = DAY + LEASE
    assert env.worker.run().sent == 1 and env.only().status == "sent"


def test_logs_and_repr_never_contain_address_or_body(caplog):
    caplog.set_level(logging.DEBUG, logger="app.notifications")
    env = Env(script=["permanent"])
    env.enqueue("security.password_changed")
    env.worker.run()
    message = RenderedMessage(uuid4(), EMAIL, "s", "본문 secret-body")
    assert EMAIL not in repr(message) and "secret-body" not in repr(message)
    assert mask_email(EMAIL) == "g***@example.invalid" and mask_email("x") == "x***@?"
    logs = caplog.text
    assert EMAIL not in logs and "gildong" not in logs and "2026-11-11 14:00" not in logs
    assert "g***@example.invalid" in logs
    assert EMAIL not in repr(env.only())


def test_purge_keeps_pending_rows_and_honours_retention_by_type():
    env = Env(consents={"marketing_notification": True})
    env.enqueue("marketing.newsletter")
    env.enqueue("security.password_changed")
    env.worker.run()
    env.enqueue("service.policy_change")         # 대기 중(조용한 시간 아님) — 지우면 안 됨
    retention = {k: s.retention for k, s in SPECS.items()}
    assert env.outbox.purge_expired(DAY + timedelta(days=91), retention) == 1      # 뉴스레터 90일
    assert {r.type for r in env.outbox.rows.values()} == {"security.password_changed", "service.policy_change"}


def test_worker_rejects_out_of_range_batch():
    env = Env()
    for bad in (0, 101):
        with pytest.raises(ValueError):
            NotificationWorker(env.outbox, env.dir, env.provider, batch=bad)
