"""T51 document analysis API (T06: requestDocumentAnalysis / getDocumentAnalysis / applyDocumentAnalysis).

POST only enqueues; analysis runs in the separate one-shot worker. GET is read-only.
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.document_analyses import SqlAnalysisRepository
from app.routers.my_skills import _to_dto as skills_to_dto
from app.schemas.document_analyses import Analysis, AnalysisApply, AnalysisRequest
from app.schemas.my_skills import UserSkill
from app.services.document_analyses import RETRY_AFTER_SECONDS, DocumentAnalysisService

router = APIRouter(tags=["documents"], responses=error_responses(401, 503))


def get_analysis_service(session: Annotated[Session, Depends(get_db)]) -> DocumentAnalysisService:
    return DocumentAnalysisService(SqlAnalysisRepository(session))


Service = Annotated[DocumentAnalysisService, Depends(get_analysis_service)]


@router.post("/documents/{document_id}/analyses", response_model=Analysis, status_code=202,
             operation_id="requestDocumentAnalysis", responses=error_responses(403, 404, 409, 429))
def request_analysis(document_id: UUID, body: AnalysisRequest, user: CurrentUserDep, service: Service,
                     response: Response) -> Analysis:
    result = service.request(user.user_id, document_id, body.analysis_type)
    response.headers["Location"] = f"/api/v1/document-analyses/{result.analysis_id}"
    response.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
    return result


@router.get("/document-analyses/{analysis_id}", response_model=Analysis, operation_id="getDocumentAnalysis",
            responses=error_responses(404))
def get_analysis(analysis_id: UUID, user: CurrentUserDep, service: Service, response: Response) -> Analysis:
    result = service.get(user.user_id, analysis_id)
    if result.status in ("queued", "running"):
        response.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
    return result


@router.post("/document-analyses/{analysis_id}/apply", response_model=list[UserSkill],
             operation_id="applyDocumentAnalysis", responses=error_responses(404, 409))
def apply_analysis(analysis_id: UUID, body: AnalysisApply, user: CurrentUserDep, service: Service) -> list[UserSkill]:
    return skills_to_dto(service.apply(user.user_id, analysis_id, body.skills))
