"""T84 단위 테스트용 메모리 저장소. SqlAdminAuditRepository 와 같은 의미로 동작한다.

정렬: (occurred_at, audit_event_id) 내림차순. Python UUID 비교(정수)는 PostgreSQL uuid 비교(바이트 순)와 같다.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy.exc import OperationalError

from app.repositories.admin_audit import NEVER, READ_ACTION_CODE, READ_RESOURCE_TYPE, AuditRow, UsageRow
from app.services.admin_audit import KST


@dataclass
class UsageRecord:
    occurred_at: datetime
    feature_code: str
    provider_model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal | None
    user_id: uuid.UUID | None = None


class MemoryAdminAuditRepository:
    def __init__(self, now: datetime) -> None:
        self.events: list[AuditRow] = []
        self.usage_records: list[UsageRecord] = []
        self.current = now
        self.fail: set[str] = set()
        self.commits = 0
        self.timeouts: list[int] = []
        self._pending: list[AuditRow] = []

    def _maybe_fail(self, op: str) -> None:
        if op in self.fail:
            raise OperationalError("SELECT", {}, Exception("synthetic failure"))

    def now(self) -> datetime:
        self._maybe_fail("now")
        return self.current

    def set_statement_timeout(self, milliseconds: int) -> None:
        self.timeouts.append(milliseconds)

    def list_events(self, f, after, exclude, limit):
        self._maybe_fail("list")
        rows = [r for r in self.events + self._pending
                if f.start <= r.occurred_at < f.end
                and (f.actor_user_id is None or r.actor_user_id == f.actor_user_id)
                and (f.action_code is None or r.action_code == f.action_code)
                and (f.resource_type is None or r.resource_type == f.resource_type)
                and (f.request_id is None or r.request_id == f.request_id)
                and (after is None or (r.occurred_at, r.audit_event_id) < after)
                and r.audit_event_id != exclude]
        rows.sort(key=lambda r: (r.occurred_at, r.audit_event_id), reverse=True)
        return rows[:limit]

    def record_read(self, actor_user_id, request_id):
        self._maybe_fail("record")
        row = AuditRow(uuid.uuid4(), actor_user_id, READ_ACTION_CODE, READ_RESOURCE_TYPE, None, request_id,
                       self.current)
        self._pending.append(row)
        return row.audit_event_id, row.occurred_at

    def usage(self, group_by, start, end, *, proposed_cost, cost_known_since):
        self._maybe_fail("usage")
        known = cost_known_since or NEVER
        groups: dict[str, list[UsageRecord]] = defaultdict(list)
        for r in self.usage_records:
            if start <= r.occurred_at < end:
                key = (r.occurred_at.astimezone(KST).date().isoformat() if group_by == "day"
                       else getattr(r, group_by))
                groups[key].append(r)
        out = []
        for key in sorted(groups):
            rs = groups[key]
            if proposed_cost:
                priced = [r.estimated_cost_usd for r in rs if r.estimated_cost_usd is not None and r.occurred_at >= known]
                cost = sum(priced) if priced else None
                unpriced = sum(1 for r in rs if r.estimated_cost_usd is None or r.occurred_at < known)
            else:
                values = [r.estimated_cost_usd for r in rs if r.estimated_cost_usd is not None]
                cost, unpriced = (sum(values) if values else None), 0
            out.append(UsageRow(key, len(rs), sum(r.input_tokens for r in rs), sum(r.output_tokens for r in rs),
                                cost, unpriced))
        return out

    def commit(self) -> None:
        self._maybe_fail("commit")
        self.events.extend(self._pending)
        self._pending.clear()
        self.commits += 1

    def rollback(self) -> None:
        self._pending.clear()
