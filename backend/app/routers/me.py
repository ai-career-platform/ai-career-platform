"""`/api/v1/me` — 내 계정·프로필 (T16).

user_id는 경로·쿼리·본문 어디에서도 받지 않고 인증 주체에서만 얻는다.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user_id
from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.repositories.user_profile import UserProfileRepository
from app.repositories.user_profile_postgres import PostgresUserProfileRepository
from app.schemas.me import Me, MePatch
from app.services import me as me_service

router = APIRouter(prefix="/me", tags=["me"], responses=error_responses(401, 404, 503))

CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]


def get_user_profile_repository(session: Annotated[Session, Depends(get_db)]) -> UserProfileRepository:
    """T14 `get_db`의 Session으로 PostgreSQL 저장소를 만든다.

    DATABASE_URL이 없으면 `get_db`가 503 DEPENDENCY_UNAVAILABLE을 낸다.
    """
    return PostgresUserProfileRepository(session)


Repository = Annotated[UserProfileRepository, Depends(get_user_profile_repository)]


@router.get("", response_model=Me, summary="내 계정·프로필")
def read_me(user_id: CurrentUserId, repository: Repository) -> Me:
    try:
        return me_service.get_me(repository, user_id)
    except me_service.UserNotFoundError:
        raise AppError(ErrorCode.NOT_FOUND, log_detail="user row missing for token subject") from None


@router.patch("", response_model=Me, summary="내 프로필 수정 (보낸 필드만 변경, null은 지움)")
def update_me(patch: MePatch, user_id: CurrentUserId, repository: Repository) -> Me:
    try:
        return me_service.update_me(repository, user_id, patch)
    except me_service.UserNotFoundError:
        raise AppError(ErrorCode.NOT_FOUND, log_detail="user row missing for token subject") from None
