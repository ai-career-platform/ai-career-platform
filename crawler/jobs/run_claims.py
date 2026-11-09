"""T64 STEP 02: single-process, in-memory atomic run claims for offline tests.

This is deliberately NOT a cross-process lock or durable scheduler. No DB,
filesystem, network, wall-clock reads or external source execution.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Mapping

from crawler.jobs.run_state import RunRecord, RunStatus, TERMINAL


class RunTrigger(str, Enum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"


class ClaimRejected(ValueError):
    """Duplicate run ID or a different active run already owns the source."""


class UnknownRun(ValueError):
    """Run ID has never been claimed."""


class InMemoryRunClaims:
    """Thread-safe within ONE Python process; immutable RunRecord snapshots."""

    def __init__(self) -> None:
        self._mutex = Lock()
        self._runs: dict[str, RunRecord] = {}
        self._triggers: dict[str, RunTrigger] = {}
        self._active_by_source: dict[str, str] = {}

    def claim(
        self, *, run_id: str, source_id: str, trigger: RunTrigger,
        requested_at: datetime, started_at: datetime,
    ) -> RunRecord:
        if not isinstance(trigger, RunTrigger):
            raise ValueError("Unsupported trigger")
        # Validate the input and chronology before taking the lock.
        candidate = RunRecord.pending(
            run_id=run_id, source_id=source_id, requested_at=requested_at,
        ).transition(RunStatus.RUNNING, at=started_at)
        with self._mutex:
            if candidate.run_id in self._runs:
                raise ClaimRejected("Run ID already claimed; replay denied")
            if candidate.source_id in self._active_by_source:
                raise ClaimRejected("Source already has an active run")
            self._runs[candidate.run_id] = candidate
            self._triggers[candidate.run_id] = trigger
            self._active_by_source[candidate.source_id] = candidate.run_id
            return candidate

    def finish(
        self, *, run_id: str, target: RunStatus, at: datetime,
        counters: Mapping[str, int] | None = None,
        error_code: str | None = None,
    ) -> RunRecord:
        if target not in TERMINAL or not isinstance(target, RunStatus):
            raise ValueError("Finish requires a terminal status")
        with self._mutex:
            current = self._runs.get(run_id)
            if current is None:
                raise UnknownRun("Run ID not found")
            # Validation must complete before releasing the source claim.
            completed = current.transition(
                target, at=at, counters=counters, error_code=error_code,
            )
            self._runs[run_id] = completed
            del self._active_by_source[current.source_id]
            return completed

    def get(self, run_id: str) -> RunRecord | None:
        with self._mutex:
            return self._runs.get(run_id)

    def trigger_for(self, run_id: str) -> RunTrigger | None:
        with self._mutex:
            return self._triggers.get(run_id)

    def active_run(self, source_id: str) -> str | None:
        with self._mutex:
            return self._active_by_source.get(source_id)
