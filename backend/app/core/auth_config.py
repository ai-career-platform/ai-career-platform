"""인증(T15) 설정. 환경변수만 읽습니다.

- JWT 서명은 HS256(대칭키) — API_CONTRACT 미결 T06-1을 T15에서 HS256으로 결정.
  단일 백엔드 서비스만 토큰을 검증하므로 키 배포가 단순한 대칭키를 쓴다.
- `JWT_SECRET`이 없으면 local-dev/test에서만 프로세스마다 임의 키를 만든다(재시작 시 토큰 무효).
  그 외 환경에서는 기동을 막는다.
"""

import logging
import os
import secrets
from dataclasses import dataclass, field

from app.core.config import env_int

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
        )
