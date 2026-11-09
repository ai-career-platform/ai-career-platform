"""T64 STEP 05: pure offline KST schedule eligibility decisions.

No scheduler, system clock, database, filesystem, network or worker execution.
All instants are supplied explicitly; 03:00 KST is a proposal, not approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from crawler.jobs.run_state import _utc

KST = ZoneInfo("Asia/Seoul")


class ScheduleDecision(str, Enum):
    DISABLED = "DISABLED"
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    ALREADY_DISPATCHED = "ALREADY_DISPATCHED"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"


@dataclass(frozen=True)
class OfflineSchedule:
    """One unapproved synthetic jobkorea schedule, never dispatches work."""
    enabled: bool = False
    local_time: time = time(3, 0)
    catchup_window: timedelta = timedelta(minutes=30)
    source_id: str = "jobkorea"

    def __post_init__(self):
        if self.source_id != "jobkorea":
            raise ValueError("Only jobkorea synthetic schedule is supported")
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be a bool")
        if not isinstance(self.local_time, time) or self.local_time.tzinfo is not None:
            raise ValueError("local_time must be timezone-naive time")
        if (not isinstance(self.catchup_window, timedelta)
                or not timedelta(0) < self.catchup_window <= timedelta(hours=2)):
            raise ValueError("catchup_window must be within (0, 2 hours]")


@dataclass(frozen=True)
class ScheduleEvaluation:
    decision: ScheduleDecision
    scheduled_at_utc: datetime
    local_day: str

    def snapshot(self) -> dict:
        return {
            "decision": self.decision.value,
            "scheduled_at_utc": self.scheduled_at_utc.isoformat().replace("+00:00", "Z"),
            "local_day": self.local_day,
        }


def evaluate_daily(
    schedule: OfflineSchedule, *,
    now: datetime,
    last_dispatched_for: datetime | None = None,
) -> ScheduleEvaluation:
    """Pure eligibility decision. DUE does not claim, start, or approve a run.

    last_dispatched_for is the *scheduled* UTC slot previously claimed by an
    external durable dispatcher, not when it happened. This function does not
    store it; multiple callers can both receive DUE without an atomic DB claim.
    """
    if not isinstance(schedule, OfflineSchedule):
        raise ValueError("Invalid schedule")
    current = _utc(now)
    local_now = current.astimezone(KST)
    scheduled_local = datetime.combine(local_now.date(), schedule.local_time, tzinfo=KST)
    scheduled = scheduled_local.astimezone(timezone.utc)
    previous = _utc(last_dispatched_for) if last_dispatched_for is not None else None
    if previous is not None and previous > current:
        raise ValueError("last_dispatched_for cannot be in the future")
    if not schedule.enabled:
        reason = ScheduleDecision.DISABLED
    elif previous == scheduled:
        reason = ScheduleDecision.ALREADY_DISPATCHED
    elif current < scheduled:
        reason = ScheduleDecision.NOT_DUE
    elif current - scheduled > schedule.catchup_window:
        reason = ScheduleDecision.WINDOW_EXPIRED
    else:
        reason = ScheduleDecision.DUE
    return ScheduleEvaluation(reason, scheduled, local_now.date().isoformat())
