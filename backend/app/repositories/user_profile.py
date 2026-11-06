"""users + user_profiles 저장소 (T16).

테이블 계약: database/DATA_DICTIONARY.md A01 `users`, A02 `user_profiles`.
실제 PostgreSQL 구현은 T14(DB 세션) 병합 후 같은 인터페이스로 추가한다.
지금은 테스트·mock용 메모리 구현만 있다.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

PROFILE_FIELDS = ("headline", "bio", "location_text")
USER_FIELDS = ("display_name",)


@dataclass(frozen=True)
class UserProfileRecord:
    """users 한 행과 (있으면) user_profiles 한 행을 합친 값."""

    user_id: UUID
    email: str
    display_name: str
    status: str
    created_at: datetime
    headline: str | None = None
    bio: str | None = None
    location_text: str | None = None


class UserProfileRepository(Protocol):
    def get(self, user_id: UUID) -> UserProfileRecord | None:
        """사용자가 없으면 None. user_profiles 행이 없으면 프로필 필드는 None."""

    def update(self, user_id: UUID, changes: dict[str, str | None]) -> UserProfileRecord | None:
        """display_name은 users, 나머지는 user_profiles(없으면 생성)에 반영한다.

        사용자가 없으면 아무것도 바꾸지 않고 None.
        """


@dataclass
class InMemoryUserProfileRepository:
    """테스트·mock 전용. 프로세스 메모리에만 저장한다."""

    _rows: dict[UUID, UserProfileRecord] = field(default_factory=dict)

    def add(self, record: UserProfileRecord) -> None:
        self._rows[record.user_id] = record

    def get(self, user_id: UUID) -> UserProfileRecord | None:
        return self._rows.get(user_id)

    def update(self, user_id: UUID, changes: dict[str, str | None]) -> UserProfileRecord | None:
        current = self._rows.get(user_id)
        if current is None:
            return None
        allowed = set(USER_FIELDS) | set(PROFILE_FIELDS)
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown fields: {sorted(unknown)}")
        updated = replace(current, **changes)
        self._rows[user_id] = updated
        return updated
