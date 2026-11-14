"""T97 알림함·수신 설정 DTO.

- 수신 설정: T95 제안 OpenAPI(docs/notifications/t95_openapi_proposal.yaml) 그대로.
- 알림함: T97 화면 계약(frontend/src/api/notifications.ts, docs/testing/T97_NOTIFICATION_UI_VALIDATION.md §3).
본문 전체·링크·토큰·이메일은 담지 않습니다.
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NotificationTypeName = Literal[
    "security.password_reset", "security.password_changed", "security.new_login", "account.email_verification",
    "account.recovery_notice", "account.deletion_receipt", "service.policy_change", "service.maintenance",
    "recommendation.new_results", "marketing.newsletter",
]
Channel = Literal["email", "in_app"]


class NotificationPreference(BaseModel):
    type: NotificationTypeName
    required: bool
    enabled: bool
    consent_policy_code: str | None
    channels: list[Channel]


class NotificationPreferences(BaseModel):
    items: list[NotificationPreference]


class NotificationPreferenceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: NotificationTypeName
    enabled: bool


class NotificationPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[NotificationPreferenceChange] = Field(min_length=1, max_length=20)


class InboxItem(BaseModel):
    notification_id: UUID
    type: NotificationTypeName
    title: str
    summary: str
    created_at: datetime
    read_at: datetime | None


class InboxPage(BaseModel):
    items: list[InboxItem]
    unread_count: int


class MarkAllReadResult(BaseModel):
    updated: int
