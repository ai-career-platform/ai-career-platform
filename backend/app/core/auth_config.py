"""인증(T15) 설정. 환경변수만 읽습니다.

- JWT 서명은 HS256(대칭키) — API_CONTRACT 미결 T06-1을 T15에서 HS256으로 결정.
  단일 백엔드 서비스만 토큰을 검증하므로 키 배포가 단순한 대칭키를 쓴다.
- `JWT_SECRET`이 없으면 local-dev/test에서만 프로세스마다 임의 키를 만든다(재시작 시 토큰 무효).
  그 외 환경에서는 기동을 막는다.
"""

import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.core.config import API_V1_PREFIX, env_int

logger = logging.getLogger(__name__)

LOCAL_ENVS = {"local-dev", "test"}
MIN_SECRET_LENGTH = 32


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret: str = field(repr=False)
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    cookie_secure: bool
    login_max_failures: int
    login_lock_seconds: int
    login_ip_max_attempts: int
    signup_ip_max_attempts: int
    rate_window_seconds: int
    # #328: 외부 공개 경로 접두사(Staging '/career'). 쿠키 Path 계산에만 쓴다. 기본 ''이면 기존 Path 그대로.
    public_path_prefix: str = ""

    @property
    def refresh_cookie_path(self) -> str:
        return f"{self.public_path_prefix}{API_V1_PREFIX}/auth"

    @classmethod
    def from_env(cls, app_env: str) -> "AuthSettings":
        secret = os.environ.get("JWT_SECRET", "")
        if not secret:
            if app_env not in LOCAL_ENVS:
                raise ValueError("JWT_SECRET is required outside local-dev/test")
            logger.warning("JWT_SECRET is not set; using a random per-process key")
            secret = secrets.token_urlsafe(48)
        elif len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
        return cls(
            jwt_secret=secret,
            access_token_ttl_seconds=env_int("ACCESS_TOKEN_TTL_SECONDS", 900, 60, 3600),
            refresh_token_ttl_seconds=env_int("REFRESH_TOKEN_TTL_SECONDS", 1_209_600, 3600, 2_592_000),
            cookie_secure=env_bool("AUTH_COOKIE_SECURE", True),
            login_max_failures=env_int("LOGIN_MAX_FAILURES", 5, 1, 100),
            login_lock_seconds=env_int("LOGIN_LOCK_SECONDS", 900, 10, 86_400),
            login_ip_max_attempts=env_int("LOGIN_IP_MAX_ATTEMPTS", 30, 1, 10_000),
            signup_ip_max_attempts=env_int("SIGNUP_IP_MAX_ATTEMPTS", 10, 1, 10_000),
            rate_window_seconds=env_int("AUTH_RATE_WINDOW_SECONDS", 900, 10, 86_400),
            public_path_prefix=normalize_public_path_prefix(os.environ.get("PUBLIC_PATH_PREFIX", "")),
        )


_PREFIX_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")


def normalize_public_path_prefix(raw: str) -> str:
    """'' 또는 '/career' 형태만 허용한다. 끝의 '/'는 지운다. '.'·'..'·빈 세그먼트·특수문자는 기동 거부."""
    value = raw.strip()
    if value in {"", "/"}:
        return ""
    if not value.startswith("/") or value.startswith("//"):
        raise ValueError("PUBLIC_PATH_PREFIX must be empty or an absolute path like /career")
    value = value.rstrip("/")
    if not all(_PREFIX_SEGMENT.match(segment) for segment in value[1:].split("/")):
        raise ValueError("PUBLIC_PATH_PREFIX has an invalid path segment")
    return value


# ---------------------------------------------------------------- #328 Google OAuth (기본 꺼짐)
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
GOOGLE_CALLBACK_PATH = f"{API_V1_PREFIX}/auth/google/callback"


