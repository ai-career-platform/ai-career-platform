"""Standalone educational read-only API for synthetic crawler records.

Run from repository root:
    py -3.12 -m uvicorn backend.training_jobs_api:app --host 127.0.0.1 --port 8001

Never mounted into production backend/app/main.py. Never performs crawling.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from crawler.storage.postgres import connect_local_training_db, validate_local_dsn
from crawler.storage.staging import database_url, using_staging, validate_staging_dsn, connect_staging_db


def _validate_database(dsn):
    (validate_staging_dsn if using_staging() else validate_local_dsn)(dsn)


def _connect_database(dsn):
    return (connect_staging_db if using_staging() else connect_local_training_db)(dsn)

app = FastAPI(title="Synthetic Crawler Training API", version="0.1.0")


class TrainingJob(BaseModel):
    external_posting_id: str
    source_code: str
    title: str
    company_name: str
    location_text: str | None = None
    employment_type: str | None = None


class CollectedJob(TrainingJob):
    source_url: str
    collected_at: str
    evidence: str


def read_collected_jobs(*, limit, title=None, location=None, employment_type=None):
    dsn = database_url()
    _validate_database(dsn)
    where = ['source_code IN (%s, %s)']
    params = ['jobkorea_live', 'jobkorea_imported']
    for value, expression in (
        (title, "strpos(lower(payload->>'title'), lower(%s)) > 0"),
        (location, "strpos(payload->>'location_text', %s) = 1"),
        (employment_type, "payload->>'employment_type' = %s"),
    ):
        if value:
            where.append(expression)
            params.append(value)
    params.append(limit)
    with _connect_database(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT payload, updated_at::text FROM crawler_training.postings WHERE '
                           + ' AND '.join(where) + ' ORDER BY updated_at DESC, external_posting_id LIMIT %s', tuple(params))
            return [{**payload, 'collected_at': collected_at,
                     'evidence': 'live_http' if payload['source_code'] == 'jobkorea_live' else 'imported_html'}
                    for payload, collected_at in cursor.fetchall()]


@app.get('/jobs/collected', response_model=list[CollectedJob], tags=['training'])
def get_collected_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    title: str | None = Query(default=None, min_length=1, max_length=80),
    location: str | None = Query(default=None, min_length=1, max_length=40),
    employment_type: str | None = Query(default=None, pattern='^(full_time|contract|intern|part_time)$'),
):
    try:
        return read_collected_jobs(limit=limit, title=title, location=location, employment_type=employment_type)
    except Exception:
        raise HTTPException(status_code=503, detail='Training database unavailable') from None


def read_training_jobs(
    *, limit: int, title: str | None = None, location: str | None = None,
    employment_type: str | None = None,
) -> list[dict]:
    """SELECT only; require the separately provisioned, isolated training DB."""
    dsn = database_url()
    _validate_database(dsn)
    # psycopg connection is closed even if SELECT or JSON decoding fails.
    with _connect_database(dsn) as connection:
        with connection.cursor() as cursor:
            # SQL parameters bind all user-provided filter values.
            where = ["source_code = %s", "external_posting_id LIKE %s"]
            params: list[str | int] = ["jobkorea", "SYNTH-%"]
            if title:
                where.append("strpos(lower(payload->>'title'), lower(%s)) > 0")
                params.append(title)
            if location:
                where.append("payload->>'location_text' = %s")
                params.append(location)
            if employment_type:
                where.append("payload->>'employment_type' = %s")
                params.append(employment_type)
            sql = (
                "SELECT payload->>'external_posting_id', "
                "payload->>'source_code', payload->>'title', "
                "payload->>'company_name', payload->>'location_text', "
                "payload->>'employment_type' "
                "FROM crawler_training.postings WHERE "
                + " AND ".join(where)
                + " ORDER BY external_posting_id LIMIT %s"
            )
            params.append(limit)
            cursor.execute(sql, tuple(params))
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
def get_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    title: str | None = Query(default=None, min_length=1, max_length=80),
    location: str | None = Query(default=None, min_length=1, max_length=40),
    employment_type: str | None = Query(default=None, pattern="^(full_time|contract)$"),
) -> list[dict]:
    try:
        filters = {}
        if title is not None:
            filters["title"] = title
        if location is not None:
            filters["location"] = location
        if employment_type is not None:
            filters["employment_type"] = employment_type
        return read_training_jobs(limit=limit, **filters)
    except Exception:
        raise HTTPException(status_code=503, detail="Training database unavailable") from None


# Same-origin training page; no CORS changes or production frontend integration.
_TRAINING_PAGE = Path(__file__).resolve().parent / "training_frontend" / "index.html"


@app.get("/training", include_in_schema=False)
def training_page() -> FileResponse:
    return FileResponse(_TRAINING_PAGE, media_type="text/html", headers={
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    })
