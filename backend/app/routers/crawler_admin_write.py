"""T155: authenticated crawler admin write/command API (default OFF).

Mounted only when ``CRAWLER_ADMIN_WRITE_API=true``. The merged read-only routes in
``crawler_admin.py`` are unchanged.

- Every route requires the T15 DB-backed ``admin`` role. Authentication and role
  checks run before the crawler DB connection is opened.
- The audited principal is ``admin:<user_id>`` from the verified session, never a
  client-provided name.
- Commands (run/stop/retry/schedule update) need an ``Idempotency-Key`` header and are
  recorded in the append-only ``admin_commands`` ledger. Refusals (LIVE collection,
  schedule activation, duplicate active job, ...) are recorded too and answered with
  409 ``CONFLICT`` plus the ``X-Crawler-Command-Id``/``X-Crawler-Command-Reason`` headers.
- RUN/RETRY only create a PENDING metadata job. No HTTP, Worker, Timer or scheduler
  activation happens in this API. Responses never include Raw HTML, storage keys,
  target URLs or approval records.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.dependencies.auth import require_roles
from app.services.auth import CurrentUser

AdminUser = Annotated[CurrentUser, Depends(require_roles("admin"))]

router = APIRouter(
    prefix="/admin/crawler",
    tags=["crawler-admin"],
    # Router-level role check runs before any endpoint dependency (DB connection).
    dependencies=[Depends(require_roles("admin"))],
    responses=error_responses(401, 403, 422, 503),
)

_KEYWORD_ID = Annotated[int, Path(ge=1, le=9_223_372_036_854_775_807)]
_IDEMPOTENCY = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200,
                                     pattern=r"^[A-Za-z0-9._:-]+$")]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeywordCreate(_Body):
    keyword: str = Field(min_length=1, max_length=100)
    priority: int = Field(default=100, ge=1, le=9999)


class KeywordUpdate(_Body):
    keyword: str = Field(min_length=1, max_length=100)
    priority: int = Field(ge=1, le=9999)


class KeywordEnabled(_Body):
    enabled: StrictBool


class RunCommand(_Body):
    keyword_id: int = Field(ge=1, le=9_223_372_036_854_775_807)
    mode: Literal["fixture", "live"] = "fixture"


class JobCommand(_Body):
    job_id: UUID


class ScheduleUpdate(_Body):
    local_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    enabled: StrictBool | None = None
    mode: Literal["fixture", "live"] | None = None


def get_crawler_admin_write_store() -> Iterator[object]:
    """Writable crawler metadata connection, opened only after admin auth.

    Fail closed (503) when the crawler package or its dedicated DB is unavailable.
    Tests override this dependency; the role dependency is never bypassed.
    """
    try:
        from crawler.admin.commands import CrawlerAdminWriteStore
        from crawler.storage.staging import connect_configured_database
        connection = connect_configured_database()
    except Exception:
        raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE,
                       log_detail="crawler admin write connection unavailable") from None
    try:
        connection.autocommit = True  # each store call runs its own explicit transaction
        yield CrawlerAdminWriteStore(connection)
    finally:
        connection.close()


Store = Annotated[object, Depends(get_crawler_admin_write_store)]


def _actor(user: CurrentUser) -> str:
    return f"admin:{user.user_id}"


def _invalid(exc: Exception) -> AppError:
    return AppError(ErrorCode.VALIDATION_FAILED, log_detail=f"crawler admin input rejected: {type(exc).__name__}")


def _call(fn):
    """Map store errors without importing the crawler package (absent from backend-only images).

    ``ValueError`` -> 422; exceptions tagged ``crawler_admin_conflict`` -> 409; others propagate.
    """
    try:
        return fn()
    except ValueError as exc:
        raise _invalid(exc) from None
    except Exception as exc:
        reason = getattr(exc, "crawler_admin_conflict", None)
        if not reason:
            raise
        error = AppError(ErrorCode.CONFLICT, log_detail=f"crawler admin conflict: {reason}")
        error.headers["X-Crawler-Command-Reason"] = str(reason)
        raise error from None


def _command_response(result, response: Response, created: bool) -> dict:
    headers = {"X-Crawler-Command-Id": str(result.command_id), "X-Crawler-Command-Reason": result.reason}
    if result.outcome == "REFUSED":
        error = AppError(ErrorCode.CONFLICT, log_detail=f"crawler admin command refused: {result.reason}")
        error.headers.update(headers)
        raise error
    response.headers.update(headers)
    response.status_code = status.HTTP_201_CREATED if created and not result.replayed else status.HTTP_200_OK
    return result.as_dict()


def _run_command(fn, response: Response, *, created: bool):
    return _command_response(_call(fn), response, created)


# ------------------------------------------------------------------ keywords
@router.post("/keywords", status_code=status.HTTP_201_CREATED, responses=error_responses(409))
def create_keyword(body: KeywordCreate, user: AdminUser, store: Store):
    return _call(lambda: store.create_keyword(body.keyword, priority=body.priority, actor=_actor(user)))


@router.patch("/keywords/{keyword_id}", responses=error_responses(404, 409))
def update_keyword(keyword_id: _KEYWORD_ID, body: KeywordUpdate, user: AdminUser, store: Store):
    row = _call(lambda: store.update_keyword(keyword_id, body.keyword, priority=body.priority,
                                             actor=_actor(user)))
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, log_detail="keyword missing or deleted")
    return row


@router.put("/keywords/{keyword_id}/enabled", responses=error_responses(404))
def set_keyword_enabled(keyword_id: _KEYWORD_ID, body: KeywordEnabled, user: AdminUser, store: Store):
    row = store.set_keyword_enabled(keyword_id, body.enabled, actor=_actor(user))
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, log_detail="keyword missing or deleted")
    return row


@router.delete("/keywords/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(404))
def delete_keyword(keyword_id: _KEYWORD_ID, user: AdminUser, store: Store) -> Response:
    if not store.delete_keyword(keyword_id, actor=_actor(user)):
        raise AppError(ErrorCode.NOT_FOUND, log_detail="keyword missing or already deleted")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/keywords/{keyword_id}/audit")
def keyword_audit(keyword_id: _KEYWORD_ID, user: AdminUser, store: Store,
                  limit: Annotated[int, Query(ge=1, le=200)] = 50):
    return store.keyword_audit(keyword_id, limit=limit)


# ------------------------------------------------------------------ settings
@router.get("/settings")
def get_settings(user: AdminUser, store: Store):
    return store.settings()


@router.patch("/schedules/{schedule_id}", responses=error_responses(409))
def update_schedule(
    schedule_id: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")],
    body: ScheduleUpdate, user: AdminUser, store: Store, response: Response, idempotency_key: _IDEMPOTENCY,
):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="empty schedule change")
    return _run_command(lambda: store.update_schedule(
        schedule_id, changes=changes, idempotency_key=idempotency_key, actor=_actor(user)), response, created=False)


# ------------------------------------------------------------------ commands
@router.post("/commands/run", status_code=status.HTTP_201_CREATED, responses=error_responses(409))
def run_command(body: RunCommand, user: AdminUser, store: Store, response: Response,
                idempotency_key: _IDEMPOTENCY):
    return _run_command(lambda: store.run(body.keyword_id, mode=body.mode, idempotency_key=idempotency_key,
                                          actor=_actor(user)), response, created=True)


@router.post("/commands/stop", responses=error_responses(409))
def stop_command(body: JobCommand, user: AdminUser, store: Store, response: Response,
                 idempotency_key: _IDEMPOTENCY):
    return _run_command(lambda: store.stop(body.job_id, idempotency_key=idempotency_key, actor=_actor(user)),
                        response, created=False)


@router.post("/commands/retry", status_code=status.HTTP_201_CREATED, responses=error_responses(409))
def retry_command(body: JobCommand, user: AdminUser, store: Store, response: Response,
                  idempotency_key: _IDEMPOTENCY):
    return _run_command(lambda: store.retry(body.job_id, idempotency_key=idempotency_key, actor=_actor(user)),
                        response, created=True)


@router.get("/commands")
def list_commands(user: AdminUser, store: Store,
                  limit: Annotated[int, Query(ge=1, le=100)] = 50,
                  offset: Annotated[int, Query(ge=0, le=100000)] = 0):
    return store.commands(limit=limit, offset=offset)
