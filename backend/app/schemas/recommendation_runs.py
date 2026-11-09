"""T45 rule-based recommendation run DTOs. T06 OpenAPI contract."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from app.schemas.job_postings import JobPostingSummary

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class RecommendationRunRequest(_Strict):
    limit: int = Field(default=20, ge=1, le=50, strict=True)

class ModelVersionRef(_Strict):
    model_code: str
    version: str
    kind: Literal["rule", "ml", "llm"]

class RecommendationItem(_Strict):
    rank: int = Field(ge=1)
    score: float | None = Field(default=None, ge=0, le=100)
    reason: str = Field(min_length=1)
    feedback: Literal["liked", "not_interested"] | None = None
    job_posting: JobPostingSummary

class RecommendationRun(_Strict):
    recommendation_run_id: UUID
    status: Literal["completed", "fallback", "failed"]
    model_version: ModelVersionRef
    generated_at: datetime
    items: list[RecommendationItem]
