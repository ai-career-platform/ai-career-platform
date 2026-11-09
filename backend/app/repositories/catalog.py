"""T17 직무·기술 읽기 전용 DB 접근 (스키마 `career`, database/DATA_DICTIONARY.md 기준).

- 서비스는 `CatalogRepository` 프로토콜에만 의존한다. 테스트는 메모리 구현을 쓴다.
- 공유 ORM 모델을 새로 만들지 않고, 사용하는 컬럼만 `table()`로 적는다.
  테이블 생성·Migration은 T09 범위이며 여기서는 SELECT만 한다.
- `is_active=false`는 목록·검색 노출만 끈다(데이터 사전: "폐기 시 참조 보존").
  이미 저장된 ID로 여는 상세와, 상세에 딸린 요구 기술은 그대로 보여준다.
"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import Boolean, Integer, String, Uuid, case, column, select, table, tuple_
from sqlalchemy.orm import Session

from app.schemas.catalog import JobRoleDetail, JobRoleRef, RequiredSkill, Skill


class CatalogRepository(Protocol):
    def list_job_roles(self, *, q: str | None, after: tuple[str, UUID] | None, limit: int) -> list[JobRoleRef]:
        """활성 직무 중 이름에 q가 들어간 것(대소문자 무시, 와일드카드는 글자 그대로).

        (name, job_role_id) 순서. `after`는 그 다음부터(미포함). 최대 `limit`개.
        """

    def job_role_name(self, job_role_id: UUID) -> str | None:
        """cursor 기준 직무의 현재 이름. 없으면 None. 활성 여부와 무관."""

    def get_job_role(self, job_role_id: UUID) -> JobRoleDetail | None:
        """요구 기술을 포함한 상세. 없으면 None."""

    def search_skills(self, *, q: str, limit: int) -> list[Skill]:
        """활성 기술 중 이름에 q가 들어간 것. 앞부분 일치 → 이름 → skill_id 순."""


_SCHEMA = "career"
job_roles = table(
    "job_roles", column("job_role_id", Uuid), column("code", String), column("name", String),
    column("description", String), column("is_active", Boolean), schema=_SCHEMA,
)
skills = table(
    "skills", column("skill_id", Uuid), column("code", String), column("name", String),
    column("is_active", Boolean), schema=_SCHEMA,
)
job_role_skills = table(
    "job_role_skills", column("job_role_id", Uuid), column("skill_id", Uuid),
    column("required_level", Integer), schema=_SCHEMA,
)


def _contains(col, q: str):
    return col.ilike(f"%{_escape_like(q)}%", escape="\\")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class SqlCatalogRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_job_roles(self, *, q: str | None, after: tuple[str, UUID] | None, limit: int) -> list[JobRoleRef]:
        r = job_roles.c
        stmt = select(r.job_role_id, r.code, r.name).where(r.is_active.is_(True))
        if q is not None:
            stmt = stmt.where(_contains(r.name, q))
        if after is not None:
            stmt = stmt.where(tuple_(r.name, r.job_role_id) > tuple_(*after))
        stmt = stmt.order_by(r.name, r.job_role_id).limit(limit)
        return [JobRoleRef.model_validate(row) for row in self._db.execute(stmt).mappings()]

    def job_role_name(self, job_role_id: UUID) -> str | None:
        r = job_roles.c
        return self._db.execute(select(r.name).where(r.job_role_id == job_role_id)).scalar_one_or_none()

    def get_job_role(self, job_role_id: UUID) -> JobRoleDetail | None:
        r, s, link = job_roles.c, skills.c, job_role_skills.c
        role = self._db.execute(
            select(r.job_role_id, r.code, r.name, r.description).where(r.job_role_id == job_role_id)
        ).mappings().one_or_none()
        if role is None:
            return None
        rows = self._db.execute(
            select(s.skill_id, s.code, s.name, link.required_level)
            .select_from(job_role_skills.join(skills, link.skill_id == s.skill_id))
            .where(link.job_role_id == job_role_id)
            .order_by(s.name, s.skill_id)
        )
        required = [
            RequiredSkill(skill=Skill(skill_id=row.skill_id, code=row.code, name=row.name),
                          required_level=row.required_level)
            for row in rows
        ]
        return JobRoleDetail(**role, required_skills=required)

    def search_skills(self, *, q: str, limit: int) -> list[Skill]:
        s = skills.c
        prefix = s.name.ilike(f"{_escape_like(q)}%", escape="\\")
        stmt = (
            select(s.skill_id, s.code, s.name)
            .where(s.is_active.is_(True), _contains(s.name, q))
            .order_by(case((prefix, 0), else_=1), s.name, s.skill_id)
            .limit(limit)
        )
        return [Skill.model_validate(row) for row in self._db.execute(stmt).mappings()]
