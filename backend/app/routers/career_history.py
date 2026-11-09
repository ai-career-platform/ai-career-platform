from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Response, status
from app.dependencies.auth import CurrentUserDep
from app.dependencies.career_history import get_career_history_repository
from app.repositories.career_history import CareerHistoryRepository
from app.schemas.career_history import Experience, ExperienceInput, ExperiencePatch, Project, ProjectInput, ProjectPatch
from app.services.career_history import CareerHistoryService

router = APIRouter(prefix="/me", tags=["me"])
Repo = Annotated[CareerHistoryRepository, Depends(get_career_history_repository)]

@router.get("/experiences", response_model=list[Experience], operation_id="listMyExperiences")
def list_experiences(user: CurrentUserDep, repo: Repo): return CareerHistoryService(repo).list_experiences(user.user_id)

@router.post("/experiences", response_model=Experience, status_code=201, operation_id="createMyExperience")
def create_experience(payload: ExperienceInput, user: CurrentUserDep, repo: Repo, response: Response):
    item = CareerHistoryService(repo).create_experience(user.user_id, payload)
    response.headers["Location"] = f"/api/v1/me/experiences/{item.experience_id}"
    return item

@router.patch("/experiences/{experience_id}", response_model=Experience, operation_id="updateMyExperience")
def update_experience(experience_id: UUID, payload: ExperiencePatch, user: CurrentUserDep, repo: Repo):
    return CareerHistoryService(repo).update_experience(user.user_id, experience_id, payload)

@router.delete("/experiences/{experience_id}", status_code=204, operation_id="deleteMyExperience")
def delete_experience(experience_id: UUID, user: CurrentUserDep, repo: Repo):
    CareerHistoryService(repo).delete_experience(user.user_id, experience_id)

@router.get("/projects", response_model=list[Project], operation_id="listMyProjects")
def list_projects(user: CurrentUserDep, repo: Repo): return CareerHistoryService(repo).list_projects(user.user_id)

@router.post("/projects", response_model=Project, status_code=201, operation_id="createMyProject")
def create_project(payload: ProjectInput, user: CurrentUserDep, repo: Repo, response: Response):
    item = CareerHistoryService(repo).create_project(user.user_id, payload)
    response.headers["Location"] = f"/api/v1/me/projects/{item.project_id}"
    return item

@router.patch("/projects/{project_id}", response_model=Project, operation_id="updateMyProject")
def update_project(project_id: UUID, payload: ProjectPatch, user: CurrentUserDep, repo: Repo):
    return CareerHistoryService(repo).update_project(user.user_id, project_id, payload)

@router.delete("/projects/{project_id}", status_code=204, operation_id="deleteMyProject")
def delete_project(project_id: UUID, user: CurrentUserDep, repo: Repo):
    CareerHistoryService(repo).delete_project(user.user_id, project_id)
