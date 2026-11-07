"""Standalone educational read-only API for synthetic crawler records.

Run from repository root:
    py -3.12 -m uvicorn backend.training_jobs_api:app --host 127.0.0.1 --port 8001

Never mounted into production backend/app/main.py. Never performs crawling.
"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from crawler.storage.postgres import connect_local_training_db, validate_local_dsn

app = FastAPI(title="Synthetic Crawler Training API", version="0.1.0")


class TrainingJob(BaseModel):
    external_posting_id: str
    source_code: str
    title: str
    company_name: str
    location_text: str | None = None
    employment_type: str | None = None


def read_training_jobs(*, limit: int) -> list[dict]:
    """SELECT only; require the separately provisioned, isolated training DB."""
    dsn = os.environ.get("CRAWLER_LOCAL_DATABASE_URL", "")
    validate_local_dsn(dsn)
    # psycopg connection is closed even if SELECT or JSON decoding fails.
    with connect_local_training_db(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT payload->>'external_posting_id',
                          payload->>'source_code',
                          payload->>'title',
                          payload->>'company_name',
                          payload->>'location_text',
                          payload->>'employment_type'
                   FROM crawler_training.postings
                   WHERE source_code = %s
                     AND external_posting_id LIKE %s
                   ORDER BY external_posting_id LIMIT %s""",
                ("jobkorea", "SYNTH-%", limit),
            )
            return [
                {
                    "external_posting_id": row[0],
                    "source_code": row[1],
                    "title": row[2],
                    "company_name": row[3],
                    "location_text": row[4],
                    "employment_type": row[5],
                }
                for row in cursor.fetchall()
            ]


@app.get("/jobs", response_model=list[TrainingJob], tags=["training"])
def get_jobs(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    try:
        return read_training_jobs(limit=limit)
    except Exception:
        # Avoid leaking DSN, DB/SQL details or environment secrets to clients.
        raise HTTPException(status_code=503, detail="Training database unavailable") from None
