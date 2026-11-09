from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.profile import ProfileRepository
from app.schemas.profile import Me, MePatch


class ProfileService:
    def __init__(self, repository: ProfileRepository):
        self.repository = repository

    @staticmethod
    def require_user(result: Me | None) -> Me:
        if result is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return result

    def get(self, user_id: UUID) -> Me:
        return self.require_user(self.repository.get(user_id))

    def patch(self, user_id: UUID, patch: MePatch) -> Me:
        return self.require_user(self.repository.patch(user_id, patch.model_dump(exclude_unset=True)))
