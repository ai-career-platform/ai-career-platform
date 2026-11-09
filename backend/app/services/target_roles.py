"""T35 target-role business rules."""

from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.target_roles import TargetRoleRepository
from app.schemas.target_roles import TargetRole, TargetRolesReplace


class TargetRoleService:
    def __init__(self, repository: TargetRoleRepository):
        self.repository = repository

    def list_for_user(self, user_id: UUID) -> list[TargetRole]:
        return self.repository.list_for_user(user_id)

    def replace(self, user_id: UUID, payload: TargetRolesReplace) -> list[TargetRole]:
        result = self.repository.replace(user_id, payload.items)
        if result is None:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail="inactive or unknown job role")
        return result
