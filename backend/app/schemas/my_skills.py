"""내 보유 기술 DTO (docs/api/openapi.yaml `UserSkill`, `UserSkillsReplace`, `Level`).

기술 정보 `{skill_id, code, name}`은 T17 카탈로그의 `Skill`(app/schemas/catalog.py)을 그대로 쓴다.
"""

import uuid
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.catalog import Skill

Level = Annotated[int, Field(ge=1, le=5, strict=True, description="1 입문 · 2 기초 · 3 실무 가능 · 4 능숙 · 5 전문가")]
MAX_SKILLS = 100


class UserSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill: Skill
    proficiency: Level | None = Field(description="NULL = 숙련도 미입력 (Skill Gap 계산 시 0)")


class UserSkillItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: uuid.UUID
    proficiency: Level | None = None


class UserSkillsReplace(BaseModel):
    """보유 기술 전체 교체. 빈 목록이면 모두 삭제."""

    model_config = ConfigDict(extra="forbid")

    items: list[UserSkillItem] = Field(max_length=MAX_SKILLS)
