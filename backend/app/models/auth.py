"""계정·인증·권한·동의 ORM 모델 (database/DATA_DICTIONARY.md A01~A08, B01, B09, 스키마 `career`).

테이블 생성은 이 모델이 아니라 승인된 Migration(T08/T09)이 담당한다. 모델은 조회·쓰기 매핑만 한다.
다른 기능(T16 프로필 등)도 `User`, `UserProfile`을 그대로 import해서 쓴다.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CHAR, DateTime, ForeignKey, ForeignKeyConstraint, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SCHEMA = "career"
_UUID_PK = {"primary_key": True, "server_default": text("gen_random_uuid()")}
_NOW = {"server_default": func.now()}


def _fk(target: str, ondelete: str) -> ForeignKey:
    return ForeignKey(f"{SCHEMA}.{target}", ondelete=ondelete)


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    email: Mapped[str] = mapped_column(String(254))
    email_canonical: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'active'"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.user_id", "CASCADE"), primary_key=True)
    headline: Mapped[str | None] = mapped_column(String(200))
    bio: Mapped[str | None] = mapped_column(Text)
    location_text: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = {"schema": SCHEMA}

    identity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.user_id", "CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    subject: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str | None] = mapped_column(Text)  # 원문 비밀번호 저장 금지
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = {"schema": SCHEMA}

    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.user_id", "CASCADE"))
    refresh_token_hash: Mapped[str] = mapped_column(CHAR(64), unique=True)  # SHA-256 hex만 저장
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = {"schema": SCHEMA}

    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class Permission(Base):
    __tablename__ = "permissions"
    __table_args__ = {"schema": SCHEMA}

    permission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    code: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = {"schema": SCHEMA}

    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("roles.role_id", "CASCADE"), primary_key=True)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), _fk("permissions.permission_id", "CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = {"schema": SCHEMA}

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.user_id", "CASCADE"), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("roles.role_id", "RESTRICT"), primary_key=True)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), _fk("users.user_id", "SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class ConsentPolicy(Base):
    __tablename__ = "consent_policies"
    __table_args__ = {"schema": SCHEMA}

    policy_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    is_required: Mapped[bool] = mapped_column(Boolean)
    content_url: Mapped[str] = mapped_column(Text)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)


class UserConsent(Base):
    __tablename__ = "user_consents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["policy_code", "policy_version"],
            [f"{SCHEMA}.consent_policies.policy_code", f"{SCHEMA}.consent_policies.version"],
            ondelete="RESTRICT",
        ),
        {"schema": SCHEMA},
    )

    consent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), **_UUID_PK)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), _fk("users.user_id", "CASCADE"))
    policy_code: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(40))
    granted: Mapped[bool] = mapped_column(Boolean)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), **_NOW)
