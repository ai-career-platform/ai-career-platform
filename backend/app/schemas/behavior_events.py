"""T72 행동 이벤트 요청·응답 DTO. 규칙은 T71 계약(docs/data/BEHAVIOR_EVENT_CONTRACT.md §3)과
mock 수집 함수(database/tests/behavior/T71_behavior_events_mock.sql)를 그대로 따른다.

- user_id는 받지 않는다(extra="forbid"). 사용자는 인증 토큰으로만 정한다.
- event_id는 클라이언트 중복 요청 식별자(UUID v4)다. DB 기본키로 그대로 쓰지 않는다(services/behavior_events.py).
"""
import json
import math
import re
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator, model_validator

TRACKING_EVENTS: dict[str, frozenset[str]] = {
    "page.view": frozenset({"page_id", "referrer_type"}),
    "search.submit": frozenset({"search_type", "filter_count", "result_count"}),
    "posting.view": frozenset({"job_posting_id", "list_position"}),
    "role.view": frozenset({"job_role_id"}),
    "skill_gap.view": frozenset({"job_role_id", "gap_count"}),
}
# T71 제안(personalization 정책)은 미승인이다. 형식은 검사하되 저장하지 않는다.
PERSONALIZATION_EVENTS: dict[str, frozenset[str]] = {
    "posting.bookmark": frozenset({"job_posting_id"}),
    "recommendation.click": frozenset({"recommendation_id", "rank"}),
    "recommendation.dismiss": frozenset({"recommendation_id", "reason_code"}),
}
ALLOWED_KEYS = {**TRACKING_EVENTS, **PERSONALIZATION_EVENTS}
TRACKING_POLICY = "behavior_tracking"

EventCode = Literal[
    "page.view", "search.submit", "posting.view", "role.view", "skill_gap.view",
    "posting.bookmark", "recommendation.click", "recommendation.dismiss",
]
MAX_METADATA_KEYS = 10
MAX_METADATA_BYTES = 1024
ID_OR_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
NIL_UUIDS = {UUID(int=0), UUID(int=(1 << 128) - 1)}


def metadata_size(metadata: dict[str, Any]) -> int:
    """PostgreSQL `octet_length(metadata::text)`과 같은 방식(`{"k": v, ...}`)으로 센 바이트 수."""
    return len(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))


class BehaviorEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_code: EventCode
    event_at: AwareDatetime
    metadata: dict[str, Any] | None = None

    @field_validator("event_id")
    @classmethod
    def _event_id(cls, value: UUID) -> UUID:
        if value in NIL_UUIDS or value.version != 4:
            raise ValueError("event_id must be a random UUID v4")
        return value

    @field_validator("metadata")
    @classmethod
    def _metadata_values(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if not value:
            return None  # 비어 있으면 NULL로 저장 (T71 §3)
        if len(value) > MAX_METADATA_KEYS:
            raise ValueError("too many metadata keys")
        for key, item in value.items():
            if isinstance(item, bool):
                continue
            if isinstance(item, (int, float)):
                if isinstance(item, float) and not math.isfinite(item):
                    raise ValueError(f"metadata {key} must be a finite number")
                continue
            if isinstance(item, str) and ID_OR_CODE.fullmatch(item):
                continue
            # 공백이 들어간 문장(검색어 원문·자유 입력), 중첩 객체, 배열, null은 모두 거부
            raise ValueError(f"metadata {key} must be a number, boolean, id or code")
        if metadata_size(value) > MAX_METADATA_BYTES:
            raise ValueError("metadata is larger than 1KB")
        return value

    @model_validator(mode="after")
    def _metadata_keys(self) -> "BehaviorEventInput":
        unknown = set(self.metadata or {}) - ALLOWED_KEYS[self.event_code]
        if unknown:
            raise ValueError(f"metadata keys not allowed for {self.event_code}: {sorted(unknown)}")
        return self

    @property
    def is_tracking(self) -> bool:
        return self.event_code in TRACKING_EVENTS


BehaviorEventStatus = Literal[
    "recorded", "duplicate", "blocked_no_consent", "blocked_policy_pending", "collection_disabled",
]


class BehaviorEventResult(BaseModel):
    """recorded만 저장된 것이다. 나머지는 저장하지 않았다는 정상 응답이다 (T71 §5 "버림")."""

    event_id: UUID
    status: BehaviorEventStatus


def event_at_window_error(event_at: datetime, now: datetime) -> bool:
    """서버 시각보다 5분 넘게 미래이거나 7일보다 오래되면 거부 (T71 §3, mock과 같은 경계)."""
    return event_at > now + timedelta(minutes=5) or event_at < now - timedelta(days=7)
