import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.core.config import APP_NAME, get_settings
from app.db import create_db_engine, create_session_factory
from app.routers import api_v1, system

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database = app.state.settings.database
    engine = create_db_engine(database) if database else None
    try:
        if engine is not None:
            app.state.db_session_factory = create_session_factory(engine)
        app.state.ready = True
        logger.info("application startup")
        yield
    finally:
        app.state.ready = False
        app.state.db_session_factory = None
        if engine is not None:
            await run_in_threadpool(engine.dispose)
        logger.info("application shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=APP_NAME, version=settings.app_version, lifespan=lifespan)
    app.state.ready = False
    app.state.settings = settings
    app.state.db_session_factory = None
    app.include_router(system.router)
    app.include_router(api_v1.api_router)
    return app


app = create_app()
