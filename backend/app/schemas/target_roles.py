"""T35 request and response DTOs for ``/me/target-roles``."""

import uuid
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.schemas.base import ORMModel


class JobRoleRef(ORMModel):
    job_role_id: uuid.UUID
    code: str
    name: str


class TargetRole(ORMModel):
    job_role: JobRoleRef
    priority: int = Field(ge=1, le=3)


class TargetRoleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_role_id: uuid.UUID
    priority: StrictInt = Field(ge=1, le=3)


class TargetRolesReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TargetRoleItem] = Field(max_length=3)

    @model_validator(mode="after")
    def reject_duplicates(self) -> Self:
        role_ids = [item.job_role_id for item in self.items]
        priorities = [item.priority for item in self.items]
        if len(role_ids) != len(set(role_ids)) or len(priorities) != len(set(priorities)):
            raise ValueError("Target roles and priorities must be unique")
        return self
