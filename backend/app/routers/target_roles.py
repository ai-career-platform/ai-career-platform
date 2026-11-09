"""T35 ``/me/target-roles`` API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.target_roles import SqlTargetRoleRepository
from app.schemas.target_roles import TargetRole, TargetRolesReplace
from app.services.target_roles import TargetRoleService


def get_target_role_service(session: Annotated[Session, Depends(get_db)]) -> TargetRoleService:
    return TargetRoleService(SqlTargetRoleRepository(session))


ServiceDep = Annotated[TargetRoleService, Depends(get_target_role_service)]

router = APIRouter(
    prefix="/me/target-roles",
    tags=["me"],
    responses=error_responses(401, 503),
)


def reject_query_parameters(request: Request) -> None:
    if request.query_params:
        raise AppError(ErrorCode.VALIDATION_FAILED)


@router.get("", response_model=list[TargetRole], operation_id="listMyTargetRoles")
def list_my_target_roles(request: Request, user: CurrentUserDep, service: ServiceDep) -> list[TargetRole]:
    reject_query_parameters(request)
    return service.list_for_user(user.user_id)


@router.put("", response_model=list[TargetRole], operation_id="replaceMyTargetRoles")
def replace_my_target_roles(
    request: Request, payload: TargetRolesReplace, user: CurrentUserDep, service: ServiceDep,
) -> list[TargetRole]:
    reject_query_parameters(request)
    return service.replace(user.user_id, payload)
