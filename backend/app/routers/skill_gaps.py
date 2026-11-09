"""T43 unregistered router. T15 authentication is wired; calculation awaits T26.

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


def get_skill_gap_user_id(user: CurrentUserDep) -> UUID:
    return user.user_id


def get_skill_gap_service() -> SkillGapService:
    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE)


router = APIRouter(prefix="/skill-gaps", tags=["insights"])
GapUser = Annotated[UUID, Depends(get_skill_gap_user_id)]
GapService = Annotated[SkillGapService, Depends(get_skill_gap_service)]


@router.get(
    "", response_model=SkillGapSummaryPage, operation_id="listMySkillGaps",
    responses=error_responses(400, 401, 422, 503),
)
def list_skill_gaps(
    user_id: GapUser, service: GapService,
    job_role_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> SkillGapSummaryPage:
    return service.list_history(user_id=user_id, query=SkillGapHistoryQuery(
        job_role_id=job_role_id, limit=limit, cursor=cursor,
    ))


@router.post(
    "", response_model=SkillGap, status_code=201, operation_id="createSkillGap",
    responses=error_responses(400, 401, 404, 422, 503),
)
def create_skill_gap(
    body: SkillGapRequest, response: Response, user_id: GapUser, service: GapService,
) -> SkillGap:
    result = service.create(user_id=user_id, job_role_id=body.job_role_id)
    response.headers["Location"] = f"/api/v1/skill-gaps/{result.assessment_id}"
    return result


@router.get(
    "/{assessment_id}", response_model=SkillGap, operation_id="getSkillGap",
    responses=error_responses(401, 404, 422, 503),
)
def get_skill_gap(assessment_id: UUID, user_id: GapUser, service: GapService) -> SkillGap:
    return service.get(user_id=user_id, assessment_id=assessment_id)
