"""`/api/v1` 서비스 API 진입점.

기능 라우터(T15 인증, T16 프로필, T17 직무·기술, T18 기업·공고 등)는
`docs/API_CONTRACT.md` 확정(T06) 후 이 라우터에 `include_router`로 추가합니다.
"""

from fastapi import APIRouter

from app.core.config import API_V1_PREFIX
from app.core.exception_handlers import error_responses
from app.routers import auth, bookmarks, career_history, catalog, crawler_admin, job_postings, me, target_roles

# 모든 /api/v1 operation의 OpenAPI에 공통 오류(422 검증, 500 내부 오류) ErrorResponse를 표시.
# 기능 라우터는 api_router.include_router(...)로 붙이면 이 설정을 물려받는다.
API_V1_RESPONSES = error_responses(422, 500)
api_router = APIRouter(prefix=API_V1_PREFIX, responses=API_V1_RESPONSES)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(target_roles.router)
api_router.include_router(career_history.router)
api_router.include_router(bookmarks.router)
api_router.include_router(crawler_admin.router)
api_router.include_router(job_postings.router)
api_router.include_router(catalog.router)

api_router.include_router(privacy.router)
