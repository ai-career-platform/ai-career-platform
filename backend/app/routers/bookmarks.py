from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.core.auth_config import AuthSettings
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep, get_auth_settings
from app.repositories.bookmarks import SqlBookmarkRepository
from app.schemas.job_postings import JobPostingPage
from app.services.bookmarks import BookmarkService
from app.services.job_postings import ListCursor, derive_cursor_key

router = APIRouter(prefix="/me/bookmarks", tags=["me"], responses=error_responses(401, 503))
def get_service(db: Annotated[Session, Depends(get_db)], settings: Annotated[AuthSettings, Depends(get_auth_settings)]):
    return BookmarkService(SqlBookmarkRepository(db), ListCursor(derive_cursor_key(settings.jwt_secret)))
Service = Annotated[BookmarkService, Depends(get_service)]

@router.get("", response_model=JobPostingPage, operation_id="listMyBookmarks", responses=error_responses(400))
def list_bookmarks(user: CurrentUserDep, service: Service, limit: Annotated[int, Query(ge=1, le=100)] = 20,
                   cursor: Annotated[str | None, Query(max_length=500)] = None):
    return service.list(user.user_id, limit, cursor)
@router.put("/{job_posting_id}", status_code=204, operation_id="addMyBookmark", responses=error_responses(404))
def add_bookmark(job_posting_id: UUID, user: CurrentUserDep, service: Service): service.add(user.user_id, job_posting_id)
@router.delete("/{job_posting_id}", status_code=204, operation_id="removeMyBookmark")
def remove_bookmark(job_posting_id: UUID, user: CurrentUserDep, service: Service): service.remove(user.user_id, job_posting_id)
