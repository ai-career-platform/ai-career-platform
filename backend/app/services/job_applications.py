"""T102 개인 지원 기록 (T101 계약 PROPOSED — docs/applications/T101_APPLICATION_TRACKING_CONTRACT.md).

- 상태는 **사용자가 직접 기록한 것**이며 채용사 공식 결과가 아닙니다.
- 본인 기록만 다룹니다. 남의 기록 ID 는 없는 것과 같이 404.
- 409 는 T101 D-7(전용 코드) 승인 전까지 기존 `CONFLICT` 하나로 응답하고, 원인은 log_detail(서버 로그)에만 남깁니다.
- memo 는 로그에 남기지 않습니다.
`JOB_APPLICATIONS_API=true` 일 때만 경로가 등록됩니다(기본 꺼짐, 표는 database/proposed — 정식 migration 아님).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.schemas.job_applications import (
    ApplicationPosting, JobApplication, JobApplicationCreate, JobApplicationPage, JobApplicationUpdate,
)
from app.services.job_postings import ListCursor

KST = timezone(timedelta(hours=9))
STAGES = ("interested", "preparing", "applied", "interviewing", "offered", "rejected", "withdrawn")
TRANSITIONS: dict[str, frozenset[str]] = {
    "interested": frozenset({"preparing", "applied", "withdrawn"}),
    "preparing": frozenset({"interested", "applied", "withdrawn"}),
    "applied": frozenset({"preparing", "interviewing", "offered", "rejected", "withdrawn"}),
    "interviewing": frozenset({"applied", "offered", "rejected", "withdrawn"}),
    "offered": frozenset({"interviewing", "withdrawn"}),
    "rejected": frozenset({"interviewing"}),
    "withdrawn": frozenset({"interested"}),
}
NEEDS_DATE = frozenset({"applied", "interviewing", "offered", "rejected"})
NO_DATE = frozenset({"interested", "preparing"})
MAX_PER_USER = 500
MIN_DATE = date(2000, 1, 1)
NEXT_STEP_HORIZON = timedelta(days=730)


def can_move(current: str, target: str) -> bool:
    return current == target or target in TRANSITIONS[current]


@dataclass(frozen=True)
class ApplicationRow:
    application_id: UUID
    user_id: UUID
    job_posting_id: UUID | None
    posting_title: str
    company_name: str
    posting_status: str | None          # 공고 원래 status(없으면 None = 삭제됨)
    posting_expires_at: datetime | None
    stage: str
    applied_on: date | None
    next_step_on: date | None
    memo: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    stage_changed_at: datetime


@dataclass(frozen=True)
class NewApplication:
    user_id: UUID
    job_posting_id: UUID
    stage: str
    applied_on: date | None
    next_step_on: date | None
    memo: str | None
    now: datetime


class JobApplicationRepository(Protocol):
    def list(self, user_id: UUID, stages: tuple[str, ...], after: tuple[datetime, UUID] | None,
             limit: int) -> list[ApplicationRow]: ...
    def get(self, user_id: UUID, application_id: UUID) -> ApplicationRow | None: ...
    def create(self, new: NewApplication, max_per_user: int) -> ApplicationRow | str:
        """성공하면 행, 실패하면 "posting_not_found" | "duplicate" | "limit"."""
    def update(self, user_id: UUID, application_id: UUID, version: int, values: dict) -> ApplicationRow | None:
        """version 이 맞을 때만 갱신(version+1). 안 맞거나 없으면 None."""
    def delete(self, user_id: UUID, application_id: UUID) -> bool: ...


def _conflict(reason: str) -> AppError:
    return AppError(ErrorCode.CONFLICT, log_detail=f"job application: {reason}")


def _invalid(reason: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_FAILED, log_detail=f"job application: {reason}")


class JobApplicationService:
    def __init__(self, repo: JobApplicationRepository, cursor: ListCursor,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.repo, self.cursor, self.clock = repo, cursor, clock

    # ------------------------------------------------------------------ 규칙
    def _today(self) -> date:
        return self.clock().astimezone(KST).date()

    def _check_dates(self, applied_on: date | None, next_step_on: date | None) -> None:
        today = self._today()
        if applied_on is not None and not MIN_DATE <= applied_on <= today:
            raise _invalid("applied_on out of range")
        if next_step_on is not None and not MIN_DATE <= next_step_on <= today + NEXT_STEP_HORIZON:
            raise _invalid("next_step_on out of range")

    def _applied_on_for(self, stage: str, applied_on: date | None, explicit: bool) -> date | None:
        """단계별 지원일 규칙(T101 §3). 준비 단계로 가면 지우고, 지원 이후 단계에 없으면 오늘(KST)."""
        if stage in NO_DATE:
            if explicit and applied_on is not None:
                raise _invalid("applied_on not allowed before applying")
            return None
        if stage in NEEDS_DATE and applied_on is None:
            return self._today()
        return applied_on

    def _view(self, row: ApplicationRow) -> JobApplication:
        now = self.clock()
        if row.job_posting_id is None or row.posting_status not in ("published", "closed"):
            status = "unavailable"
        elif row.posting_status == "closed" or (row.posting_expires_at is not None and row.posting_expires_at <= now):
            status = "closed"
        else:
            status = "published"
        return JobApplication(
            application_id=row.application_id, stage=row.stage, applied_on=row.applied_on, next_step_on=row.next_step_on,
            memo=row.memo, version=row.version, created_at=row.created_at, updated_at=row.updated_at,
            stage_changed_at=row.stage_changed_at,
            posting=ApplicationPosting(job_posting_id=row.job_posting_id, title=row.posting_title,
                                       company_name=row.company_name, status=status,
                                       expires_at=row.posting_expires_at if status != "unavailable" else None))

    # ------------------------------------------------------------------ 동작
    def list(self, user_id: UUID, stages: list[str] | None, limit: int, cursor: str | None) -> JobApplicationPage:
        stage_filter = tuple(sorted(set(stages or [])))
        params = {"stage": list(stage_filter)}
        after = None
        if cursor is not None:
            last_id, raw = self.cursor.decode(cursor, "job_applications", params)
            try:
                after = (datetime.fromisoformat(raw or ""), last_id)
            except ValueError:
                raise AppError(ErrorCode.INVALID_CURSOR, log_detail="application cursor key unparsable") from None
        rows = self.repo.list(user_id, stage_filter, after, limit + 1)
        page = rows[:limit]
        next_cursor = (self.cursor.encode("job_applications", params, page[-1].application_id,
                                          page[-1].updated_at.isoformat()) if len(rows) > limit else None)
        return JobApplicationPage(items=[self._view(r) for r in page], next_cursor=next_cursor)

    def get(self, user_id: UUID, application_id: UUID) -> JobApplication:
        row = self.repo.get(user_id, application_id)
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="job application not found")
        return self._view(row)

    def create(self, user_id: UUID, body: JobApplicationCreate) -> JobApplication:
        explicit = "applied_on" in body.model_fields_set
        applied_on = self._applied_on_for(body.stage, body.applied_on, explicit)
        self._check_dates(applied_on, body.next_step_on)
        result = self.repo.create(NewApplication(user_id, body.job_posting_id, body.stage, applied_on,
                                                 body.next_step_on, body.memo, self.clock()), MAX_PER_USER)
        if result == "posting_not_found":
            raise AppError(ErrorCode.NOT_FOUND, log_detail="job application: posting not found")
        if result == "duplicate":
            raise _conflict("APPLICATION_EXISTS")
        if result == "limit":
            raise _conflict("APPLICATION_LIMIT")
        return self._view(result)

    def update(self, user_id: UUID, application_id: UUID, body: JobApplicationUpdate) -> JobApplication:
        sent = body.model_fields_set - {"version"}
        if not sent:
            raise _invalid("nothing to update")
        if "stage" in sent and body.stage is None:
            raise _invalid("stage cannot be null")
        current = self.repo.get(user_id, application_id)
        if current is None:
            raise AppError(ErrorCode.NOT_FOUND, log_detail="job application not found")
        if current.version != body.version:
            raise _conflict("VERSION_CONFLICT")
        target = body.stage if "stage" in sent else current.stage
        if not can_move(current.stage, target):
            raise _conflict(f"INVALID_STAGE_TRANSITION {current.stage}->{target}")
        explicit = "applied_on" in sent
        applied_on = self._applied_on_for(target, body.applied_on if explicit else current.applied_on, explicit)
        next_step_on = body.next_step_on if "next_step_on" in sent else current.next_step_on
        self._check_dates(applied_on if (explicit or applied_on != current.applied_on) else None,
                          next_step_on if "next_step_on" in sent else None)
        now = self.clock()
        values = {"stage": target, "applied_on": applied_on, "next_step_on": next_step_on,
                  "memo": body.memo if "memo" in sent else current.memo, "updated_at": now,
                  "stage_changed_at": now if target != current.stage else current.stage_changed_at}
        row = self.repo.update(user_id, application_id, body.version, values)
        if row is None:   # 읽은 뒤 다른 요청이 먼저 바꿨거나 지웠음
            if self.repo.get(user_id, application_id) is None:
                raise AppError(ErrorCode.NOT_FOUND, log_detail="job application deleted concurrently")
            raise _conflict("VERSION_CONFLICT")
        return self._view(row)

    def delete(self, user_id: UUID, application_id: UUID) -> None:
        if not self.repo.delete(user_id, application_id):
            raise AppError(ErrorCode.NOT_FOUND, log_detail="job application not found")
