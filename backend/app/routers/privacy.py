"""T31 self-only routes. Cancellation remains explicitly HOLD, fail closed."""
from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session
from app.db import get_db
from app.dependencies.auth import CurrentUserDep
from app.core.exception_handlers import error_responses
from app.repositories.privacy import SqlPrivacyRepository
from app.services.privacy import PrivacyService
from app.schemas.privacy import Consent, OptionalConsentInput, DeletionRequest, DeletionRequestInput
from app.routers.me import private_request

router = APIRouter(prefix="/me", tags=["me"], responses=error_responses(401, 422, 503))

def get_privacy_service(session: Annotated[Session, Depends(get_db)]) -> PrivacyService:
    return PrivacyService(SqlPrivacyRepository(session))

Service = Annotated[PrivacyService, Depends(get_privacy_service)]

@router.get("/consents", response_model=list[Consent], operation_id="listMyConsents")
def list_consents(request: Request, user: CurrentUserDep, service: Service):
    private_request(request)
    return service.list_consents(user.user_id)

@router.post("/consents", status_code=201, response_model=Consent, operation_id="recordMyConsent")
def record_consent(body: OptionalConsentInput, request: Request, user: CurrentUserDep, service: Service):
    private_request(request)
    return service.record_consent(user.user_id, body)

@router.get("/deletion-request", response_model=DeletionRequest,
            operation_id="getMyDeletionRequest", responses=error_responses(404))
def get_deletion(request: Request, user: CurrentUserDep, service: Service):
    private_request(request)
    return service.get_deletion(user.user_id)

@router.post("/deletion-request", status_code=202, response_model=DeletionRequest,
            operation_id="requestMyDeletion", responses=error_responses(409))
def request_deletion(body: DeletionRequestInput, request: Request, response: Response,
                     user: CurrentUserDep, service: Service):
    private_request(request)
    result = service.request_deletion(user.user_id)
    response.headers['Location'] = '/api/v1/me/deletion-request'
    return result

@router.delete("/deletion-request", status_code=204, operation_id="cancelMyDeletion",
    responses=error_responses(404), openapi_extra={"x-implementation-status":"HOLD"},
    description="HOLD: disabled/revoked users cannot reauthenticate under T15; no bypass is provided.")
def cancel_deletion(request: Request, user: CurrentUserDep, service: Service):
    private_request(request)
    service.cancel_deletion(user.user_id)
    return Response(status_code=204)
