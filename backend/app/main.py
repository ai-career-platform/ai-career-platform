import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from app.core.auth_config import AuthSettings
from app.core.config import API_V1_PREFIX, APP_NAME, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.observability import AccessLogMiddleware, RequestMetrics, install_uvicorn_access_filter
from app.core.rate_limit import AttemptLimiter
from app.core.request_id import RequestIdMiddleware
from app.db import create_db_engine, create_session_factory
from app.routers import api_v1, company_accounts, company_postings, job_applications, job_postings, system
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
    # T112: 요청 로그·지표(안쪽) → request_id(바깥). add_middleware 는 나중에 넣은 것이 바깥이다.
    app.state.request_metrics = RequestMetrics()
    app.add_middleware(AccessLogMiddleware, metrics=app.state.request_metrics)
    app.add_middleware(RequestIdMiddleware)
    install_uvicorn_access_filter()
    register_exception_handlers(app)
    app.include_router(system.router)
    app.include_router(api_v1.api_router)
    # 공고 목록: 기본 T18 확정 계약, JOB_SEARCH_ADVANCED=true 일 때만 T98 제안 계약(T99)
    list_router = job_postings.advanced_list_router if settings.job_search_advanced else job_postings.legacy_list_router
    app.include_router(list_router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.job_applications_api:  # T102: 미승인·기본 비활성
        app.include_router(job_applications.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.company_accounts_api:  # T123: 기본 비활성
        app.include_router(company_accounts.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.company_postings_api:  # T126: 기본 비활성
        app.include_router(company_postings.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    return app


app = create_app()
