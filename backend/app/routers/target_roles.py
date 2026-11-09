"""T35 ``/me/target-roles`` API."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.dependencies.auth import CurrentUserDep
from app.dependencies.target_roles import get_target_role_repository
from app.repositories.target_roles import TargetRoleRepository
from app.schemas.target_roles import TargetRole, TargetRolesReplace
from app.services.target_roles import TargetRoleService

router = APIRouter(
    prefix="/me/target-roles",
    tags=["me"],
    responses=error_responses(401, 503),
)


def reject_query_parameters(request: Request) -> None:
    if request.query_params:
        raise AppError(ErrorCode.VALIDATION_FAILED)


@router.get("", response_model=list[TargetRole], operation_id="listMyTargetRoles")
def list_my_target_roles(
    request: Request,
    user: CurrentUserDep,
    repository: Annotated[TargetRoleRepository, Depends(get_target_role_repository)],
) -> list[TargetRole]:
    reject_query_parameters(request)
    return TargetRoleService(repository).list_for_user(user.user_id)


@router.put("", response_model=list[TargetRole], operation_id="replaceMyTargetRoles")
def replace_my_target_roles(
    request: Request,
    payload: TargetRolesReplace,
    user: CurrentUserDep,
    repository: Annotated[TargetRoleRepository, Depends(get_target_role_repository)],
) -> list[TargetRole]:
    reject_query_parameters(request)
    return TargetRoleService(repository).replace(user.user_id, payload)
