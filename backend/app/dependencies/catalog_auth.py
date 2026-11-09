"""T17 optional authentication, composed from the existing T15 dependencies.

No Authorization header means anonymous catalog access. If a header is
present, T15 validates its token and checks the current session/user state.
This does not add a second JWT verifier or trust user IDs from the client.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.auth_config import AuthSettings
from app.core.security import AccessClaims
from app.db import get_db
from app.dependencies.auth import (
    CurrentUser, get_access_claims, get_auth_repository, get_auth_settings, get_current_user,
)
from app.repositories.auth import AuthRepository

_optional_bearer = HTTPBearer(auto_error=False)


def get_optional_catalog_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> AccessClaims | None:
    if request.headers.get("Authorization") is None:
        return None
    return get_access_claims(credentials, settings)


def get_optional_catalog_auth_repository(
    request: Request,
    claims: Annotated[AccessClaims | None, Depends(get_optional_catalog_claims)],
) -> Iterator[AuthRepository | None]:
    if claims is None:
        yield None
        return
    # Only authenticated requests acquire an auth DB session. T14 still owns
    # exception translation and cleanup on success and error.
    with contextmanager(get_db)(request) as session:
        yield get_auth_repository(session)


def get_optional_catalog_user(
    claims: Annotated[AccessClaims | None, Depends(get_optional_catalog_claims)],
    repository: Annotated[AuthRepository | None, Depends(get_optional_catalog_auth_repository)],
) -> CurrentUser | None:
    if claims is None:
        return None
    return get_current_user(claims, repository)
