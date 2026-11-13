"""인증·내 계정 DTO (docs/api/openapi.yaml components.schemas 기준)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PolicyCode = Literal["terms", "privacy", "llm_processing", "behavior_tracking"]
# 형식만 검사한다(전송 가능 여부·DNS 확인 없음). 앞뒤 공백만 제거하고 원래 값을 보존한다.
Email = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsentInput(_Strict):
    policy_code: PolicyCode
    policy_version: str = Field(max_length=40)
    granted: bool


class SignupRequest(_Strict):
    email: Email
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)
    consents: list[ConsentInput] = Field(min_length=1)


class GoogleSignupRequest(_Strict):
    """#328 Google 최초 가입: 이메일·비밀번호 대신 서명된 pending 쿠키가 신원을 증명한다."""
    display_name: str = Field(min_length=1, max_length=100)
    consents: list[ConsentInput] = Field(min_length=1)


class GooglePendingSignup(_Strict):
    email: str
    display_name: str
    expires_at: datetime


class LoginRequest(_Strict):
    email: Email
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(_Strict):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


class ConsentPolicy(_Strict):
    policy_code: PolicyCode
    version: str
    is_required: bool
    content_url: str
    effective_at: datetime


class Profile(_Strict):
    headline: str | None
    bio: str | None
    location_text: str | None


class Me(_Strict):
    user_id: uuid.UUID
    email: str
    display_name: str
    status: Literal["active", "disabled"]
    profile: Profile
    created_at: datetime


class Permissions(_Strict):
    roles: list[str]
    permissions: list[str]


class Session(_Strict):
    session_id: uuid.UUID
    user_agent: str | None
    created_at: datetime
    expires_at: datetime
    is_current: bool
