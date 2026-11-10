"""`POST /matches`, `GET /matches/{match_id}` (openapi.yaml tag `insights`, FR-ANL-001).

사용자는 토큰의 `sub`로만 정한다. 결과는 본인 것만 조회되고 다른 사람 결과는 404.
"""

import uuid
from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.config import API_V1_PREFIX
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.matching import MatchRecord, SqlMatchRepository
from app.schemas.matching import Match, MatchRequest, MatchTarget, ModelVersionRef
from app.services.matching import MatchService

router = APIRouter(prefix="/matches", tags=["insights"], responses=error_responses(401, 404))


def get_match_service(session: Annotated[Session, Depends(get_db)]) -> MatchService:
    return MatchService(SqlMatchRepository(session))


ServiceDep = Annotated[MatchService, Depends(get_match_service)]


def to_match(record: MatchRecord) -> Match:
    mv = record.model_version
    return Match(
        match_id=record.match_id,
        target=MatchTarget(job_posting_id=record.job_posting_id, job_role_id=record.job_role_id),
        status=record.status,
        score=None if record.score is None else float(record.score),
        matched_skill_count=record.matched_skill_count,
        missing_skill_count=record.missing_skill_count,
        model_version=ModelVersionRef(model_code=mv.model_code, version=mv.version, kind=mv.kind),
        limitations=record.limitations,
        evaluated_at=record.evaluated_at.astimezone(UTC),  # DB 세션 시간대와 무관하게 UTC로 응답
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=Match, responses=error_responses(400, 503))
def create_match(body: MatchRequest, user: CurrentUserDep, service: ServiceDep, response: Response) -> Match:
    record = service.create(user.user_id, job_posting_id=body.job_posting_id, job_role_id=body.job_role_id)
    response.headers["Location"] = f"{API_V1_PREFIX}/matches/{record.match_id}"
    return to_match(record)


@router.get("/{match_id}", response_model=Match)
def get_match(match_id: uuid.UUID, user: CurrentUserDep, service: ServiceDep) -> Match:
    return to_match(service.get(user.user_id, match_id))
