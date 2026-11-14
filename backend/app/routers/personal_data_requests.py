"""T142 내 데이터 반출 요청 API — `PERSONAL_DATA_REQUESTS_API=true` 일 때만 등록(기본 꺼짐, T141 미승인).

- 모두 로그인 필수, 본인 것만. 재인증이 필요한 동작은 `X-Reauth-Token` 헤더(10분, 세션에 묶임).
  재인증이 없거나 만료면 403 FORBIDDEN + `X-Reauth-Required: true`.
- 다운로드 토큰은 URL 경로·쿼리에 넣지 않는다(접근 로그 노출 방지). POST 본문으로 받는다.
- 응답은 모두 `Cache-Control: no-store`. 묶음은 64 KiB 단위로 흘려보낸다.
- 저장소: migration 0006(PostgreSQL). DB 가 설정되지 않으면 503. 처리 worker 는 `python -m app.personal_data_worker`
  (수동 1회 실행, 스케줄 없음).
"""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.core.rate_limit import AttemptLimiter
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.repositories.personal_data_requests import (
    SqlDeletionSource, SqlPasswordVerifier, SqlPersonalDataSource, SqlRequestRepository,
)
from app.services import personal_data_requests as svc

router = APIRouter(prefix="/me/data-requests", tags=["me"], responses=error_responses(401, 503))
NO_STORE = {"Cache-Control": "no-store"}
CHUNK = 64 * 1024
REAUTH_LIMIT, REAUTH_WINDOW = 5, 300      # 사용자당 5분 5회(PROPOSED)


class ReauthInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)


class DownloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=100)


def build_sql_service(db: Session, **options) -> svc.PersonalDataRequestService:
    """운영 배선: migration 0006 표 + T15 비밀번호 확인 + T31 탈퇴 조회 + 본인 데이터 원본(SQL)."""
    return svc.PersonalDataRequestService(SqlRequestRepository(db), SqlPersonalDataSource(db),
                                          SqlPasswordVerifier(db), SqlDeletionSource(db), **options)


def get_data_request_service(db: Annotated[Session, Depends(get_db)]) -> svc.PersonalDataRequestService:
    # DB 가 없으면 get_db 가 503 DEPENDENCY_UNAVAILABLE.
    return build_sql_service(db)


def get_reauth_limiter(request: Request) -> AttemptLimiter:
    return request.app.state.attempt_limiter


Service = Annotated[svc.PersonalDataRequestService, Depends(get_data_request_service)]
ReauthToken = Annotated[str | None, Header(alias="X-Reauth-Token", max_length=100)]


@router.post("/reauth", operation_id="reauthenticateForDataRequest", responses=error_responses(422, 429))
def reauth(body: ReauthInput, user: CurrentUserDep, service: Service, response: Response,
           limiter: Annotated[AttemptLimiter, Depends(get_reauth_limiter)]) -> dict:
    key = f"dsr-reauth:{user.user_id}"
    if limiter.retry_after(key) or limiter.hit(key, REAUTH_LIMIT, REAUTH_WINDOW):
        raise AppError(ErrorCode.RATE_LIMITED, log_detail="reauth rate limited", retry_after=REAUTH_WINDOW)
    token, expires = service.reauthenticate(user.user_id, user.session_id, body.password)
    response.headers.update(NO_STORE)
    return {"reauth_token": token, "expires_at": expires.isoformat()}


@router.get("", operation_id="listMyDataRequests")
def list_requests(user: CurrentUserDep, service: Service, response: Response) -> dict:
    response.headers.update(NO_STORE)
    return {"items": service.list_requests(user.user_id)}


@router.post("/exports", status_code=202, operation_id="requestMyDataExport",
             responses=error_responses(403, 409, 429))
def create_export(user: CurrentUserDep, service: Service, response: Response, reauth_token: ReauthToken = None) -> dict:
    service.require_reauth(user.user_id, user.session_id, reauth_token)
    req = service.create_export(user.user_id)
    response.headers.update(NO_STORE)
    response.headers["Location"] = f"/api/v1/me/data-requests/exports/{req.request_id}"
    return service.public_view(req)


@router.get("/exports/{request_id}", operation_id="getMyDataExport", responses=error_responses(404))
def get_export(request_id: UUID, user: CurrentUserDep, service: Service, response: Response) -> dict:
    response.headers.update(NO_STORE)
    return service.public_view(service.get_export(user.user_id, request_id))


@router.post("/exports/{request_id}/cancel", operation_id="cancelMyDataExport", responses=error_responses(404, 409))
def cancel_export(request_id: UUID, user: CurrentUserDep, service: Service) -> dict:
    return service.public_view(service.cancel_export(user.user_id, request_id))


@router.post("/exports/{request_id}/download-link", status_code=201, operation_id="issueMyDataExportDownload",
             responses=error_responses(403, 404, 409))
def issue_download(request_id: UUID, user: CurrentUserDep, service: Service, response: Response,
                   reauth_token: ReauthToken = None) -> dict:
    service.require_reauth(user.user_id, user.session_id, reauth_token)
    token, expires = service.issue_download(user.user_id, request_id)
    response.headers.update(NO_STORE)
    return {"token": token, "expires_at": expires.isoformat(), "uses": 1,
            "notice": "이 다운로드는 한 번만 받을 수 있습니다."}


@router.post("/download", operation_id="downloadMyDataExport", responses=error_responses(404, 422))
def download(body: DownloadInput, user: CurrentUserDep, service: Service) -> StreamingResponse:
    data = service.consume_download(user.user_id, body.token)
    chunks = (data[i:i + CHUNK] for i in range(0, len(data), CHUNK))
    return StreamingResponse(chunks, media_type="application/json", headers={
        **NO_STORE, "Content-Disposition": 'attachment; filename="my-data-export.json"',
        "Content-Length": str(len(data)), "X-Content-Type-Options": "nosniff"})
