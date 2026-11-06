"""애플리케이션 설정.

환경변수만 읽습니다(.env 자동 로드 없음). 비밀값은 이 단계(T13)에서 다루지 않으며,
DB 접속 설정은 T14(DB 연결·세션 수명주기)에서 추가합니다.
"""

import os
from dataclasses import dataclass
from functools import lru_cache

APP_NAME = "ai-career-platform"
API_V1_PREFIX = "/api/v1"


@dataclass(frozen=True)
class Settings:
    app_env: str
    app_version: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=os.environ.get("APP_ENV", "local-dev"),
            app_version=os.environ.get("APP_VERSION", "0.1.0"),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
