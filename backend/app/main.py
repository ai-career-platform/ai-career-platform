import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.core.auth_config import AuthSettings
from app.core.config import API_V1_PREFIX, APP_NAME, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.rate_limit import AttemptLimiter
from app.core.request_id import RequestIdMiddleware
from app.db import create_db_engine, create_session_factory
from app.routers import api_v1, job_applications, system
from app.services.behavior_events import BehaviorEventSettings

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
    app.state.auth_settings = AuthSettings.from_env(settings.app_env)
    app.state.attempt_limiter = AttemptLimiter()
    app.state.behavior_event_settings = BehaviorEventSettings.from_env()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(system.router)
    app.include_router(api_v1.api_router)
    if settings.job_applications_api:  # T102: 제안 표가 있는 일회용 DB 에서만(기본 꺼짐)
        app.include_router(job_applications.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    return app


app = create_app()
