"""T97 알림함·수신 설정 DB 접근. 표: database/migrations/0005_notifications.sql.

모든 쿼리는 user_id 로 범위를 묶습니다(본인 알림·설정만). 값은 바인딩 변수로만 전달합니다.
알림함은 `channel='in_app' AND status='sent'` 행만 다룹니다. 각 쓰기 메서드는 스스로 커밋합니다.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.services.notification_inbox import InboxRow

_COLUMNS = "delivery_id, notification_type, template_code, variables, created_at, read_at"
_MINE = ("user_id = :u AND channel = 'in_app' AND status = 'sent' AND notification_type IN :types")


def _row(r) -> InboxRow:
    variables = r.variables if isinstance(r.variables, dict) else json.loads(r.variables)
    return InboxRow(r.delivery_id, r.notification_type, r.template_code, variables, r.created_at, r.read_at)


def _types(stmt):
    return stmt.bindparams(bindparam("types", expanding=True))


class SqlNotificationInboxRepository:
    def __init__(self, session: Session) -> None:
        self.db = session

    def list_inbox(self, user_id: UUID, types: tuple[str, ...], limit: int) -> tuple[list[InboxRow], int]:
        params = {"u": user_id, "types": list(types), "limit": limit}
        rows = self.db.execute(_types(text(
            f"SELECT {_COLUMNS} FROM career.notification_deliveries WHERE {_MINE} "
            "ORDER BY created_at DESC, delivery_id DESC LIMIT :limit")), params).all()
        unread = self.db.execute(_types(text(
            f"SELECT count(*) FROM career.notification_deliveries WHERE {_MINE} AND read_at IS NULL")),
            params).scalar_one()
        self.db.rollback()   # 읽기 전용 — 트랜잭션을 열어 두지 않음
        return [_row(r) for r in rows], int(unread)

    def mark_read(self, user_id: UUID, delivery_id: UUID, types: tuple[str, ...], now: datetime) -> InboxRow | None:
        # 이미 읽었으면 처음 읽은 시각 유지(멱등)
        r = self.db.execute(_types(text(
            "UPDATE career.notification_deliveries SET read_at = COALESCE(read_at, :now) "
            f"WHERE delivery_id = :id AND {_MINE} RETURNING {_COLUMNS}")),
            {"u": user_id, "id": delivery_id, "types": list(types), "now": now}).first()
        self.db.commit()
        return None if r is None else _row(r)

    def mark_all_read(self, user_id: UUID, types: tuple[str, ...], now: datetime) -> int:
        count = self.db.execute(_types(text(
            f"UPDATE career.notification_deliveries SET read_at = :now WHERE {_MINE} AND read_at IS NULL")),
            {"u": user_id, "types": list(types), "now": now}).rowcount
        self.db.commit()
        return int(count)

    def preferences(self, user_id: UUID) -> Mapping[tuple[str, str], bool]:
        rows = self.db.execute(text(
            "SELECT notification_type, channel, enabled FROM career.notification_preferences WHERE user_id = :u"),
            {"u": user_id}).all()
        self.db.rollback()
        return {(r.notification_type, r.channel): r.enabled for r in rows}

    def set_preferences(self, user_id: UUID, changes: list[tuple[str, str, bool]], now: datetime) -> None:
        for type_, channel, enabled in changes:
            self.db.execute(text(
                "INSERT INTO career.notification_preferences (user_id, notification_type, channel, enabled, updated_at) "
                "VALUES (:u, :t, :c, :e, :now) ON CONFLICT (user_id, notification_type, channel) "
                "DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = EXCLUDED.updated_at"),
                {"u": user_id, "t": type_, "c": channel, "e": enabled, "now": now})
        self.db.commit()   # 한 요청의 변경은 한 트랜잭션(일부만 저장되지 않음)
