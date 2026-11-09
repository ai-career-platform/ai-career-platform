"""T17 catalog read port and SQL implementation, following repositories/auth.py.

CatalogService depends on the protocol; runtime uses SqlCatalogRepository.
The caller supplies and closes the T14 Session. These table expressions do
not create schema, migrations or a competing set of shared ORM models.
"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import Boolean, String, Uuid, case, column, select, table, tuple_
from sqlalchemy.orm import Session

from app.schemas.catalog import JobRoleDetail, JobRoleRef, RequiredSkill, Skill


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


class SqlCatalogRepository:
    def __init__(self, session: Session, *, schema: str | None = "career"):
        self.session = session
        self.roles = table(
            "job_roles", column("job_role_id", Uuid), column("code", String),
            column("name", String), column("description", String),
            column("is_active", Boolean), schema=schema,
        )
        self.skills = table(
            "skills", column("skill_id", Uuid), column("code", String),
            column("name", String), column("is_active", Boolean), schema=schema,
        )
        self.links = table(
            "job_role_skills", column("job_role_id", Uuid),
            column("skill_id", Uuid), column("required_level"), schema=schema,
        )

    @staticmethod
    def _escape(value: str) -> str:
        return value.replace("/", "//").replace("%", "/%").replace("_", "/_")

    def list_job_roles(
        self, *, q: str | None, after: tuple[str, UUID] | None, limit: int
    ) -> list[JobRoleRef]:
        r = self.roles.c
        statement = select(r.job_role_id, r.code, r.name).where(r.is_active.is_(True))
        if q is not None:
            statement = statement.where(r.name.ilike(f"%{self._escape(q)}%", escape="/"))
        if after is not None:
            statement = statement.where(tuple_(r.name, r.job_role_id) > tuple_(after[0], after[1]))
        statement = statement.order_by(r.name, r.job_role_id).limit(limit)
        return [JobRoleRef.model_validate(row) for row in self.session.execute(statement).mappings()]

    def get_job_role(self, job_role_id: UUID) -> JobRoleDetail | None:
        r, s, link = self.roles.c, self.skills.c, self.links.c
        role = self.session.execute(
            select(r.job_role_id, r.code, r.name, r.description)
            .where(r.job_role_id == job_role_id)
        ).mappings().one_or_none()
        if role is None:
            return None
        statement = (
            select(s.skill_id, s.code, s.name, link.required_level)
            .select_from(self.links.join(self.skills, link.skill_id == s.skill_id))
            .where(link.job_role_id == job_role_id)
            .order_by(s.name, s.skill_id)
        )
        # Preserve referenced skills in detail, including retired catalog items.
        # is_active is a list/search visibility flag, not deletion of a relation.
        required = [
            RequiredSkill(
                skill=Skill(skill_id=row.skill_id, code=row.code, name=row.name),
                required_level=row.required_level,
            ) for row in self.session.execute(statement)
        ]
        return JobRoleDetail(**role, required_skills=required)

    def search_skills(self, *, q: str, limit: int) -> list[Skill]:
        s = self.skills.c
        escaped = self._escape(q)
        prefix = s.name.ilike(f"{escaped}%", escape="/")
        statement = (
            select(s.skill_id, s.code, s.name)
            .where(s.is_active.is_(True), s.name.ilike(f"%{escaped}%", escape="/"))
            .order_by(case((prefix, 0), else_=1), s.name, s.skill_id)
            .limit(limit)
        )
        return [Skill.model_validate(row) for row in self.session.execute(statement).mappings()]
