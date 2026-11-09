"""T35 repository binding."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.repositories.target_roles import PostgresTargetRoleRepository, TargetRoleRepository


def get_target_role_repository(session: Annotated[Session, Depends(get_db)]) -> TargetRoleRepository:
    return PostgresTargetRoleRepository(session)
