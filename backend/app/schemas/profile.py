"""T16 DTOs, matching docs/api/openapi.yaml (Me, Profile, MePatch)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    headline: str | None = Field(max_length=200)
    bio: str | None = Field(max_length=5000)
    location_text: str | None = Field(max_length=120)


class Me(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    email: str
    display_name: str
    status: Literal["active", "disabled"]
    profile: Profile
    created_at: datetime


class MePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra={"minProperties": 1})
    # None is an internal omitted default, NOT an accepted display_name value.
    display_name: str = Field(default=None, min_length=1, max_length=100)
    headline: str | None = Field(default=None, max_length=200)
    bio: str | None = Field(default=None, max_length=5000)
    location_text: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one profile field is required")
        return self
