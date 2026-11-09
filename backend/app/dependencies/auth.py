"""인증·인가 의존성 (API_CONTRACT §1.3, NFR-SEC-002).

- `get_current_user`: Bearer 토큰 → 401(UNAUTHENTICATED / TOKEN_EXPIRED).
  매 요청 DB에서 세션(폐기·만료)·사용자 상태·역할을 다시 읽으므로, 로그아웃·역할 회수·정지는
  다음 요청부터 바로 반영된다(토큰 안의 `roles`는 신뢰하지 않음).
- `require_roles` / `require_permissions`: 역할·권한 없음 → 403(FORBIDDEN).
- `ensure_owner`: 다른 사람 리소스 → 404(NOT_FOUND)로 존재를 숨김.

기능 라우터 사용 예:
    @router.get("/admin/audit", dependencies=[Depends(require_roles("admin"))])
    def list_audit(user: CurrentUserDep): ...

    doc = repo.get_document(document_id)
    ensure_owner(doc.owner_user_id if doc else None, user)
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth_config import AuthSettings
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import AttemptLimiter
from app.core.security import AccessClaims, TokenExpired, TokenInvalid, decode_access_token
from app.db import get_db
from app.repositories.auth import AuthRepository, SqlAuthRepository
from app.services.auth import AuthService, is_session_active

_bearer = HTTPBearer(auto_error=False)


def get_auth_settings(request: Request) -> AuthSettings:
    return request.app.state.auth_settings


def get_attempt_limiter(request: Request) -> AttemptLimiter:
    return request.app.state.attempt_limiter


def get_auth_repository(session: Annotated[Session, Depends(get_db)]) -> AuthRepository:
    return SqlAuthRepository(session)


def get_auth_service(
    repo: Annotated[AuthRepository, Depends(get_auth_repository)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    limiter: Annotated[AttemptLimiter, Depends(get_attempt_limiter)],
) -> AuthService:
    return AuthService(repo, settings, limiter)


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    session_id: uuid.UUID
    roles: frozenset[str]
    permissions: frozenset[str]


def get_access_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AccessClaims:
    """토큰 서명·만료만 검사한다. DB 연결 전에 실패시켜 미인증 요청이 DB 자원을 쓰지 않게 한다."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise AppError(ErrorCode.UNAUTHENTICATED, log_detail="bearer token missing")
    try:
        return decode_access_token(settings.jwt_secret, credentials.credentials)
    except TokenExpired:
        raise AppError(ErrorCode.TOKEN_EXPIRED) from None
    except TokenInvalid:
        raise AppError(ErrorCode.UNAUTHENTICATED, log_detail="bearer token invalid") from None


def get_current_user(
    claims: Annotated[AccessClaims, Depends(get_access_claims)],
    repo: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> CurrentUser:
    session = repo.get_session(claims.session_id)
    if not is_session_active(session, datetime.now(UTC)) or session.user_id != claims.user_id:
        raise AppError(ErrorCode.UNAUTHENTICATED, log_detail="session revoked, expired or mismatched")
    user = repo.get_user(claims.user_id)
    if user is None or user.status != "active":
        raise AppError(ErrorCode.UNAUTHENTICATED, log_detail="user missing or disabled")
    return CurrentUser(
        user_id=claims.user_id,
        session_id=claims.session_id,
        roles=frozenset(repo.role_codes(claims.user_id)),
        permissions=frozenset(repo.permission_codes(claims.user_id)),
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    """나열한 역할 중 하나라도 있으면 통과."""
    wanted = frozenset(roles)

    def checker(user: CurrentUserDep) -> CurrentUser:
        if not wanted & user.roles:
            raise AppError(ErrorCode.FORBIDDEN, log_detail=f"requires {sorted(wanted)}")
        return user

    return checker


def require_permissions(*permissions: str) -> Callable[[CurrentUser], CurrentUser]:
    """나열한 권한을 모두 가져야 통과."""
    wanted = frozenset(permissions)

    def checker(user: CurrentUserDep) -> CurrentUser:
        if not wanted <= user.permissions:
            raise AppError(ErrorCode.FORBIDDEN, log_detail=f"requires {sorted(wanted)}")
        return user

    return checker


def ensure_owner(owner_user_id: uuid.UUID | None, user: CurrentUser) -> None:
    """리소스가 없거나 다른 사람 소유면 404."""
    if owner_user_id is None or owner_user_id != user.user_id:
        raise AppError(ErrorCode.NOT_FOUND, log_detail="resource missing or owned by another user")
