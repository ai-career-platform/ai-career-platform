"""T49 multipart parsing occurs after authentication, entirely in bounded memory."""
import os
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep, get_auth_settings
from app.repositories.documents import SqlDocumentRepository
from app.schemas.documents import Document, DocumentPage
from app.services.document_storage import DirectoryDocumentStorage, UnavailableDocumentStorage
from app.services.document_validation import MAX_FILE_BYTES, PDF, DOCX
from app.services.documents import DocumentService
from app.services.job_postings import ListCursor, derive_cursor_key

router = APIRouter(prefix="/documents", tags=["documents"], responses=error_responses(401, 503))


def get_document_storage():
    root = os.environ.get("DOCUMENT_STORAGE_ROOT")
    if not root:
        return UnavailableDocumentStorage()
    try:
        return DirectoryDocumentStorage(root)
    except (OSError, ValueError):
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE) from None


def get_document_service(db: Annotated[Session, Depends(get_db)],
                         settings=Depends(get_auth_settings), storage=Depends(get_document_storage)):
    return DocumentService(SqlDocumentRepository(db), storage, ListCursor(derive_cursor_key(settings.jwt_secret)))


Service = Annotated[DocumentService, Depends(get_document_service)]


class BoundedMultipartParser(MultiPartParser):
    # Starlette 0.46 uses max_file_size as its in-memory spool threshold.
    max_file_size = MAX_FILE_BYTES + 65536
    spool_max_size = MAX_FILE_BYTES + 65536


async def parse_upload(request: Request):
    async def bounded():
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_FILE_BYTES + 65536:
                raise AppError(ErrorCode.FILE_TOO_LARGE)
            yield chunk

    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "multipart/form-data":
        raise AppError(ErrorCode.VALIDATION_FAILED)
    parser = BoundedMultipartParser(request.headers, bounded(), max_files=1, max_fields=1)
    try:
        form = await parser.parse()
    except (MultiPartException, ValueError):
        for file in parser._files_to_close_on_error:
            file.close()
        raise AppError(ErrorCode.VALIDATION_FAILED) from None
    except BaseException:
        for file in parser._files_to_close_on_error:
            file.close()
        raise
    try:
        if sorted(form.keys()) != ["file", "kind"] or len(form.multi_items()) != 2:
            raise AppError(ErrorCode.VALIDATION_FAILED)
        file, kind = form["file"], form["kind"]
        if not isinstance(file, UploadFile) or not isinstance(kind, str):
            raise AppError(ErrorCode.VALIDATION_FAILED)
        return kind, file.filename, file.content_type, await file.read(MAX_FILE_BYTES + 1)
    finally:
        await form.close()


@router.get("", response_model=DocumentPage, operation_id="listMyDocuments", responses=error_responses(400))
def list_documents(user: CurrentUserDep, service: Service,
                   limit: Annotated[int, Query(ge=1, le=100)] = 20,
                   cursor: Annotated[str | None, Query(max_length=500)] = None):
    return service.list(user.user_id, limit, cursor)


@router.post("", response_model=Document, status_code=202, operation_id="uploadDocument",
             responses=error_responses(413, 415), openapi_extra={"requestBody": {"required": True,
             "content": {"multipart/form-data": {"schema": {"type": "object", "required": ["file", "kind"],
             "properties": {"file": {"type": "string", "format": "binary"},
             "kind": {"type": "string", "enum": ["resume", "portfolio"]}}}}}}})
async def upload_document(request: Request, response: Response, user: CurrentUserDep, service: Service):
    kind, filename, mime, content = await parse_upload(request)
    result = await run_in_threadpool(service.upload, user.user_id, kind, filename, mime, content)
    response.headers["Location"] = f"/api/v1/documents/{result.document_id}"
    response.headers["Retry-After"] = "3"
    return result


@router.get("/{document_id}", response_model=Document, operation_id="getMyDocument", responses=error_responses(404))
def get_document(document_id: UUID, user: CurrentUserDep, service: Service):
    return service.get(user.user_id, document_id)


@router.delete("/{document_id}", response_model=Document, status_code=202,
               operation_id="deleteMyDocument", responses=error_responses(404))
def delete_document(document_id: UUID, response: Response, user: CurrentUserDep, service: Service):
    result = service.delete(user.user_id, document_id)
    response.headers["Location"] = f"/api/v1/documents/{document_id}"
    response.headers["Retry-After"] = "3"
    return result


@router.get("/{document_id}/file", operation_id="downloadMyDocument", response_class=Response,
            responses={**error_responses(404, 409), 200: {"content": {
                PDF: {"schema": {"type": "string", "format": "binary"}},
                DOCX: {"schema": {"type": "string", "format": "binary"}},
            }}})
def download_document(document_id: UUID, user: CurrentUserDep, service: Service):
    doc, content = service.download(user.user_id, document_id)
    return Response(content, media_type=doc.mime_type, headers={
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(doc.original_filename, safe=""),
        "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
    })
