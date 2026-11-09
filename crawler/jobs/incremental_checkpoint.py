"""T154 fixture-only incremental checkpoint and bounded retry decisions.

This module neither fetches URLs nor launches workers or modifies schedules.
A checkpoint advances only after the matching T151 keyword job is COMPLETED.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from uuid import UUID

from crawler.jobs.offline_recovery import retry_decision, RecoveryPolicy, RecoveryDecision


@dataclass(frozen=True)
class Candidate:
    external_id: str
    observed_at: datetime


def _aware(value):
    return (isinstance(value,datetime) and value.tzinfo is not None
            and value.utcoffset() is not None)


def select_incremental_candidates(*, items, checkpoint: datetime | None,
                                  lookback_days: int = 3) -> tuple[str, ...]:
    """Keep observed items from last success minus overlap, newest first.

    Data is supplied by caller as synthetic fixture observations; no network.
    An unobserved real-world update cannot be inferred from this filter.
    """
    if checkpoint is not None and not _aware(checkpoint):
        raise ValueError("Aware checkpoint required")
    if type(lookback_days) is not int or not 3 <= lookback_days <= 7:
        raise ValueError("lookback_days must be 3..7")
    threshold=(checkpoint.astimezone(timezone.utc)-timedelta(days=lookback_days)
               if checkpoint is not None else None)
    if not isinstance(items,(list,tuple)):
        raise ValueError("Items must be list or tuple")
    candidates=[]
    for item in items:
        if not isinstance(item,Candidate) or not _aware(item.observed_at):
            raise ValueError("Candidate and aware observed_at required")
        if not isinstance(item.external_id,str) or not item.external_id.isascii() or not item.external_id.isdigit() or not 1 <= len(item.external_id) <= 30:
            raise ValueError("Synthetic numeric posting ID required")
        instant=item.observed_at.astimezone(timezone.utc)
        if threshold is None or instant >= threshold:
            candidates.append((instant,item.external_id))
    candidates.sort(key=lambda pair:(-pair[0].timestamp(),pair[1]))
    unique=[]
    seen=set()
    for _,external_id in candidates:
        if external_id not in seen:
            unique.append(external_id)
            seen.add(external_id)
    return tuple(unique)


def retry_fixture_decision(*, status: str, error_code: str | None,
                           attempt: int, max_attempts: int = 3) -> RecoveryDecision:
    """Only a decision. No retry execution and never bypass 403/429/robots."""
    policy=RecoveryPolicy(max_attempts=max_attempts)
    if type(attempt) is not int or not 1 <= attempt <= max_attempts:
        raise ValueError("Invalid attempt")
    if status=="COMPLETED":
        return RecoveryDecision.NO_ACTION
    if status!="FAILED":
        return RecoveryDecision.WAIT
    return retry_decision(error_code=error_code,attempt=attempt,policy=policy)


class KeywordCheckpointStore:
    """Uses existing T151 job record as proof of completion.

    A conditional insert/upsert transaction prevents regressions and accidental
    advancement for PENDING/FAILED work. Requires manual 0007 migration.
    """
    def __init__(self,connection):
        self.connection=connection

    def read(self,keyword_id:int):
        if type(keyword_id) is not int or keyword_id < 1:
            raise ValueError("Positive keyword_id required")
        with self.connection.cursor() as cur:
            cur.execute("""SELECT last_success_at,last_completed_job_id
                FROM crawler_training.keyword_checkpoints WHERE keyword_id=%s""",
                (keyword_id,))
            return cur.fetchone()

    def mark_completed(self,*,keyword_id:int,job_id,completed_at:datetime) -> bool:
        if type(keyword_id) is not int or keyword_id < 1:
            raise ValueError("Positive keyword_id required")
        if not _aware(completed_at):
            raise ValueError("Aware completion time required")
        job_uuid=UUID(str(job_id))
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO crawler_training.keyword_checkpoints
                    (keyword_id,last_success_at,last_completed_job_id)
                    SELECT j.keyword_id,%s,j.job_id
                    FROM crawler_training.keyword_jobs j
                    WHERE j.job_id=%s AND j.keyword_id=%s AND j.status='COMPLETED'
                    AND j.ended_at IS NOT NULL AND j.ended_at<=%s
                    ON CONFLICT (keyword_id) DO UPDATE
                    SET last_success_at=EXCLUDED.last_success_at,
                        last_completed_job_id=EXCLUDED.last_completed_job_id,
                        updated_at=now()
                    WHERE crawler_training.keyword_checkpoints.last_success_at
                          < EXCLUDED.last_success_at
                    RETURNING keyword_id""",
                    (completed_at,job_uuid,keyword_id,completed_at))
                return cur.fetchone() is not None
