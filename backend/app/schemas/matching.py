"""적합도 API DTO (docs/api/openapi.yaml `MatchRequest`, `Match`, `ModelVersionRef`)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MatchRequest(BaseModel):
    """job_posting_id와 job_role_id 중 정확히 하나."""

    model_config = ConfigDict(extra="forbid")

    job_posting_id: uuid.UUID | None = None
    job_role_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def exactly_one_target(self) -> "MatchRequest":
        if (self.job_posting_id is None) == (self.job_role_id is None):
            raise ValueError("exactly one of job_posting_id, job_role_id is required")
        return self


class MatchTarget(BaseModel):
    job_posting_id: uuid.UUID | None
    job_role_id: uuid.UUID | None


class ModelVersionRef(BaseModel):
    model_code: str
    version: str
    kind: Literal["rule", "ml", "llm"]


class Match(BaseModel):
    match_id: uuid.UUID
    target: MatchTarget
    status: Literal["pending", "completed", "failed"]
    score: float | None = Field(ge=0, le=100, description="0~100 적합 점수. 확률이 아님")
    score_is_probability: Literal[False] = False
    matched_skill_count: int | None = Field(ge=0)
    missing_skill_count: int | None = Field(ge=0)
    model_version: ModelVersionRef
    limitations: list[str] = Field(min_length=1)
    evaluated_at: datetime
