"""Owner-scoped metadata transactions. Status rows are durable worker candidates.

Workers must lock the row for their entire operation so scan cannot resurrect a
deleting document. Only the internal worker API may change ready/rejected status.
"""
from contextlib import contextmanager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.models.documents import UserDocument


class DocumentRepository(Protocol):
    def transaction(self): ...
    def get(self, owner: UUID, document_id: UUID) -> UserDocument | None: ...
    def list(self, owner: UUID, after: tuple[datetime, UUID] | None, limit: int) -> list[UserDocument]: ...
    def add(self, row: UserDocument) -> None: ...
    def remove(self, row: UserDocument) -> None: ...


class SqlDocumentRepository:
    def __init__(self, session: Session):
        self.session = session

    @contextmanager
    def transaction(self):
        try:
            yield
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None
        except Exception:
            self.session.rollback()
            raise

    def get(self, owner, document_id):
        return self.session.scalar(select(UserDocument).where(
            UserDocument.owner_user_id == owner, UserDocument.document_id == document_id,
        ).with_for_update())

    def list(self, owner, after, limit):
        query = select(UserDocument).where(UserDocument.owner_user_id == owner)
        if after:
            query = query.where(tuple_(UserDocument.created_at, UserDocument.document_id) < tuple_(*after))
        return list(self.session.scalars(query.order_by(
            UserDocument.created_at.desc(), UserDocument.document_id.desc(),
        ).limit(limit)))

    def add(self, row):
        self.session.add(row)
        self.session.flush()

    def remove(self, row):
        self.session.delete(row)
