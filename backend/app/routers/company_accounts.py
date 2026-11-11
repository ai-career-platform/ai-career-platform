"""T123 기업 등록·초대·소속 API — `COMPANY_ACCOUNTS_API=true` 일 때만 create_app 이 등록(기본 꺼짐, T121·T122 미승인).

저장소는 아직 없다(정식 migration 승인 전). 그래서 기본 의존성 `get_company_service` 는 503 을 돌려주고,
시험만 메모리 저장소로 바꿔 끼운다. 권한: 소속이 아니면 404, 같은 조직에서 역할이 부족하면 403(T121).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.dependencies.auth import CurrentUserDep
from app.schemas import company_accounts as dto
from app.services import company_accounts as svc

router = APIRouter(tags=["company"], responses=error_responses(401, 503))


def get_company_service() -> svc.CompanyAccountService:
    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="company storage not provisioned (T122 migration HOLD)")


Service = Annotated[svc.CompanyAccountService, Depends(get_company_service)]


def _org(org: svc.Organization) -> dto.Organization:
    return dto.Organization(organization_id=org.organization_id, name=org.name, status=org.status,
                            linked_company_id=org.linked_company_id, status_reason=org.status_reason,
                            version=org.version, created_at=org.created_at)


def _inv(inv: svc.Invitation) -> dto.Invitation:
    return dto.Invitation(invitation_id=inv.invitation_id, email_masked=svc.masked(inv.email_canonical), role=inv.role,
                          status=inv.status, expires_at=inv.expires_at, resend_count=inv.resend_count)


def _member(member: svc.Member, info: svc.UserInfo | None) -> dto.Member:
    return dto.Member(user_id=member.user_id, display_name=info.display_name if info else "(탈퇴한 사용자)",
                      email_masked=svc.masked(info.email) if info else "", role=member.role,
                      joined_at=member.joined_at, version=member.version)


@router.post("/organizations", response_model=dto.Organization, status_code=201, operation_id="registerOrganization",
             responses=error_responses(409, 422))
def register(body: dto.OrganizationCreate, user: CurrentUserDep, service: Service) -> dto.Organization:
    org, _ = service.register(user.user_id, body.name, body.linked_company_id)
    return _org(org)


@router.get("/me/organizations", response_model=list[dto.MyOrganization], operation_id="listMyOrganizations")
def my_organizations(user: CurrentUserDep, service: Service) -> list[dto.MyOrganization]:
    return [dto.MyOrganization(organization=_org(o), role=r) for o, r in service.my_organizations(user.user_id)]


@router.get("/organizations/{organization_id}", response_model=dto.Organization, operation_id="getOrganization",
            responses=error_responses(403, 404))
def get_organization(organization_id: UUID, user: CurrentUserDep, service: Service) -> dto.Organization:
    return _org(service.get(user.user_id, organization_id))


@router.get("/organizations/{organization_id}/members", response_model=list[dto.Member],
            operation_id="listOrganizationMembers", responses=error_responses(403, 404))
def list_members(organization_id: UUID, user: CurrentUserDep, service: Service) -> list[dto.Member]:
    return [_member(m, u) for m, u in service.members(user.user_id, organization_id)]


@router.patch("/organizations/{organization_id}/members/{user_id}", response_model=dto.Member,
              operation_id="changeMemberRole", responses=error_responses(403, 404, 409, 422))
def change_role(organization_id: UUID, user_id: UUID, body: dto.MemberUpdate, user: CurrentUserDep,
                service: Service) -> dto.Member:
    member = service.change_role(user.user_id, organization_id, user_id, body.role, body.version)
    return _member(member, service.users.get(member.user_id))


@router.delete("/organizations/{organization_id}/members/{user_id}", status_code=204, operation_id="removeMember",
               responses=error_responses(403, 404, 409))
def remove_member(organization_id: UUID, user_id: UUID, user: CurrentUserDep, service: Service) -> Response:
    service.remove(user.user_id, organization_id, user_id)
    return Response(status_code=204)


@router.get("/organizations/{organization_id}/invitations", response_model=list[dto.Invitation],
            operation_id="listInvitations", responses=error_responses(403, 404))
def list_invitations(organization_id: UUID, user: CurrentUserDep, service: Service) -> list[dto.Invitation]:
    return [_inv(i) for i in service.invitations(user.user_id, organization_id)]


@router.post("/organizations/{organization_id}/invitations", response_model=dto.Invitation, status_code=201,
             operation_id="createInvitation", responses=error_responses(403, 404, 409, 422))
def create_invitation(organization_id: UUID, body: dto.InvitationCreate, user: CurrentUserDep,
                      service: Service) -> dto.Invitation:
    return _inv(service.invite(user.user_id, organization_id, body.email, body.role))


@router.post("/organizations/{organization_id}/invitations/{invitation_id}/resend", response_model=dto.Invitation,
             operation_id="resendInvitation", responses=error_responses(403, 404, 409))
def resend_invitation(organization_id: UUID, invitation_id: UUID, user: CurrentUserDep,
                      service: Service) -> dto.Invitation:
    return _inv(service.resend(user.user_id, organization_id, invitation_id))


@router.delete("/organizations/{organization_id}/invitations/{invitation_id}", status_code=204,
               operation_id="revokeInvitation", responses=error_responses(403, 404, 409))
def revoke_invitation(organization_id: UUID, invitation_id: UUID, user: CurrentUserDep, service: Service) -> Response:
    service.revoke(user.user_id, organization_id, invitation_id)
    return Response(status_code=204)


@router.post("/organization-invitations/accept", response_model=dto.MyOrganization, operation_id="acceptInvitation",
             responses=error_responses(404, 409, 422))
def accept_invitation(body: dto.InvitationAccept, user: CurrentUserDep, service: Service) -> dto.MyOrganization:
    org, role = service.accept(user.user_id, user.roles, body.token)
    return dto.MyOrganization(organization=_org(org), role=role)


@router.post("/admin/organizations/{organization_id}/verification", response_model=dto.Organization,
             operation_id="verifyOrganization", responses=error_responses(403, 404, 409, 422))
def verify_organization(organization_id: UUID, body: dto.VerificationDecision, user: CurrentUserDep,
                        service: Service) -> dto.Organization:
    return _org(service.verify(user.user_id, user.roles, organization_id, body.decision, body.reason, body.version))
