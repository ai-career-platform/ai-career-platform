"""T17 catalog services, independent of HTTP and database lifecycle."""

import base64
import hashlib
import hmac
import json
from uuid import UUID

from app.core.errors import AppError, ErrorCode
from app.repositories.catalog import CatalogRepository
from app.schemas.catalog import (
    JobRoleDetail, JobRolePage, JobRoleQuery, SkillQuery, SkillSearchResult,
)


class CatalogService:
    def __init__(self, repository: CatalogRepository, *, cursor_key: bytes):
        # Supplied by the integration layer; never hardcode a production key.
        if not isinstance(cursor_key, bytes) or len(cursor_key) < 32:
            raise ValueError("cursor_key must contain at least 32 bytes")
        self.repository = repository
        self._cursor_key = cursor_key

    def _encode_cursor(self, q: str | None, name: str, role_id: UUID) -> str:
        # Hash variable-length fields to keep every cursor below 500 characters.
        payload = json.dumps(
            [1, self._digest(q), self._digest(name), str(role_id)],
            separators=(",", ":")
        ).encode()
        signature = hmac.digest(self._cursor_key, payload, "sha256")
        return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")

    @staticmethod
    def _digest(value: str | None) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode()).hexdigest()

    def _decode_cursor(self, token: str, q: str | None) -> tuple[str, UUID]:
        try:
            raw = base64.b64decode(
                token + "=" * (-len(token) % 4), altchars=b"-_", validate=True
            )
            if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
                raise ValueError
            signature, payload = raw[:32], raw[32:]
            expected = hmac.digest(self._cursor_key, payload, "sha256")
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            version, saved_q, name_hash, role_id = json.loads(payload)
            if type(version) is not int or version != 1 or saved_q != self._digest(q):
                raise ValueError
            anchor = self.repository.get_job_role(UUID(role_id))
            if anchor is None or name_hash != self._digest(anchor.name):
                raise ValueError
            return anchor.name, anchor.job_role_id
        except (ValueError, TypeError, UnicodeError) as exc:
            raise AppError(ErrorCode.INVALID_CURSOR) from exc

    def list_job_roles(self, query: JobRoleQuery) -> JobRolePage:
        after = (
            self._decode_cursor(query.cursor, query.q)
            if query.cursor is not None else None
        )
        rows = self.repository.list_job_roles(
            q=query.q, after=after, limit=query.limit + 1
        )
        items = rows[:query.limit]
        cursor = None
        if len(rows) > query.limit:
            last = items[-1]
            cursor = self._encode_cursor(query.q, last.name, last.job_role_id)
        return JobRolePage(items=items, next_cursor=cursor)

    def get_job_role(self, role_id: UUID) -> JobRoleDetail:
        role = self.repository.get_job_role(role_id)
        if role is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return role

    def search_skills(self, query: SkillQuery) -> SkillSearchResult:
        return SkillSearchResult(
            items=self.repository.search_skills(q=query.q, limit=query.limit)
        )
