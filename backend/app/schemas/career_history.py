from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.catalog import Skill


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _reject_explicit_null(model: BaseModel, fields: tuple[str, ...]) -> None:
    """PATCH에서 보낸 필드가 null이면 거부한다. 생략은 허용(변경 없음), null은 계약 위반(DB NOT NULL)."""
    if not model.model_fields_set:
        raise ValueError("at least one field is required")
    for name in fields:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} must not be null")


class DateRangeModel(StrictModel):
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class ExperienceInput(DateRangeModel):
    organization: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ExperiencePatch(DateRangeModel):
    organization: str | None = Field(default=None, min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None

    @model_validator(mode="after")
    def require_field(self):
        _reject_explicit_null(self, ("organization", "title"))
        return self


class Experience(ExperienceInput):
    experience_id: UUID
    updated_at: datetime


class ProjectInput(DateRangeModel):
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = None
    skill_ids: list[UUID] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_skills(self):
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("skill_ids must be unique")
        return self


class ProjectPatch(DateRangeModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = None
    skill_ids: list[UUID] | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def validate_patch(self):
        _reject_explicit_null(self, ("title", "skill_ids"))
        if self.skill_ids is not None and len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("skill_ids must be unique")
        return self


class Project(DateRangeModel):
    project_id: UUID
    title: str
    summary: str | None
    skills: list[Skill]
    updated_at: datetime
