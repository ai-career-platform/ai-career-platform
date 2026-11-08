"""T17 routes using the T14 request-scoped SQLAlchemy session.

T17_CURSOR_KEY must contain at least 32 UTF-8 bytes and remain stable across
workers/restarts. No default key or synthetic runtime data is provided.
"""

import os
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.repositories.catalog_sqlalchemy import SQLAlchemyCatalogRepository
from app.schemas.catalog import (
    JobRoleDetail, JobRolePage, JobRoleQuery, SkillQuery, SkillSearchResult,
)
from app.services.catalog import CatalogService


def get_catalog_service(db: Annotated[Session, Depends(get_db)]) -> CatalogService:
    cursor_key = os.environ.get("T17_CURSOR_KEY", "").encode("utf-8")
    if len(cursor_key) < 32:
        raise AppError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            log_detail="T17 cursor key is missing or too short",
        )
    return CatalogService(SQLAlchemyCatalogRepository(db), cursor_key=cursor_key)


router = APIRouter(tags=["catalog"])
CatalogDependency = Annotated[CatalogService, Depends(get_catalog_service)]


@router.get(
    "/job-roles", response_model=JobRolePage, operation_id="listJobRoles",
    responses=error_responses(400, 422, 503),
)
def list_job_roles(
    service: CatalogDependency,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> JobRolePage:
    return service.list_job_roles(JobRoleQuery(q=q, limit=limit, cursor=cursor))


@router.get(
    "/job-roles/{job_role_id}", response_model=JobRoleDetail,
    operation_id="getJobRole", responses=error_responses(404, 422, 503),
)
def get_job_role(job_role_id: UUID, service: CatalogDependency) -> JobRoleDetail:
    return service.get_job_role(job_role_id)


@router.get(
    "/skills", response_model=SkillSearchResult, operation_id="searchSkills",
    responses=error_responses(422, 503),
)
def search_skills(
    service: CatalogDependency,
    q: Annotated[str, Query(min_length=2, max_length=60)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SkillSearchResult:
    return service.search_skills(SkillQuery(q=q, limit=limit))
