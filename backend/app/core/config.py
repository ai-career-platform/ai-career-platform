"""애플리케이션 설정. 환경변수만 읽으며 .env는 자동으로 로드하지 않습니다."""

import os
from dataclasses import dataclass, field
from functools import lru_cache

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict

APP_NAME = "ai-career-platform"
API_V1_PREFIX = "/api/v1"


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = field(repr=False)
    pool_size: int
    timeout: int

    @classmethod
    def from_env(cls) -> "DatabaseSettings | None":
        url = os.environ.get("DATABASE_URL")
        if not url:
            return None
        if not url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        try:
            options = conninfo_to_dict(url)
        except ProgrammingError:
            raise ValueError("DATABASE_URL is invalid") from None
        if not all(options.get(key) for key in ("host", "user", "dbname")):
            raise ValueError("DATABASE_URL requires a host, user and database")
        return cls(
            url=url,
            pool_size=env_int("DB_POOL_SIZE", 5, 1, 100),
            timeout=env_int("DB_TIMEOUT_SECONDS", 5, 1, 60),
        )


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_version: str
    database: DatabaseSettings | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.environ.get("APP_ENV", "local-dev"),
            app_version=os.environ.get("APP_VERSION", "0.1.0"),
            database=DatabaseSettings.from_env(),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
