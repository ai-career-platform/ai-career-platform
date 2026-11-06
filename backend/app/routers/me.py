"""`/api/v1/me` — 내 계정·프로필 (T16).

user_id는 경로·쿼리·본문 어디에서도 받지 않고 인증 주체에서만 얻는다.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import get_current_user_id
from app.repositories.user_profile import UserProfileRepository
from app.schemas.me import Me, MePatch
from app.services import me as me_service

router = APIRouter(prefix="/me", tags=["me"])

CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]


def get_user_profile_repository() -> UserProfileRepository:
    """T14 병합 후 PostgreSQL 저장소로 교체한다. 그 전에는 저장소가 없음을 503으로 알린다."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="User profile storage is not configured",
    )


Repository = Annotated[UserProfileRepository, Depends(get_user_profile_repository)]

_ERRORS = {
    401: {"description": "토큰 없음·만료·위조"},
    404: {"description": "토큰은 유효하지만 사용자가 없음"},
}


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


@router.get("", response_model=Me, summary="내 계정·프로필", responses=_ERRORS)
def read_me(user_id: CurrentUserId, repository: Repository) -> Me:
    try:
        return me_service.get_me(repository, user_id)
    except me_service.UserNotFoundError:
        raise _not_found() from None


@router.patch(
    "",
    response_model=Me,
    summary="내 프로필 수정 (보낸 필드만 변경, null은 지움)",
    responses=_ERRORS,
)
def update_me(patch: MePatch, user_id: CurrentUserId, repository: Repository) -> Me:
    try:
        return me_service.update_me(repository, user_id, patch)
    except me_service.UserNotFoundError:
        raise _not_found() from None
