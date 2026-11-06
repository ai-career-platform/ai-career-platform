"""`/api/v1/me` 요청·응답 DTO (T16).

계약: docs/api/openapi.yaml `Me`, `MePatch`, `Profile` / docs/API_CONTRACT.md §1.1·§1.3
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Profile(BaseModel):
    headline: str | None = Field(max_length=200)
    bio: str | None = Field(max_length=5000)
    location_text: str | None = Field(max_length=120)


class Me(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    status: Literal["active", "disabled"]
    profile: Profile
    created_at: datetime


class MePatch(BaseModel):
    """보낸 필드만 바꾼다. null을 보내면 값을 지운다(display_name은 null 불가).

    보내지 않은 필드와 null로 보낸 필드는 `model_fields_set`으로 구분한다.
    user_id·email 등 계약에 없는 필드는 거부한다(extra="forbid").
    """

    model_config = ConfigDict(extra="forbid")

    # 기본값 None은 "보내지 않음"을 뜻할 뿐이다. 타입이 str이라 null을 보내면 422.
    display_name: str = Field(default=None, min_length=1, max_length=100)
    headline: str | None = Field(default=None, max_length=200)
    bio: str | None = Field(default=None, max_length=5000)
    location_text: str | None = Field(default=None, max_length=120)

    @field_validator("display_name")
    @classmethod
    def display_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("display_name must not be blank")
        return value

    @model_validator(mode="after")
    def at_least_one_field(self) -> "MePatch":
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self

    def changes(self) -> dict[str, str | None]:
        """요청에 실제로 들어온 필드만 돌려준다."""
        return self.model_dump(include=self.model_fields_set)
