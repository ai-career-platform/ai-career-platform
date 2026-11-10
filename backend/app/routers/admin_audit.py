"""T84 운영 감사·AI 사용량 조회 API (읽기 전용, 확정 계약 docs/api/openapi.yaml).

- GET /api/v1/admin/audit-events (listAuditEvents): `admin` 역할 + Seed 권한 `admin.audit.read`
- GET /api/v1/admin/ai-usage (getAiUsage): `admin` 역할 (API_CONTRACT "관리자"). `admin.audit.read` 추가 요구는 D1 PROPOSED

정책은 `get_admin_query_policy` 하나에서 정한다. 운영 값은 항상 CONFIRMED_POLICY 이고 환경변수로 바꿀 수 없다.
미승인 정책(D1~D5)을 켜려면 PM 승인 후 코드 변경과 계약(T06) 반영이 필요하다.
"""
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.auth_config import AuthSettings
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import (
    CurrentUserDep, get_attempt_limiter, get_auth_settings, require_permissions, require_roles,
)
from app.core.rate_limit import AttemptLimiter
from app.repositories.admin_audit import SqlAdminAuditRepository
from app.schemas.admin_audit import AiUsageBucket, AuditEventPage
from app.services.admin_audit import CONFIRMED_POLICY, AdminAuditService, AdminQueryPolicy, to_event
from app.services.job_postings import ListCursor, derive_cursor_key

# 확정 계약의 비용은 검증되지 않은 저장값 합계다(D2 미승인). 화면이 0원을 '무료'로 단정하지 않도록 표시한다.
COST_STATUS_HEADER = "X-AI-Cost-Status"
COST_STATUS_UNVERIFIED = "unverified"

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_roles("admin"))],
                   responses=error_responses(401, 403, 503))


def get_admin_query_policy() -> AdminQueryPolicy:
    return CONFIRMED_POLICY


def get_admin_audit_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    policy: Annotated[AdminQueryPolicy, Depends(get_admin_query_policy)],
    limiter: Annotated[AttemptLimiter, Depends(get_attempt_limiter)],
) -> AdminAuditService:
    return AdminAuditService(SqlAdminAuditRepository(db), ListCursor(derive_cursor_key(settings.jwt_secret)),
                             policy, limiter)


Service = Annotated[AdminAuditService, Depends(get_admin_audit_service)]


@router.get("/audit-events", response_model=AuditEventPage, operation_id="listAuditEvents",
            dependencies=[Depends(require_permissions("admin.audit.read"))], responses=error_responses(400))
def list_audit_events(
    request: Request,
    user: CurrentUserDep,
    service: Service,
    from_: Annotated[datetime, Query(alias="from")],
    to: Annotated[datetime, Query()],
    actor_user_id: Annotated[UUID | None, Query()] = None,
    action_code: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> AuditEventPage:
    page = service.list_events(user.user_id, start=from_, end=to, actor_user_id=actor_user_id,
                               action_code=action_code, limit=limit, cursor=cursor,
                               call_request_id=getattr(request.state, "request_id", None))
    return AuditEventPage(items=[to_event(r) for r in page.rows], next_cursor=page.next_cursor)


@router.get("/ai-usage", response_model=list[AiUsageBucket], operation_id="getAiUsage")
def get_ai_usage(
    response: Response,
    user: CurrentUserDep,
    service: Service,
    from_: Annotated[date, Query(alias="from")],
    to: Annotated[date, Query()],
    group_by: Annotated[Literal["day", "feature_code", "provider_model"], Query()] = "day",
) -> list[AiUsageBucket]:
    service.require_usage_permission(user.permissions)
    buckets = service.usage(user.user_id, from_, to, group_by)
    response.headers[COST_STATUS_HEADER] = COST_STATUS_UNVERIFIED
    return buckets
