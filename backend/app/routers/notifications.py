"""T97 `/me/notifications`·`/me/notification-preferences` — 화면 내 알림함과 알림 수신 설정.

`NOTIFICATIONS_API=true` 일 때만 app.main.create_app 이 등록합니다(기본 꺼짐 — 계약 PROPOSED, PM 승인 전).
로그인 필수. 남의 알림 ID 는 404. 계약: docs/testing/T97_NOTIFICATION_UI_VALIDATION.md §3, T95 §8.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.notification_inbox import SqlNotificationInboxRepository
from app.schemas.notifications import (
    InboxItem, InboxPage, MarkAllReadResult, NotificationPreferences, NotificationPreferencesUpdate,
)
from app.services.notification_inbox import INBOX_LIMIT, NotificationInboxService

router = APIRouter(prefix="/me", tags=["me"], responses=error_responses(401, 503))


def get_notification_inbox_service(db: Annotated[Session, Depends(get_db)]) -> NotificationInboxService:
    return NotificationInboxService(SqlNotificationInboxRepository(db))


Service = Annotated[NotificationInboxService, Depends(get_notification_inbox_service)]


@router.get("/notifications", response_model=InboxPage, operation_id="listMyNotifications",
            summary="내 알림함 (최신 순, 안 읽음 개수)")
def list_notifications(user: CurrentUserDep, service: Service,
                       limit: Annotated[int, Query(ge=1, le=INBOX_LIMIT)] = 50) -> InboxPage:
    return service.list(user.user_id, limit)


@router.post("/notifications/read-all", response_model=MarkAllReadResult, operation_id="markAllMyNotificationsRead",
             summary="알림 모두 읽음")
def mark_all_read(user: CurrentUserDep, service: Service) -> MarkAllReadResult:
    return service.mark_all_read(user.user_id)


@router.post("/notifications/{notification_id}/read", response_model=InboxItem, operation_id="markMyNotificationRead",
             summary="알림 1건 읽음 (이미 읽었으면 그대로)", responses=error_responses(404))
def mark_read(notification_id: UUID, user: CurrentUserDep, service: Service) -> InboxItem:
    return service.mark_read(user.user_id, notification_id)


@router.get("/notification-preferences", response_model=NotificationPreferences,
            operation_id="getMyNotificationPreferences", summary="내 알림 수신 설정 (필수 유형 포함, 필수는 끌 수 없음)")
def get_preferences(user: CurrentUserDep, service: Service) -> NotificationPreferences:
    return service.preferences(user.user_id)


@router.put("/notification-preferences", response_model=NotificationPreferences,
            operation_id="updateMyNotificationPreferences", summary="선택 알림 켜기·끄기",
            responses=error_responses(422))
def update_preferences(body: NotificationPreferencesUpdate, user: CurrentUserDep,
                       service: Service) -> NotificationPreferences:
    return service.update_preferences(user.user_id, body)
