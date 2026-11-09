"""T43 API DTOs, following the T06 OpenAPI contract."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class GapModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GapSkill(GapModel):
    skill_id: UUID
    code: str
    name: str


class GapJobRole(GapModel):
    job_role_id: UUID
    code: str
    name: str


class GapModelVersion(GapModel):
    model_code: str
    version: str
    kind: Literal["rule"]


class SkillGapRequest(GapModel):
    job_role_id: UUID


class SkillGapItem(GapModel):
    skill: GapSkill
    required_level: int = Field(ge=1, le=5, strict=True)
    observed_level: int = Field(ge=0, le=5, strict=True)
    gap: int = Field(ge=0, le=5, strict=True)

    @model_validator(mode="after")
    def consistent_gap(self):
        if self.gap != max(self.required_level - self.observed_level, 0):
            raise ValueError("Gap must match the contract formula")
        return self


class SkillGap(GapModel):
    assessment_id: UUID
    job_role: GapJobRole
    model_version: GapModelVersion
    is_stale: bool
    evaluated_at: AwareDatetime
    items: list[SkillGapItem]


class SkillGapSummary(GapModel):
    assessment_id: UUID
    job_role: GapJobRole
    missing_skill_count: int = Field(ge=0)
    total_gap: int = Field(ge=0)
    is_stale: bool
    evaluated_at: AwareDatetime


class SkillGapSummaryPage(GapModel):
    items: list[SkillGapSummary]
    next_cursor: str | None


class SkillGapHistoryQuery(GapModel):
    job_role_id: UUID | None = None
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    cursor: str | None = Field(default=None, max_length=500)
