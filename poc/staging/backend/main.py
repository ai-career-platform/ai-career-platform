import logging
import os

import psycopg
from fastapi import FastAPI, HTTPException

app = FastAPI(root_path="/api")
logger = logging.getLogger(__name__)


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
