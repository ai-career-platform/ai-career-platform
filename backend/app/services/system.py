from app.core.config import APP_NAME, Settings
from app.schemas.system import HealthResponse, VersionResponse


def get_health() -> HealthResponse:
    return HealthResponse(status="ok", service="ai-career-backend")


def get_version(settings: Settings) -> VersionResponse:
    return VersionResponse(
        application=APP_NAME,
        environment=settings.app_env,
        version=settings.app_version,
    )
