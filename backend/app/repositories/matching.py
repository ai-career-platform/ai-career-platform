"""적합도 계산 DB 접근 (database/DATA_DICTIONARY.md B03·B04·B06·B07·B10·C02·C03·D01·D02, 스키마 `career`).

T17·T18·T33과 같은 방식으로 공용 ORM 모델 없이 필요한 컬럼만 `table()`로 적는다.
직무·기술·공고 테이블 선언은 T17(catalog)·T18(job_postings)·T33(my_skills) 것을 그대로 쓴다.
서비스는 `MatchRepository` 프로토콜에만 의존한다. 운영은 `SqlMatchRepository`, 테스트는 `tests/fakes_matching.py`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Boolean, DateTime, Numeric, SmallInteger, String, Text, Uuid, column, insert, select, table
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.repositories.catalog import job_role_skills
from app.repositories.job_postings import job_posting_skills, job_postings
from app.repositories.my_skills import user_skills

SCHEMA = "career"
job_roles = table("job_roles", column("job_role_id", Uuid), column("is_active", Boolean), schema=SCHEMA)
user_projects = table("user_projects", column("project_id", Uuid), column("user_id", Uuid), schema=SCHEMA)
user_project_skills = table("user_project_skills", column("project_id", Uuid), column("skill_id", Uuid), schema=SCHEMA)
model_versions = table(
    "model_versions", column("model_version_id", Uuid), column("model_code", String), column("version", String),
    column("kind", String), column("approved_at", DateTime(timezone=True)), schema=SCHEMA,
)
match_evaluations = table(
    "match_evaluations", column("match_id", Uuid), column("user_id", Uuid), column("job_posting_id", Uuid),
    column("job_role_id", Uuid), column("model_version_id", Uuid), column("status", String),
    column("score", Numeric(5, 2)), column("matched_skill_count", SmallInteger),
    column("missing_skill_count", SmallInteger), column("limitations", Text),
    column("evaluated_at", DateTime(timezone=True)), schema=SCHEMA,
)


@dataclass(frozen=True)
class PostingRecord:
    job_posting_id: uuid.UUID
    job_role_id: uuid.UUID | None
    status: str
    expires_at: datetime | None


@dataclass(frozen=True)
class PostingSkillRecord:
    skill_id: uuid.UUID
    required_level: int | None
    is_required: bool


@dataclass(frozen=True)
class ModelVersionRecord:
    model_version_id: uuid.UUID
    model_code: str
    version: str
    kind: str


@dataclass(frozen=True)
class NewMatch:
    user_id: uuid.UUID
    job_posting_id: uuid.UUID | None
    job_role_id: uuid.UUID | None
    model_version_id: uuid.UUID
    status: str
    score: Decimal | None
    matched_skill_count: int | None
    missing_skill_count: int | None
    limitations: list[str]
    evaluated_at: datetime


@dataclass(frozen=True)
class MatchRecord:
    match_id: uuid.UUID
    user_id: uuid.UUID
    job_posting_id: uuid.UUID | None
    job_role_id: uuid.UUID | None
    status: str
    score: Decimal | None
    matched_skill_count: int | None
    missing_skill_count: int | None
    limitations: list[str]
    evaluated_at: datetime
    model_version: ModelVersionRecord


class MatchRepository(Protocol):
    def user_proficiencies(self, user_id: uuid.UUID) -> dict[uuid.UUID, int | None]: ...
    def user_project_skill_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]: ...
    def get_posting(self, job_posting_id: uuid.UUID) -> PostingRecord | None: ...
    def posting_skills(self, job_posting_id: uuid.UUID) -> list[PostingSkillRecord]: ...
    def role_is_active(self, job_role_id: uuid.UUID) -> bool | None: ...
    def role_skill_levels(self, job_role_id: uuid.UUID) -> dict[uuid.UUID, int]: ...
    def approved_model_version(self, model_code: str, version: str) -> ModelVersionRecord | None: ...
    def add_match(self, new: NewMatch) -> MatchRecord: ...
    def get_match(self, match_id: uuid.UUID) -> MatchRecord | None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


# limitations는 DB에 text 한 칸으로 저장하고 API에서는 목록으로 보낸다.
LIMITATION_SEPARATOR = "\n"


def split_limitations(text: str | None) -> list[str]:
    return [line for line in (text or "").split(LIMITATION_SEPARATOR) if line]


class SqlMatchRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    def _run(self, fn):
        try:
            return fn()
        except SQLAlchemyError as exc:
            self._db.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

    def user_proficiencies(self, user_id: uuid.UUID) -> dict[uuid.UUID, int | None]:
        us = user_skills.c
        rows = self._run(lambda: self._db.execute(select(us.skill_id, us.proficiency).where(us.user_id == user_id)).all())
        return {skill_id: proficiency for skill_id, proficiency in rows}

    def user_project_skill_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        p, ps = user_projects.c, user_project_skills.c
        stmt = (select(ps.skill_id).select_from(user_project_skills.join(user_projects, p.project_id == ps.project_id))
                .where(p.user_id == user_id))
        return set(self._run(lambda: self._db.scalars(stmt).all()))

    def get_posting(self, job_posting_id: uuid.UUID) -> PostingRecord | None:
        jp = job_postings.c
        row = self._run(lambda: self._db.execute(
            select(jp.job_posting_id, jp.job_role_id, jp.status, jp.expires_at).where(jp.job_posting_id == job_posting_id)
        ).first())
        return PostingRecord(*row) if row else None

    def posting_skills(self, job_posting_id: uuid.UUID) -> list[PostingSkillRecord]:
        s = job_posting_skills.c
        rows = self._run(lambda: self._db.execute(
            select(s.skill_id, s.required_level, s.is_required).where(s.job_posting_id == job_posting_id)
        ).all())
        return [PostingSkillRecord(*r) for r in rows]

    def role_is_active(self, job_role_id: uuid.UUID) -> bool | None:
        r = job_roles.c
        return self._run(lambda: self._db.scalar(select(r.is_active).where(r.job_role_id == job_role_id)))

    def role_skill_levels(self, job_role_id: uuid.UUID) -> dict[uuid.UUID, int]:
        s = job_role_skills.c
        rows = self._run(lambda: self._db.execute(
            select(s.skill_id, s.required_level).where(s.job_role_id == job_role_id)
        ).all())
        return {skill_id: level for skill_id, level in rows}

    def approved_model_version(self, model_code: str, version: str) -> ModelVersionRecord | None:
        m = model_versions.c
        row = self._run(lambda: self._db.execute(
            select(m.model_version_id, m.model_code, m.version, m.kind)
            .where(m.model_code == model_code, m.version == version, m.approved_at.is_not(None))
        ).first())
        return ModelVersionRecord(*row) if row else None

    def add_match(self, new: NewMatch) -> MatchRecord:
        stmt = insert(match_evaluations).values(
            user_id=new.user_id, job_posting_id=new.job_posting_id, job_role_id=new.job_role_id,
            model_version_id=new.model_version_id, status=new.status, score=new.score,
            matched_skill_count=new.matched_skill_count, missing_skill_count=new.missing_skill_count,
            limitations=LIMITATION_SEPARATOR.join(new.limitations), evaluated_at=new.evaluated_at,
        ).returning(match_evaluations.c.match_id)
        match_id = self._run(lambda: self._db.execute(stmt).scalar_one())
        record = self.get_match(match_id)
        assert record is not None
        return record

    def get_match(self, match_id: uuid.UUID) -> MatchRecord | None:
        e, m = match_evaluations.c, model_versions.c
        row = self._run(lambda: self._db.execute(
            select(e.match_id, e.user_id, e.job_posting_id, e.job_role_id, e.status, e.score,
                   e.matched_skill_count, e.missing_skill_count, e.limitations, e.evaluated_at,
                   m.model_version_id, m.model_code, m.version, m.kind)
            .select_from(match_evaluations.join(model_versions, m.model_version_id == e.model_version_id))
            .where(e.match_id == match_id)
        ).first())
        if row is None:
            return None
        return MatchRecord(
            row.match_id, row.user_id, row.job_posting_id, row.job_role_id, row.status, row.score,
            row.matched_skill_count, row.missing_skill_count, split_limitations(row.limitations), row.evaluated_at,
            ModelVersionRecord(row.model_version_id, row.model_code, row.version, row.kind),
        )

    def commit(self) -> None:
        self._run(self._db.commit)

    def rollback(self) -> None:
        self._db.rollback()
