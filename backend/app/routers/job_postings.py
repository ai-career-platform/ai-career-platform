"""T18 `/companies`, `/job-postings` (openapi.yaml tag `catalog`, FR-JOB-004~006).

- 로그인 없이 조회할 수 있다. `Authorization` 헤더가 있으면 T15 의존성으로 검증하고,
  틀린 토큰은 401로 막는다(조용히 비로그인으로 바꾸지 않음). 로그인 여부는 공고 상세의 `is_bookmarked`에만 쓴다.
- 허용하지 않는 sort 값은 계약(enum)대로 422. 화면에서 기본 정렬로 되돌리는 처리는 Frontend(T24) 몫.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.auth_config import AuthSettings
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import (
    CurrentUser, get_access_claims, get_auth_repository, get_auth_settings, get_current_user,
)
from app.repositories.auth import AuthRepository
from app.repositories.job_postings import PostingFilter, SqlJobPostingRepository
from app.schemas.job_postings import CompanyDetail, CompanyPage, JobPostingDetail, JobPostingPage, PostingSort
from app.services.job_postings import JobPostingService, ListCursor, derive_cursor_key

_optional_bearer = HTTPBearer(auto_error=False)


def get_job_posting_service(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> JobPostingService:
    return JobPostingService(SqlJobPostingRepository(session), ListCursor(derive_cursor_key(settings.jwt_secret)))


def _current_user_or_none(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    repo: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> CurrentUser | None:
    """헤더가 없으면 비로그인(None). 있으면 T15와 같은 검증(서명·만료·세션·사용자 상태)을 거친다.

    get_auth_repository는 요청당 하나인 get_db 세션을 같이 쓰므로 DB 연결이 늘지 않는다.
    """
    if request.headers.get("Authorization") is None:
        return None
    return get_current_user(get_access_claims(credentials, settings), repo)


OptionalUser = Annotated[CurrentUser | None, Depends(_current_user_or_none)]
ServiceDep = Annotated[JobPostingService, Depends(get_job_posting_service)]
Q = Annotated[str | None, Query(min_length=1, max_length=100, description="이름 검색어 (부분 일치, 대소문자 무시)")]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=500, description="이전 응답의 next_cursor 그대로")]

router = APIRouter(tags=["catalog"], responses=error_responses(401))


@router.get("/companies", response_model=CompanyPage, summary="기업 목록·검색", responses=error_responses(400))
def list_companies(service: ServiceDep, _user: OptionalUser, q: Q = None, limit: Limit = 20,
                   cursor: Cursor = None) -> CompanyPage:
    return service.list_companies(q, limit, cursor)


@router.get("/companies/{company_id}", response_model=CompanyDetail, summary="기업 상세 (진행 중 공고 수 포함)",
            responses=error_responses(404))
def get_company(company_id: UUID, service: ServiceDep, _user: OptionalUser) -> CompanyDetail:
    return service.get_company(company_id)


@router.get("/job-postings", response_model=JobPostingPage, summary="채용공고 목록·필터 (기본은 게시 중인 공고만)",
            responses=error_responses(400))
def list_job_postings(
    service: ServiceDep,
    _user: OptionalUser,
    q: Q = None,
    company_id: UUID | None = None,
    job_role_id: UUID | None = None,
    include_closed: Annotated[bool, Query(description="true면 마감 공고 포함")] = False,
    sort: PostingSort = "-published_at",
    limit: Limit = 20,
    cursor: Cursor = None,
) -> JobPostingPage:
    f = PostingFilter(q=q, company_id=company_id, job_role_id=job_role_id, include_closed=include_closed, sort=sort)
    return service.list_postings(f, limit, cursor)


@router.get("/job-postings/{job_posting_id}", response_model=JobPostingDetail,
            summary="공고 상세 (요구 기술, 로그인 시 내 저장 여부)", responses=error_responses(404))
def get_job_posting(job_posting_id: UUID, service: ServiceDep, user: OptionalUser) -> JobPostingDetail:
    return service.get_posting(job_posting_id, None if user is None else user.user_id)
