"""T17 read interface; PostgreSQL adapter awaits the T14 session contract.

Implementations must use bound parameters, filter inactive records, and limit
results in the database. Never load the whole catalog for application paging.
"""

from typing import Protocol
from uuid import UUID

from app.schemas.catalog import JobRoleDetail, JobRoleRef, Skill


class CatalogRepository(Protocol):
    def list_job_roles(
        self, *, q: str | None, after: tuple[str, UUID] | None, limit: int
    ) -> list[JobRoleRef]:
        """Active names matching q literally (case insensitive substring).

        Order by (name, job_role_id), using the same collation for keyset
        comparison. `after` is exclusive. Return at most `limit` rows.
        """
        ...

    def get_job_role(self, job_role_id: UUID) -> JobRoleDetail | None:
        """Return detail with required skills, or None for a missing role."""
        ...

    def search_skills(self, *, q: str, limit: int) -> list[Skill]:
        """Active literal substring matches, case insensitive.

        Rank prefix matches first, then name and skill_id; no duplicates.
        Wildcards in q are literal characters, not user-controlled SQL syntax.
        """
        ...
