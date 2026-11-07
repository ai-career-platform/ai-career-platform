"""내 계정·프로필 조회·부분 수정 업무 규칙 (T16, FR-ACC-005)."""

from uuid import UUID

from app.repositories.user_profile import UserProfileRecord, UserProfileRepository
from app.schemas.me import Me, MePatch, Profile


class UserNotFoundError(Exception):
    """토큰은 유효하지만 사용자 행이 없음 (예: 탈퇴 처리 완료)."""


def _to_me(record: UserProfileRecord) -> Me:
    return Me(
        user_id=record.user_id,
        email=record.email,
        display_name=record.display_name,
        status=record.status,
        profile=Profile(
            headline=record.headline,
            bio=record.bio,
            location_text=record.location_text,
        ),
        created_at=record.created_at,
    )


def get_me(repository: UserProfileRepository, user_id: UUID) -> Me:
    record = repository.get(user_id)
    if record is None:
        raise UserNotFoundError
    return _to_me(record)


def update_me(repository: UserProfileRepository, user_id: UUID, patch: MePatch) -> Me:
    record = repository.update(user_id, patch.changes())
    if record is None:
        raise UserNotFoundError
    return _to_me(record)
