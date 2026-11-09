from datetime import date, datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, String, Uuid, column, delete, func, insert, select, table, update
from sqlalchemy.orm import Session

from app.schemas.career_history import Experience, ExperienceInput, ExperiencePatch, Project, ProjectInput, ProjectPatch
from app.schemas.catalog import Skill

S = "career"
experiences = table("user_experiences", column("experience_id", Uuid), column("user_id", Uuid),
    column("organization", String), column("title", String), column("start_date", Date), column("end_date", Date),
    column("description", String), column("created_at", DateTime(timezone=True)), column("updated_at", DateTime(timezone=True)), schema=S)
projects = table("user_projects", column("project_id", Uuid), column("user_id", Uuid), column("title", String),
    column("summary", String), column("start_date", Date), column("end_date", Date),
    column("created_at", DateTime(timezone=True)), column("updated_at", DateTime(timezone=True)), schema=S)
project_skills = table("user_project_skills", column("project_id", Uuid), column("skill_id", Uuid), schema=S)
skills = table("skills", column("skill_id", Uuid), column("code", String), column("name", String), schema=S)


class CareerHistoryRepository(Protocol):
    def list_experiences(self, user_id: UUID) -> list[Experience]: ...
    def create_experience(self, user_id: UUID, data: ExperienceInput) -> Experience: ...
    def update_experience(self, user_id: UUID, item_id: UUID, data: ExperiencePatch) -> Experience | None: ...
    def delete_experience(self, user_id: UUID, item_id: UUID) -> bool: ...
    def list_projects(self, user_id: UUID) -> list[Project]: ...
    def create_project(self, user_id: UUID, data: ProjectInput) -> Project:
        """모르는 skill_id가 있으면 ValueError."""
    def update_project(self, user_id: UUID, item_id: UUID, data: ProjectPatch) -> Project | None:
        """본인 프로젝트가 없으면 None, 모르는 skill_id·잘못된 기간이면 ValueError."""
    def delete_project(self, user_id: UUID, item_id: UUID) -> bool: ...


class SqlCareerHistoryRepository:
    def __init__(self, db: Session): self.db = db

    @staticmethod
    def _experience(r) -> Experience:
        return Experience(experience_id=r.experience_id, organization=r.organization, title=r.title,
            start_date=r.start_date, end_date=r.end_date, description=r.description, updated_at=r.updated_at)

    def list_experiences(self, user_id):
        rows = self.db.execute(select(experiences).where(experiences.c.user_id == user_id)
            .order_by(experiences.c.start_date.desc().nullslast(), experiences.c.experience_id)).all()
        return [self._experience(r) for r in rows]

    def create_experience(self, user_id, data):
        item_id = uuid4()
        self.db.execute(insert(experiences).values(experience_id=item_id, user_id=user_id, **data.model_dump()))
        self.db.commit()
        return self._experience(self.db.execute(select(experiences).where(experiences.c.experience_id == item_id)).one())

    def update_experience(self, user_id, item_id, data):
        current = self.db.execute(select(experiences).where(experiences.c.experience_id == item_id,
            experiences.c.user_id == user_id)).one_or_none()
        if current is None: return None
        values = data.model_dump(exclude_unset=True)
        start, end = values.get("start_date", current.start_date), values.get("end_date", current.end_date)
        if start and end and end < start: raise ValueError("invalid date range")
        self.db.execute(update(experiences).where(experiences.c.experience_id == item_id)
            .values(**values, updated_at=func.now()))
        self.db.commit()
        return self._experience(self.db.execute(select(experiences).where(experiences.c.experience_id == item_id)).one())

    def delete_experience(self, user_id, item_id):
        result = self.db.execute(delete(experiences).where(experiences.c.experience_id == item_id,
            experiences.c.user_id == user_id)); self.db.commit(); return bool(result.rowcount)

    def _project(self, r) -> Project:
        skill_rows = self.db.execute(select(skills).select_from(project_skills.join(skills,
            project_skills.c.skill_id == skills.c.skill_id)).where(project_skills.c.project_id == r.project_id)
            .order_by(skills.c.name, skills.c.skill_id)).all()
        return Project(project_id=r.project_id, title=r.title, summary=r.summary, start_date=r.start_date,
            end_date=r.end_date, updated_at=r.updated_at,
            skills=[Skill(skill_id=s.skill_id, code=s.code, name=s.name) for s in skill_rows])

    def list_projects(self, user_id):
        rows = self.db.execute(select(projects).where(projects.c.user_id == user_id)
            .order_by(projects.c.start_date.desc().nullslast(), projects.c.project_id)).all()
        return [self._project(r) for r in rows]

    def _check_skills(self, ids):
        if ids and len(ids) != len(set(self.db.scalars(select(skills.c.skill_id).where(skills.c.skill_id.in_(ids))))):
            raise ValueError("unknown skill")

    def create_project(self, user_id, data):
        self._check_skills(data.skill_ids)
        item_id, values = uuid4(), data.model_dump(exclude={"skill_ids"})
        self.db.execute(insert(projects).values(project_id=item_id, user_id=user_id, **values))
        if data.skill_ids: self.db.execute(insert(project_skills), [{"project_id": item_id, "skill_id": x} for x in data.skill_ids])
        self.db.commit(); return self._project(self.db.execute(select(projects).where(projects.c.project_id == item_id)).one())

    def update_project(self, user_id, item_id, data):
        current = self.db.execute(select(projects).where(projects.c.project_id == item_id,
            projects.c.user_id == user_id)).one_or_none()
        if current is None: return None
        values = data.model_dump(exclude_unset=True); ids = values.pop("skill_ids", None)
        if ids is not None: self._check_skills(ids)
        start, end = values.get("start_date", current.start_date), values.get("end_date", current.end_date)
        if start and end and end < start: raise ValueError("invalid date range")
        # skill_ids만 바꿔도 수정 시각은 갱신한다.
        self.db.execute(update(projects).where(projects.c.project_id == item_id)
            .values(**values, updated_at=func.now()))
        if ids is not None:
            self.db.execute(delete(project_skills).where(project_skills.c.project_id == item_id))
            if ids: self.db.execute(insert(project_skills), [{"project_id": item_id, "skill_id": x} for x in ids])
        self.db.commit(); return self._project(self.db.execute(select(projects).where(projects.c.project_id == item_id)).one())

    def delete_project(self, user_id, item_id):
        result = self.db.execute(delete(projects).where(projects.c.project_id == item_id,
            projects.c.user_id == user_id)); self.db.commit(); return bool(result.rowcount)
