"""T154 STEP14: durable retry budget for *manual fixture* job execution.

The caller MUST use an independent, committed connection for this store.
The actual fixture worker uses a DIFFERENT connection and transaction. A
worker rollback must not undo its previously reserved attempt. No scheduling,
timeouts, sleeps, process launching, HTTP requests or automatic recovery.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from crawler.jobs.offline_recovery import (
    RecoveryDecision, RecoveryPolicy, retry_decision,
)


@dataclass(frozen=True)
class AttemptReservation:
    job_id: UUID
    attempt: int


class DurableFixtureAttemptStore:
    def __init__(self, connection):
        self.connection = connection

    def reserve(self, job_id) -> AttemptReservation | None:
        """Claim one budget slot only when job PENDING and attempt RETRYABLE.

        The initial request is INSERT; retry uses atomic ON CONFLICT UPDATE.
        No stale IN_PROGRESS auto-reclaim: interruption needs inspection.
        """
        job_id = UUID(str(job_id))
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""INSERT INTO crawler_training.fixture_job_attempts
                    (job_id,attempt_count,state)
                    SELECT j.job_id,1,'IN_PROGRESS'
                    FROM crawler_training.keyword_jobs j
                    JOIN crawler_training.fixture_job_payloads p ON p.job_id=j.job_id
                    WHERE j.job_id=%s AND j.status='PENDING'
                    ON CONFLICT (job_id) DO UPDATE
                    SET attempt_count=crawler_training.fixture_job_attempts.attempt_count+1,
                        state='IN_PROGRESS',last_error_code=NULL,updated_at=now()
                    WHERE crawler_training.fixture_job_attempts.state='RETRYABLE'
                      AND crawler_training.fixture_job_attempts.attempt_count<3
                      AND EXISTS (
                        SELECT 1 FROM crawler_training.keyword_jobs j2
                        WHERE j2.job_id=EXCLUDED.job_id AND j2.status='PENDING'
                      )
                    RETURNING attempt_count""", (job_id,))
                row=cur.fetchone()
                return AttemptReservation(job_id,row[0]) if row else None

    def record_failure(self, *, job_id, attempt:int, error_code:str) -> bool:
        """Classify a failed *completed/rolled-back* worker call.

        Requires a separate connection and explicit error code; does not
        restart a worker. A database exception must never be hidden by the
        caller: unclassified interruption stays IN_PROGRESS for inspection.
        """
        job_id=UUID(str(job_id))
        if type(attempt) is not int or not 1<=attempt<=3:
            raise ValueError("attempt outside 1..3")
        if not isinstance(error_code,str) or not 1<=len(error_code)<=64:
            raise ValueError("invalid error code")
        decision=retry_decision(error_code=error_code,attempt=attempt,
                                policy=RecoveryPolicy(max_attempts=3))
        state=("RETRYABLE" if decision==RecoveryDecision.RETRY_ELIGIBLE
               else "STOPPED")
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""UPDATE crawler_training.fixture_job_attempts a
                    SET state=%s,last_error_code=%s,updated_at=now()
                    WHERE a.job_id=%s AND a.attempt_count=%s
                      AND a.state='IN_PROGRESS'
                      AND EXISTS (SELECT 1 FROM crawler_training.keyword_jobs j
                                  WHERE j.job_id=a.job_id AND j.status='PENDING')
                    RETURNING job_id""", (state,error_code,job_id,attempt))
                return cur.fetchone() is not None

    def record_success(self, *, job_id, attempt:int) -> bool:
        """Mark attempt complete only after worker committed COMPLETED."""
        job_id=UUID(str(job_id))
        if type(attempt) is not int or not 1<=attempt<=3:
            raise ValueError("attempt outside 1..3")
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("""UPDATE crawler_training.fixture_job_attempts a
                    SET state='COMPLETED',last_error_code=NULL,updated_at=now()
                    WHERE a.job_id=%s AND a.attempt_count=%s
                      AND a.state='IN_PROGRESS'
                      AND EXISTS (SELECT 1 FROM crawler_training.keyword_jobs j
                                  WHERE j.job_id=a.job_id AND j.status='COMPLETED')
                    RETURNING job_id""", (job_id,attempt))
                return cur.fetchone() is not None

    def read(self,job_id):
        job_id=UUID(str(job_id))
        with self.connection.cursor() as cur:
            cur.execute("""SELECT attempt_count,state,last_error_code
                FROM crawler_training.fixture_job_attempts WHERE job_id=%s""",
                (job_id,))
            return cur.fetchone()
