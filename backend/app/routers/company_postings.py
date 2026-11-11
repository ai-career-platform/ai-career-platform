"""T126 기업 공고 작성·검수 요청 API — `COMPANY_POSTINGS_API=true` 일 때만 등록(기본 꺼짐, T125 미승인).

공개 공고 목록(T18·T99 `/job-postings`)은 바꾸지 않는다. 운영 승인 전 공고는 공개 경로에 나오지 않는다.
저장소가 없어서(migration 승인 전) 기본 의존성은 503.
"""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.dependencies.auth import CurrentUserDep
from app.services import company_postings as svc

router = APIRouter(tags=["company-postings"], responses=error_responses(401, 503))
EmploymentType = Literal["full_time", "contract", "intern", "part_time"]


class PostingFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=20000)
    employment_type: EmploymentType | None = None
    location_text: str | None = Field(default=None, max_length=120)
    apply_url: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None


class PostingCreate(PostingFields):
    title: str = Field(min_length=1, max_length=240)


class PostingEdit(PostingFields):
    version: int = Field(ge=1)


class VersionOnly(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    reason_code: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    version: int = Field(ge=1)


class Takedown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=500)


class Posting(BaseModel):
    posting_id: UUID
    organization_id: UUID
    status: Literal["draft", "pending_review", "rejected", "published", "closed", "expired", "taken_down"]
    title: str
    description: str | None
    employment_type: str | None
    location_text: str | None
    apply_url: str | None
    expires_at: datetime | None
    version: int
    reason_code: str | None
    reason_note: str | None
    revision_of: UUID | None
    public_posting_id: UUID | None
    updated_at: datetime | None


def get_posting_service() -> svc.CompanyPostingService:
    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="posting storage not provisioned (T125 migration HOLD)")


Service = Annotated[svc.CompanyPostingService, Depends(get_posting_service)]


def _out(p: svc.CompanyPosting) -> Posting:
    return Posting(**{k: getattr(p, k) for k in Posting.model_fields})


def _values(body: PostingFields) -> dict:
    return body.model_dump(exclude_unset=True, exclude={"version"})


ORG = "/organizations/{organization_id}/postings"


@router.get(ORG, response_model=list[Posting], operation_id="listCompanyPostings", responses=error_responses(403, 404))
def list_postings(organization_id: UUID, user: CurrentUserDep, service: Service) -> list[Posting]:
    return [_out(p) for p in service.list(user.user_id, organization_id)]


@router.post(ORG, response_model=Posting, status_code=201, operation_id="createCompanyPosting",
             responses=error_responses(403, 404, 422))
def create(organization_id: UUID, body: PostingCreate, user: CurrentUserDep, service: Service) -> Posting:
    return _out(service.create(user.user_id, organization_id, _values(body)))


@router.get(ORG + "/{posting_id}", response_model=Posting, operation_id="getCompanyPosting",
            responses=error_responses(403, 404))
def get(organization_id: UUID, posting_id: UUID, user: CurrentUserDep, service: Service) -> Posting:
    return _out(service.get(user.user_id, organization_id, posting_id))


@router.patch(ORG + "/{posting_id}", response_model=Posting, operation_id="editCompanyPosting",
              responses=error_responses(403, 404, 409, 422))
def edit(organization_id: UUID, posting_id: UUID, body: PostingEdit, user: CurrentUserDep, service: Service) -> Posting:
    return _out(service.edit(user.user_id, organization_id, posting_id, _values(body), body.version))


@router.post(ORG + "/{posting_id}/revisions", response_model=Posting, status_code=201,
             operation_id="reviseCompanyPosting", responses=error_responses(403, 404, 409))
def revise(organization_id: UUID, posting_id: UUID, user: CurrentUserDep, service: Service) -> Posting:
    return _out(service.revise(user.user_id, organization_id, posting_id))


@router.post(ORG + "/{posting_id}/submit", response_model=Posting, operation_id="submitCompanyPosting",
             responses=error_responses(403, 404, 409, 422))
def submit(organization_id: UUID, posting_id: UUID, body: VersionOnly, user: CurrentUserDep,
           service: Service) -> Posting:
    return _out(service.submit(user.user_id, organization_id, posting_id, body.version))


@router.post(ORG + "/{posting_id}/withdraw", response_model=Posting, operation_id="withdrawCompanyPosting",
             responses=error_responses(403, 404, 409))
def withdraw(organization_id: UUID, posting_id: UUID, body: VersionOnly, user: CurrentUserDep,
             service: Service) -> Posting:
    return _out(service.withdraw(user.user_id, organization_id, posting_id, body.version))


@router.post(ORG + "/{posting_id}/close", response_model=Posting, operation_id="closeCompanyPosting",
             responses=error_responses(403, 404, 409))
def close(organization_id: UUID, posting_id: UUID, body: VersionOnly, user: CurrentUserDep,
          service: Service) -> Posting:
    return _out(service.close(user.user_id, user.roles, organization_id, posting_id, body.version))


@router.get("/admin/company-postings", response_model=list[Posting], operation_id="listPostingReviewQueue",
            responses=error_responses(403))
def review_queue(user: CurrentUserDep, service: Service) -> list[Posting]:
    return [_out(p) for p in service.queue(user.user_id, user.roles)]


@router.post("/admin/company-postings/{posting_id}/decision", response_model=Posting,
             operation_id="decideCompanyPosting", responses=error_responses(403, 404, 409, 422))
def decide(posting_id: UUID, body: Decision, user: CurrentUserDep, service: Service) -> Posting:
    return _out(service.decide(user.user_id, user.roles, posting_id, body.decision, body.reason_code, body.note,
                               body.version))


@router.post("/admin/company-postings/{posting_id}/takedown", response_model=Posting,
             operation_id="takedownCompanyPosting", responses=error_responses(403, 404, 409, 422))
def takedown(posting_id: UUID, body: Takedown, user: CurrentUserDep, service: Service) -> Posting:
    return _out(service.takedown(user.user_id, user.roles, posting_id, body.reason_code, body.note))
