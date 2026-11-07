"""T64 STEP 01: immutable, offline crawler run lifecycle contract.

Pure Python only: no scheduling, network, database, filesystem writes or clock
reads. Callers supply timezone-aware UTC instants explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Mapping


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL = frozenset({
    RunStatus.SUCCEEDED, RunStatus.PARTIAL, RunStatus.FAILED, RunStatus.CANCELLED,
})
_ALLOWED = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: TERMINAL,
}
_METRIC_KEYS = frozenset({
    "fetched", "normalized", "duplicates", "review", "invalid",
    "inserted", "updated", "unchanged", "db_writes", "external_requests",
})


class InvalidRunTransition(ValueError):
    """Requested run-state transition violates the offline contract."""


def _utc(instant: datetime) -> datetime:
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return instant.astimezone(timezone.utc)


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    source_id: str
    status: RunStatus
    requested_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    counters: tuple[tuple[str, int], ...] = ()
    error_code: str | None = None

    @classmethod
    def pending(cls, *, run_id: str, source_id: str, requested_at: datetime) -> RunRecord:
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id is required")
        if source_id != "jobkorea":
            raise ValueError("Only the jobkorea synthetic source is supported")
        return cls(run_id.strip(), source_id, RunStatus.PENDING, _utc(requested_at))

    def transition(
        self,
        target: RunStatus,
        *,
        at: datetime,
        counters: Mapping[str, int] | None = None,
        error_code: str | None = None,
    ) -> RunRecord:
        if not isinstance(target, RunStatus):
            raise InvalidRunTransition("Invalid target status")
        if target not in _ALLOWED.get(self.status, frozenset()):
            raise InvalidRunTransition("Illegal or terminal state transition")
        timestamp = _utc(at)
        reference = self.started_at or self.requested_at
        if timestamp < reference:
            raise InvalidRunTransition("Transition time must be monotonic")

        if target == RunStatus.RUNNING:
            if counters is not None or error_code is not None:
                raise InvalidRunTransition("RUNNING cannot have final metrics or error")
            return replace(self, status=target, started_at=timestamp)

        values: tuple[tuple[str, int], ...] = ()
        if counters is not None:
            if not isinstance(counters, Mapping):
                raise InvalidRunTransition("Counters must be a mapping")
            if any(
                key not in _METRIC_KEYS or type(value) is not int or value < 0
                for key, value in counters.items()
            ):
                raise InvalidRunTransition("Invalid counter key or value")
            values = tuple(sorted(counters.items()))

        if target == RunStatus.FAILED:
            if not isinstance(error_code, str) or re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", error_code) is None:
                raise InvalidRunTransition("FAILED requires a safe error code")
        elif error_code is not None:
            raise InvalidRunTransition("Error code is only permitted for FAILED")

        return replace(
            self, status=target, ended_at=timestamp,
            counters=values, error_code=error_code,
        )

    def snapshot(self) -> dict:
        """Sanitized JSON-ready run summary, no secret fields or payloads."""
        def iso(value: datetime | None) -> str | None:
            return value.isoformat().replace("+00:00", "Z") if value is not None else None

        return {
            "run_id": self.run_id,
            "source_id": self.source_id,
            "status": self.status.value,
            "requested_at": iso(self.requested_at),
            "started_at": iso(self.started_at),
            "ended_at": iso(self.ended_at),
            "counters": dict(self.counters),
            "error_code": self.error_code,
        }
