import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import APP_NAME, get_settings
from app.routers import api_v1, system

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 시작/종료 시 자원(DB 풀 등)을 여는 자리. DB 연결은 T14에서 추가합니다.
    app.state.ready = True
    logger.info("application startup")
    yield
    app.state.ready = False
    logger.info("application shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=APP_NAME, version=settings.app_version, lifespan=lifespan)
    app.state.ready = False
    app.include_router(system.router)
    app.include_router(api_v1.api_router)
    return app


app = create_app()
