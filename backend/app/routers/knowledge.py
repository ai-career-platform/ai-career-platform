"""T56 `POST /api/v1/knowledge/answers` (openapi.yaml operationId askKnowledge, tag documents).

검색 API는 공개하지 않고 이 endpoint 안에서만 쓴다. 검색기·생성기·청크 본문 소스는 app.state로 교체 가능하며
기본값은 외부 호출 없는 mock이다(T53·T54·LLM 승인 전).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.knowledge import SqlKnowledgeRepository
from app.schemas.knowledge import KnowledgeAnswer, KnowledgeQuestion
from app.services.knowledge import KnowledgeService
from app.services.knowledge_provider import ExtractiveMockGenerator, LexicalMockRetriever, UnavailableChunkText

router = APIRouter(tags=["documents"], responses=error_responses(401, 503))

_DEFAULTS = {"knowledge_retriever": LexicalMockRetriever(), "knowledge_generator": ExtractiveMockGenerator(),
             "knowledge_text_source": UnavailableChunkText()}


def _state(request: Request, name: str):
    return getattr(request.app.state, name, None) or _DEFAULTS[name]


def get_knowledge_service(request: Request, session: Annotated[Session, Depends(get_db)]) -> KnowledgeService:
    return KnowledgeService(SqlKnowledgeRepository(session), _state(request, "knowledge_retriever"),
                            _state(request, "knowledge_generator"), _state(request, "knowledge_text_source"))


@router.post("/knowledge/answers", response_model=KnowledgeAnswer, operation_id="askKnowledge",
             summary="근거 기반 커리어 Q&A (내 문서 + 공용 자료, 동기)", responses=error_responses(504))
def ask_knowledge(body: KnowledgeQuestion, request: Request, response: Response, user: CurrentUserDep,
                  service: Annotated[KnowledgeService, Depends(get_knowledge_service)]) -> KnowledgeAnswer:
    if request.query_params:
        raise AppError(ErrorCode.VALIDATION_FAILED)
    response.headers["Cache-Control"] = "no-store"
    return service.answer(user.user_id, body.question, body.document_ids)
