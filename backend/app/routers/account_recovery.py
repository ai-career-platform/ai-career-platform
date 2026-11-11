"""T93 계정 복구 API (확정 계약 docs/api/openapi.yaml `requestPasswordReset`, `resetPassword`).

메일 공급자가 설정되기 전에는 `get_mail_sender` 가 UnavailableMailSender 를 돌려주므로 재설정 요청은 모두 503 입니다
(= 실제 운영 활성화 HOLD). 공급자·발송 정책 승인 후 이 의존성 한 곳만 바꿉니다. 환경변수로 켜는 경로는 두지 않았습니다.
"""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.exception_handlers import error_responses
from app.core.rate_limit import AttemptLimiter
from app.db import get_db
from app.dependencies.auth import get_attempt_limiter
from app.repositories.account_recovery import SqlRecoveryRepository
from app.schemas.auth import Email
from app.services.account_recovery import AccountRecoveryService
from app.services.mail import MailSender, UnavailableMailSender

DEFAULT_LINK_BASE = "/password-reset"   # Frontend 화면(T94). 절대 URL 은 공급자 연결 시 설정


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email   # 가입과 같은 형식 규칙(app/schemas/auth.py)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=16, max_length=200)
    new_password: str = Field(min_length=10, max_length=128)


def get_mail_sender() -> MailSender:
    return UnavailableMailSender()


def get_recovery_service(
    db: Annotated[Session, Depends(get_db)],
    mail: Annotated[MailSender, Depends(get_mail_sender)],
    limiter: Annotated[AttemptLimiter, Depends(get_attempt_limiter)],
) -> AccountRecoveryService:
    return AccountRecoveryService(SqlRecoveryRepository(db), mail, limiter,
                                  os.environ.get("PASSWORD_RESET_LINK_BASE", DEFAULT_LINK_BASE))


Service = Annotated[AccountRecoveryService, Depends(get_recovery_service)]
router = APIRouter(tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/password-reset-requests", status_code=status.HTTP_202_ACCEPTED, operation_id="requestPasswordReset",
             responses=error_responses(429, 503))
def request_password_reset(body: PasswordResetRequest, request: Request, service: Service) -> Response:
    service.request_reset(body.email, _client_ip(request))
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/auth/password-resets", status_code=status.HTTP_204_NO_CONTENT, operation_id="resetPassword",
             responses=error_responses(400, 429, 503))
def reset_password(body: PasswordReset, request: Request, service: Service) -> Response:
    service.reset_password(body.token, body.new_password, _client_ip(request), getattr(request.state, "request_id", None))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
