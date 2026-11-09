"""T155 STEP03: authenticated, read-only crawler administration API.

This module depends on the T15 DB-backed authentication integration.
The T155 route is intentionally staged on top of the unmerged T15 branch.
No crawler jobs can be enqueued, retried, stopped or scheduled from this API.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.dependencies.auth import require_roles

router = APIRouter(
    prefix="/admin/crawler",
    tags=["crawler-admin"],
    dependencies=[Depends(require_roles("admin"))],
    responses=error_responses(401, 403, 503),
)

_LIMIT = Annotated[int, Query(ge=1, le=100)]
_OFFSET = Annotated[int, Query(ge=0, le=100000)]


def get_crawler_admin_store() -> Iterator[object]:
    """Separate crawler DB and read-only transaction, after T15 auth/RBAC.

    Dependency override is allowed only in unit tests; never bypasses the
    role dependency. Fail closed if crawler is not included in a backend image.
    """
    try:
        from crawler.admin.read_models import CrawlerAdminReadStore
        from crawler.storage.staging import connect_configured_database
        connection = connect_configured_database()
    except Exception:
        raise AppError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            log_detail="crawler admin metadata connection unavailable",
        ) from None

    try:
        with connection.transaction():
            try:
                connection.execute("SET TRANSACTION READ ONLY")
            except Exception:
                raise AppError(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    log_detail="crawler admin read-only transaction unavailable",
                ) from None
            # Errors from the handler must never be converted into a spurious
            # 503 by the yield dependency. Rollback/close occur on exit.
            yield CrawlerAdminReadStore(connection)
    finally:
        connection.close()


Store = Annotated[object, Depends(get_crawler_admin_store)]


@router.get("/keywords")
def get_keywords(store: Store, limit: _LIMIT = 50, offset: _OFFSET = 0):
    return store.keywords(limit=limit, offset=offset)


@router.get("/jobs")
def get_jobs(
    store: Store,
    limit: _LIMIT = 50,
    offset: _OFFSET = 0,
    keyword_id: Annotated[int | None, Query(ge=1)] = None,
    status: Annotated[str | None, Query(pattern=r"^(PENDING|RUNNING|FETCHED|FAILED|COMPLETED|CANCELLED)$")] = None,
):
    return store.jobs(limit=limit, offset=offset, keyword_id=keyword_id, status=status)


@router.get("/schedules")
def get_schedules(store: Store, limit: _LIMIT = 20, offset: _OFFSET = 0):
    return store.schedules(limit=limit, offset=offset)


@router.get("/runs")
def get_runs(store: Store, limit: _LIMIT = 50, offset: _OFFSET = 0):
    return store.runs(limit=limit, offset=offset)


@router.get("/runs/{run_id}/events")
def get_events(run_id: UUID, store: Store, limit: _LIMIT = 50, offset: _OFFSET = 0):
    return store.events(run_id=run_id, limit=limit, offset=offset)


@router.get("/stats/keywords")
def get_keyword_stats(store: Store, limit: _LIMIT = 50, offset: _OFFSET = 0):
    return store.keyword_stats(limit=limit, offset=offset)
