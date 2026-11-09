import hashlib
import secrets
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.errors import AppError, ErrorCode
from app.models.documents import UserDocument
from app.repositories.documents import DocumentRepository
from app.schemas.documents import Document, DocumentPage
from app.services.document_storage import DocumentStorage, DocumentDerivativePurger
from app.services.document_validation import validate_document
from app.services.job_postings import ListCursor


class DocumentService:
    def __init__(self, repo: DocumentRepository, storage: DocumentStorage, cursor: ListCursor):
        self.repo, self.storage, self.cursor = repo, storage, cursor

    def _owned(self, owner, document_id):
        row = self.repo.get(owner, document_id)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return row

    def upload(self, owner, kind, filename, mime, content):
        if kind not in {"resume", "portfolio"}:
            raise AppError(ErrorCode.VALIDATION_FAILED)
        validate_document(filename, mime, content)
        now = datetime.now(UTC)
        row = UserDocument(document_id=uuid4(), owner_user_id=owner, kind=kind,
                           original_filename=filename, mime_type=mime, size_bytes=len(content),
                           storage_key=secrets.token_hex(32), checksum_sha256=hashlib.sha256(content).hexdigest(),
                           visibility="private", status="scanning", created_at=now, updated_at=now)
        self.storage.put(row.storage_key, content)
        try:
            with self.repo.transaction():
                self.repo.add(row)
                result = Document.model_validate(row)
        except Exception:
            self.storage.delete(row.storage_key)
            raise
        return result

    def get(self, owner, document_id):
        with self.repo.transaction():
            return Document.model_validate(self._owned(owner, document_id))

    def list(self, owner, limit, cursor):
        after = None
        if cursor is not None:
            item_id, raw = self.cursor.decode(cursor, "documents", {"owner": str(owner)})
            try:
                moment = datetime.fromisoformat(raw)
                if moment.tzinfo is None:
                    raise ValueError()
                after = (moment, item_id)
            except (ValueError, TypeError):
                raise AppError(ErrorCode.INVALID_CURSOR) from None
        with self.repo.transaction():
            rows = self.repo.list(owner, after, limit + 1)
            page = rows[:limit]
            next_cursor = self.cursor.encode("documents", {"owner": str(owner)}, page[-1].document_id,
                (page[-1].created_at if page[-1].created_at.tzinfo else
                 page[-1].created_at.replace(tzinfo=UTC)).isoformat()) if len(rows) > limit else None
            return DocumentPage(items=[Document.model_validate(row) for row in page], next_cursor=next_cursor)

    def download(self, owner, document_id):
        with self.repo.transaction():
            row = self._owned(owner, document_id)
            if row.status != "ready":
                raise AppError(ErrorCode.DOCUMENT_NOT_READY)
            content = self.storage.read(row.storage_key)
            if len(content) != row.size_bytes or hashlib.sha256(content).hexdigest() != row.checksum_sha256:
                raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)
            return Document.model_validate(row), content

    def delete(self, owner, document_id):
        with self.repo.transaction():
            row = self._owned(owner, document_id)
            row.status, row.updated_at = "deleting", datetime.now(UTC)
            return Document.model_validate(row)

    def verify(self, owner: UUID, document_id: UUID):
        """Internal format/integrity verification only; no antivirus execution."""
        with self.repo.transaction():
            row = self._owned(owner, document_id)
            if row.status != "scanning":
                return
            content = self.storage.read(row.storage_key)
            if len(content) != row.size_bytes or hashlib.sha256(content).hexdigest() != row.checksum_sha256:
                row.status = "rejected"
            else:
                try:
                    validate_document(row.original_filename, row.mime_type, content)
                except AppError as exc:
                    if exc.code not in {ErrorCode.VALIDATION_FAILED, ErrorCode.UNSUPPORTED_FILE_TYPE, ErrorCode.FILE_TOO_LARGE}:
                        raise
                    row.status = "rejected"
                else:
                    row.status = "ready"
            row.updated_at = datetime.now(UTC)

    def purge(self, owner: UUID, document_id: UUID, derivatives: DocumentDerivativePurger):
        """Retry-safe internal deletion. Metadata is removed last."""
        with self.repo.transaction():
            row = self.repo.get(owner, document_id)
            if row is None or row.status != "deleting":
                return
            derivatives.purge(document_id)
            self.storage.delete(row.storage_key)
            self.repo.remove(row)
