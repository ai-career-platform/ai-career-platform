"""T81 운영 콘텐츠 검수 API — `ADMIN_MODERATION_API=true` 일 때만 등록(기본 꺼짐, T80 정책 승인 전).

경로(제안 docs/admin/t81_openapi_proposal.yaml + 해제): `/api/v1/admin/moderation-cases`
  GET    ''                              검수 큐 (status·target_type·priority·overdue·limit·cursor)
  GET    '/{case_id}'                    상세 + 처리 이력 (열람 감사)
  POST   '/{case_id}/assignment'         담당 시작(본인) T02·T09
  POST   '/{case_id}/assignment/release' 담당 해제 T04·T05
  POST   '/{case_id}/decision'           승인·반려 T06·T07
`admin` 역할 필수(권한 코드 admin.content.review 는 Seed 승인 전 — PM 결정 §9-12). 저장소는 PostgreSQL(migration 0010).
"""
from __future__ import annotations

import importlib
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth_config import AuthSettings
from app.core.exception_handlers import error_responses
from app.db import get_db
from app.dependencies.auth import CurrentUserDep, get_auth_settings, require_roles
from app.repositories.moderation import SqlModerationRepository
from app.services import moderation as svc
from app.services.job_postings import ListCursor, derive_cursor_key

router = APIRouter(prefix="/admin/moderation-cases", tags=["admin"], dependencies=[Depends(require_roles("admin"))],
                   responses=error_responses(401, 403, 503))

TargetType = Literal["job_posting", "company", "shared_document", "document_analysis", "retrieval_run", "agent_run",
                     "match_evaluation", "recommendation_run", "company_posting"]
Status = Literal["PENDING", "IN_REVIEW", "APPROVED", "REJECTED", "APPEALED", "CLOSED"]
ReasonCode = Literal["RIGHTS_UNCLEAR", "INACCURATE", "PERSONAL_DATA", "HARMFUL", "DISCRIMINATORY", "DUPLICATE",
                     "EXPIRED", "MALWARE", "OTHER"]
T125_SQL_MODULE = "app.repositories.company_postings"   # T125 SQL 저장소가 생기면 moderation_transitions(db) 제공


class VersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    decision: Literal["APPROVE", "REJECT"]
    reason_code: ReasonCode | None = None
    note: str | None = Field(default=None, min_length=1, max_length=svc.NOTE_MAX)


class CaseEventOut(BaseModel):
    event_id: UUID
    event: str
    from_status: str | None
    to_status: str
    actor_user_id: UUID | None
    reason_code: str | None
    occurred_at: datetime


class CaseSummaryOut(BaseModel):
    case_id: UUID
    target_type: str
    target_id: UUID
    target_summary: str | None
    trigger: str
    status: str
    priority: int
    assignee_id: UUID | None
    due_at: datetime
    overdue: bool
    flags: list[str]
    report_count: int
    version: int
    created_at: datetime


class CaseDetailOut(CaseSummaryOut):
    content_owner_id: UUID | None
    submitted_by: UUID | None
    first_decider_id: UUID | None
    decided_by: UUID | None
    decided_at: datetime | None
    reason_code: str | None
    appeal_count: int
    close_reason: str | None
    events: list[CaseEventOut]


class CasePageOut(BaseModel):
    items: list[CaseSummaryOut]
    next_cursor: str | None


def get_company_posting_transitions(db: Annotated[Session, Depends(get_db)]) -> svc.CompanyPostingTransitions | None:
    """T125 기업 공고 SQL 전이(같은 세션). T125 SQL 저장소가 이 브랜치에 없으면 None → company_posting 결정은 503.

    T125 가 `app.repositories.company_postings.moderation_transitions(session)` 을 제공하면 자동으로 연결된다.
    그 객체의 decide 는 `/admin/company-postings/{id}/decision` 과 같은 전이여야 하고 커밋하지 않아야 한다.
    """
    try:
        module = importlib.import_module(T125_SQL_MODULE)
    except ModuleNotFoundError:
        return None
    factory = getattr(module, "moderation_transitions", None)
    return factory(db) if factory else None


