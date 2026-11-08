"""T154 STEP16: explicitly invoked, fixture-only retry-budget coordinator.

Distinct PostgreSQL connections are mandatory: reserve/record on attempt_db
commits independently of worker_db's atomic job/parse/checkpoint transaction.
No automatic retry, timer, dispatcher, live HTTP or system process execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from crawler.jobs.fixture_retry_budget import DurableFixtureAttemptStore
from crawler.jobs.fixture_worker import process_fixture_job
from crawler.jobs.offline_recovery import RETRYABLE_CODES, STOP_CODES


class AttemptUnavailable(RuntimeError):
    """Attempt already active, terminal, limited or job not eligible."""


class AttemptFinalizationRequired(RuntimeError):
    """Worker committed but attempt ledger could not be marked COMPLETED."""


@dataclass(frozen=True)
class ManualAttemptResult:
    job_id: UUID
    attempt: int
    status: str
    detail_count: int
    valid_count: int
    checkpoint_advanced: bool


def execute_manual_fixture_attempt(
    *, attempt_connection, worker_connection, files, job_id,
    failure_error_code: str | None = None,
) -> ManualAttemptResult:
    """Reserve one attempt then invoke the existing fixture worker once.

    On worker exception, record a caller-supplied, recognized error ONLY after
    the worker transaction has rolled back. Unknown failure stays IN_PROGRESS
    for manual diagnosis; original exception is always re-raised.

    A caller must not invoke this function inside another DB transaction.
    Both connections must be independently committed/autocommit-free and
    connected to the SAME dedicated crawler training database.
    """
    if attempt_connection is worker_connection:
        raise ValueError("Attempt and worker connections must be distinct")
    job_uuid = UUID(str(job_id))
    if failure_error_code is not None and failure_error_code not in RETRYABLE_CODES | STOP_CODES:
        raise ValueError("Unknown failure code: leave attempt IN_PROGRESS for review")

    budget = DurableFixtureAttemptStore(attempt_connection)
    reservation = budget.reserve(job_uuid)
    if reservation is None:
        raise AttemptUnavailable("No permitted manual fixture attempt")

    return _execute_reserved_fixture_attempt(
        attempt_connection=attempt_connection, worker_connection=worker_connection,
        files=files, job_id=job_uuid, reservation=reservation,
        failure_error_code=failure_error_code,
    )


def _execute_reserved_fixture_attempt(
    *, attempt_connection, worker_connection, files, job_id, reservation,
    failure_error_code=None,
):
    """Internal continuation after a durable atomic night/manual reservation."""
    job_uuid = UUID(str(job_id))
    budget = DurableFixtureAttemptStore(attempt_connection)
    if (reservation.job_id != job_uuid or
            budget.read(job_uuid) != (reservation.attempt, "IN_PROGRESS", None)):
        raise AttemptUnavailable("Reserved attempt is no longer active")
    try:
        outcome = process_fixture_job(
            connection=worker_connection, files=files, job_id=job_uuid
        )
    except Exception:
        # The fixture worker's transaction context has already unwound.
        # Do not hide the original error even if recording the failure fails.
        if failure_error_code is not None:
            try:
                budget.record_failure(
                    job_id=job_uuid, attempt=reservation.attempt,
                    error_code=failure_error_code,
                )
            except Exception:
                # An unrecorded interrupted attempt must remain IN_PROGRESS.
                pass
        raise

    if outcome.status != "COMPLETED":
        raise AttemptFinalizationRequired("Worker returned non-completed state")
    if not budget.record_success(job_id=job_uuid, attempt=reservation.attempt):
        raise AttemptFinalizationRequired(
            "Worker committed but attempt completion ledger is unresolved"
        )
    return ManualAttemptResult(
        job_id=job_uuid, attempt=reservation.attempt, status=outcome.status,
        detail_count=outcome.detail_count, valid_count=outcome.valid_count,
        checkpoint_advanced=outcome.checkpoint_advanced,
    )
