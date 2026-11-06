"""T16 persistence, injected connection compatible with T14 psycopg proposal.

No pool, credentials, migrations, or fixtures are created here.
"""

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from app.core.profile_problems import ProfileProblem
from app.schemas.profile import Me, Profile


class ProfileRepository(Protocol):
    def get(self, user_id: UUID) -> Me | None: ...
    def patch(self, user_id: UUID, changes: Mapping[str, str | None]) -> Me | None: ...


class Cursor(Protocol):
    def fetchone(self) -> Sequence[Any] | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: Sequence[Any]) -> Cursor: ...
    def transaction(self) -> AbstractContextManager: ...
    def commit(self) -> None: ...


class PostgresProfileRepository:
    """Use psycopg's default tuple row factory; T14 owns connection lifetime."""

    PROFILE_FIELDS = ("headline", "bio", "location_text")

    def __init__(self, connection: Connection):
        self.connection = connection

    def get(self, user_id: UUID) -> Me | None:
        try:
            row = self.connection.execute(
                "SELECT u.user_id, u.email, u.display_name, u.status, u.created_at, "
                "p.headline, p.bio, p.location_text "
                "FROM users AS u LEFT JOIN user_profiles AS p ON p.user_id = u.user_id "
                "WHERE u.user_id = %s AND u.status = 'active'", (str(user_id),)
            ).fetchone()
            if row is None:
                return None
            return Me(user_id=row[0], email=row[1], display_name=row[2], status=row[3],
                      created_at=row[4], profile=Profile(headline=row[5], bio=row[6], location_text=row[7]))
        except Exception:
            raise ProfileProblem(503, "DEPENDENCY_UNAVAILABLE", "Profile storage unavailable") from None

    def patch(self, user_id: UUID, changes: Mapping[str, str | None]) -> Me | None:
        if not changes or set(changes) - {"display_name", *self.PROFILE_FIELDS}:
            raise ValueError("Unsupported profile fields")
        now = datetime.now(timezone.utc)
        try:
            # Both users and user_profiles change atomically. Updating users also
            # serializes concurrent PATCHes and rechecks active status at write time.
            with self.connection.transaction():
                assignments = ["updated_at = %s"]
                params: list[Any] = [now]
                if "display_name" in changes:
                    assignments.append("display_name = %s")
                    params.append(changes["display_name"])
                params.append(str(user_id))
                row = self.connection.execute(
                    "UPDATE users SET " + ", ".join(assignments) +
                    " WHERE user_id = %s AND status = 'active' RETURNING user_id", params
                ).fetchone()
                if row is None:
                    return None
                fields = [field for field in self.PROFILE_FIELDS if field in changes]
                if fields:
                    # Identifiers come only from the static allowlist above.
                    columns = ["user_id", *fields, "updated_at"]
                    values = [str(user_id), *(changes[field] for field in fields), now]
                    updates = [f"{field} = EXCLUDED.{field}" for field in [*fields, "updated_at"]]
                    self.connection.execute(
                        "INSERT INTO user_profiles (" + ", ".join(columns) + ") VALUES (" +
                        ", ".join(["%s"] * len(columns)) + ") ON CONFLICT (user_id) DO UPDATE SET " +
                        ", ".join(updates), values
                    )
                result = self.get(user_id)
            # T14 makes the caller commit successful writes. An auth dependency
            # may have opened an outer transaction, making the block a savepoint.
            self.connection.commit()
            return result
        except ProfileProblem:
            raise
        except Exception:
            raise ProfileProblem(503, "DEPENDENCY_UNAVAILABLE", "Profile storage unavailable") from None
