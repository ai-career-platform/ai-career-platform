"""T102 개인 지원 기록 DTO (T101 제안 계약 — docs/applications/t101_openapi_proposal.yaml)."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ApplicationStage = Literal["interested", "preparing", "applied", "interviewing", "offered", "rejected", "withdrawn"]
MEMO_MAX = 2000


class ApplicationPosting(BaseModel):
    job_posting_id: UUID | None
    title: str
    company_name: str
    status: Literal["published", "closed", "unavailable"]
    expires_at: datetime | None


class JobApplication(BaseModel):
    application_id: UUID
    stage: ApplicationStage
    applied_on: date | None
    next_step_on: date | None
    memo: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    stage_changed_at: datetime
    posting: ApplicationPosting


class JobApplicationPage(BaseModel):
    items: list[JobApplication]
    next_cursor: str | None


class JobApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_posting_id: UUID
    stage: ApplicationStage = "interested"
    applied_on: date | None = None
    next_step_on: date | None = None
    memo: str | None = Field(default=None, max_length=MEMO_MAX)


class JobApplicationUpdate(BaseModel):
    """보내지 않은 필드는 그대로, null 은 지움(applied_on·next_step_on·memo). version 필수."""
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    stage: ApplicationStage | None = None
    applied_on: date | None = None
    next_step_on: date | None = None
    memo: str | None = Field(default=None, max_length=MEMO_MAX)
