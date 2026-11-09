"""T47 `POST /recommendation-feedback` (openapi.yaml tag `insights`, operationId `createRecommendationFeedback`).

- 로그인 필요(401). 사용자는 토큰의 `sub`로만 정한다. 본문에 user_id를 받지 않는다(받으면 422).
- 내 추천에 없던 공고·다른 사람의 추천 실행은 404 (API_CONTRACT §1.3, 403 아님).
- 중복·정정·감사 규칙은 `app/services/recommendation_feedback.py` 참고.
- T45(추천 실행 생성·조회)가 머지되기 전이라 실제 DB 연동 검증은 HOLD. 테스트는 메모리 저장소로 한다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.recommendation_feedback import SqlRecommendationFeedbackRepository
from app.schemas.recommendation_feedback import RecommendationFeedback, RecommendationFeedbackInput
from app.services.recommendation_feedback import RecommendationFeedbackService


def get_recommendation_feedback_service(
    session: Annotated[Session, Depends(get_db)],
) -> RecommendationFeedbackService:
    return RecommendationFeedbackService(SqlRecommendationFeedbackRepository(session))


ServiceDep = Annotated[RecommendationFeedbackService, Depends(get_recommendation_feedback_service)]

router = APIRouter(tags=["insights"], responses=error_responses(401, 503))


@router.post(
    "/recommendation-feedback", response_model=RecommendationFeedback, status_code=status.HTTP_201_CREATED,
    operation_id="createRecommendationFeedback", summary="추천 공고 피드백 (이력 추가)",
    description="기록됨. not_interested 공고는 다음 추천에서 제외. 같은 값을 다시 보내면 새 이력을 만들지 않는다.",
    responses=error_responses(404),
)
def create_recommendation_feedback(
    request: Request, body: RecommendationFeedbackInput, user: CurrentUserDep, service: ServiceDep,
) -> RecommendationFeedback:
    return service.create(user.user_id, body, getattr(request.state, "request_id", None))
