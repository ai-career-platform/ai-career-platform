"""T16 persistence using the existing request-scoped T14 SQLAlchemy Session."""
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.errors import AppError, ErrorCode
from app.models.auth import User, UserProfile
from app.repositories.auth import SqlAuthRepository
from app.schemas.profile import Me, Profile


class ProfileRepository(Protocol):
    def get(self, user_id: UUID) -> Me | None: ...
    def patch(self, user_id: UUID, changes: Mapping[str, str | None]) -> Me | None: ...


class PostgresProfileRepository:
    PROFILE_FIELDS = ("headline", "bio", "location_text")

    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id: UUID) -> Me | None:
        try:
            row = SqlAuthRepository(self.session).get_user(user_id)
            if row is None or row.status != "active":
                return None
            return Me(user_id=row.user_id, email=row.email, display_name=row.display_name,
                      status=row.status, created_at=row.created_at,
                      profile=Profile(headline=row.headline, bio=row.bio, location_text=row.location_text))
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

    def patch(self, user_id: UUID, changes: Mapping[str, str | None]) -> Me | None:
        if not changes or set(changes) - {"display_name", *self.PROFILE_FIELDS}:
            raise ValueError("Unsupported profile fields")
        try:
            # Auth SELECTs may already have started this Session transaction.
            # Lock the parent first, including when a profile row does not yet exist.
            user = self.session.scalar(select(User).where(
                User.user_id == user_id, User.status == "active"
            ).with_for_update().execution_options(populate_existing=True))
            if user is None:
                self.session.rollback()
                return None
            now = datetime.now(UTC)
            user.updated_at = now
            if "display_name" in changes:
                user.display_name = changes["display_name"]
            fields = [f for f in self.PROFILE_FIELDS if f in changes]
            if fields:
                profile = self.session.get(UserProfile, user_id, populate_existing=True)
                if profile is None:
                    profile = UserProfile(user_id=user_id, created_at=now)
                    self.session.add(profile)
                for field in fields:
                    setattr(profile, field, changes[field])
                profile.updated_at = now
            self.session.flush()
            result = self.get(user_id)
            self.session.commit()
            return result
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
        except Exception:
            self.session.rollback()
            raise
