"""Explicit one-shot worker: python -m app.document_worker (schedule externally).

Uses existing scanning/deleting rows as durable work; no in-process background
tasks or startup jobs. Nothing runs during API startup. Verification checks
format and integrity only; no antivirus or uploaded code is executed.
"""
import logging

from sqlalchemy import select, text

from app.core.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.db import create_db_engine, create_session_factory
from app.models.documents import UserDocument
from app.routers.documents import get_document_storage
from app.services.documents import DocumentService
from app.repositories.documents import SqlDocumentRepository
from app.services.job_postings import ListCursor


class DatabaseDerivativePurger:
    def __init__(self, session):
        self.session = session

    def purge(self, document_id):
        # The existing FK CASCADE purges analyses, chunks and citations when the
        # document row is removed. External indexes need a T53 adapter first.
        indexed = self.session.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM career.document_chunks "
            "WHERE document_id = :document_id AND index_ref IS NOT NULL)"
        ), {"document_id": document_id})
        if indexed:
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)


def run_batch(session, storage, purger, limit=100):
    candidates = session.execute(select(UserDocument.owner_user_id, UserDocument.document_id, UserDocument.status)
        .where(UserDocument.status.in_(["scanning", "deleting"]))
        .order_by(UserDocument.updated_at, UserDocument.document_id).limit(limit)).all()
    session.commit()
    service = DocumentService(SqlDocumentRepository(session), storage, ListCursor(b"worker-unused-cursor-key-00000000"))
    failures = 0
    for owner, document_id, status in candidates:
        try:
            if status == "scanning":
                service.verify(owner, document_id)
            else:
                service.purge(owner, document_id, purger)
        except AppError:
            failures += 1
            # No identifiers, filenames, keys, content or provider output.
            logging.getLogger(__name__).warning("document worker dependency unavailable; retry required")
    return failures


def main():
    settings = get_settings()
    if settings.database is None:
        raise SystemExit("DATABASE_URL is required")
    engine = create_db_engine(settings.database)
    try:
        with create_session_factory(engine)() as session:
            failures = run_batch(session, get_document_storage(), DatabaseDerivativePurger(session))
            return 1 if failures else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
