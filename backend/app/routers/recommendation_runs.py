"""T45 recommendation runs: T06 POST create / GET read-only contract."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.recommendation_runs import SqlRecommendationRepository
from app.schemas.recommendation_runs import RecommendationRun, RecommendationRunRequest
from app.services.recommendation_runs import RecommendationService

router = APIRouter(prefix="/recommendation-runs", tags=["insights"],
                   responses=error_responses(401, 503))


def get_recommendation_service(session: Annotated[Session, Depends(get_db)]) -> RecommendationService:
    return RecommendationService(SqlRecommendationRepository(session))

Service = Annotated[RecommendationService, Depends(get_recommendation_service)]


@router.post("", response_model=RecommendationRun, status_code=201,
             operation_id="createRecommendationRun")
def create_run(user: CurrentUserDep, service: Service, response: Response,
               payload: RecommendationRunRequest | None = None) -> RecommendationRun:
    result = service.create(user.user_id, 20 if payload is None else payload.limit)
    response.headers["Location"] = f"/api/v1/recommendation-runs/{result.recommendation_run_id}"
    return result


@router.get("/latest", response_model=RecommendationRun, operation_id="getLatestRecommendationRun",
            responses=error_responses(404))
def latest_run(user: CurrentUserDep, service: Service) -> RecommendationRun:
    return service.latest(user.user_id)


@router.get("/{recommendation_run_id}", response_model=RecommendationRun,
            operation_id="getRecommendationRun", responses=error_responses(404))
def get_run(recommendation_run_id: UUID, user: CurrentUserDep, service: Service) -> RecommendationRun:
    return service.get(user.user_id, recommendation_run_id)
