"""T72 `POST /api/v1/me/behavior-events`. 사용자는 토큰으로만 정하고 본문·쿼리로 user_id를 받지 않는다."""
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep, get_attempt_limiter
from app.repositories.behavior_events import SqlBehaviorEventRepository
from app.routers.me import private_request
from app.schemas.behavior_events import BehaviorEventInput, BehaviorEventResult
from app.services.behavior_events import BehaviorEventService, BehaviorEventSettings

router = APIRouter(prefix="/me", tags=["me"], responses=error_responses(400, 401, 422, 429, 503))


def get_behavior_event_settings(request: Request) -> BehaviorEventSettings:
    return request.app.state.behavior_event_settings


def get_behavior_event_service(
    request: Request,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[BehaviorEventSettings, Depends(get_behavior_event_settings)],
) -> BehaviorEventService:
    return BehaviorEventService(SqlBehaviorEventRepository(session), settings, get_attempt_limiter(request))


Service = Annotated[BehaviorEventService, Depends(get_behavior_event_service)]


@router.post(
    "/behavior-events", status_code=201, response_model=BehaviorEventResult,
    operation_id="recordMyBehaviorEvent",
    responses={200: {"model": BehaviorEventResult,
                     "description": "저장하지 않음: duplicate, blocked_no_consent, blocked_policy_pending, collection_disabled"}},
    openapi_extra={"x-implementation-status": "PARTIAL"},
    description="동의(behavior_tracking)한 사용자의 허용 이벤트만 저장한다. 수집 스위치는 기본 꺼짐. "
                "personalization 3종은 T71 미승인이라 저장하지 않는다.",
)
def record_behavior_event(body: BehaviorEventInput, request: Request, response: Response,
                          user: CurrentUserDep, service: Service) -> BehaviorEventResult:
    private_request(request)
    result = service.record(user.user_id, body)
    if result.status != "recorded":
        response.status_code = 200
    return result
