"""T17 DTOs matching the T06 catalog contract."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Skill(CatalogModel):
    skill_id: UUID
    code: str
    name: str


class JobRoleRef(CatalogModel):
    job_role_id: UUID
    code: str
    name: str


class RequiredSkill(CatalogModel):
    skill: Skill
    required_level: int = Field(ge=1, le=5)


class JobRoleDetail(JobRoleRef):
    description: str | None
    required_skills: list[RequiredSkill]


class JobRolePage(CatalogModel):
    items: list[JobRoleRef]
    next_cursor: str | None


class SkillSearchResult(CatalogModel):
    items: list[Skill]


class JobRoleQuery(CatalogModel):
    q: str | None = Field(default=None, min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    cursor: str | None = Field(default=None, max_length=500)


class SkillQuery(CatalogModel):
    q: str = Field(min_length=2, max_length=60)
    limit: int = Field(default=20, ge=1, le=100, strict=True)
