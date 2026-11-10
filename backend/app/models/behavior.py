"""T72 행동 이벤트 ORM 매핑 (database/DATA_DICTIONARY.md F07, 0001 `career.behavior_events`).

테이블은 0001 Migration 그대로 쓴다. T71이 제안한 policy_code·retain_until 컬럼은 아직 Migration에 없어
매핑하지 않는다(docs/data/BEHAVIOR_EVENT_CONTRACT.md §10-3).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.auth import SCHEMA
from app.models.base import Base


class BehaviorEvent(Base):
    __tablename__ = "behavior_events"
    __table_args__ = {"schema": SCHEMA}

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.user_id", ondelete="CASCADE"))
    event_code: Mapped[str] = mapped_column(String(80))
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
