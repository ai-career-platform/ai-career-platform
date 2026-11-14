"""T96 알림 이벤트 발송 모듈 (T95 계약 PROPOSED 를 그대로 옮김).

흐름: 이벤트 → `NotificationDispatcher.enqueue` (동의·계정 상태·중복 확인 후 outbox 에 기록)
      → `NotificationWorker.run` (발송 직전 재확인, 조용한 시간, 공급자 호출, 재시도·영구 실패)

운영 안전장치 — 승인 전에는 아무것도 발송되지 않습니다:
- 기본 공급자는 `UnavailableNotificationProvider` (worker 가 아무 행도 꺼내지 않음).
- 기본 템플릿 목록(`DEFAULT_TEMPLATES`)은 T95 대로 **전부 미승인**이라 enqueue 가 거부합니다.
- outbox 표는 `database/migrations/0005_notifications.sql` (T96·T97).
- 비밀 변수(링크·토큰)가 있는 템플릿은 outbox 에 넣지 않습니다(저장 금지). 비밀번호 재설정은 T93 즉시 발송 경로를 유지합니다.
- 채널: worker 는 `channel='email'` 행만 꺼내고 메일 공급자에 넘깁니다. `in_app` 유형은 enqueue 시점에
  바로 전달 완료(`status='sent'`, `sent_at`) 행으로 기록되어 T97 알림함(`channel='in_app' AND status='sent'`)에 보이며,
  메일 공급자에는 절대 전달되지 않습니다.
로그에는 delivery_id·유형·상태·마스킹된 주소만 남깁니다.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

from app.services.mail import MailDeliveryError

logger = logging.getLogger("app.notifications")

KST = timezone(timedelta(hours=9))           # 사용자 시간대 기본값(Asia/Seoul, DST 없음). users 에 시간대 열 없음
QUIET_START_HOUR, QUIET_END_HOUR = 21, 8
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6))
LEASE = timedelta(minutes=5)                  # worker 가 꺼낸 행의 점유 시간. 지나면 다른 worker 가 회수
MAX_BATCH = 100


# ---------------------------------------------------------------- 유형·템플릿 (T95_PREFERENCE_MATRIX.md)

@dataclass(frozen=True)
class NotificationSpec:
    type: str
    required: bool
    consent: str | None
    default_on: bool
    quiet_hours: bool
    dedupe_window: timedelta
    max_attempts: int
    retention: timedelta
    channel: str = "email"


def _spec(type_: str, required: bool, consent: str | None, default_on: bool, quiet: bool, window: timedelta,
          attempts: int, retention_days: int) -> NotificationSpec:
    return NotificationSpec(type_, required, consent, default_on, quiet, window, attempts, timedelta(days=retention_days))


_M, _H, _D = timedelta(minutes=1), timedelta(hours=1), timedelta(days=1)
SPECS: dict[str, NotificationSpec] = {s.type: s for s in (
    _spec("security.password_reset", True, None, True, False, 5 * _M, 3, 365),
    _spec("security.password_changed", True, None, True, False, 5 * _M, 5, 365),
    _spec("security.new_login", True, None, True, False, 60 * _M, 5, 365),
    _spec("account.email_verification", True, None, True, False, 5 * _M, 3, 90),
    _spec("account.recovery_notice", True, None, True, False, 5 * _M, 3, 365),
    _spec("account.deletion_receipt", True, None, True, False, 24 * _H, 5, 365),
    _spec("service.policy_change", True, None, True, True, 24 * _H, 5, 365),
    _spec("service.maintenance", False, "service_updates", True, True, 24 * _H, 3, 90),
    _spec("recommendation.new_results", False, "recommendation_alerts", False, True, 24 * _H, 3, 90),
    _spec("marketing.newsletter", False, "marketing_notification", False, True, 7 * _D, 2, 90),
)}
INACTIVE_ALLOWED = frozenset({"account.deletion_receipt"})   # T95 §3-3
CHANNELS = frozenset({"email", "in_app"})                     # migration 0005 CHECK
MAIL_CHANNEL = "email"                                        # worker·메일 공급자가 다루는 유일한 채널


@dataclass(frozen=True)
class Template:
    code: str
    version: str
    approved: bool
    subject: str
    body: str
    variables: Mapping[str, str] = field(default_factory=dict)   # 이름 → "plain" | "secret"

    @property
    def has_secret(self) -> bool:
        return "secret" in self.variables.values()


def _draft(code: str, subject: str, body: str, **variables: str) -> Template:
    return Template(code, "draft-1", False, subject, body, variables)


# T95 §7: 현재 모든 템플릿 미승인. 문구는 초안이며 PM·법무 승인 전 발송 불가.
DEFAULT_TEMPLATES: dict[str, Template] = {t.code: t for t in (
    _draft("security.password_reset", "비밀번호 재설정 안내", "회원님, 30분 안에 아래 링크로 비밀번호를 재설정하세요.\n{reset_link}",
           reset_link="secret"),
    _draft("security.password_changed", "비밀번호가 변경되었습니다", "회원님 계정의 비밀번호가 {changed_at_kst}에 변경되었습니다.",
           changed_at_kst="plain"),
    _draft("security.new_login", "새 기기 로그인 알림", "회원님 계정에 {login_at_kst} 새 로그인이 있었습니다.", login_at_kst="plain"),
    _draft("account.email_verification", "이메일 주소 확인", "아래 링크로 이메일 주소를 확인하세요.\n{verify_link}", verify_link="secret"),
    _draft("account.recovery_notice", "계정 복구 안내", "회원님 계정 복구 요청이 접수되었습니다."),
    _draft("account.deletion_receipt", "탈퇴 요청 접수", "회원님의 탈퇴 요청이 {requested_at_kst}에 접수되었습니다.",
           requested_at_kst="plain"),
    _draft("service.policy_change", "약관·개인정보 처리방침 변경", "{effective_date}부터 변경된 정책이 적용됩니다.", effective_date="plain"),
    _draft("service.maintenance", "서비스 점검 예정", "{window_kst} 동안 서비스 점검이 있습니다.", window_kst="plain"),
    _draft("recommendation.new_results", "새 맞춤 추천", "새 추천 결과 {count}건이 준비되었습니다.", count="plain"),
    _draft("marketing.newsletter", "(광고) 소식", "{headline}\n수신 거부: 설정 > 알림", headline="plain"),
)}


# ---------------------------------------------------------------- 마스킹

def mask_email(address: str) -> str:
    local, _, domain = address.partition("@")
    return (local[:1] or "?") + "***@" + (domain or "?")


def dedupe_key(user_id: UUID, type_: str, subject_ref: str) -> str:
    return hashlib.sha256(f"{user_id}|{type_}|{subject_ref}".encode()).hexdigest()


# ---------------------------------------------------------------- 공급자

class PermanentDeliveryError(Exception):
    """주소 없음·수신 거부 등 — 재시도하지 않음."""


TransientDeliveryError = MailDeliveryError   # T93 메일 어댑터의 일시 실패와 같은 의미


@dataclass(frozen=True)
class RenderedMessage:
    delivery_id: UUID          # 공급자 멱등 키로 전달 (worker 중단 후 재회수 시 중복 발송 방지 근거)
    to: str
    subject: str
    body: str

    def __repr__(self) -> str:  # 본문·주소 원문을 repr/로그에 남기지 않음
        return f"RenderedMessage(delivery_id={self.delivery_id}, to={mask_email(self.to)})"


class NotificationProvider(Protocol):
    available: bool

    def deliver(self, message: RenderedMessage) -> None: ...


class UnavailableNotificationProvider:
    """기본값. 공급자 미정(PM) → worker 는 아무것도 꺼내지 않고 대기열을 그대로 둡니다."""

    available = False

    def deliver(self, message: RenderedMessage) -> None:  # pragma: no cover - guarded by `available`
        raise TransientDeliveryError("notification provider not configured")


@dataclass
class MockNotificationProvider:
    """시험 전용. script 의 결과를 순서대로 냄: "ok" | "transient" | "permanent". 비면 "ok"."""

    script: list[str] = field(default_factory=list)
    sent: list[RenderedMessage] = field(default_factory=list)
    calls: int = 0
    available: bool = True

    def deliver(self, message: RenderedMessage) -> None:
        self.calls += 1
        outcome = self.script.pop(0) if self.script else "ok"
        if outcome == "transient":
            raise TransientDeliveryError("synthetic transient failure")
        if outcome == "permanent":
            raise PermanentDeliveryError("synthetic permanent failure")
        self.sent.append(message)


# ---------------------------------------------------------------- 저장소 계약

@dataclass(frozen=True)
class Recipient:
    user_id: UUID
    email: str
    active: bool
    consents: Mapping[str, bool]      # 동의 코드 → 최신 행의 granted


class RecipientDirectory(Protocol):
    def lookup(self, user_id: UUID) -> Recipient | None: ...


@dataclass(frozen=True)
class Delivery:
    delivery_id: UUID
    user_id: UUID | None
    type: str
    channel: str
    status: str
    attempts: int
    dedupe_key: str
    template_code: str
    template_version: str
    variables: Mapping[str, str]
    created_at: datetime
    next_attempt_at: datetime
    sent_at: datetime | None = None
    last_error_code: str | None = None


class NotificationOutbox(Protocol):
    def enqueue(self, delivery: Delivery, window_start: datetime) -> bool:
        """같은 dedupe_key 의 취소되지 않은 행이 window_start 이후에 있으면 False(중복)."""

    def claim_due(self, now: datetime, limit: int, lease_until: datetime) -> list[Delivery]:
        """`channel='email'` 중 due 인 queued 행과 점유가 만료된 sending 행을 sending 으로 바꿔 돌려줌
        (동시 worker 간 겹치지 않음). in_app 행은 절대 꺼내지 않습니다."""

    def finish(self, delivery_id: UUID, *, status: str, attempts: int, next_attempt_at: datetime,
               sent_at: datetime | None, last_error_code: str | None) -> None: ...

    def purge_expired(self, now: datetime, retention: Mapping[str, timedelta]) -> int: ...


class PreferenceStore(Protocol):
    """T97 `notification_preferences` 사용자 선택 (행 없음 = T95 기본값). 예: SqlNotificationInboxRepository."""

    def preferences(self, user_id: UUID) -> Mapping[tuple[str, str], bool]: ...


# ---------------------------------------------------------------- 판정

def consent_allows(spec: NotificationSpec, recipient: Recipient) -> bool:
    if spec.required:
        return True
    granted = recipient.consents.get(spec.consent or "")
    return spec.default_on if granted is None else granted


def release_time(spec: NotificationSpec, at: datetime) -> datetime:
    """조용한 시간(21:00~08:00 KST)이면 다음 08:00 으로 미룸. 보안·인증·복구는 그대로."""
    if not spec.quiet_hours:
        return at
    local = at.astimezone(KST)
    if QUIET_END_HOUR <= local.hour < QUIET_START_HOUR:
        return at
    day = local.date() if local.hour < QUIET_END_HOUR else local.date() + timedelta(days=1)
    return datetime(day.year, day.month, day.day, QUIET_END_HOUR, tzinfo=KST).astimezone(UTC)


def render(template: Template, variables: Mapping[str, str], delivery_id: UUID, to: str) -> RenderedMessage:
    if set(variables) != set(template.variables):
        raise ValueError(f"template {template.code} expects variables {sorted(template.variables)}")
    return RenderedMessage(delivery_id, to, template.subject, template.body.format_map(dict(variables)))


@dataclass(frozen=True)
class NotificationEvent:
    user_id: UUID
    type: str
    subject_ref: str = ""
    variables: Mapping[str, str] = field(default_factory=dict)


class NotificationDispatcher:
    """이벤트 접수. 결과: queued(email) | delivered(in_app, 알림함에 바로 보임) | duplicate | blocked_consent |
    blocked_preference | blocked_inactive | unknown_recipient.

    `preferences` 를 주면 선택 유형은 사용자가 끈(`enabled=false`) (유형, 채널) 조합을 보내지 않습니다(필수 유형은 무시).
    켜 둔 설정이 동의(consent) 부재를 덮어쓰지는 않습니다(동의가 발송 근거)."""

    def __init__(self, outbox: NotificationOutbox, directory: RecipientDirectory,
                 templates: Mapping[str, Template] = DEFAULT_TEMPLATES, clock: Callable[[], datetime] | None = None,
                 *, specs: Mapping[str, NotificationSpec] = SPECS, preferences: PreferenceStore | None = None):
        self.outbox, self.directory, self.templates = outbox, directory, templates
        self.clock = clock or (lambda: datetime.now(UTC))
        self.specs, self.preferences = specs, preferences

    def enqueue(self, event: NotificationEvent) -> str:
        spec = self.specs.get(event.type)
        if spec is None:
            raise ValueError(f"unknown notification type {event.type!r}")
        template = self.templates.get(event.type)
        if template is None or not template.approved:
            raise ValueError(f"template for {event.type} is not approved (T95 §7)")
        if template.has_secret:
            raise ValueError(f"{event.type} carries secret variables and must not be queued")
        if set(event.variables) != set(template.variables):
            raise ValueError(f"template {template.code} expects variables {sorted(template.variables)}")
        if len(event.subject_ref) > 200:
            raise ValueError("subject_ref too long")
        recipient = self.directory.lookup(event.user_id)
        if recipient is None:
            return "unknown_recipient"
        if not recipient.active and event.type not in INACTIVE_ALLOWED:
            return "blocked_inactive"
        if not consent_allows(spec, recipient):
            return "blocked_consent"
        if not spec.required and self.preferences is not None and \
                self.preferences.preferences(event.user_id).get((spec.type, spec.channel)) is False:
            return "blocked_preference"
        if spec.channel not in CHANNELS:
            raise ValueError(f"unknown channel {spec.channel!r}")
        now = self.clock()
        in_app = spec.channel == "in_app"
        # in_app 은 메일 발송 대상이 아님 → 대기열을 거치지 않고 바로 전달 완료(알림함 표시) 행으로 기록
        delivery = Delivery(uuid4(), event.user_id, event.type, spec.channel, "sent" if in_app else "queued", 0,
                            dedupe_key(event.user_id, event.type, event.subject_ref), template.code, template.version,
                            dict(event.variables), now, now if in_app else release_time(spec, now),
                            sent_at=now if in_app else None)
        if not self.outbox.enqueue(delivery, now - spec.dedupe_window):
            logger.info("notification duplicate type=%s", event.type)
            return "duplicate"
        status = "delivered" if in_app else "queued"
        logger.info("notification %s id=%s type=%s channel=%s", status, delivery.delivery_id, event.type, spec.channel)
        return status


@dataclass
class WorkerSummary:
    sent: int = 0
    retried: int = 0
    failed: int = 0
    failed_permanent: int = 0
    cancelled: int = 0
    deferred: int = 0


class NotificationWorker:
    """명시적 1회 실행(스케줄 없음). 발송 직전에 계정 상태·동의·템플릿 승인을 다시 확인합니다(T95 §3-2, §5)."""

    def __init__(self, outbox: NotificationOutbox, directory: RecipientDirectory, provider: NotificationProvider,
                 templates: Mapping[str, Template] = DEFAULT_TEMPLATES, clock: Callable[[], datetime] | None = None,
                 batch: int = MAX_BATCH, *, specs: Mapping[str, NotificationSpec] = SPECS):
        if not 1 <= batch <= MAX_BATCH:
            raise ValueError("batch out of range")
        self.outbox, self.directory, self.provider, self.templates = outbox, directory, provider, templates
        self.clock = clock or (lambda: datetime.now(UTC))
        self.batch = batch
        self.specs = specs

    def run(self) -> WorkerSummary:
        summary = WorkerSummary()
        if not self.provider.available:
            logger.warning("notification worker skipped: provider not configured")
            return summary
        now = self.clock()
        for item in self.outbox.claim_due(now, self.batch, now + LEASE):
            self._process(item, now, summary)
        return summary

    def _finish(self, item: Delivery, status: str, *, attempts: int | None = None, at: datetime | None = None,
                sent_at: datetime | None = None, error: str | None = None) -> None:
        self.outbox.finish(item.delivery_id, status=status, attempts=item.attempts if attempts is None else attempts,
                           next_attempt_at=at or item.next_attempt_at, sent_at=sent_at, last_error_code=error)
        logger.info("notification id=%s type=%s status=%s", item.delivery_id, item.type, status)

    def _process(self, item: Delivery, now: datetime, summary: WorkerSummary) -> None:
        if item.channel != MAIL_CHANNEL:   # 방어선: claim_due 가 이미 거르지만, 메일 공급자에는 절대 넘기지 않음
            summary.cancelled += 1
            logger.error("notification worker got non-email row id=%s channel=%s", item.delivery_id, item.channel)
            return self._finish(item, "cancelled", error="channel_not_email")
        spec = self.specs[item.type]
        recipient = self.directory.lookup(item.user_id) if item.user_id else None
        if recipient is None or (not recipient.active and item.type not in INACTIVE_ALLOWED):
            summary.cancelled += 1
            return self._finish(item, "cancelled", error="recipient_inactive")
        if not consent_allows(spec, recipient):
            summary.cancelled += 1
            return self._finish(item, "cancelled", error="consent_withdrawn")
        template = self.templates.get(item.template_code)
        if template is None or not template.approved or template.version != item.template_version:
            summary.failed_permanent += 1
            return self._finish(item, "failed_permanent", error="template_unapproved")
        later = release_time(spec, now)
        if later > now:
            summary.deferred += 1
            return self._finish(item, "queued", at=later)
        attempts = item.attempts + 1
        try:
            self.provider.deliver(render(template, item.variables, item.delivery_id, recipient.email))
        except PermanentDeliveryError:
            summary.failed_permanent += 1
            logger.warning("notification permanent failure id=%s to=%s", item.delivery_id, mask_email(recipient.email))
            return self._finish(item, "failed_permanent", attempts=attempts, error="permanent")
        except TransientDeliveryError:
            if attempts >= spec.max_attempts:
                summary.failed += 1
                if spec.required:
                    logger.error("required notification failed id=%s type=%s attempts=%d", item.delivery_id,
                                 item.type, attempts)
                return self._finish(item, "failed", attempts=attempts, error="max_attempts")
            summary.retried += 1
            return self._finish(item, "queued", attempts=attempts, at=now + BACKOFF[attempts - 1], error="transient")
        summary.sent += 1
        self._finish(item, "sent", attempts=attempts, sent_at=now)


# ---------------------------------------------------------------- 메모리 구현 (단위 시험·Mock 전용)

class MemoryRecipientDirectory:
    def __init__(self, recipients: Mapping[UUID, Recipient] | None = None):
        self.recipients = dict(recipients or {})

    def lookup(self, user_id: UUID) -> Recipient | None:
        return self.recipients.get(user_id)


class MemoryOutbox:
    def __init__(self) -> None:
        self.rows: dict[UUID, Delivery] = {}
        self.locked: dict[UUID, datetime] = {}

    def enqueue(self, delivery: Delivery, window_start: datetime) -> bool:
        for row in self.rows.values():
            if row.dedupe_key == delivery.dedupe_key and (
                    row.status in {"queued", "sending"} or (row.status != "cancelled" and row.created_at > window_start)):
                return False
        self.rows[delivery.delivery_id] = delivery
        return True

    def claim_due(self, now: datetime, limit: int, lease_until: datetime) -> list[Delivery]:
        due = [r for r in self.rows.values()
               if r.channel == MAIL_CHANNEL and (
                   (r.status == "queued" and r.next_attempt_at <= now)
                   or (r.status == "sending" and self.locked[r.delivery_id] <= now))]
        due.sort(key=lambda r: (r.next_attempt_at, str(r.delivery_id)))
        claimed = []
        for row in due[:limit]:
            self.rows[row.delivery_id] = replace(row, status="sending")
            self.locked[row.delivery_id] = lease_until
            claimed.append(self.rows[row.delivery_id])
        return claimed

    def finish(self, delivery_id: UUID, *, status: str, attempts: int, next_attempt_at: datetime,
               sent_at: datetime | None, last_error_code: str | None) -> None:
        self.locked.pop(delivery_id, None)
        self.rows[delivery_id] = replace(self.rows[delivery_id], status=status, attempts=attempts,
                                         next_attempt_at=next_attempt_at, sent_at=sent_at,
                                         last_error_code=last_error_code)

    def purge_expired(self, now: datetime, retention: Mapping[str, timedelta]) -> int:
        expired = [k for k, r in self.rows.items()
                   if r.status not in {"queued", "sending"} and r.created_at < now - retention[r.type]]
        for key in expired:
            del self.rows[key]
        return len(expired)
