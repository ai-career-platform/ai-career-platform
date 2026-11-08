"""T154 STEP04: materialize offline fixture batch plans as T151 metadata jobs.

No worker claims, network activity, scheduler writes, or timer activation.
The supplied observations must be synthetic. Persistent jobs are *metadata
only*; no posting IDs are persisted in the existing keyword_jobs table.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from crawler.jobs.incremental_checkpoint import (
    KeywordCheckpointStore, select_incremental_candidates,
)
from crawler.jobs.incremental_fixture_plan import (
    PlannedBatch, in_fixture_window, plan_fixture_batches,
)
from crawler.jobs.keyword_management import KeywordStore


@dataclass(frozen=True)
class PlannedJob:
    batch: PlannedBatch
    job_id: object


def create_fixture_keyword_jobs(
    *,
    connection,
    keyword_id: int,
    observations,
    now: datetime,
    lookback_days: int = 3,
    batch_size: int = 5,
) -> tuple[PlannedJob, ...]:
    """Filter, chunk and create idempotent T151 PENDING jobs, without executing.

    An inactive keyword causes KeywordStore.create_job to fail closed.
    No checkpoints advance here; only a later COMPLETED job may advance one.
    """
    if type(keyword_id) is not int or keyword_id <= 0:
        raise ValueError("Positive keyword_id required")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware now required")
    if type(lookback_days) is not int or not 3 <= lookback_days <= 7:
        raise ValueError("lookback_days must be 3..7")
    if type(batch_size) is not int or not 1 <= batch_size <= 10:
        raise ValueError("batch_size must be 1..10")

    # Don't even query DB outside the permitted fixture-only KST window.
    if not in_fixture_window(now):
        return ()

    # Validate all supplied observations before attempting a DB write.
    # A future checkpoint can filter observations, but does not authorize
    # real-world fetching or imply an observed listing is up-to-date.
    ids_for_validation = select_incremental_candidates(
        items=observations, checkpoint=None, lookback_days=lookback_days
    )
    if not ids_for_validation:
        return ()

    checkpoint_row = KeywordCheckpointStore(connection).read(keyword_id)
    checkpoint = checkpoint_row[0] if checkpoint_row else None
    candidates = select_incremental_candidates(
        items=observations, checkpoint=checkpoint, lookback_days=lookback_days
    )
    batches = plan_fixture_batches(
        keyword_id=keyword_id, posting_ids=candidates, now=now,
        checkpoint=checkpoint, lookback_days=lookback_days, batch_size=batch_size
    )
    if not batches:
        return ()
    keyword_store = KeywordStore(connection)
    # Nested transactions in psycopg use savepoints. A failure creating
    # any batch rolls back earlier metadata jobs in this call as well.
    with connection.transaction():
        return tuple(PlannedJob(batch, keyword_store.create_job(
            keyword_id, batch.idempotency_key
        )) for batch in batches)
