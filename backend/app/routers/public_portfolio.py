"""T129 공개 포트폴리오 API — `PUBLIC_PORTFOLIO_API=true` 일 때만 등록(기본 꺼짐, T128 미승인).

소유자 설정(`/me/public-profile/...`)은 로그인 필수. 공개 조회(`/public/portfolios/{token}`)는 비로그인 가능하며
항상 `Cache-Control: no-store`, `X-Robots-Tag: noindex, nofollow, noarchive`, `Referrer-Policy: no-referrer`.
저장소가 없어서(migration 승인 전) 기본 의존성은 503. 공개 조회는 IP 당 요청 한도(토큰 대입 방지).
"""
import json
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.core.rate_limit import AttemptLimiter
from app.dependencies.auth import CurrentUserDep
from app.services import public_portfolio as svc

router = APIRouter(tags=["public-portfolio"], responses=error_responses(503))
PUBLIC_HEADERS = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow, noarchive",
                  "Referrer-Policy": "no-referrer"}
VIEW_LIMIT, VIEW_WINDOW = 60, 60       # IP 당 60초 60회(PROPOSED)

Field_ = Literal["display_name", "headline", "bio", "location_text", "experience.organization", "experience.title",
                 "experience.period", "experience.description", "project.title", "project.summary",
                 "project.period", "skills", "target_roles", "email", "documents", "analysis_results",
                 "job_applications", "behavior_events", "consents_and_account"]


class SelectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: list[Field_] = Field(max_length=20)
    experience_ids: list[UUID] = Field(default_factory=list, max_length=100)
    project_ids: list[UUID] = Field(default_factory=list, max_length=100)
    alias: str | None = Field(default=None, max_length=50)
    version: int = Field(ge=1)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class LinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ttl_days: int = Field(default=30, ge=1, le=90)


def get_portfolio_service() -> svc.PublicPortfolioService:
    raise AppError(ErrorCode.DEPENDENCY_UNAVAILABLE, log_detail="portfolio storage not provisioned (T128 migration HOLD)")


def get_view_limiter(request: Request) -> AttemptLimiter:
    return request.app.state.attempt_limiter


Service = Annotated[svc.PublicPortfolioService, Depends(get_portfolio_service)]


def _selection(sel: svc.Selection) -> dict:
    return {"fields": sorted(sel.fields), "experience_ids": sorted(map(str, sel.experience_ids)),
            "project_ids": sorted(map(str, sel.project_ids)), "alias": sel.alias, "version": sel.version,
            "consented": sel.consented}


def _link(link: svc.ShareLink) -> dict:
    return {"link_id": str(link.link_id), "created_at": link.created_at.isoformat(),
            "expires_at": link.expires_at.isoformat(), "revoked": link.revoked_at is not None, "views": link.views}


@router.get("/me/public-profile", operation_id="getMyPublicProfileSettings", responses=error_responses(401))
def settings(user: CurrentUserDep, service: Service) -> dict:
    return {"selection": _selection(service.selection(user.user_id)),
            "links": [_link(l) for l in service.links(user.user_id)]}


@router.put("/me/public-profile/selection", operation_id="updateMyPublicProfileSelection",
            responses=error_responses(401, 404, 409, 422))
def update_selection(body: SelectionUpdate, user: CurrentUserDep, service: Service) -> dict:
    return _selection(service.update_selection(user.user_id, set(body.fields), set(body.experience_ids),
                                               set(body.project_ids), body.alias, body.version))


@router.get("/me/public-profile/preview", operation_id="previewMyPublicProfile", responses=error_responses(401, 404))
def preview(user: CurrentUserDep, service: Service, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return service.preview(user.user_id)


@router.post("/me/public-profile/consent", operation_id="confirmMyPublicProfile",
             responses=error_responses(401, 409, 422))
def confirm(body: ConfirmRequest, user: CurrentUserDep, service: Service) -> dict:
    return _selection(service.confirm(user.user_id, body.version))


@router.delete("/me/public-profile/consent", status_code=204, operation_id="withdrawMyPublicProfile",
               responses=error_responses(401))
def withdraw(user: CurrentUserDep, service: Service) -> Response:
    service.withdraw(user.user_id)
    return Response(status_code=204)


@router.post("/me/public-profile/links", status_code=201, operation_id="createMyPublicProfileLink",
             responses=error_responses(401, 409, 422))
def create_link(body: LinkCreate, user: CurrentUserDep, service: Service, response: Response) -> dict:
    link, token = service.create_link(user.user_id, timedelta(days=body.ttl_days))
    response.headers["Cache-Control"] = "no-store"
    return {**_link(link), "url": f"/p/{token}", "notice": "이 주소는 지금 한 번만 보여 줍니다."}


@router.delete("/me/public-profile/links/{link_id}", status_code=204, operation_id="revokeMyPublicProfileLink",
               responses=error_responses(401, 404))
def revoke_link(link_id: UUID, user: CurrentUserDep, service: Service) -> Response:
    service.revoke_link(user.user_id, link_id)
    return Response(status_code=204)


@router.get("/public/portfolios/{token}", operation_id="viewPublicPortfolio", responses=error_responses(404, 429))
def view(token: str, request: Request, service: Service,
         limiter: Annotated[AttemptLimiter, Depends(get_view_limiter)]) -> Response:
    client = request.client.host if request.client else "unknown"
    if limiter.retry_after(f"portfolio-view:{client}") or limiter.hit(f"portfolio-view:{client}", VIEW_LIMIT, VIEW_WINDOW):
        raise AppError(ErrorCode.RATE_LIMITED, log_detail="portfolio view rate limited", retry_after=VIEW_WINDOW)
    if not 32 <= len(token) <= 100:
        raise AppError(ErrorCode.NOT_FOUND, log_detail="malformed portfolio token")
    body = json.dumps(service.view(token), ensure_ascii=False)
    return Response(content=body, media_type="application/json", headers=PUBLIC_HEADERS)
