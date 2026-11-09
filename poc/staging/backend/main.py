import logging
import os

import psycopg
from fastapi import FastAPI, HTTPException

if os.environ.get('ENABLE_SERVICE_API') == '1':
    from app.main import create_app
    from fastapi.openapi.docs import get_swagger_ui_html
    from fastapi.exception_handlers import http_exception_handler
    from starlette.exceptions import HTTPException as StarletteHTTPException

    # One application/lifespan owns T14 sessions and T15 authentication.
    app = create_app()
    app.routes[:] = [r for r in app.routes if r.path not in {
        '/health', '/version', '/health/db', '/docs', '/docs/oauth2-redirect', '/redoc'}]
    service_http_error = app.exception_handlers[StarletteHTTPException]

    @app.exception_handler(StarletteHTTPException)
    async def staging_http_error(request, exc):
        if request.url.path.startswith('/api/v1/'):
            return await service_http_error(request, exc)
        return await http_exception_handler(request, exc)

    @app.get('/docs', include_in_schema=False)
    def staging_docs():
        return get_swagger_ui_html(openapi_url='/api/openapi.json', title=app.title + ' - Swagger UI')

    original_openapi = app.openapi

    def external_openapi():
        spec = original_openapi()
        # The proxy retains /api/v1 for service routes and strips /api for PoC.
        # Document their actual external URLs with a single origin-relative server.
        spec['paths'] = {path if path.startswith('/api/') else '/api' + path: value
                         for path, value in spec['paths'].items()}
        spec['servers'] = [{'url': '/'}]
        return spec

    app.openapi = external_openapi
else:
    app = FastAPI(root_path="/api")
logger = logging.getLogger(__name__)

# Integrated image only. The original standalone PoC image remains supported.
if os.environ.get('ENABLE_CRAWLER_API') == '1':
    from backend import training_jobs_api as training
    app.add_api_route('/jobs', training.get_jobs, response_model=list[training.TrainingJob])
    app.add_api_route('/jobs/collected', training.get_collected_jobs, response_model=list[training.CollectedJob])
    app.add_api_route('/training', training.training_page, include_in_schema=False)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ai-career-backend"}


@app.get("/version")
def version() -> dict[str, str]:
    return {
        "application": "ai-career-platform",
        "environment": os.environ.get("APP_ENV", "staging-poc"),
        "version": os.environ.get("APP_VERSION", "0.1.0"),
    }


@app.get("/health/db")
def health_db() -> dict[str, str]:
    try:
        with psycopg.connect(
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"],
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            connect_timeout=3,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise psycopg.DatabaseError("Unexpected database health check result")
    except (psycopg.Error, KeyError) as exc:
        logger.warning("Database health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "service": "ai-career-database"}
