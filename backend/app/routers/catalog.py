"""T17 `/job-roles`, `/skills` (openapi.yaml tag `catalog`, FR-JOB-001~003).

- 로그인 없이 쓰는 공개 조회 API다. 로그인 여부로 달라지는 응답이 없으므로 Authorization 헤더는
  읽지 않는다. 만료·잘못된 토큰이 와도 비로그인과 같은 200을 준다(openapi.yaml도 401을 선언하지 않음).
- DB 세션은 T14 공통 `get_db`, cursor 서명 키는 기동 시 검증된 `JWT_SECRET`에서 용도별로 파생한다.
  별도 환경변수가 없으므로 설정 누락으로 카탈로그 전체가 503이 되는 일이 없다.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth_config import AuthSettings
from app.core.exception_handlers import error_responses
from app.core.security import derive_key
from app.db import get_db
from app.dependencies.auth import get_auth_settings
from app.repositories.catalog import SqlCatalogRepository
from app.schemas.catalog import JobRoleDetail, JobRolePage, JobRoleQuery, SkillQuery, SkillSearchResult
from app.services.catalog import CURSOR_KEY_PURPOSE, CatalogService


def get_catalog_service(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> CatalogService:
    return CatalogService(SqlCatalogRepository(session), cursor_key=derive_key(settings.jwt_secret, CURSOR_KEY_PURPOSE))


ServiceDep = Annotated[CatalogService, Depends(get_catalog_service)]
Limit = Annotated[int, Query(ge=1, le=100)]
# openapi.yaml의 `security: [{}, {bearerAuth: []}]` (인증 선택)과 같은 표기.
OPTIONAL_AUTH = {"security": [{}, {"HTTPBearer": []}]}

router = APIRouter(tags=["catalog"], responses=error_responses(503))


@router.get("/job-roles", response_model=JobRolePage, operation_id="listJobRoles", summary="직무 목록·검색",
            responses=error_responses(400), openapi_extra=OPTIONAL_AUTH)
def list_job_roles(
    service: ServiceDep,
    q: Annotated[str | None, Query(min_length=1, max_length=100, description="직무 이름 검색어 (부분 일치)")] = None,
    limit: Limit = 20,
    cursor: Annotated[str | None, Query(max_length=500, description="이전 응답의 next_cursor 그대로")] = None,
) -> JobRolePage:
    return service.list_job_roles(JobRoleQuery(q=q, limit=limit, cursor=cursor))


@router.get("/job-roles/{job_role_id}", response_model=JobRoleDetail, operation_id="getJobRole",
            summary="직무 상세 (요구 기술 포함)", responses=error_responses(404), openapi_extra=OPTIONAL_AUTH)
def get_job_role(job_role_id: UUID, service: ServiceDep) -> JobRoleDetail:
    return service.get_job_role(job_role_id)


@router.get("/skills", response_model=SkillSearchResult, operation_id="searchSkills", summary="기술 검색 (자동완성)",
            openapi_extra=OPTIONAL_AUTH)
def search_skills(
    service: ServiceDep,
    q: Annotated[str, Query(min_length=2, max_length=60, description="기술 이름 검색어")],
    limit: Limit = 20,
) -> SkillSearchResult:
    return service.search_skills(SkillQuery(q=q, limit=limit))
