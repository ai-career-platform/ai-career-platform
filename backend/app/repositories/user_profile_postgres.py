"""users + user_profiles PostgreSQL 저장소 (T16).

테이블 계약: database/DATA_DICTIONARY.md A01 `users`, A02 `user_profiles` (스키마 `career`).
T14 `app.db.get_db`가 요청마다 주는 SQLAlchemy `Session`으로 쿼리한다.
T14 규칙("성공한 쓰기는 호출자가 commit")에 따라 update가 성공하면 여기서 commit한다.

ORM 모델은 T09 스키마 확정 후 `app.models`에 추가될 예정이라(app/models/__init__.py),
그 전까지는 SQL 문으로 쿼리한다. 모델이 생기면 이 파일만 바꾸면 된다.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.repositories.user_profile import PROFILE_FIELDS, USER_FIELDS, UserProfileRecord

SCHEMA = "career"

_SELECT = text(
    f"""
    SELECT u.user_id, u.email, u.display_name, u.status, u.created_at,
           p.headline, p.bio, p.location_text
      FROM {SCHEMA}.users AS u
      LEFT JOIN {SCHEMA}.user_profiles AS p ON p.user_id = u.user_id
     WHERE u.user_id = :user_id
    """
)

_LOCK_USER = text(f"SELECT 1 FROM {SCHEMA}.users WHERE user_id = :user_id FOR UPDATE")


class PostgresUserProfileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: UUID) -> UserProfileRecord | None:
        row = self._session.execute(_SELECT, {"user_id": user_id}).mappings().one_or_none()
        return UserProfileRecord(**row) if row else None

    def update(self, user_id: UUID, changes: dict[str, str | None]) -> UserProfileRecord | None:
        unknown = set(changes) - set(USER_FIELDS) - set(PROFILE_FIELDS)
        if unknown:
            raise ValueError(f"unknown fields: {sorted(unknown)}")

        user_changes = {k: v for k, v in changes.items() if k in USER_FIELDS}
        profile_changes = {k: v for k, v in changes.items() if k in PROFILE_FIELDS}

        try:
            if not self._lock_user(user_id, user_changes):
                self._session.rollback()
                return None
            if profile_changes:
                self._upsert_profile(user_id, profile_changes)
            record = self.get(user_id)
            self._session.commit()
            return record
        except Exception:
            self._session.rollback()
            raise

    def _lock_user(self, user_id: UUID, user_changes: dict[str, str | None]) -> bool:
        """users 행을 잠그고(필요하면 수정하고) 존재 여부를 돌려준다."""
        if user_changes:
            # 컬럼 이름은 USER_FIELDS 허용 목록에서만 온다. 값은 모두 바인딩.
            assignments = ", ".join(f"{col} = :{col}" for col in user_changes)
            query = text(
                f"UPDATE {SCHEMA}.users SET {assignments}, updated_at = now() "
                "WHERE user_id = :user_id RETURNING 1"
            )
        else:
            query = _LOCK_USER
        return self._session.execute(query, {**user_changes, "user_id": user_id}).first() is not None

    def _upsert_profile(self, user_id: UUID, profile_changes: dict[str, str | None]) -> None:
        """user_profiles 행이 없으면 만들고, 있으면 보낸 컬럼만 바꾼다."""
        # 컬럼 이름은 PROFILE_FIELDS 허용 목록에서만 온다. 값은 모두 바인딩.
        cols = list(profile_changes)
        query = text(
            f"INSERT INTO {SCHEMA}.user_profiles (user_id, {', '.join(cols)}) "
            f"VALUES (:user_id, {', '.join(':' + c for c in cols)}) "
            f"ON CONFLICT (user_id) DO UPDATE SET "
            f"{', '.join(f'{c} = EXCLUDED.{c}' for c in cols)}, updated_at = now()"
        )
        self._session.execute(query, {**profile_changes, "user_id": user_id})
