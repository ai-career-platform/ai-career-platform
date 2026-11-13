"""#328 Google 로그인·게이트 엔드포인트. `GOOGLE_LOGIN_ENABLED=1` 일 때만 앱에 등록된다(꺼져 있으면 404).

설계: docs/security/GOOGLE_SSO_AUTO_SIGNUP_DESIGN.md §3~§7 (PR #329), 보안 검토 8개 항목 반영.
- 리디렉트 URL 에는 토큰·이메일·sub 를 넣지 않는다. 상대 경로와 고정 오류 코드(`google_error`)만 쓴다.
- 앱 세션은 기존 `AuthService._start_session()` + refresh 쿠키(`routers.auth._issue`)를 그대로 쓴다.
- POST(가입·완전 로그아웃)는 기존 CSRF 정책(`require_csrf_protection`)을 그대로 적용한다.
"""

from __future__ import annotations

import html
import logging
import secrets
import urllib.parse
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.auth_config import AuthSettings
from app.core.config import API_V1_PREFIX
from app.core.errors import AppError, ErrorCode
from app.core.exception_handlers import error_responses
from app.core.rate_limit import AttemptLimiter
from app.dependencies.auth import get_attempt_limiter, get_auth_service, get_auth_settings
from app.dependencies.csrf import require_csrf_protection
from app.routers.auth import REFRESH_COOKIE, _client_ip, _issue
from app.schemas.auth import GooglePendingSignup, GoogleSignupRequest, TokenResponse
from app.services.auth import AuthService
from app.services.google_oauth import (
    GATE_TTL_SECONDS,
    PENDING_TTL_SECONDS,
    PURPOSE_GATE,
    PURPOSE_PENDING,
    PURPOSE_TX,
    TX_TTL_SECONDS,
    GoogleAuthError,
    GoogleRuntime,
    new_pkce_pair,
    safe_return_to,
    sub_hash,
)

logger = logging.getLogger(__name__)

TX_COOKIE = "career_g_tx"
PENDING_COOKIE = "career_g_pending"
GATE_COOKIE = "career_gate"

START_PATH = f"{API_V1_PREFIX}/auth/google/start"
CALLBACK_PATH = f"{API_V1_PREFIX}/auth/google/callback"
GATE_PATH = f"{API_V1_PREFIX}/auth/gate"
SIGNOUT_PATH = f"{API_V1_PREFIX}/auth/google/signout"
SIGNED_OUT_PATH = f"{API_V1_PREFIX}/auth/google/signed-out"
# 게이트 미들웨어 예외: 실제 인증 수행에 꼭 필요한 경로만(정확 일치). pending·signup 은 게이트 쿠키가 있어야 한다.
GATE_EXEMPT_PATHS = frozenset({START_PATH, CALLBACK_PATH, GATE_PATH, SIGNOUT_PATH, SIGNED_OUT_PATH})

# start·callback IP 제한. nginx 뒤에서는 모든 사용자가 같은 프록시 주소로 보이므로(routers.auth._client_ip 주석)
# 11~30명이 동시에 로그인해도 막히지 않을 만큼 넉넉하게 둔다. 남용 완화용이며 1차 방어는 Google·Allowlist.
GOOGLE_IP_MAX_ATTEMPTS = 300
_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "Pragma": "no-cache"}
_HTML_CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

router = APIRouter(
    tags=["auth"], dependencies=[Depends(require_csrf_protection)], responses=error_responses(403),
)


def get_google_runtime(request: Request) -> GoogleRuntime:
    return request.app.state.google


RuntimeDep = Annotated[GoogleRuntime, Depends(get_google_runtime)]
ServiceDep = Annotated[AuthService, Depends(get_auth_service)]
SettingsDep = Annotated[AuthSettings, Depends(get_auth_settings)]
LimiterDep = Annotated[AttemptLimiter, Depends(get_attempt_limiter)]


# ---------------------------------------------------------------- helpers
def _google_cookie_path(settings: AuthSettings) -> str:
    return f"{settings.public_path_prefix}{API_V1_PREFIX}/auth/google"


def _gate_cookie_path(settings: AuthSettings) -> str:
    return f"{settings.public_path_prefix}/"


