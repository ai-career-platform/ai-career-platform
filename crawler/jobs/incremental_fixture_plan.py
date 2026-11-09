"""T154 pure fixture-only incremental batch planner.

No DB, HTTP, worker, dispatcher, schedules or runtime activation. Existing
T151 job idempotency and T64 dispatcher can consume the planned slots later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
WINDOW_START = time(21, 0)
WINDOW_END = time(8, 0)


@dataclass(frozen=True)
class PlannedBatch:
    keyword_id: int
    slot: int
    posting_ids: tuple[str, ...]
    idempotency_key: str


def in_fixture_window(now: datetime, *, start: time = WINDOW_START,
                      end: time = WINDOW_END) -> bool:
    """True for start-inclusive, end-exclusive KST overnight window."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone-aware datetime required")
    if not isinstance(start, time) or not isinstance(end, time) or start == end:
        raise ValueError("Distinct local start/end times required")
    if start.tzinfo is not None or end.tzinfo is not None:
        raise ValueError("Use naive KST wall-clock time")
    clock = now.astimezone(KST).time().replace(tzinfo=None)
    return start <= clock < end if start < end else clock >= start or clock < end


def plan_fixture_batches(*, keyword_id: int, posting_ids, now: datetime,
                         checkpoint: datetime | None = None,
                         lookback_days: int = 3, batch_size: int = 5,
                         window_required: bool = True) -> tuple[PlannedBatch, ...]:
    """Offline deterministic idempotent slots for explicitly supplied synthetic IDs.

    The caller must preselect recent/new fixture IDs; this function never
    discovers pages, guesses timestamps, or issues network requests.
    checkpoint is validated here and reserved for the separate DB checkpoint
    adapter. It is not used to silently discard caller-supplied fixture IDs.
    """
    if type(keyword_id) is not int or keyword_id < 1:
        raise ValueError("Positive keyword_id required")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Aware now required")
    if checkpoint is not None and (not isinstance(checkpoint, datetime)
                                   or checkpoint.tzinfo is None or checkpoint.utcoffset() is None
                                   or checkpoint > now):
        raise ValueError("Invalid checkpoint")
    if type(lookback_days) is not int or not 3 <= lookback_days <= 7:
        raise ValueError("lookback_days must be 3..7")
    if type(batch_size) is not int or not 1 <= batch_size <= 10:
        raise ValueError("batch_size must be 1..10")
    if window_required and not in_fixture_window(now):
        return ()
    if not isinstance(posting_ids, (tuple,list)):
        raise ValueError("Fixture posting_ids must be a list/tuple")
    unique = []
    seen = set()
    for value in posting_ids:
        if not isinstance(value,str) or not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 30:
            raise ValueError("Synthetic numeric posting identifier required")
        if value not in seen:
            seen.add(value)
            unique.append(value)
    # A KST night spans midnight; jobs before 08:00 belong to the prior date.
    local=now.astimezone(KST)
    night=local.date() if local.time().replace(tzinfo=None) >= WINDOW_START else local.date()-timedelta(days=1)
    key_date=night.isoformat()
    groups=[]
    for offset in range(0,len(unique),batch_size):
        group=tuple(unique[offset:offset+batch_size])
        slot=offset//batch_size+1
        groups.append(PlannedBatch(keyword_id,slot,group,
                                   f"fixture:t154:{key_date}:{keyword_id}:{slot}"))
    return tuple(groups)
