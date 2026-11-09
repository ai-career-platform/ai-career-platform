"""`GET /me/skills`, `PUT /me/skills` (openapi.yaml tag `me`, FR-PRF-001).

사용자는 토큰의 `sub`로만 정한다. 쿼리·본문으로 user_id를 받지 않는다 (API_CONTRACT §1.3).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.my_skills import MySkillsRepository, SqlMySkillsRepository, UserSkillRecord
from app.routers.me import private_request
from app.schemas.catalog import Skill
from app.schemas.my_skills import UserSkill, UserSkillsReplace
from app.services.my_skills import MySkillsService

router = APIRouter(prefix="/me/skills", tags=["me"], responses=error_responses(401, 503))


def get_my_skills_repository(session: Annotated[Session, Depends(get_db)]) -> MySkillsRepository:
    return SqlMySkillsRepository(session)


def get_my_skills_service(repo: Annotated[MySkillsRepository, Depends(get_my_skills_repository)]) -> MySkillsService:
    return MySkillsService(repo)


ServiceDep = Annotated[MySkillsService, Depends(get_my_skills_service)]


def _to_dto(records: list[UserSkillRecord]) -> list[UserSkill]:
    return [
        UserSkill(skill=Skill(skill_id=r.skill_id, code=r.code, name=r.name), proficiency=r.proficiency)
        for r in records
    ]


@router.get("", response_model=list[UserSkill], operation_id="listMySkills")
def list_my_skills(request: Request, user: CurrentUserDep, service: ServiceDep) -> list[UserSkill]:
    private_request(request)
    return _to_dto(service.get_all(user.user_id))


@router.put("", response_model=list[UserSkill], operation_id="replaceMySkills")
def replace_my_skills(
    request: Request, body: UserSkillsReplace, user: CurrentUserDep, service: ServiceDep
) -> list[UserSkill]:
    private_request(request)
    return _to_dto(service.replace(user.user_id, body.items))
