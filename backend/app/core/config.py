"""애플리케이션 설정. 환경변수만 읽으며 .env는 자동으로 로드하지 않습니다."""

import os
import re
from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

# '%' 뒤에 16진수 두 자리가 오지 않는 잘못된 퍼센트 인코딩 (예: '%xx')
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")

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
        # SQLAlchemy URL 파서로 검사한다 (DB 드라이버 라이브러리를 직접 참조하지 않음).
        # 오류 메시지에는 URL 값(자격정보)을 넣지 않는다.
        if _BAD_PERCENT.search(url):
            raise ValueError("DATABASE_URL is invalid")
        try:
            parsed = make_url(url)
        except (ArgumentError, ValueError):
            raise ValueError("DATABASE_URL is invalid") from None
        if not (parsed.host and parsed.username and parsed.database):
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
    # T99: T98 고급 검색 계약(PROPOSED)을 켬. 기본 꺼짐 — PM 승인 전 운영·Staging 에서 켜지 않음
    job_search_advanced: bool = False
    # T102: 개인 지원 기록 API (미승인·기본 비활성)
    job_applications_api: bool = False
    # T123: 기업 등록·초대 API (T121·T122 미승인·기본 비활성, DB 저장소 없음 → 켜도 503)
    company_accounts_api: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.environ.get("APP_ENV", "local-dev"),
            app_version=os.environ.get("APP_VERSION", "0.1.0"),
            database=DatabaseSettings.from_env(),
            job_search_advanced=os.environ.get("JOB_SEARCH_ADVANCED", "false").lower() == "true",
            job_applications_api=os.environ.get("JOB_APPLICATIONS_API", "false").lower() == "true",
            company_accounts_api=os.environ.get("COMPANY_ACCOUNTS_API", "false").lower() == "true",
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
