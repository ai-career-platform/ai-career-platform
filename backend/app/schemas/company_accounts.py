"""T123 기업 조직·소속·초대 DTO (T122 제안 계약 docs/enterprise/t122_openapi_proposal.yaml 과 같은 모양)."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import Email

OrganizationStatus = Literal["pending", "active", "suspended", "closed", "rejected"]
MemberRole = Literal["owner", "member"]
InvitationStatus = Literal["pending", "accepted", "revoked", "expired"]


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    linked_company_id: UUID | None = None


class Organization(BaseModel):
    organization_id: UUID
    name: str
    status: OrganizationStatus
    linked_company_id: UUID | None = None
    status_reason: str | None = None
    version: int
    created_at: datetime


class MyOrganization(BaseModel):
    organization: Organization
    role: MemberRole


class Member(BaseModel):
    user_id: UUID
    display_name: str
    email_masked: str
    role: MemberRole
    joined_at: datetime
    version: int


class MemberUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: MemberRole
    version: int = Field(ge=1)


class InvitationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    role: MemberRole = "member"


class Invitation(BaseModel):
    invitation_id: UUID
    email_masked: str
    role: MemberRole
    status: InvitationStatus
    expires_at: datetime
    resend_count: int


class InvitationAccept(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=200)


class VerificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=300)
    version: int = Field(ge=1)
