"""T154 STEP07: persist immutable fixture batch payloads by T151 job ID.

No worker dispatch, HTTP, schedules, timer, DDL, posting mutation or checkpoint
advance. Existing T151 job idempotency and T154 planning are reused.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from crawler.jobs.fixture_keyword_jobs import create_fixture_keyword_jobs


class FixturePayloadConflict(ValueError):
    """A reused job ID has a different frozen set/order of synthetic IDs."""


@dataclass(frozen=True)
class StoredFixtureJob:
    job_id: UUID
    keyword_id: int
    posting_ids: tuple[str, ...]
    idempotency_key: str


class FixturePayloadStore:
    def __init__(self, connection):
        self.connection=connection

    def register(self, *, job_id, keyword_id: int, posting_ids) -> None:
        """One immutable payload, idempotent only when IDs match exactly."""
        job_id=UUID(str(job_id))
        if type(keyword_id) is not int or keyword_id <= 0:
            raise ValueError("Positive keyword_id required")
        if not isinstance(posting_ids,(tuple,list)) or not 1 <= len(posting_ids) <= 10:
            raise ValueError("Fixture payload size must be 1..10")
        ids=tuple(posting_ids)
        if len(set(ids)) != len(ids) or any(
            not isinstance(x,str) or not x.isascii() or not x.isdigit()
            or not 1 <= len(x) <= 30 for x in ids
        ):
            raise ValueError("Invalid or duplicate synthetic posting IDs")
        with self.connection.cursor() as cur:
            cur.execute("""INSERT INTO crawler_training.fixture_job_payloads
                (job_id,keyword_id,posting_ids)
                SELECT j.job_id,j.keyword_id,%s::text[]
                FROM crawler_training.keyword_jobs j
                WHERE j.job_id=%s AND j.keyword_id=%s
                ON CONFLICT (job_id) DO NOTHING
                RETURNING job_id""", (list(ids),job_id,keyword_id))
            if cur.fetchone() is not None:
                return
            cur.execute("""SELECT keyword_id,posting_ids
                FROM crawler_training.fixture_job_payloads
                WHERE job_id=%s""",(job_id,))
            row=cur.fetchone()
            if row is None or row[0] != keyword_id or tuple(row[1]) != ids:
                raise FixturePayloadConflict("Job payload missing or changed")

    def read(self, job_id) -> StoredFixtureJob:
        job_id=UUID(str(job_id))
        with self.connection.cursor() as cur:
            cur.execute("""SELECT p.job_id,p.keyword_id,p.posting_ids,j.idempotency_key
                FROM crawler_training.fixture_job_payloads p
                JOIN crawler_training.keyword_jobs j ON j.job_id=p.job_id
                WHERE p.job_id=%s""",(job_id,))
            row=cur.fetchone()
        if row is None:
            raise ValueError("Unknown fixture payload")
        return StoredFixtureJob(row[0],row[1],tuple(row[2]),row[3])


def persist_fixture_keyword_jobs(*, connection, keyword_id: int,
                                 observations, now,
                                 lookback_days: int = 3, batch_size: int = 5):
    """Atomically create T151 job metadata and freeze its fixture IDs.

    Replaying same job key with changed candidate IDs fails closed, rather than
    silently assigning an old job to a different set of synthetic postings.
    """
    # First-stage validation and fixture window checks are in existing planner.
    with connection.transaction():
        jobs=create_fixture_keyword_jobs(connection=connection,keyword_id=keyword_id,
            observations=observations,now=now,lookback_days=lookback_days,
            batch_size=batch_size)
        payloads=FixturePayloadStore(connection)
        for planned in jobs:
            payloads.register(job_id=planned.job_id,
                keyword_id=planned.batch.keyword_id,
                posting_ids=planned.batch.posting_ids)
    return jobs
