"""T96 알림 outbox·수신자 조회 (PostgreSQL). 표는 database/migrations/0005_notifications.sql (T96·T97).

- 중복 방지: 같은 dedupe_key 를 트랜잭션 advisory lock 으로 직렬화한 뒤 창(window) 안 기존 행을 확인하고,
  부분 unique index(queued/sending)가 최종 방어선입니다.
- 꺼내기: `FOR UPDATE SKIP LOCKED` 로 동시 worker 가 같은 행을 잡지 않습니다. 점유(locked_until)가 만료된 sending 행은
  worker 중단으로 보고 다시 꺼냅니다(최소 1회 전달 — 공급자에 delivery_id 를 멱등 키로 넘김).
  `channel='email'` 행만 꺼냅니다 — in_app 행은 메일 worker 대상이 아니며 enqueue 때 바로 sent 로 기록됩니다.
각 메서드는 스스로 커밋합니다(worker 가 행 단위로 상태를 확정).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services.notifications import Delivery, Recipient

_COLUMNS = ("delivery_id, user_id, notification_type, channel, status, attempts, dedupe_key, template_code, "
            "template_version, variables, created_at, next_attempt_at, sent_at, last_error_code")


def _row(r) -> Delivery:
    variables = r.variables if isinstance(r.variables, dict) else json.loads(r.variables)
    return Delivery(r.delivery_id, r.user_id, r.notification_type, r.channel, r.status, r.attempts, r.dedupe_key.strip(),
                    r.template_code, r.template_version, variables, r.created_at, r.next_attempt_at, r.sent_at,
                    r.last_error_code)


class SqlNotificationOutbox:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue(self, delivery: Delivery, window_start: datetime) -> bool:
        s = self.session
        try:
            s.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 96))"), {"k": delivery.dedupe_key})
            exists = s.execute(text(
                "SELECT 1 FROM career.notification_deliveries WHERE dedupe_key = :k AND "
                "(status IN ('queued', 'sending') OR (status <> 'cancelled' AND created_at > :w)) LIMIT 1"),
                {"k": delivery.dedupe_key, "w": window_start}).first()
            if exists:
                s.rollback()
                return False
            s.execute(text(
                "INSERT INTO career.notification_deliveries (delivery_id, user_id, notification_type, channel, status, "
                "attempts, dedupe_key, template_code, template_version, variables, created_at, next_attempt_at, sent_at) "
                "VALUES (:id, :u, :t, :c, :s, 0, :k, :tc, :tv, CAST(:v AS jsonb), :at, :next, :sent)"),
                {"id": delivery.delivery_id, "u": delivery.user_id, "t": delivery.type, "c": delivery.channel,
                 "s": delivery.status, "sent": delivery.sent_at,
                 "k": delivery.dedupe_key, "tc": delivery.template_code, "tv": delivery.template_version,
                 "v": json.dumps(dict(delivery.variables), ensure_ascii=False), "at": delivery.created_at,
                 "next": delivery.next_attempt_at})
            s.commit()
            return True
        except IntegrityError:
            s.rollback()
            return False

    def claim_due(self, now: datetime, limit: int, lease_until: datetime) -> list[Delivery]:
        rows = self.session.execute(text(
            f"UPDATE career.notification_deliveries d SET status = 'sending', locked_until = :lease "
            f"WHERE d.delivery_id IN (SELECT delivery_id FROM career.notification_deliveries "
            f"  WHERE channel = 'email' AND ((status = 'queued' AND next_attempt_at <= :now) "
            f"    OR (status = 'sending' AND locked_until <= :now)) "
            f"  ORDER BY next_attempt_at, delivery_id LIMIT :limit FOR UPDATE SKIP LOCKED) "
            f"RETURNING {_COLUMNS}"), {"lease": lease_until, "now": now, "limit": limit}).all()
        self.session.commit()
        return sorted((_row(r) for r in rows), key=lambda d: (d.next_attempt_at, str(d.delivery_id)))

    def finish(self, delivery_id: UUID, *, status: str, attempts: int, next_attempt_at: datetime,
               sent_at: datetime | None, last_error_code: str | None) -> None:
        self.session.execute(text(
            "UPDATE career.notification_deliveries SET status = :s, attempts = :a, next_attempt_at = :n, sent_at = :sent, "
            "last_error_code = :e, locked_until = NULL WHERE delivery_id = :id AND status = 'sending'"),
            {"s": status, "a": attempts, "n": next_attempt_at, "sent": sent_at, "e": last_error_code, "id": delivery_id})
        self.session.commit()

    def purge_expired(self, now: datetime, retention: Mapping[str, timedelta]) -> int:
        total = 0
        for type_, keep in sorted(retention.items()):
            total += self.session.execute(text(
                "DELETE FROM career.notification_deliveries WHERE notification_type = :t "
                "AND status NOT IN ('queued', 'sending') AND created_at < :cut"), {"t": type_, "cut": now - keep}).rowcount
        self.session.commit()
        return total


class SqlRecipientDirectory:
    """users.status 와 user_consents 최신 행(동의 코드별)으로 수신 가능 여부 판단 (T31 방식)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def lookup(self, user_id: UUID) -> Recipient | None:
        user = self.session.execute(text("SELECT email, status FROM career.users WHERE user_id = :u"),
                                    {"u": user_id}).first()
        if user is None:
            return None
        consents = self.session.execute(text(
            "SELECT DISTINCT ON (policy_code) policy_code, granted FROM career.user_consents WHERE user_id = :u "
            "ORDER BY policy_code, recorded_at DESC, consent_id DESC"), {"u": user_id}).all()
        self.session.rollback()   # 읽기 전용 — 트랜잭션을 열어 두지 않음
        return Recipient(user_id, user.email, user.status == "active", {c.policy_code: c.granted for c in consents})
