"""T97 화면 내 알림함·수신 설정 (T95 계약 PROPOSED, T96 outbox 재사용).

- 알림함 = 본인 `notification_deliveries` 중 `channel='in_app' AND status='sent'` 행. 읽음은 `read_at`.
- 제목·요약은 저장하지 않고 조회 시 승인 템플릿 문구 + 비밀이 아닌 변수로 만듭니다(본문·링크·토큰 저장 금지 유지).
- 수신 설정 = T95 매트릭스(`SPECS`) + 사용자 선택(`notification_preferences`). 필수 유형은 항상 켜짐, 끄려 하면 422.
- 남의 알림 ID 는 없는 것과 같이 404. 알림 내용·변수는 로그에 남기지 않습니다.
`NOTIFICATIONS_API=true` 일 때만 경로가 등록됩니다(기본 꺼짐). 이메일 발송 흐름(T96 dispatcher/worker)은 바꾸지 않습니다.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.schemas.notifications import (
    InboxItem, InboxPage, MarkAllReadResult, NotificationPreference, NotificationPreferences,
    NotificationPreferencesUpdate,
)
from app.services.notifications import DEFAULT_TEMPLATES, SPECS, Template

INBOX_LIMIT = 100
TYPES = tuple(SPECS)
SUMMARY_MAX = 200


@dataclass(frozen=True)
class InboxRow:
    delivery_id: UUID
    type: str
    template_code: str
    variables: Mapping[str, str]
    created_at: datetime
    read_at: datetime | None


class NotificationInboxRepository(Protocol):
    def list_inbox(self, user_id: UUID, types: tuple[str, ...], limit: int) -> tuple[list[InboxRow], int]:
        """본인 in_app·sent 행(알려진 유형만) 최신 순(최대 limit) + 안 읽음 개수."""

    def mark_read(self, user_id: UUID, delivery_id: UUID, types: tuple[str, ...], now: datetime) -> InboxRow | None: ...

    def mark_all_read(self, user_id: UUID, types: tuple[str, ...], now: datetime) -> int: ...

    def preferences(self, user_id: UUID) -> Mapping[tuple[str, str], bool]: ...

    def set_preferences(self, user_id: UUID, changes: list[tuple[str, str, bool]], now: datetime) -> None: ...


def _text(template: Template | None, variables: Mapping[str, str]) -> tuple[str, str]:
    if template is None:
        return "알림", ""
    if template.has_secret or set(variables) != set(template.variables):
        return template.subject, ""
    try:
        body = template.body.format_map(dict(variables))
    except (KeyError, ValueError, IndexError):
        return template.subject, ""
    summary = " ".join(body.split())
    if len(summary) > SUMMARY_MAX:
        summary = summary[: SUMMARY_MAX - 1] + "…"
    return template.subject, summary


class NotificationInboxService:
    def __init__(self, repo: NotificationInboxRepository, templates: Mapping[str, Template] = DEFAULT_TEMPLATES,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.repo, self.templates = repo, templates
        self.clock = clock or (lambda: datetime.now(UTC))

    # ------------------------------------------------------------ 알림함
    def _item(self, row: InboxRow) -> InboxItem:
        title, summary = _text(self.templates.get(row.template_code), row.variables)
        return InboxItem(notification_id=row.delivery_id, type=row.type, title=title, summary=summary,
                         created_at=row.created_at, read_at=row.read_at)

    def list(self, user_id: UUID, limit: int = INBOX_LIMIT) -> InboxPage:
        rows, unread = self.repo.list_inbox(user_id, TYPES, min(max(limit, 1), INBOX_LIMIT))
        return InboxPage(items=[self._item(r) for r in rows], unread_count=unread)

    def mark_read(self, user_id: UUID, delivery_id: UUID) -> InboxItem:
        row = self.repo.mark_read(user_id, delivery_id, TYPES, self.clock())
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="notification inbox: not found or not own")
        return self._item(row)

    def mark_all_read(self, user_id: UUID) -> MarkAllReadResult:
        return MarkAllReadResult(updated=self.repo.mark_all_read(user_id, TYPES, self.clock()))

    # ------------------------------------------------------------ 수신 설정
    def preferences(self, user_id: UUID) -> NotificationPreferences:
        stored = self.repo.preferences(user_id)
        items = []
        for spec in SPECS.values():
            enabled = True if spec.required else stored.get((spec.type, spec.channel), spec.default_on)
            items.append(NotificationPreference(type=spec.type, required=spec.required, enabled=enabled,
                                                consent_policy_code=spec.consent, channels=[spec.channel]))
        return NotificationPreferences(items=items)

    def update_preferences(self, user_id: UUID, update: NotificationPreferencesUpdate) -> NotificationPreferences:
        seen: set[str] = set()
        changes: list[tuple[str, str, bool]] = []
        for change in update.items:
            spec = SPECS[change.type]
            if change.type in seen:
                raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="notification preferences: duplicate type")
            seen.add(change.type)
            if spec.required:
                if not change.enabled:   # T95 §8: 필수 유형은 끌 수 없음 (일부만 바뀌지 않도록 저장 전에 전부 검사)
                    raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="notification preferences: required type")
                continue
            changes.append((spec.type, spec.channel, change.enabled))
        if changes:
            self.repo.set_preferences(user_id, changes, self.clock())
        return self.preferences(user_id)


# ---------------------------------------------------------------- 메모리 구현 (단위 시험 전용)

@dataclass
class MemoryInboxRow:
    user_id: UUID
    row: InboxRow
    channel: str = "in_app"
    status: str = "sent"


class MemoryNotificationInboxRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, MemoryInboxRow] = {}
        self.prefs: dict[tuple[UUID, str, str], bool] = {}

    def _mine(self, user_id: UUID, types) -> list[MemoryInboxRow]:
        return [r for r in self.rows.values()
                if r.user_id == user_id and r.channel == "in_app" and r.status == "sent" and r.row.type in types]

    def list_inbox(self, user_id, types, limit):
        mine = sorted(self._mine(user_id, types), key=lambda r: (r.row.created_at, str(r.row.delivery_id)), reverse=True)
        return [r.row for r in mine[:limit]], sum(1 for r in mine if r.row.read_at is None)

    def mark_read(self, user_id, delivery_id, types, now):
        found = next((r for r in self._mine(user_id, types) if r.row.delivery_id == delivery_id), None)
        if found is None:
            return None
        if found.row.read_at is None:
            found.row = InboxRow(**{**found.row.__dict__, "read_at": now})
        return found.row

    def mark_all_read(self, user_id, types, now):
        count = 0
        for r in self._mine(user_id, types):
            if r.row.read_at is None:
                r.row = InboxRow(**{**r.row.__dict__, "read_at": now})
                count += 1
        return count

    def preferences(self, user_id):
        return {(t, c): v for (u, t, c), v in self.prefs.items() if u == user_id}

    def set_preferences(self, user_id, changes, now):
        for type_, channel, enabled in changes:
            self.prefs[(user_id, type_, channel)] = enabled
