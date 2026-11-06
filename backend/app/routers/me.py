"""`/me`, `/me/permissions`, `/me/sessions` (openapi.yaml tag `me`).

사용자는 토큰의 `sub`로만 정한다. 경로·본문·쿼리로 user_id를 받지 않는다 (API_CONTRACT §1.3).
`PATCH /me`(프로필 수정)는 T16 범위.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.dependencies.auth import CurrentUserDep, get_auth_repository, get_auth_service
from app.repositories.auth import AuthRepository
from app.schemas.auth import Me, Permissions, Profile, Session
from app.services.auth import AuthService

router = APIRouter(prefix="/me", tags=["me"], responses=error_responses(401))


@router.get("", response_model=Me)
def get_me(user: CurrentUserDep, repo: Annotated[AuthRepository, Depends(get_auth_repository)]) -> Me:
    record = repo.get_user(user.user_id)
    if record is None:
        raise AppError(ErrorCode.UNAUTHENTICATED, log_detail="user vanished")
    return Me(
        user_id=record.user_id, email=record.email, display_name=record.display_name,
        status=record.status, created_at=record.created_at,
        profile=Profile(headline=record.headline, bio=record.bio, location_text=record.location_text),
    )


@router.get("/permissions", response_model=Permissions)
def get_my_permissions(user: CurrentUserDep) -> Permissions:
    return Permissions(roles=sorted(user.roles), permissions=sorted(user.permissions))


@router.get("/sessions", response_model=list[Session])
def list_my_sessions(user: CurrentUserDep, service: Annotated[AuthService, Depends(get_auth_service)]) -> list[Session]:
    return [
        Session(
            session_id=s.session_id, user_agent=s.user_agent, created_at=s.created_at,
            expires_at=s.expires_at, is_current=s.session_id == user.session_id,
        )
        for s in service.list_sessions(user.user_id)
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404))
def revoke_my_session(
    session_id: uuid.UUID, user: CurrentUserDep, service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    service.revoke_my_session(user.user_id, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
