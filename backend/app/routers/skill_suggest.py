"""T139 `GET /api/v1/skills/suggest` — `SKILL_AUTOCOMPLETE_API=true` 일 때만 등록(기본 꺼짐, 계약 PROPOSED).

- T17 `GET /skills`(확정 계약)는 그대로 두고, 별칭·표준 코드 변환이 필요한 자동완성만 별도 경로로 둔다.
- T17 과 같이 로그인 없이 쓰는 공개 조회다(개인 데이터 없음). Authorization 은 읽지 않는다.
- 공개 조회이므로 IP 당 요청 한도를 둔다(입력마다 호출되는 자동완성 남용 방지, PROPOSED 값).
- 응답에는 표준 코드·이름·일치 종류만. 내부 상태(merged/deprecated 원래 코드)는 내보내지 않는다.
"""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth_config import AuthSettings
from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.core.rate_limit import AttemptLimiter
from app.core.security import derive_key
from app.db import get_db
from app.dependencies.auth import get_auth_settings
from app.repositories.skill_suggest import SqlSkillSource
from app.services.skill_suggest import CURSOR_KEY_PURPOSE, MAX_QUERY_LEN, SkillSuggestService

SUGGEST_LIMIT, SUGGEST_WINDOW = 120, 60   # IP 당 60초 120회 (PROPOSED)


class SuggestItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    name: str
    match_type: Literal["code", "alias", "ambiguous", "prefix", "partial"]
    matched: str
    skill_id: UUID | None


class SuggestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    items: list[SuggestItem]
    next_cursor: str | None
    alias_source: Literal["taxonomy", "none"]


def get_skill_suggest_service(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> SkillSuggestService:
    return SkillSuggestService(SqlSkillSource(session), cursor_key=derive_key(settings.jwt_secret, CURSOR_KEY_PURPOSE))


def get_suggest_limiter(request: Request) -> AttemptLimiter:
    return request.app.state.attempt_limiter


router = APIRouter(tags=["catalog"], responses=error_responses(503))


@router.get("/skills/suggest", response_model=SuggestResponse, operation_id="suggestSkills",
            summary="기술 자동완성 (동의어 → 표준 코드, PROPOSED)", responses=error_responses(400, 422, 429),
            openapi_extra={"security": [{}, {"HTTPBearer": []}]})
def suggest_skills(
    request: Request,
    service: Annotated[SkillSuggestService, Depends(get_skill_suggest_service)],
    limiter: Annotated[AttemptLimiter, Depends(get_suggest_limiter)],
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_LEN, description="검색어 (한글·영문, 코드·동의어)")],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> SuggestResponse:
    client = request.client.host if request.client else "unknown"
    key = f"t139-suggest:{client}"
    if limiter.retry_after(key) or limiter.hit(key, SUGGEST_LIMIT, SUGGEST_WINDOW):
        raise AppError(ErrorCode.RATE_LIMITED, log_detail="skill suggest rate limited", retry_after=SUGGEST_WINDOW)
    page = service.suggest(q, limit=limit, cursor=cursor)
    return SuggestResponse(
        items=[SuggestItem(code=s.code, name=s.name, match_type=s.match_type, matched=s.matched, skill_id=s.skill_id)
               for s in page.items],
        next_cursor=page.next_cursor, alias_source=page.alias_source,
    )