def _set(response: Response, name: str, value: str, max_age: int, path: str, samesite: str,
         settings: AuthSettings) -> None:
    response.set_cookie(name, value, max_age=max_age, path=path, secure=settings.cookie_secure, httponly=True,
                        samesite=samesite)


def _clear(response: Response, name: str, path: str, samesite: str, settings: AuthSettings) -> None:
    response.delete_cookie(name, path=path, secure=settings.cookie_secure, httponly=True, samesite=samesite)


def _limit(limiter: AttemptLimiter, key: str, limit: int, window: int) -> None:
    if wait := limiter.retry_after(key):
        raise AppError(ErrorCode.RATE_LIMITED, retry_after=wait)
    if wait := limiter.hit(key, limit, window):
        raise AppError(ErrorCode.RATE_LIMITED, retry_after=wait)


def _spa(settings: AuthSettings, path: str, **query: str) -> str:
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    return f"{settings.public_path_prefix}{path}{suffix}"


def _redirect(location: str) -> RedirectResponse:
    return RedirectResponse(location, status_code=status.HTTP_302_FOUND, headers=dict(_NO_STORE))


def _page(title: str, message: str, settings: AuthSettings, status_code: int, retry: bool = True) -> HTMLResponse:
    """게이트 밖에서도 보이는 정적 안내 페이지(외부 리소스·스크립트 없음). SPA 리디렉트 무한 루프를 막는다."""
    retry_link = ""
    if retry:
        href = html.escape(f"{settings.public_path_prefix}{START_PATH}?prompt=select_account")
        retry_link = f'<p><a href="{href}">다른 Google 계정으로 다시 시도</a></p>'
    body = (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;"
        "line-height:1.6}</style></head><body>"
        f"<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{retry_link}</body></html>"
    )
    return HTMLResponse(body, status_code=status_code,
                        headers={**_NO_STORE, "Content-Security-Policy": _HTML_CSP, "X-Frame-Options": "DENY"})


# ---------------------------------------------------------------- start
@router.get("/auth/google/start", status_code=302, responses={302: {"description": "Google 인가 화면으로 이동"}})
def google_start(
    request: Request, runtime: RuntimeDep, settings: SettingsDep, limiter: LimiterDep,
    return_to: Annotated[str | None, Query(max_length=2048)] = None,
    prompt: Literal["select_account"] | None = None,
) -> Response:
    _limit(limiter, f"google-start-ip:{_client_ip(request)}", GOOGLE_IP_MAX_ATTEMPTS, settings.rate_window_seconds)
    verifier, challenge = new_pkce_pair()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    target = safe_return_to(return_to, settings.public_path_prefix)
    tx_token, _ = runtime.signer.sign(PURPOSE_TX, TX_TTL_SECONDS, state=state, nonce=nonce, cv=verifier, rt=target)
    response = _redirect(runtime.client.authorization_url(state, nonce, challenge, prompt == "select_account"))
    # Google 에서 돌아오는 top-level GET 에 실려야 하므로 Lax. Path 는 Google 엔드포인트로 한정.
    _set(response, TX_COOKIE, tx_token, TX_TTL_SECONDS, _google_cookie_path(settings), "lax", settings)
    return response


