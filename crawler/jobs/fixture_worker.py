"""T154 STEP09: explicit fixture-only job processor, no dispatcher or HTTP.

A caller invokes this directly with a dedicated crawler training connection and
T152 content-addressed store. The entire DB flow is one transaction; failures
leave the job pending and checkpoint unchanged for deliberate retry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from crawler.adapters.jobkorea_html_offline import _source_id
from crawler.jobs.fixture_payloads import FixturePayloadStore
from crawler.jobs.incremental_checkpoint import KeywordCheckpointStore
from crawler.jobs.keyword_management import KeywordStore
from crawler.jobs.raw_parse_ledger import RawParseLedger

@dataclass(frozen=True)
class FixtureExecution:
    job_id: UUID
    status: str
    detail_count: int
    valid_count: int
    checkpoint_advanced: bool


def process_fixture_job(*, connection, files, job_id) -> FixtureExecution:
    """Consume ONLY persisted synthetic detail Raw for a frozen job payload.

    Never starts Scheduler, runs, subprocess, HTTP or Timer. All Raw metadata
    must already exist, have matching job_id and synthetic mode. A failed or
    incomplete batch rolls back all database changes and remains PENDING.
    """
    job_id=UUID(str(job_id))
    with connection.transaction():
        with connection.cursor() as cur:
            # Fail fast when another process already owns this job row. Runtime\n            # has UPDATE on keyword_jobs, unlike raw_artifacts.
            cur.execute("""SELECT keyword_id,status
                FROM crawler_training.keyword_jobs WHERE job_id=%s FOR UPDATE NOWAIT""",
                (job_id,))
            job=cur.fetchone()
            if job is None:
                raise ValueError("Unknown fixture job")
            keyword_id,status=job
            if status=="COMPLETED":
                return FixtureExecution(job_id,"COMPLETED",0,0,False)
            if status!="PENDING":
                raise ValueError("Fixture job not PENDING")

            payload=FixturePayloadStore(connection).read(job_id)
            if payload.keyword_id != keyword_id:
                raise ValueError("Job keyword mismatch")
            cur.execute("""SELECT artifact_id,source_url
                FROM crawler_training.raw_artifacts
                WHERE job_id=%s AND keyword_id=%s AND kind='detail'
                  AND mode='synthetic_fixture_only'
                ORDER BY artifact_id""", (job_id,keyword_id))
            raw_rows=cur.fetchall()
            expected=set(payload.posting_ids)
            found={}
            for artifact_id,url in raw_rows:
                external_id=_source_id(url)
                if external_id not in expected or external_id in found:
                    raise ValueError("Unmatched or duplicate fixture Raw")
                found[external_id]=artifact_id
            if set(found)!=expected:
                raise ValueError("Incomplete fixture Raw")

        jobs=KeywordStore(connection)
        if not jobs.transition(job_id,"PENDING","RUNNING"):
            raise ValueError("Failed to claim fixture job")
        valid=0
        ledger=RawParseLedger(connection,files)
        for external_id in payload.posting_ids:
            result=ledger.process(found[external_id])
            if result.status!="VALID":
                raise ValueError("Invalid fixture detail")
            valid+=1
        if not jobs.transition(job_id,"RUNNING","FETCHED"):
            raise ValueError("Fixture transition to FETCHED failed")
        if not jobs.transition(job_id,"FETCHED","COMPLETED"):
            raise ValueError("Fixture completion failed")
        # Read DB-issued completion time; Python timestamps taken before a
        # SQL ended_at=now() transition would precede ended_at and fail gate.
        with connection.cursor() as cur:
            cur.execute("""SELECT ended_at FROM crawler_training.keyword_jobs
                WHERE job_id=%s AND status='COMPLETED'""", (job_id,))
            row=cur.fetchone()
            if row is None or row[0] is None:
                raise ValueError("Missing completed timestamp")
            completed_at=row[0]
        advanced=KeywordCheckpointStore(connection).mark_completed(
            keyword_id=keyword_id,job_id=job_id,completed_at=completed_at)
        return FixtureExecution(job_id,"COMPLETED",len(found),valid,advanced)