@dataclass(frozen=True)
class GoogleSettings:
    """Google 로그인·게이트 설정. 두 플래그가 꺼져 있으면 다른 값은 읽기만 하고 검증하지 않는다."""

    login_enabled: bool
    gate_enforced: bool
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)
    redirect_uri: str = ""
    allowlist_file: str = ""
    cookie_secret: str = field(default="", repr=False)
    authorization_endpoint: str = GOOGLE_AUTHORIZATION_ENDPOINT
    token_endpoint: str = GOOGLE_TOKEN_ENDPOINT
    jwks_uri: str = GOOGLE_JWKS_URI
    issuers: tuple[str, ...] = GOOGLE_ISSUERS

    @classmethod
    def disabled(cls) -> "GoogleSettings":
        return cls(login_enabled=False, gate_enforced=False)

    @classmethod
    def from_env(cls, app_env: str, auth: AuthSettings) -> "GoogleSettings":
        login_enabled = env_bool("GOOGLE_LOGIN_ENABLED", False)
        gate_enforced = env_bool("GOOGLE_GATE_ENFORCED", False)
        test_idp = os.environ.get("GOOGLE_TEST_IDP_BASE_URL", "").strip().rstrip("/")
        if test_idp and app_env not in LOCAL_ENVS:
            # 가짜 IdP 주입은 local-dev/test 에서만. Staging 에 남아 있으면 기동을 막는다.
            raise ValueError("GOOGLE_TEST_IDP_BASE_URL is allowed only in local-dev/test")
        if gate_enforced and not login_enabled:
            raise ValueError("GOOGLE_GATE_ENFORCED requires GOOGLE_LOGIN_ENABLED")
        if not login_enabled:
            return cls.disabled()

        client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        if not client_id or any(c.isspace() for c in client_id):
            raise ValueError("GOOGLE_CLIENT_ID is required when GOOGLE_LOGIN_ENABLED")
        if app_env not in LOCAL_ENVS and not client_id.endswith(".apps.googleusercontent.com"):
            raise ValueError("GOOGLE_CLIENT_ID must be a Google OAuth web client id")

        secret_file = os.environ.get("GOOGLE_CLIENT_SECRET_FILE", "").strip()
        client_secret = _read_secret_file(secret_file)

        redirect_uri = os.environ.get("GOOGLE_REDIRECT_URI", "").strip()
        parsed = urlsplit(redirect_uri)
        allowed_schemes = {"https", "http"} if app_env in LOCAL_ENVS else {"https"}
        expected_path = f"{auth.public_path_prefix}{GOOGLE_CALLBACK_PATH}"
        if parsed.scheme not in allowed_schemes or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("GOOGLE_REDIRECT_URI must be an absolute https URL without query")
        if parsed.path != expected_path:
            raise ValueError("GOOGLE_REDIRECT_URI path must be PUBLIC_PATH_PREFIX + /api/v1/auth/google/callback")

        allowlist_file = os.environ.get("GOOGLE_ALLOWLIST_FILE", "").strip()
        if not allowlist_file or not os.path.isfile(allowlist_file):
            # 빈 파일은 허용(전원 거부)하지만 파일이 없으면 설정 누락으로 보고 기동을 막는다.
            raise ValueError("GOOGLE_ALLOWLIST_FILE must point to an existing file")

        cookie_secret = os.environ.get("GOOGLE_COOKIE_SECRET", "")
        if len(cookie_secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"GOOGLE_COOKIE_SECRET must be at least {MIN_SECRET_LENGTH} characters")
        if cookie_secret == auth.jwt_secret:
            raise ValueError("GOOGLE_COOKIE_SECRET must differ from JWT_SECRET")
        if not auth.cookie_secure and app_env not in LOCAL_ENVS:
            raise ValueError("Google login requires AUTH_COOKIE_SECURE outside local-dev/test")

        endpoints: dict[str, object] = {}
        if test_idp:
            endpoints = {
                "authorization_endpoint": f"{test_idp}/authorize", "token_endpoint": f"{test_idp}/token",
                "jwks_uri": f"{test_idp}/jwks", "issuers": (test_idp,),
            }
        return cls(
            login_enabled=True, gate_enforced=gate_enforced, client_id=client_id, client_secret=client_secret,
            redirect_uri=redirect_uri, allowlist_file=allowlist_file, cookie_secret=cookie_secret, **endpoints,
        )


def _read_secret_file(path: str) -> str:
    if not path:
        raise ValueError("GOOGLE_CLIENT_SECRET_FILE is required when GOOGLE_LOGIN_ENABLED")
    try:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
    except OSError:
        raise ValueError("GOOGLE_CLIENT_SECRET_FILE is not readable") from None
    if not value or "\n" in value:
        raise ValueError("GOOGLE_CLIENT_SECRET_FILE must contain exactly one secret value")
    return value