def get_moderation_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    company_postings: Annotated[svc.CompanyPostingTransitions | None, Depends(get_company_posting_transitions)],
) -> svc.ModerationService:
    effects = {"company_posting": svc.CompanyPostingEffect(company_postings)} if company_postings else {}
    return svc.ModerationService(SqlModerationRepository(db), ListCursor(derive_cursor_key(settings.jwt_secret)),
                                 effects)


Service = Annotated[svc.ModerationService, Depends(get_moderation_service)]


def _summary_fields(case: svc.ModerationCase, now: datetime) -> dict:
    return dict(case_id=case.case_id, target_type=case.target_type, target_id=case.target_id,
                target_summary=case.target_summary(), trigger=case.trigger, status=case.status,
                priority=case.priority, assignee_id=case.assignee_id, due_at=case.due_at, overdue=case.overdue(now),
                flags=list(case.flags), report_count=case.report_count, version=case.version,
                created_at=case.created_at)


def _detail(found: svc.CaseDetail, service: svc.ModerationService) -> CaseDetailOut:
    c = found.case          # reviewer_note 는 응답에 넣지 않는다
    return CaseDetailOut(
        **_summary_fields(c, service.clock()), content_owner_id=c.content_owner_id, submitted_by=c.submitted_by,
        first_decider_id=c.first_decider_id, decided_by=c.decided_by, decided_at=c.decided_at,
        reason_code=c.reason_code, appeal_count=c.appeal_count, close_reason=c.close_reason,
        events=[CaseEventOut(event_id=e.event_id, event=e.event, from_status=e.from_status, to_status=e.to_status,
                             actor_user_id=e.actor_user_id, reason_code=e.reason_code, occurred_at=e.occurred_at)
                for e in found.events])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@router.get("", response_model=CasePageOut, operation_id="listModerationCases", responses=error_responses(400, 422))
def list_cases(
    service: Service,
    status: Annotated[Status | None, Query()] = None,
    target_type: Annotated[TargetType | None, Query()] = None,
    priority: Annotated[int | None, Query(ge=1, le=3)] = None,
    overdue: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> CasePageOut:
    page = service.list(svc.QueueFilter(status, target_type, priority, overdue), limit, cursor)
    now = service.clock()
    return CasePageOut(items=[CaseSummaryOut(**_summary_fields(c, now)) for c in page.items],
                       next_cursor=page.next_cursor)


@router.get("/{case_id}", response_model=CaseDetailOut, operation_id="getModerationCase",
            responses=error_responses(404))
def get_case(case_id: UUID, request: Request, user: CurrentUserDep, service: Service) -> CaseDetailOut:
    return _detail(service.detail(user.user_id, case_id, _request_id(request)), service)


@router.post("/{case_id}/assignment", response_model=CaseDetailOut, operation_id="assignModerationCase",
             responses=error_responses(404, 409, 422))
def assign(case_id: UUID, body: VersionBody, request: Request, user: CurrentUserDep,
           service: Service) -> CaseDetailOut:
    return _detail(service.assign(user.user_id, case_id, body.version, _request_id(request)), service)


@router.post("/{case_id}/assignment/release", response_model=CaseDetailOut, operation_id="releaseModerationCase",
             responses=error_responses(404, 409, 422))
def release(case_id: UUID, body: VersionBody, request: Request, user: CurrentUserDep,
            service: Service) -> CaseDetailOut:
    return _detail(service.release(user.user_id, case_id, body.version, _request_id(request)), service)


@router.post("/{case_id}/decision", response_model=CaseDetailOut, operation_id="decideModerationCase",
             responses=error_responses(404, 409, 422))
def decide(case_id: UUID, body: DecisionBody, request: Request, user: CurrentUserDep,
           service: Service) -> CaseDetailOut:
    return _detail(service.decide(user.user_id, user.roles, case_id, body.version, body.decision, body.reason_code,
                                  body.note, _request_id(request)), service)
