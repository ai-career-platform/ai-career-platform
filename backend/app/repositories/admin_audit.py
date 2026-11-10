"""T84 감사 기록·AI 사용량 읽기 저장소 (0001 실제 컬럼만 사용).

- `career.audit_events` 7컬럼, `career.ai_usage_records` 10컬럼 중 필요한 것만 SELECT 한다.
  T83 제안 컬럼(result, metadata, recorded_at 등)은 Migration 전이라 쓰지 않는다.
- 모든 값은 바인딩 파라미터로 넘긴다. 문자열로 붙이는 것은 아래 고정 목록(정렬·묶음 식)뿐이다.
- 쓰기는 PROPOSED 감사 조회 기록(`admin.audit.view`) INSERT 하나뿐이며, 운영 경로에서는 쓰지 않는다(D4 미승인).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

AUDIT_COLUMNS = ("audit_event_id", "actor_user_id", "action_code", "resource_type", "resource_id",
                 "request_id", "occurred_at")
NEVER = datetime(9999, 12, 31, tzinfo=UTC)
READ_ACTION_CODE = "admin.audit.view"
READ_RESOURCE_TYPE = "audit_events"

# group_by 값 → SQL 식. 사용자 입력을 SQL에 붙이지 않도록 이 표에 있는 식만 쓴다.
# day 는 KST(Asia/Seoul, UTC+9, 일광절약시간 없음) 날짜.
GROUP_EXPRESSIONS = {
    "day": "to_char((occurred_at AT TIME ZONE 'Asia/Seoul')::date, 'YYYY-MM-DD')",
    "feature_code": "feature_code",
    "provider_model": "provider_model",
}


@dataclass(frozen=True)
class AuditFilter:
    start: datetime                 # 포함
    end: datetime                   # 제외 (첫 페이지에서 min(to, as_of) 로 고정)
    actor_user_id: UUID | None = None
    action_code: str | None = None
    resource_type: str | None = None   # PROPOSED 필터 (HTTP 미노출)
    request_id: str | None = None      # PROPOSED 필터 (HTTP 미노출)


@dataclass(frozen=True)
class AuditRow:
    audit_event_id: UUID
    actor_user_id: UUID | None
    action_code: str
    resource_type: str
    resource_id: UUID | None
    request_id: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class UsageRow:
    key: str
    request_count: int
    input_tokens: int
    output_tokens: int
    cost_sum: Decimal | None          # proposed_cost 이면 cost_known_since 규칙을 적용한 합
    unpriced_request_count: int


class AdminAuditRepository(Protocol):
    def now(self) -> datetime: ...
    def set_statement_timeout(self, milliseconds: int) -> None: ...
    def list_events(self, f: AuditFilter, after: tuple[datetime, UUID] | None, exclude: UUID | None,
                    limit: int) -> list[AuditRow]: ...
    def record_read(self, actor_user_id: UUID, request_id: str | None) -> tuple[UUID, datetime]: ...
    def usage(self, group_by: str, start: datetime, end: datetime, *, proposed_cost: bool,
              cost_known_since: datetime | None) -> list[UsageRow]: ...
    def commit(self) -> None: ...


class SqlAdminAuditRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def now(self) -> datetime:
        # 트랜잭션 시작 시각. 같은 트랜잭션의 INSERT 기본값(now())과 같은 값이다.
        return self.session.execute(text("SELECT now()")).scalar_one()

    def set_statement_timeout(self, milliseconds: int) -> None:
        # SET LOCAL 은 바인딩 파라미터를 받지 않는다 → 정수만 허용해 붙인다.
        self.session.execute(text(f"SET LOCAL statement_timeout = {int(milliseconds)}"))

    def list_events(self, f, after, exclude, limit):
        where = ["occurred_at >= :start", "occurred_at < :end"]
        params: dict = {"start": f.start, "end": f.end, "limit": limit}
        for column in ("actor_user_id", "action_code", "resource_type", "request_id"):
            value = getattr(f, column)
            if value is not None:
                where.append(f"{column} = :{column}")
                params[column] = value
        if after is not None:
            where.append("(occurred_at, audit_event_id) < (:after_at, :after_id)")
            params["after_at"], params["after_id"] = after
        if exclude is not None:
            where.append("audit_event_id <> :exclude")
            params["exclude"] = exclude
        sql = (f"SELECT {', '.join(AUDIT_COLUMNS)} FROM career.audit_events WHERE {' AND '.join(where)} "
               "ORDER BY occurred_at DESC, audit_event_id DESC LIMIT :limit")
        return [AuditRow(*row) for row in self.session.execute(text(sql), params)]

    def record_read(self, actor_user_id, request_id):
        row = self.session.execute(text(
            "INSERT INTO career.audit_events (actor_user_id, action_code, resource_type, resource_id, request_id) "
            "VALUES (:actor, :action, :resource, NULL, :request_id) RETURNING audit_event_id, occurred_at"),
            {"actor": actor_user_id, "action": READ_ACTION_CODE, "resource": READ_RESOURCE_TYPE,
             "request_id": request_id}).one()
        return row[0], row[1]

    def usage(self, group_by, start, end, *, proposed_cost, cost_known_since):
        key = GROUP_EXPRESSIONS[group_by]
        if not proposed_cost:
            # 확정 계약 경로: 저장된 추정값을 그대로 합한다(0은 '미기록'일 수 있음 → 라우터가 미확인 표시).
            cost = "sum(estimated_cost_usd)"
            unpriced = "0"
            params = {"start": start, "end": end}
        else:
            # PROPOSED(D2): 경계 시각 이전 행과 NULL 행은 '비용 미확인' — 0으로 더하지 않는다.
            cost = "sum(estimated_cost_usd) FILTER (WHERE estimated_cost_usd IS NOT NULL AND occurred_at >= :known)"
            unpriced = "count(*) FILTER (WHERE estimated_cost_usd IS NULL OR occurred_at < :known)"
            # 경계 시각이 없으면(D2 Migration 전) 모든 행이 미확인이다.
            params = {"start": start, "end": end, "known": cost_known_since or NEVER}
        sql = (f"SELECT {key} AS key, count(*), coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0), "
               f"{cost}, {unpriced} FROM career.ai_usage_records "
               "WHERE occurred_at >= :start AND occurred_at < :end GROUP BY 1 ORDER BY 1")
        return [UsageRow(r[0], int(r[1]), int(r[2]), int(r[3]), r[4], int(r[5]))
                for r in self.session.execute(text(sql), params)]

    def commit(self) -> None:
        self.session.commit()
