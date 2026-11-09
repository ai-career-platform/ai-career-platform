"""내 보유 기술 DB 접근 (database/DATA_DICTIONARY.md B05 `skills`, B07 `user_skills`, 스키마 `career`).

T17 카탈로그 저장소와 같은 방식으로 필요한 컬럼만 `table()`로 선언한다(공용 ORM 모델을 따로 만들지 않음).
`skills` 테이블 선언은 T17의 `app.repositories.catalog.skills`를 그대로 쓴다.
서비스는 `MySkillsRepository` 프로토콜에만 의존하고, 테스트는 `tests/fakes_my_skills.py`를 쓴다.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import DateTime, SmallInteger, Uuid, column, delete, select, table
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.repositories.catalog import skills

SCHEMA = "career"


@dataclass(frozen=True)
class UserSkillRecord:
    skill_id: uuid.UUID
    code: str
    name: str
    proficiency: int | None


class MySkillsRepository(Protocol):
    def list_skills(self, user_id: uuid.UUID) -> list[UserSkillRecord]:
        """이름, skill_id 순."""
        ...

    def usable_skill_ids(self, user_id: uuid.UUID, skill_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        """요청한 기술 중 등록 가능한 것: 활성 기술이거나, 비활성이어도 이미 보유 중인 기술."""
        ...

    def replace_skills(self, user_id: uuid.UUID, items: dict[uuid.UUID, int | None], now: datetime) -> None:
        """보유 기술을 items로 통째로 바꾼다. 남는 기술의 created_at은 유지한다. commit은 호출자가."""
        ...

    def commit(self) -> None: ...
    def rollback(self) -> None: ...


user_skills = table(
    "user_skills", column("user_id", Uuid), column("skill_id", Uuid), column("proficiency", SmallInteger),
    column("created_at", DateTime(timezone=True)), column("updated_at", DateTime(timezone=True)), schema=SCHEMA,
)
users = table("users", column("user_id", Uuid), schema=SCHEMA)


class SqlMySkillsRepository:
    def __init__(self, session: Session) -> None:
        self._db = session

    def list_skills(self, user_id: uuid.UUID) -> list[UserSkillRecord]:
        s, us = skills.c, user_skills.c
        stmt = (
            select(s.skill_id, s.code, s.name, us.proficiency)
            .select_from(user_skills.join(skills, us.skill_id == s.skill_id))
            .where(us.user_id == user_id)
            .order_by(s.name, s.skill_id)
        )
        return [UserSkillRecord(*row) for row in self._run(lambda: self._db.execute(stmt).all())]

    def usable_skill_ids(self, user_id: uuid.UUID, skill_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not skill_ids:
            return set()
        s, us = skills.c, user_skills.c
        owned = select(us.skill_id).where(us.user_id == user_id)
        stmt = select(s.skill_id).where(s.skill_id.in_(skill_ids), s.is_active.is_(True) | s.skill_id.in_(owned))
        return set(self._run(lambda: self._db.scalars(stmt).all()))

    def replace_skills(self, user_id: uuid.UUID, items: dict[uuid.UUID, int | None], now: datetime) -> None:
        us = user_skills.c

        def write() -> None:
            # 같은 사용자의 동시 교체를 사용자 행 잠금으로 직렬화한다
            self._db.execute(select(users.c.user_id).where(users.c.user_id == user_id).with_for_update())
            remove = delete(user_skills).where(us.user_id == user_id)
            if items:
                remove = remove.where(us.skill_id.not_in(items))
            self._db.execute(remove)
            if items:
                stmt = insert(user_skills).values([
                    {"user_id": user_id, "skill_id": sid, "proficiency": p, "created_at": now, "updated_at": now}
                    for sid, p in items.items()
                ])
                stmt = stmt.on_conflict_do_update(
                    index_elements=[us.user_id, us.skill_id],
                    set_={"proficiency": stmt.excluded.proficiency, "updated_at": now},
                    # 숙련도가 그대로면 updated_at을 바꾸지 않는다
                    where=us.proficiency.is_distinct_from(stmt.excluded.proficiency),
                )
                self._db.execute(stmt)

        self._run(write)

    def _run(self, fn):
        try:
            return fn()
        except SQLAlchemyError as exc:
            self._db.rollback()
            raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail=type(exc).__name__) from None

    def commit(self) -> None:
        self._run(self._db.commit)

    def rollback(self) -> None:
        self._db.rollback()
