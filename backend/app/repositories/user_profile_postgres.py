"""users + user_profiles PostgreSQL 저장소 (T16).

테이블 계약: database/DATA_DICTIONARY.md A01 `users`, A02 `user_profiles` (스키마 `career`).
연결은 T14의 `get_db`가 요청마다 빌려주는 psycopg Connection을 받는다.
T14 계약상 "성공한 쓰기의 커밋은 호출자 책임"이므로 update는 자기 트랜잭션 안에서 커밋한다.

psycopg는 T14가 requirements.txt에 추가한다. 그 전에는 이 모듈을 앱이 import하지 않는다.
"""

from typing import Any
from uuid import UUID

from psycopg import Connection, sql
from psycopg.rows import dict_row

from app.repositories.user_profile import PROFILE_FIELDS, USER_FIELDS, UserProfileRecord

SCHEMA = "career"

_SELECT = sql.SQL(
    """
    SELECT u.user_id, u.email, u.display_name, u.status, u.created_at,
           p.headline, p.bio, p.location_text
      FROM {users} AS u
      LEFT JOIN {profiles} AS p ON p.user_id = u.user_id
     WHERE u.user_id = %s
    """
).format(
    users=sql.Identifier(SCHEMA, "users"),
    profiles=sql.Identifier(SCHEMA, "user_profiles"),
)


class PostgresUserProfileRepository:
    def __init__(self, connection: Connection[Any]) -> None:
        self._conn = connection

    def get(self, user_id: UUID) -> UserProfileRecord | None:
        with self._conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(_SELECT, (user_id,)).fetchone()
        return UserProfileRecord(**row) if row else None

    def update(self, user_id: UUID, changes: dict[str, str | None]) -> UserProfileRecord | None:
        unknown = set(changes) - set(USER_FIELDS) - set(PROFILE_FIELDS)
        if unknown:
            raise ValueError(f"unknown fields: {sorted(unknown)}")

        user_changes = {k: v for k, v in changes.items() if k in USER_FIELDS}
        profile_changes = {k: v for k, v in changes.items() if k in PROFILE_FIELDS}

        with self._conn.transaction():
            if not self._lock_user(user_id, user_changes):
                return None
            if profile_changes:
                self._upsert_profile(user_id, profile_changes)
            return self.get(user_id)

    def _lock_user(self, user_id: UUID, user_changes: dict[str, str | None]) -> bool:
        """users 행을 잠그고(필요하면 수정하고) 존재 여부를 돌려준다."""
        users = sql.Identifier(SCHEMA, "users")
        if user_changes:
            assignments = sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(col)) for col in user_changes
            )
            query = sql.SQL("UPDATE {} SET {}, updated_at = now() WHERE user_id = %s RETURNING 1").format(
                users, assignments
            )
            params = (*user_changes.values(), user_id)
        else:
            query = sql.SQL("SELECT 1 FROM {} WHERE user_id = %s FOR UPDATE").format(users)
            params = (user_id,)
        return self._conn.execute(query, params).fetchone() is not None

    def _upsert_profile(self, user_id: UUID, profile_changes: dict[str, str | None]) -> None:
        """user_profiles 행이 없으면 만들고, 있으면 보낸 컬럼만 바꾼다."""
        cols = [sql.Identifier(col) for col in profile_changes]
        query = sql.SQL(
            "INSERT INTO {table} (user_id, {cols}) VALUES (%s, {placeholders}) "
            "ON CONFLICT (user_id) DO UPDATE SET {updates}, updated_at = now()"
        ).format(
            table=sql.Identifier(SCHEMA, "user_profiles"),
            cols=sql.SQL(", ").join(cols),
            placeholders=sql.SQL(", ").join(sql.Placeholder() for _ in cols),
            updates=sql.SQL(", ").join(sql.SQL("{0} = EXCLUDED.{0}").format(col) for col in cols),
        )
        self._conn.execute(query, (user_id, *profile_changes.values()))
