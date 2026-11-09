"""T64 STEP 03: offline heartbeat expiry and bounded retry decision model.

No timers, sleep, database, subprocesses, HTTP or real worker restarts.
All times are supplied by callers; this simulator holds state in memory only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from threading import Lock

from crawler.jobs.run_claims import InMemoryRunClaims, UnknownRun
from crawler.jobs.run_state import RunStatus, _utc


class RecoveryDecision(str, Enum):
    WAIT = "WAIT"
    EXPIRED = "EXPIRED"
    RETRY_ELIGIBLE = "RETRY_ELIGIBLE"
    STOP_NONRETRYABLE = "STOP_NONRETRYABLE"
    STOP_LIMIT = "STOP_LIMIT"
    NO_ACTION = "NO_ACTION"


RETRYABLE_CODES = frozenset({"WORKER_TIMEOUT", "HEARTBEAT_TIMEOUT", "TEMPORARY_IO"})
STOP_CODES = frozenset({"ACCESS_FORBIDDEN", "RATE_LIMITED", "INVALID_CONTRACT", "UNAPPROVED_SOURCE"})


@dataclass(frozen=True)
class RecoveryPolicy:
    heartbeat_timeout: timedelta = timedelta(minutes=5)
    max_attempts: int = 3

    def __post_init__(self):
        if (not isinstance(self.heartbeat_timeout, timedelta)
                or not timedelta(seconds=0) < self.heartbeat_timeout <= timedelta(hours=1)):
            raise ValueError("heartbeat_timeout must be within (0, 1 hour]")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")


def retry_decision(*, error_code: str, attempt: int, policy: RecoveryPolicy) -> RecoveryDecision:
    """Return only a decision. Caller must request a NEW run_id to retry."""
    if type(attempt) is not int or not 1 <= attempt <= policy.max_attempts:
        raise ValueError("attempt outside policy bounds")
    if not isinstance(error_code, str) or error_code not in RETRYABLE_CODES | STOP_CODES:
        return RecoveryDecision.STOP_NONRETRYABLE
    if error_code not in RETRYABLE_CODES:
        return RecoveryDecision.STOP_NONRETRYABLE
    if attempt >= policy.max_attempts:
        return RecoveryDecision.STOP_LIMIT
    return RecoveryDecision.RETRY_ELIGIBLE


class OfflineHeartbeatMonitor:
    """Monitor an existing single-process claim registry; no actual restart.

    Explicit heartbeat and inspection times allow deterministic tests.
    Lock guards heartbeat tracking, but cross-process safety is NOT provided.
    """

    def __init__(self, claims: InMemoryRunClaims, policy: RecoveryPolicy | None = None):
        self.claims = claims
        self.policy = policy if policy is not None else RecoveryPolicy()
        self._last_seen: dict[str, datetime] = {}
        self._mutex = Lock()

    def heartbeat(self, *, run_id: str, at: datetime) -> None:
        instant = _utc(at)
        with self._mutex:
            record = self.claims.get(run_id)
            if record is None:
                raise UnknownRun("Run ID not found")
            if record.status != RunStatus.RUNNING:
                raise ValueError("Heartbeat requires RUNNING status")
            previous = self._last_seen.get(run_id, record.started_at)
            if previous is None or instant < previous:
                raise ValueError("Heartbeat time cannot precede start or previous beat")
            self._last_seen[run_id] = instant

    def inspect(self, *, run_id: str, at: datetime) -> RecoveryDecision:
        """Expire an inactive run, releasing its in-process source claim.

        Exactly at the timeout boundary, it is considered stale.
        This is a deterministic *simulated* timeout: no process is killed.
        """
        instant = _utc(at)
        with self._mutex:
            record = self.claims.get(run_id)
            if record is None:
                raise UnknownRun("Run ID not found")
            if record.status != RunStatus.RUNNING:
                return RecoveryDecision.NO_ACTION
            previous = self._last_seen.get(run_id, record.started_at)
            if previous is None or instant < previous:
                raise ValueError("Inspection time cannot precede last heartbeat")
            if instant - previous < self.policy.heartbeat_timeout:
                return RecoveryDecision.WAIT
            self.claims.finish(
                run_id=run_id, target=RunStatus.FAILED,
                at=instant, error_code="HEARTBEAT_TIMEOUT",
            )
            self._last_seen.pop(run_id, None)
            return RecoveryDecision.EXPIRED
