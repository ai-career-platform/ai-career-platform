"""인증·권한 DB 접근 (database/DATA_DICTIONARY.md A01~A08, B01, B09 기준, 스키마 `career`).

서비스는 `AuthRepository` 프로토콜에만 의존한다. 운영은 `SqlAuthRepository`(T14 `get_db`의 SQLAlchemy Session),
테스트는 `tests/fakes.py`의 메모리 구현을 쓴다. 쓰기는 서비스가 `commit()`을 호출해야 확정된다.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import (
    AuthIdentity,
    AuthSession,
    ConsentPolicy,
    Permission,
    Role,
    RolePermission,
    User,
    UserConsent,
    UserProfile,
    UserRole,
)


@dataclass(frozen=True)
class UserRecord:
    user_id: uuid.UUID
    email: str
    display_name: str
    status: str
    created_at: datetime
    headline: str | None = None
    bio: str | None = None
    location_text: str | None = None


@dataclass(frozen=True)
class LocalIdentity:
    user_id: uuid.UUID
    password_hash: str | None
    status: str


@dataclass(frozen=True)
class SessionRecord:
    session_id: uuid.UUID
    user_id: uuid.UUID
    user_agent: str | None
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class PolicyRecord:
    policy_code: str
    version: str
    is_required: bool
    content_url: str
    effective_at: datetime


@dataclass(frozen=True)
class NewUser:
    email: str
    email_canonical: str
    display_name: str
    password_hash: str
    consents: list[tuple[str, str, bool]]  # (policy_code, version, granted)
    role_code: str


class EmailTaken(Exception):
    pass


class AuthRepository(Protocol):
    def current_policies(self, now: datetime) -> list[PolicyRecord]: ...
    def email_exists(self, email_canonical: str) -> bool: ...
    def create_user(self, new: NewUser, now: datetime) -> uuid.UUID: ...
    def find_local_identity(self, email_canonical: str) -> LocalIdentity | None: ...
    def update_password_hash(self, user_id: uuid.UUID, password_hash: str, now: datetime) -> None: ...
    def touch_last_login(self, user_id: uuid.UUID, now: datetime) -> None: ...
    def get_user(self, user_id: uuid.UUID) -> UserRecord | None: ...
    def role_codes(self, user_id: uuid.UUID) -> list[str]: ...
    def permission_codes(self, user_id: uuid.UUID) -> list[str]: ...
    def create_session(
        self, user_id: uuid.UUID, refresh_hash: str, user_agent: str | None, now: datetime, expires_at: datetime
    ) -> uuid.UUID: ...
    def get_session(self, session_id: uuid.UUID) -> SessionRecord | None: ...
    def find_session_by_refresh(self, refresh_hash: str) -> SessionRecord | None: ...
    def rotate_refresh(self, session_id: uuid.UUID, old_hash: str, new_hash: str) -> bool: ...
    def list_active_sessions(self, user_id: uuid.UUID, now: datetime) -> list[SessionRecord]: ...
    def revoke_session(self, session_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> bool: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


class SqlAuthRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    @staticmethod
    def _session_record(row: AuthSession) -> SessionRecord:
        return SessionRecord(row.session_id, row.user_id, row.user_agent, row.created_at, row.expires_at, row.revoked_at)

    def current_policies(self, now: datetime) -> list[PolicyRecord]:
        rows = self._db.scalars(
            select(ConsentPolicy)
            .where(ConsentPolicy.effective_at <= now)
            .order_by(ConsentPolicy.policy_code, ConsentPolicy.effective_at.desc())
            .distinct(ConsentPolicy.policy_code)
        )
        return [PolicyRecord(r.policy_code, r.version, r.is_required, r.content_url, r.effective_at) for r in rows]

    def email_exists(self, email_canonical: str) -> bool:
        return self._db.scalar(select(User.user_id).where(User.email_canonical == email_canonical)) is not None

    def create_user(self, new: NewUser, now: datetime) -> uuid.UUID:
        role_id = self._db.scalar(select(Role.role_id).where(Role.code == new.role_code))
        if role_id is None:
            raise RuntimeError(f"role '{new.role_code}' is not seeded")
        user = User(
            email=new.email, email_canonical=new.email_canonical, display_name=new.display_name,
            status="active", last_login_at=now, created_at=now, updated_at=now,
        )
        self._db.add(user)
        try:
            self._db.flush()
        except IntegrityError:
            # 동시 가입 경쟁으로 비교용 이메일 UNIQUE 위반
            self._db.rollback()
            raise EmailTaken() from None
        self._db.add_all([
            UserProfile(user_id=user.user_id, created_at=now, updated_at=now),
            AuthIdentity(
                user_id=user.user_id, provider="local", subject=new.email_canonical,
                password_hash=new.password_hash, created_at=now, updated_at=now,
            ),
            UserRole(user_id=user.user_id, role_id=role_id, granted_by_user_id=None, granted_at=now),
            *[
                UserConsent(
                    user_id=user.user_id, policy_code=code, policy_version=version, granted=granted, recorded_at=now,
                )
                for code, version, granted in new.consents
            ],
        ])
        self._db.flush()
        return user.user_id

    def find_local_identity(self, email_canonical: str) -> LocalIdentity | None:
        row = self._db.execute(
            select(AuthIdentity.user_id, AuthIdentity.password_hash, User.status)
            .join(User, User.user_id == AuthIdentity.user_id)
            .where(AuthIdentity.provider == "local", AuthIdentity.subject == email_canonical)
        ).one_or_none()
        return LocalIdentity(*row) if row else None

    def update_password_hash(self, user_id: uuid.UUID, password_hash: str, now: datetime) -> None:
        self._db.execute(
            update(AuthIdentity)
            .where(AuthIdentity.user_id == user_id, AuthIdentity.provider == "local")
            .values(password_hash=password_hash, updated_at=now)
        )

    def touch_last_login(self, user_id: uuid.UUID, now: datetime) -> None:
        self._db.execute(update(User).where(User.user_id == user_id).values(last_login_at=now))

    def get_user(self, user_id: uuid.UUID) -> UserRecord | None:
        row = self._db.execute(
            select(User, UserProfile)
            .outerjoin(UserProfile, UserProfile.user_id == User.user_id)
            .where(User.user_id == user_id)
        ).one_or_none()
        if row is None:
            return None
        user, profile = row
        return UserRecord(
            user.user_id, user.email, user.display_name, user.status, user.created_at,
            profile.headline if profile else None,
            profile.bio if profile else None,
            profile.location_text if profile else None,
        )

    def role_codes(self, user_id: uuid.UUID) -> list[str]:
        return list(self._db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(Role.code)
        ))

    def permission_codes(self, user_id: uuid.UUID) -> list[str]:
        return list(self._db.scalars(
            select(Permission.code)
            .distinct()
            .join(RolePermission, RolePermission.permission_id == Permission.permission_id)
            .join(UserRole, UserRole.role_id == RolePermission.role_id)
            .where(UserRole.user_id == user_id)
            .order_by(Permission.code)
        ))

    def create_session(
        self, user_id: uuid.UUID, refresh_hash: str, user_agent: str | None, now: datetime, expires_at: datetime
    ) -> uuid.UUID:
        row = AuthSession(
            user_id=user_id, refresh_token_hash=refresh_hash, user_agent=user_agent,
            created_at=now, expires_at=expires_at,
        )
        self._db.add(row)
        self._db.flush()
        return row.session_id

    def get_session(self, session_id: uuid.UUID) -> SessionRecord | None:
        row = self._db.get(AuthSession, session_id)
        return self._session_record(row) if row else None

    def find_session_by_refresh(self, refresh_hash: str) -> SessionRecord | None:
        row = self._db.scalar(
            select(AuthSession).where(AuthSession.refresh_token_hash == refresh_hash).with_for_update()
        )
        return self._session_record(row) if row else None

    def rotate_refresh(self, session_id: uuid.UUID, old_hash: str, new_hash: str) -> bool:
        result = self._db.execute(
            update(AuthSession)
            .where(
                AuthSession.session_id == session_id,
                AuthSession.refresh_token_hash == old_hash,
                AuthSession.revoked_at.is_(None),
            )
            .values(refresh_token_hash=new_hash)
        )
        return result.rowcount == 1

    def list_active_sessions(self, user_id: uuid.UUID, now: datetime) -> list[SessionRecord]:
        rows = self._db.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)
            .order_by(AuthSession.created_at.desc(), AuthSession.session_id)
        )
        return [self._session_record(r) for r in rows]

    def revoke_session(self, session_id: uuid.UUID, user_id: uuid.UUID, now: datetime) -> bool:
        result = self._db.execute(
            update(AuthSession)
            .where(
                AuthSession.session_id == session_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
            .values(revoked_at=now)
        )
        return result.rowcount == 1

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()
