"""T43 unregistered router. T15/T26 are reused; runtime policy wiring is pending.

No client-supplied user ID, header, or token is trusted by this scaffold.
The user ID comes only from T15's verified principal.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.dependencies.auth import CurrentUserDep
from app.schemas.skill_gaps import (
    SkillGap, SkillGapHistoryQuery, SkillGapRequest, SkillGapSummaryPage,
)
from app.services.skill_gaps import SkillGapService


def get_skill_gap_service() -> SkillGapService:
    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)


router = APIRouter(prefix="/skill-gaps", tags=["insights"])
ServiceDep = Annotated[SkillGapService, Depends(get_skill_gap_service)]


@router.get(
    "", response_model=SkillGapSummaryPage, operation_id="listMySkillGaps",
    responses=error_responses(400, 401, 422, 503),
)
def list_skill_gaps(
    user: CurrentUserDep, service: ServiceDep,
    job_role_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> SkillGapSummaryPage:
    return service.list_history(user_id=user.user_id, query=SkillGapHistoryQuery(
        job_role_id=job_role_id, limit=limit, cursor=cursor,
    ))


@router.post(
    "", response_model=SkillGap, status_code=201, operation_id="createSkillGap",
    responses=error_responses(400, 401, 404, 422, 503),
)
def create_skill_gap(
    body: SkillGapRequest, response: Response, user: CurrentUserDep, service: ServiceDep,
) -> SkillGap:
    result = service.create(user_id=user.user_id, job_role_id=body.job_role_id)
    response.headers["Location"] = f"/api/v1/skill-gaps/{result.assessment_id}"
    return result


@router.get(
    "/{assessment_id}", response_model=SkillGap, operation_id="getSkillGap",
    responses=error_responses(401, 404, 422, 503),
)
def get_skill_gap(assessment_id: UUID, user: CurrentUserDep, service: ServiceDep) -> SkillGap:
    return service.get(user_id=user.user_id, assessment_id=assessment_id)
