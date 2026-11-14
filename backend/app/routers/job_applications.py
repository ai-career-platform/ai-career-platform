"""T102 `/me/job-applications` — 개인 지원 기록 (T101 제안 계약, 사용자가 직접 기록한 상태).

`JOB_APPLICATIONS_API=true` 일 때만 app.main.create_app 이 등록합니다(기본 꺼짐 — 표가 제안 단계, PM 승인 전).
로그인 필수. 남의 기록은 404.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth_config import AuthSettings
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep, get_auth_settings
from app.repositories.job_applications import SqlJobApplicationRepository
from app.schemas.job_applications import (
    ApplicationStage, JobApplication, JobApplicationCreate, JobApplicationPage, JobApplicationUpdate,
)
from app.repositories.notification_inbox import SqlNotificationInboxRepository
from app.repositories.notifications import SqlNotificationOutbox, SqlRecipientDirectory
from app.services.job_applications import JobApplicationService
from app.services.job_postings import ListCursor, derive_cursor_key
from app.services.notification_events import EventNotifier
from app.services.notifications import NotificationDispatcher

router = APIRouter(prefix="/me/job-applications", tags=["me"], responses=error_responses(401, 503))


def _in_app_dispatcher(db: Session) -> NotificationDispatcher:
    return NotificationDispatcher(SqlNotificationOutbox(db), SqlRecipientDirectory(db),
                                  preferences=SqlNotificationInboxRepository(db))


def get_job_application_service(db: Annotated[Session, Depends(get_db)],
                                settings: Annotated[AuthSettings, Depends(get_auth_settings)]) -> JobApplicationService:
    # 단계 변경 in_app 알림: 스위치 꺼짐·유형 미승인이라 현재 DB 에 아무것도 쓰지 않음 (notification_events)
    return JobApplicationService(SqlJobApplicationRepository(db), ListCursor(derive_cursor_key(settings.jwt_secret)),
                                 events=EventNotifier(lambda: _in_app_dispatcher(db)))


Service = Annotated[JobApplicationService, Depends(get_job_application_service)]


@router.get("", response_model=JobApplicationPage, operation_id="listMyJobApplications",
            summary="내 지원 기록 (최근 수정순, 사용자가 직접 기록한 상태)", responses=error_responses(400))
def list_applications(user: CurrentUserDep, service: Service,
                      stage: Annotated[list[ApplicationStage] | None, Query(max_length=7)] = None,
                      limit: Annotated[int, Query(ge=1, le=100)] = 20,
                      cursor: Annotated[str | None, Query(max_length=500)] = None) -> JobApplicationPage:
    return service.list(user.user_id, stage, limit, cursor)


@router.post("", response_model=JobApplication, status_code=201, operation_id="createMyJobApplication",
             summary="지원 기록 추가 (같은 공고는 1건)", responses=error_responses(404, 409))
def create_application(body: JobApplicationCreate, user: CurrentUserDep, service: Service) -> JobApplication:
    return service.create(user.user_id, body)


@router.get("/{application_id}", response_model=JobApplication, operation_id="getMyJobApplication",
            summary="지원 기록 1건", responses=error_responses(404))
def get_application(application_id: UUID, user: CurrentUserDep, service: Service) -> JobApplication:
    return service.get(user.user_id, application_id)


@router.patch("/{application_id}", response_model=JobApplication, operation_id="updateMyJobApplication",
              summary="단계·날짜·메모 수정 (version 이 다르면 409)", responses=error_responses(404, 409))
def update_application(application_id: UUID, body: JobApplicationUpdate, user: CurrentUserDep,
                       service: Service) -> JobApplication:
    return service.update(user.user_id, application_id, body)


@router.delete("/{application_id}", status_code=204, operation_id="deleteMyJobApplication",
               summary="지원 기록 삭제 (즉시 물리 삭제)", responses=error_responses(404))
def delete_application(application_id: UUID, user: CurrentUserDep, service: Service) -> None:
    service.delete(user.user_id, application_id)