# ---------------------------------------------------------------- callback
@router.get("/auth/google/callback", status_code=302, responses={302: {"description": "인증 결과에 따른 SPA 경로"}})
def google_callback(
    request: Request, runtime: RuntimeDep, service: ServiceDep, settings: SettingsDep, limiter: LimiterDep,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> Response:
    _limit(limiter, f"google-callback-ip:{_client_ip(request)}", GOOGLE_IP_MAX_ATTEMPTS,
           settings.rate_window_seconds)
    tx = runtime.signer.verify(PURPOSE_TX, request.cookies.get(TX_COOKIE))
    had_gate = runtime.gate_claims(request.cookies.get(GATE_COOKIE)) is not None

    def finish(response: Response) -> Response:
        # tx 쿠키는 성공·실패와 관계없이 항상 지운다(브라우저 측 1회용). 서버 측 1회용은 once.claim.
        _clear(response, TX_COOKIE, _google_cookie_path(settings), "lax", settings)
        return response

    def fail(reason: str, code_name: str = "failed", gate: bool = had_gate) -> Response:
        logger.info("google_login result=%s reason=%s", code_name, reason)
        if gate:  # 로그인 화면이 게이트 뒤에 있어도 볼 수 있으므로 SPA 로 안내
            return finish(_redirect(_spa(settings, "/login", google_error=code_name)))
        title = "Google 로그인이 취소되었습니다" if code_name == "cancelled" else "Google 로그인에 실패했습니다"
        return finish(_page(title, "잠시 후 다시 시도해 주세요.", settings, status.HTTP_400_BAD_REQUEST))

    if tx is None:
        return fail("tx_missing_or_invalid")
    if not runtime.once.claim(tx["jti"], tx["exp"]):
        return fail("tx_replayed")  # 같은 로그인 시도의 두 번째 callback(재사용·동시 요청)
    if error:
        return fail("provider_error", "cancelled" if error == "access_denied" else "failed")
    if not state or not compare_digest(state, str(tx.get("state", ""))):
        return fail("state_mismatch")
    try:
        id_token = runtime.client.exchange_code(code or "", str(tx["cv"]))
        identity = runtime.client.verify_id_token(id_token, str(tx["nonce"]))
    except GoogleAuthError as exc:
        return fail(str(exc))

    hashed = sub_hash(identity.sub)
    if not runtime.allowlist.contains(identity.email):
        logger.info("google_login result=not_allowed sub_hash=%s", hashed)
        response = _page("허용되지 않은 Google 계정입니다",
                         "이 Google 계정은 사용이 허용되지 않았습니다. 관리자에게 문의하거나 다른 계정으로 시도해 주세요.",
                         settings, status.HTTP_403_FORBIDDEN)
        _clear(response, GATE_COOKIE, _gate_cookie_path(settings), "lax", settings)  # 이전 계정 게이트도 끊는다
        return finish(response)

    gate_token, _ = runtime.signer.sign(PURPOSE_GATE, GATE_TTL_SECONDS, sub=identity.sub, email=identity.email)
    outcome = service.google_login(identity.sub, identity.email, request.headers.get("user-agent"))
    logger.info("google_login result=%s sub_hash=%s", outcome.kind, hashed)
    if outcome.kind == "login" and outcome.tokens is not None:
        next_path = safe_return_to(str(tx.get("rt", "")), settings.public_path_prefix)
        response = _redirect(_spa(settings, "/auth/google/done", next=next_path))
        _issue(response, outcome.tokens, settings)
    elif outcome.kind == "signup_required":
        pending, _ = runtime.signer.sign(PURPOSE_PENDING, PENDING_TTL_SECONDS,
                                         sub=identity.sub, email=identity.email, name=identity.name)
        response = _redirect(_spa(settings, "/auth/google/signup"))
        _set(response, PENDING_COOKIE, pending, PENDING_TTL_SECONDS, _google_cookie_path(settings), "strict",
             settings)
    elif outcome.kind == "email_conflict":
        response = _redirect(_spa(settings, "/login", google_error="email_conflict"))
    else:  # inactive: 계정 상태를 구분해 알리지 않는다
        response = _redirect(_spa(settings, "/login", google_error="failed"))
    _set(response, GATE_COOKIE, gate_token, GATE_TTL_SECONDS, _gate_cookie_path(settings), "lax", settings)
    return finish(response)


# ---------------------------------------------------------------- pending / signup
def _pending_claims(runtime: GoogleRuntime, token: str | None) -> dict:
    claims = runtime.signer.verify(PURPOSE_PENDING, token)
    if claims is None or not all(isinstance(claims.get(k), str) for k in ("sub", "email", "name")):
        raise AppError(ErrorCode.GOOGLE_SIGNUP_EXPIRED, log_detail="google pending missing or invalid")
    if runtime.once.is_used(claims["jti"]):
        raise AppError(ErrorCode.GOOGLE_SIGNUP_EXPIRED, log_detail="google pending already used")
    if not runtime.allowlist.contains(claims["email"]):
        raise AppError(ErrorCode.GOOGLE_NOT_ALLOWED, log_detail="google pending email no longer allowlisted")
    return claims


@router.get("/auth/google/pending", response_model=GooglePendingSignup, responses=error_responses(401, 403))
def google_pending(
    runtime: RuntimeDep, response: Response,
    pending: Annotated[str | None, Cookie(alias=PENDING_COOKIE)] = None,
) -> GooglePendingSignup:
    claims = _pending_claims(runtime, pending)
    response.headers.update(_NO_STORE)
    return GooglePendingSignup(email=claims["email"], display_name=claims["name"],
                               expires_at=datetime.fromtimestamp(claims["exp"], UTC))


@router.post("/auth/google/signup", status_code=status.HTTP_201_CREATED, response_model=TokenResponse,
             responses=error_responses(401, 409, 422, 429))
def google_signup(
    body: GoogleSignupRequest, request: Request, response: Response, runtime: RuntimeDep, service: ServiceDep,
    settings: SettingsDep, limiter: LimiterDep,
    pending: Annotated[str | None, Cookie(alias=PENDING_COOKIE)] = None,
) -> TokenResponse:
    _limit(limiter, f"google-signup-ip:{_client_ip(request)}", GOOGLE_IP_MAX_ATTEMPTS, 3600)
    claims = _pending_claims(runtime, pending)
    # 서버 측 1회 사용: 이중 제출·동시 요청 중 하나만 계속한다.
    if not runtime.once.claim(claims["jti"], claims["exp"]):
        raise AppError(ErrorCode.GOOGLE_SIGNUP_EXPIRED, log_detail="google pending already used")
    try:
        tokens = service.google_signup(claims["sub"], claims["email"], body.display_name.strip() or claims["name"],
                                       body.consents, request.headers.get("user-agent"))
    except AppError as exc:
        if exc.code == ErrorCode.VALIDATION_FAILED:
            runtime.once.release(claims["jti"])  # 동의 누락은 고쳐서 다시 제출할 수 있다
        raise
    except Exception:
        runtime.once.release(claims["jti"])
        raise
    logger.info("google_signup result=created_or_linked sub_hash=%s", sub_hash(claims["sub"]))
    _clear(response, PENDING_COOKIE, _google_cookie_path(settings), "strict", settings)
    return _issue(response, tokens, settings)


# ---------------------------------------------------------------- gate / signout
@router.get("/auth/gate", status_code=status.HTTP_204_NO_CONTENT, responses=error_responses(401))
def google_gate(runtime: RuntimeDep, gate: Annotated[str | None, Cookie(alias=GATE_COOKIE)] = None) -> Response:
    """nginx auth_request 용. 204 = 허용된 Google 사용자, 401 = 아님."""
    if runtime.gate_claims(gate) is None:
        raise AppError(ErrorCode.EDGE_AUTH_REQUIRED)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.post("/auth/google/signout", status_code=status.HTTP_204_NO_CONTENT)
def google_signout(
    service: ServiceDep, settings: SettingsDep,
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> Response:
    """완전 로그아웃: 앱 세션 + 게이트 쿠키 종료. Google 계정 자체는 로그아웃하지 않는다."""
    if refresh_token:
        try:
            service.logout(refresh_token)
        except AppError:
            pass  # 이미 끝난 세션이어도 쿠키는 지운다
    response = Response(status_code=status.HTTP_204_NO_CONTENT, headers=dict(_NO_STORE))
    response.delete_cookie(REFRESH_COOKIE, path=settings.refresh_cookie_path, secure=settings.cookie_secure,
                           httponly=True, samesite="strict")
    _clear(response, GATE_COOKIE, _gate_cookie_path(settings), "lax", settings)
    _clear(response, PENDING_COOKIE, _google_cookie_path(settings), "strict", settings)
    return response


@router.get("/auth/google/signed-out", response_class=HTMLResponse)
def google_signed_out(settings: SettingsDep) -> HTMLResponse:
    """완전 로그아웃 뒤 보여 줄 정적 페이지(게이트 밖). 데이터 없음."""
    return _page("로그아웃되었습니다", "AI Career Platform 에서 로그아웃했습니다. 다시 이용하려면 Google로 로그인해 주세요.",
                 settings, status.HTTP_200_OK)
