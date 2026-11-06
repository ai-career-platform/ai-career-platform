from typing import Annotated

from fastapi import APIRouter, Depends
from psycopg import Connection

from app.core.config import Settings, get_settings
from app.db import get_db
from app.schemas.system import HealthResponse, VersionResponse
from app.services import system as system_service

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return system_service.get_health()


@router.get("/health/db")
def database_health(connection: Annotated[Connection, Depends(get_db)]) -> dict[str, str]:
    connection.execute("SELECT 1")
    return {"status": "ok"}


@router.get("/version", response_model=VersionResponse)
def version(settings: Annotated[Settings, Depends(get_settings)]) -> VersionResponse:
    return system_service.get_version(settings)
