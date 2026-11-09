"""Mapping of existing 0001 schema; no DDL is executed by the app."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CHAR, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserDocument(Base):
    __tablename__ = "user_documents"
    __table_args__ = {"schema": "career"}

    document_id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("career.users.user_id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(64))
    checksum_sha256: Mapped[str] = mapped_column(CHAR(64))
    visibility: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
