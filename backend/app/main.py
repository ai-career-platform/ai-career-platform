import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.core.config import APP_NAME, get_settings
from app.db import create_pool
from app.routers import api_v1, system

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database = app.state.settings.database
    pool = create_pool(database) if database else None
    try:
        if pool is not None:
            pool.open()
        app.state.db_pool = pool
        app.state.ready = True
        logger.info("application startup")
        yield
    finally:
        app.state.ready = False
        app.state.db_pool = None
        if pool is not None:
            await run_in_threadpool(pool.close)
        logger.info("application shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=APP_NAME, version=settings.app_version, lifespan=lifespan)
    app.state.ready = False
    app.state.settings = settings
    app.state.db_pool = None
    app.include_router(system.router)
    app.include_router(api_v1.api_router)
    return app


app = create_app()
