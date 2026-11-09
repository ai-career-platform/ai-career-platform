from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.career_history import SqlCareerHistoryRepository
from app.schemas.career_history import Experience, ExperienceInput, ExperiencePatch, Project, ProjectInput, ProjectPatch
from app.services.career_history import CareerHistoryService


def get_career_history_service(session: Annotated[Session, Depends(get_db)]) -> CareerHistoryService:
    return CareerHistoryService(SqlCareerHistoryRepository(session))


Service = Annotated[CareerHistoryService, Depends(get_career_history_service)]
router = APIRouter(prefix="/me", tags=["me"], responses=error_responses(401, 503))

@router.get("/experiences", response_model=list[Experience], operation_id="listMyExperiences")
def list_experiences(user: CurrentUserDep, service: Service): return service.list_experiences(user.user_id)

@router.post("/experiences", response_model=Experience, status_code=201, operation_id="createMyExperience")
def create_experience(payload: ExperienceInput, user: CurrentUserDep, service: Service, response: Response):
    item = service.create_experience(user.user_id, payload)
    response.headers["Location"] = f"/api/v1/me/experiences/{item.experience_id}"
    return item

@router.patch("/experiences/{experience_id}", response_model=Experience, operation_id="updateMyExperience",
             responses=error_responses(404))
def update_experience(experience_id: UUID, payload: ExperiencePatch, user: CurrentUserDep, service: Service):
    return service.update_experience(user.user_id, experience_id, payload)

@router.delete("/experiences/{experience_id}", status_code=204, operation_id="deleteMyExperience",
             responses=error_responses(404))
def delete_experience(experience_id: UUID, user: CurrentUserDep, service: Service):
    service.delete_experience(user.user_id, experience_id)

@router.get("/projects", response_model=list[Project], operation_id="listMyProjects")
def list_projects(user: CurrentUserDep, service: Service): return service.list_projects(user.user_id)

@router.post("/projects", response_model=Project, status_code=201, operation_id="createMyProject")
def create_project(payload: ProjectInput, user: CurrentUserDep, service: Service, response: Response):
    item = service.create_project(user.user_id, payload)
    response.headers["Location"] = f"/api/v1/me/projects/{item.project_id}"
    return item

@router.patch("/projects/{project_id}", response_model=Project, operation_id="updateMyProject",
             responses=error_responses(404))
def update_project(project_id: UUID, payload: ProjectPatch, user: CurrentUserDep, service: Service):
    return service.update_project(user.user_id, project_id, payload)

@router.delete("/projects/{project_id}", status_code=204, operation_id="deleteMyProject",
             responses=error_responses(404))
def delete_project(project_id: UUID, user: CurrentUserDep, service: Service):
    service.delete_project(user.user_id, project_id)
