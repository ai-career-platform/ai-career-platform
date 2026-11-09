"""T16 bindings reuse the T14 request Session and T15 verified principal."""
from typing import Annotated
from fastapi import Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.dependencies.auth import CurrentUser as AuthenticatedUser, get_current_user as get_authenticated_user
from app.repositories.profile import PostgresProfileRepository, ProfileRepository


def get_profile_repository(session: Annotated[Session, Depends(get_db)]) -> ProfileRepository:
    return PostgresProfileRepository(session)
