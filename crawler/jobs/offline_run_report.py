"""T64 STEP 04: sanitized, offline run report from T62/T63 worker result.

This builder records metadata only. No network, DB, file or real dispatcher.
"""
from __future__ import annotations

from datetime import datetime

from crawler.jobs.run_claims import InMemoryRunClaims
from crawler.jobs.run_state import RunStatus


_SUMMARY_KEYS = (
    "fetched", "normalized", "duplicates", "review", "invalid",
    "inserted", "updated", "unchanged", "db_writes", "external_requests",
)


def finish_from_worker(
    claims: InMemoryRunClaims,
    *,
    run_id: str,
    summary: dict,
    finished_at: datetime,
) -> dict:
    """Finish claimed run only if worker metadata is internally consistent.

    Partial success is retained; errors must be reported through a separate
    failure transition with a safe error_code (never raw exception text).
    """
    record = claims.get(run_id)
    if record is None:
        raise ValueError("Unknown run_id")
    if record.status != RunStatus.RUNNING:
        raise ValueError("Run must be RUNNING")
    if not isinstance(summary, dict):
        raise ValueError("Summary must be a dictionary")
    if summary.get("run_id") != run_id or summary.get("source_id") != record.source_id:
        raise ValueError("Worker run identity mismatch")
    if summary.get("mode") != "synthetic_fixture_only" or summary.get("external_requests") != 0:
        raise ValueError("Non-offline source results are not permitted")
    status = summary.get("status")
    if status not in {"SUCCEEDED", "PARTIAL"}:
        raise ValueError("Unsupported worker result status")

    counters = {}
    for key in _SUMMARY_KEYS:
        value = summary.get(key)
        if type(value) is not int or value < 0:
            raise ValueError("Missing or invalid result counter")
        counters[key] = value

    if counters["fetched"] != (
        counters["normalized"] + counters["invalid"]
        + counters["duplicates"] + counters["review"]
    ):
        raise ValueError("Worker input conservation rule violated")
    if counters["normalized"] != (
        counters["inserted"] + counters["updated"] + counters["unchanged"]
    ):
        raise ValueError("Worker result conservation rule violated")
    store = summary.get("store")
    if store == "in_memory_only" and counters["db_writes"] != 0:
        raise ValueError("In-memory worker must have zero DB writes")
    if store == "local_postgres" and counters["db_writes"] != (
        counters["inserted"] + counters["updated"]
    ):
        raise ValueError("Local DB write count does not match insert/update totals")
    if store not in {"in_memory_only", "local_postgres"}:
        raise ValueError("Unsupported result store")
    expected_status = (
        "SUCCEEDED" if not any(
            counters[key] for key in ("invalid", "duplicates", "review")
        ) else "PARTIAL"
    )
    if status != expected_status:
        raise ValueError("Worker status disagrees with quality counters")

    completed = claims.finish(
        run_id=run_id, target=RunStatus(status), at=finished_at,
        counters=counters,
    )
    return completed.snapshot()
