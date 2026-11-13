"""`/auth/*`, `/consent-policies` (openapi.yaml tag `auth`). 비밀번호 재설정은 T93 범위."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.core.auth_config import AuthSettings
from app.core.config import API_V1_PREFIX
from app.core.exception_handlers import error_responses
from app.dependencies.auth import get_auth_service, get_auth_settings
from app.dependencies.csrf import require_csrf_protection
from app.schemas.auth import ConsentPolicy, LoginRequest, SignupRequest, TokenResponse
from app.services.auth import AuthService, IssuedTokens

REFRESH_COOKIE = "refresh_token"
# 기본값. 실제 Path 는 settings.refresh_cookie_path (PUBLIC_PATH_PREFIX 반영, #328). 접두사가 없으면 이 값과 같다.
REFRESH_COOKIE_PATH = f"{API_V1_PREFIX}/auth"

router = APIRouter(
    tags=["auth"], dependencies=[Depends(require_csrf_protection)], responses=error_responses(403),
)
ServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SettingsDep = Annotated[AuthSettings, Depends(get_auth_settings)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def _client_ip(request: Request) -> str:
    # Nginx 뒤에서는 프록시 주소가 된다. 신뢰할 프록시 헤더 처리는 배포 구성(T30)과 함께 결정.
    return request.client.host if request.client else "unknown"


def _issue(response: Response, tokens: IssuedTokens, settings: AuthSettings) -> TokenResponse:
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh_token,
        max_age=settings.refresh_token_ttl_seconds, path=settings.refresh_cookie_path,
        secure=settings.cookie_secure, httponly=True, samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED, response_model=TokenResponse,
             responses=error_responses(409, 429))
def signup(body: SignupRequest, request: Request, response: Response, service: ServiceDep, settings: SettingsDep):
    tokens = service.signup(body, _client_ip(request), request.headers.get("user-agent"))
    return _issue(response, tokens, settings)


@router.post("/auth/login", response_model=TokenResponse, responses=error_responses(401, 429))
def login(body: LoginRequest, request: Request, response: Response, service: ServiceDep, settings: SettingsDep):
    tokens = service.login(body, _client_ip(request), request.headers.get("user-agent"))
    return _issue(response, tokens, settings)


@router.post("/auth/refresh", response_model=TokenResponse, responses=error_responses(401))
def refresh(response: Response, service: ServiceDep, settings: SettingsDep, refresh_token: RefreshCookie = None):
    return _issue(response, service.refresh(refresh_token), settings)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(401))
def logout(service: ServiceDep, settings: SettingsDep, refresh_token: RefreshCookie = None) -> Response:
    service.logout(refresh_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        REFRESH_COOKIE, path=settings.refresh_cookie_path, secure=settings.cookie_secure, httponly=True,
        samesite="strict",
    )
    return response


@router.get("/consent-policies", response_model=list[ConsentPolicy])
def consent_policies(service: ServiceDep) -> list[ConsentPolicy]:
    return service.consent_policies()
