"""내 보유 기술 업무 규칙 (FR-PRF-001, API listMySkills·replaceMySkills).

- 사용자는 토큰의 sub로만 정한다. 본문·쿼리의 user_id는 받지 않는다(422).
- PUT은 전체 교체: 목록에 없는 기술은 지우고, 있는 기술은 숙련도를 갱신한다. 빈 목록이면 모두 삭제.
- 같은 skill_id가 두 번 오면 422 DUPLICATE_SKILL.
- 없는 기술, 또는 비활성(폐기)인데 보유하지 않은 기술은 422 VALIDATION_FAILED. 이미 보유한 폐기 기술은 유지 가능.
- 숙련도는 1~5 또는 null(미입력). 범위 밖은 요청 검증에서 422.
"""

import uuid
from datetime import UTC, datetime

from app.core.errors import AppError, ErrorCode
from app.repositories.my_skills import MySkillsRepository, UserSkillRecord
from app.schemas.my_skills import UserSkillItem


def _now() -> datetime:
    return datetime.now(UTC)


class MySkillsService:
    def __init__(self, repo: MySkillsRepository, clock=_now) -> None:
        self._repo = repo
        self._clock = clock

    def get_all(self, user_id: uuid.UUID) -> list[UserSkillRecord]:
        return self._repo.list_skills(user_id)

    def replace(self, user_id: uuid.UUID, items: list[UserSkillItem]) -> list[UserSkillRecord]:
        wanted: dict[uuid.UUID, int | None] = {}
        for item in items:
            if item.skill_id in wanted:
                raise AppError(ErrorCode.DUPLICATE_SKILL, log_detail=f"duplicate skill_id {item.skill_id}")
            wanted[item.skill_id] = item.proficiency

        unknown = set(wanted) - self._repo.usable_skill_ids(user_id, set(wanted))
        if unknown:
            raise AppError(ErrorCode.VALIDATION_FAILED, log_detail=f"unknown or retired skills {sorted(map(str, unknown))}")

        try:
            self._repo.replace_skills(user_id, wanted, self._clock())
            self._repo.commit()
        except Exception:
            self._repo.rollback()
            raise
        return self._repo.list_skills(user_id)
