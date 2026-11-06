"""현재 사용자 식별 (T16용 임시 경계).

계약(docs/API_CONTRACT.md §1.2·§1.3): `Authorization: Bearer <JWT>`의 `sub`로만 사용자를 정한다.
실제 토큰 검증은 T15(인증·인가)에서 구현한다. 그 전까지 기본 검증기는 모든 토큰을 거부하므로
배포되더라도 `/me`는 401만 돌려준다. 테스트는 `get_token_verifier`를 바꿔 끼워 검증한다.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TokenVerifier = Callable[[str], UUID]

_bearer = HTTPBearer(auto_error=False)


class InvalidTokenError(Exception):
    pass


def _reject_all_tokens(token: str) -> UUID:
    raise InvalidTokenError("token verification is not implemented yet (T15)")


def get_token_verifier() -> TokenVerifier:
    """T15가 실제 JWT 검증 함수로 교체한다."""
    return _reject_all_tokens


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    verify: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> UUID:
    if credentials is None:
        raise _unauthorized()
    try:
        return verify(credentials.credentials)
    except InvalidTokenError:
        raise _unauthorized() from None
