import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.routers import crawler_admin_write
from starlette.concurrency import run_in_threadpool

from app.core.auth_config import AuthSettings, GoogleSettings
from app.core.google_gate import GoogleGateMiddleware
from app.core.config import API_V1_PREFIX, APP_NAME, get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.observability import AccessLogMiddleware, RequestMetrics, install_uvicorn_access_filter
from app.core.rate_limit import AttemptLimiter
from app.core.request_id import RequestIdMiddleware
from app.db import create_db_engine, create_session_factory
from app.routers import api_v1, company_accounts, company_postings, job_applications, job_postings, notifications, personal_data_requests, public_portfolio, system
from app.services.behavior_events import BehaviorEventSettings
from app.routers import skill_suggest
from app.routers import google_auth
from app.services.google_oauth import GoogleRuntime

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
    # #328 Google 로그인·게이트: 기본 꺼짐. 켜면 설정 검증에 실패할 때 기동을 막는다(fail closed).
    app.state.google_settings = GoogleSettings.from_env(settings.app_env, app.state.auth_settings)
    app.state.google = GoogleRuntime.build(app.state.google_settings) if app.state.google_settings.login_enabled else None
    app.state.attempt_limiter = AttemptLimiter()
    app.state.behavior_event_settings = BehaviorEventSettings.from_env()
    # T112: 요청 로그·지표(안쪽) → request_id(바깥). add_middleware 는 나중에 넣은 것이 바깥이다.
    app.state.request_metrics = RequestMetrics()
    if app.state.google_settings.gate_enforced:  # 가장 안쪽: 요청 ID·접근 로그가 401 에도 남는다
        app.add_middleware(GoogleGateMiddleware, exempt_paths=google_auth.GATE_EXEMPT_PATHS,
                           cookie_name=google_auth.GATE_COOKIE)
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
    if settings.notifications_api:  # T97: 미승인·기본 비활성 (migration 0005 필요)
        app.include_router(notifications.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.crawler_admin_write_api:  # T155: 기본 비활성
        app.include_router(crawler_admin_write.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.company_accounts_api:  # T123: 기본 비활성
        app.include_router(company_accounts.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.company_postings_api:  # T126: 기본 비활성
        app.include_router(company_postings.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.skill_autocomplete_api:  # T139: 기본 비활성 (T137 별칭 표 미승인)
        app.include_router(skill_suggest.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.public_portfolio_api:  # T129: 기본 비활성
        app.include_router(public_portfolio.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if settings.personal_data_requests_api:  # T142: 기본 비활성
        app.include_router(personal_data_requests.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    if app.state.google_settings.login_enabled:  # #328: 기본 비활성 (꺼져 있으면 Google 경로 404)
        app.include_router(google_auth.router, prefix=API_V1_PREFIX, responses=api_v1.API_V1_RESPONSES)
    return app


app = create_app()
