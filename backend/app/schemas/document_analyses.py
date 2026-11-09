"""T51 document analysis DTOs (docs/api/openapi.yaml Analysis*, T06 contract)."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from app.schemas.catalog import Skill
from app.schemas.my_skills import Level

AnalysisType = Literal["skill_extraction", "summary"]
AnalysisStatus = Literal["queued", "running", "succeeded", "failed"]
AnalysisErrorCode = Literal["TIMEOUT", "PROVIDER_ERROR", "UNREADABLE_DOCUMENT"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisRequest(_Strict):
    analysis_type: AnalysisType


class AnalysisSkill(_Strict):
    skill: Skill
    suggested_proficiency: Level
    evidence: str = Field(max_length=300)


class AnalysisExperience(_Strict):
    organization: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None


class AnalysisResult(_Strict):
    """All properties are optional and non-nullable in T06; absent keys are omitted."""
    summary: str | None = Field(default=None, max_length=2000)
    skills: list[AnalysisSkill] | None = None
    experiences: list[AnalysisExperience] | None = None

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler):
        return {k: v for k, v in handler(self).items() if v is not None}


class ModelVersionRef(_Strict):
    model_code: str
    version: str
    kind: Literal["rule", "ml", "llm"]


class Analysis(_Strict):
    analysis_id: UUID
    document_id: UUID
    analysis_type: AnalysisType
    status: AnalysisStatus
    result: AnalysisResult | None
    error_code: AnalysisErrorCode | None
    model_version: ModelVersionRef
    requested_at: datetime
    completed_at: datetime | None


class AnalysisApplyItem(_Strict):
    skill_id: UUID
    proficiency: Level


class AnalysisApply(_Strict):
    skills: list[AnalysisApplyItem] = Field(min_length=1, max_length=100)
