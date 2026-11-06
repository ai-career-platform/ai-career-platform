"""T14/T15 integration ports. Default is fail closed, never mock authentication.

T15 must replace get_authenticated_user with verified sub/session validation.
T14 must bind get_profile_repository to a request-scoped psycopg connection.
Only tests override these dependencies on their own create_app() instance.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.profile_problems import ProfileProblem
from app.repositories.profile import ProfileRepository

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID


def get_authenticated_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthenticatedUser:
    if credentials is None:
        raise ProfileProblem(401, "UNAUTHENTICATED", "Authentication required")
    # Do not parse/trust sub from an unsigned token or accept user IDs as tokens.
    raise ProfileProblem(503, "DEPENDENCY_UNAVAILABLE", "Authentication integration unavailable")


def get_profile_repository() -> ProfileRepository:
    raise ProfileProblem(503, "DEPENDENCY_UNAVAILABLE", "Profile storage unavailable")
