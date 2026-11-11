"""T155: authenticated crawler admin write/command service (metadata only).

Not an HTTP router. Callers must already be authenticated/authorized admins and
must pass the authenticated principal as ``actor``; this module never trusts a
browser-supplied name.

Safety boundaries (fail closed):
- No network, filesystem, worker launch, timer or scheduler activation here.
  A RUN/RETRY command only inserts a PENDING ``keyword_jobs`` metadata row.
- ``mode='live'`` is evaluated by the T61 source approval gate with no approval
  record (the project has none), so it is always REFUSED and the refusal is recorded.
- Schedules cannot be enabled or switched to live from this API.
- Every command is idempotent by key and recorded in the append-only
  ``admin_commands`` ledger (migration 0011) in the same transaction as its effect.
- Responses carry metadata only: never Raw HTML, storage keys, target URLs or approval data.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from crawler.jobs import fixture_night_window as night
from crawler.jobs.keyword_management import KeywordStore, check_idempotency, check_priority, normalize_keyword
from crawler.policy.source_approval_gate import CollectionIntent, check_collection_permission

KST = ZoneInfo("Asia/Seoul")
ACTIVE_JOB_STATUSES = ("PENDING", "RUNNING", "FETCHED")
RETRYABLE_STATUSES = frozenset({"FAILED", "CANCELLED"})
COMMAND_TYPES = frozenset({"RUN", "STOP", "RETRY", "SCHEDULE_UPDATE"})
_SCHEDULE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_LOCAL_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
# Placeholder canonical URL used only to ask the T61 gate; never fetched.
_GATE_PROBE_URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/1"


class KeywordConflict(Exception):
    """Normalized keyword already exists (including soft-deleted rows)."""

    crawler_admin_conflict = "KEYWORD_EXISTS"


class IdempotencyConflict(Exception):
    """Same idempotency key reused with a different request."""

    crawler_admin_conflict = "IDEMPOTENCY_KEY_REUSED"


@dataclass(frozen=True)
class CommandResult:
    command_id: UUID
    command_type: str
    target: str
    outcome: str  # ACCEPTED | REFUSED
    reason: str
    result: dict = field(default_factory=dict)
    replayed: bool = False

    def as_dict(self) -> dict:
        return {
            "command_id": str(self.command_id), "command_type": self.command_type, "target": self.target,
            "outcome": self.outcome, "reason": self.reason, "result": self.result, "replayed": self.replayed,
        }


def _check_actor(actor: str) -> str:
    return KeywordStore._check_actor(actor)


def _request_hash(command_type: str, target: str, params: dict) -> str:
    raw = json.dumps([command_type, target, params], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def next_local_run(local_time: time, now: datetime) -> datetime:
    """Next KST occurrence of ``local_time`` strictly after ``now``."""
    local_now = now.astimezone(KST)
    candidate = datetime.combine(local_now.date(), local_time, KST)
    if candidate <= local_now:
        candidate = datetime.combine(local_now.date() + timedelta(days=1), local_time, KST)
    return candidate


def live_gate_reason(now: datetime) -> str:
    """Ask the T61 fail-closed gate with no approval record: never ALLOWED."""
    decision = check_collection_permission(None, CollectionIntent(
        source_code="jobkorea", url=_GATE_PROBE_URL, method="WEB",
        purpose="admin-manual-run", requested_calls=1, at_utc=now))
    if decision.allowed:  # pragma: no cover - impossible without an approval record
        raise RuntimeError("live collection gate unexpectedly allowed without approval")
    return f"LIVE_NOT_APPROVED:{decision.reason.value}"


class CrawlerAdminWriteStore:
    """psycopg connection (not autocommit-dependent); each call is one transaction."""

    def __init__(self, connection, *, clock=None):
        self.connection = connection
        self.keywords = KeywordStore(connection)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    # ------------------------------------------------------------ helpers
    def _one(self, sql: str, params: tuple):
        from psycopg.rows import dict_row
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchone()

    def _all(self, sql: str, params: tuple):
        from psycopg.rows import dict_row
        with self.connection.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return cur.fetchall()

    def _keyword_row(self, keyword_id: int):
        return self._one(
            """SELECT keyword_id,keyword,enabled,priority,created_at,updated_at
               FROM crawler_training.search_keywords WHERE keyword_id=%s AND deleted_at IS NULL""",
            (keyword_id,))

    # ------------------------------------------------------------ keywords
    def create_keyword(self, value: str, *, priority: int, actor: str) -> dict:
        import psycopg
        normalize_keyword(value)
        check_priority(priority)
        try:
            with self.connection.transaction():
                keyword_id = self.keywords.add_keyword(value, priority=priority, actor=_check_actor(actor))
                return self._keyword_row(keyword_id)
        except psycopg.errors.UniqueViolation:
            raise KeywordConflict() from None

    def update_keyword(self, keyword_id: int, value: str, *, priority: int, actor: str) -> dict | None:
        import psycopg
        try:
            with self.connection.transaction():
                if not self.keywords.edit_keyword(keyword_id, value, priority=priority, actor=_check_actor(actor)):
                    return None
                return self._keyword_row(keyword_id)
        except psycopg.errors.UniqueViolation:
            raise KeywordConflict() from None

    def set_keyword_enabled(self, keyword_id: int, enabled: bool, *, actor: str) -> dict | None:
        with self.connection.transaction():
            if not self.keywords.set_enabled(keyword_id, enabled, actor=_check_actor(actor)):
                return None
            return self._keyword_row(keyword_id)

    def delete_keyword(self, keyword_id: int, *, actor: str) -> bool:
        return self.keywords.soft_delete(keyword_id, actor=_check_actor(actor))

    def keyword_audit(self, keyword_id: int, *, limit: int = 50) -> list[dict]:
        rows = self.keywords.list_audit(keyword_id, limit=limit)
        return [{k: row[k] for k in ("audit_id", "keyword_id", "actor", "action",
                                     "before_state", "after_state", "occurred_at")} for row in rows]

    # ------------------------------------------------------------ settings
    def settings(self) -> dict:
        schedules = self._all(
            """SELECT schedule_id,source_id,enabled,timezone,local_time,mode,next_run_at,last_run_at,updated_at
               FROM crawler_training.schedules ORDER BY schedule_id""", ())
        for row in schedules:
            row["local_time"] = row["local_time"].strftime("%H:%M")
        return {
            "schedules": schedules,
            "night_window": {
                "timezone": "Asia/Seoul", "start": night.START.strftime("%H:%M"), "end": night.END.strftime("%H:%M"),
                "slot_minutes": night.SLOT_MINUTES, "max_slots": night.MAX_SLOTS, "editable": False,
            },
            "live_collection": "HOLD",
            "schedule_activation": "REQUIRES_SEPARATE_APPROVAL",
        }

    def commands(self, *, limit: int = 50, offset: int = 0) -> list[dict]:
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 100000:
            raise ValueError("invalid pagination")
        return self._all(
            """SELECT command_id,command_type,target,outcome,reason,result,actor,created_at
               FROM crawler_training.admin_commands
               ORDER BY created_at DESC,command_id LIMIT %s OFFSET %s""", (limit, offset))

    # ------------------------------------------------------------ commands
    def _execute(self, command_type: str, target: str, params: dict, idempotency_key: str, actor: str, effect):
        if command_type not in COMMAND_TYPES:
            raise ValueError("unknown command")
        check_idempotency(idempotency_key)
        actor = _check_actor(actor)
        request_hash = _request_hash(command_type, target, params)
        with self.connection.transaction():
            with self.connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 155))", (idempotency_key,))
            existing = self._one(
                """SELECT command_id,command_type,target,outcome,reason,result,request_hash
                   FROM crawler_training.admin_commands WHERE idempotency_key=%s""", (idempotency_key,))
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict()
                return CommandResult(existing["command_id"], existing["command_type"], existing["target"],
                                     existing["outcome"], existing["reason"], existing["result"], replayed=True)
            command_id = uuid4()
            outcome, reason, result = effect(command_id)
            with self.connection.cursor() as cur:
                cur.execute(
                    """INSERT INTO crawler_training.admin_commands
                       (command_id,idempotency_key,request_hash,actor,command_type,target,outcome,reason,result)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)""",
                    (command_id, idempotency_key, request_hash, actor, command_type, target, outcome, reason,
                     json.dumps(result, ensure_ascii=False)))
            return CommandResult(command_id, command_type, target, outcome, reason, result)

    def _active_job_exists(self, keyword_id: int) -> bool:
        return self._one(
            """SELECT 1 AS x FROM crawler_training.keyword_jobs
               WHERE keyword_id=%s AND status = ANY(%s) LIMIT 1""",
            (keyword_id, list(ACTIVE_JOB_STATUSES))) is not None

    def _enqueue_fixture_job(self, keyword_id: int, command_id: UUID):
        keyword = self._one(
            """SELECT keyword_id,enabled FROM crawler_training.search_keywords
               WHERE keyword_id=%s AND deleted_at IS NULL FOR UPDATE""", (keyword_id,))
        if keyword is None:
            return "REFUSED", "KEYWORD_NOT_FOUND", {}
        if not keyword["enabled"]:
            return "REFUSED", "KEYWORD_DISABLED", {}
        if self._active_job_exists(keyword_id):
            return "REFUSED", "ACTIVE_JOB_EXISTS", {}
        job_id = self.keywords.create_job(keyword_id, f"t155-admin:{command_id}")
        # Metadata only: PENDING job, no worker/timer dispatch, no HTTP.
        return "ACCEPTED", "FIXTURE_JOB_PENDING", {"job_id": str(job_id), "keyword_id": keyword_id,
                                                    "status": "PENDING", "mode": "fixture"}

    def run(self, keyword_id: int, *, mode: str, idempotency_key: str, actor: str) -> CommandResult:
        if type(keyword_id) is not int or keyword_id <= 0:
            raise ValueError("keyword_id must be a positive integer")
        if mode not in ("fixture", "live"):
            raise ValueError("mode must be fixture or live")

        def effect(command_id):
            if mode == "live":
                return "REFUSED", live_gate_reason(self._clock()), {}
            return self._enqueue_fixture_job(keyword_id, command_id)

        return self._execute("RUN", f"keyword:{keyword_id}", {"mode": mode}, idempotency_key, actor, effect)

    def _job(self, job_id: UUID):
        return self._one(
            """SELECT job_id,keyword_id,status FROM crawler_training.keyword_jobs WHERE job_id=%s FOR UPDATE""",
            (job_id,))

    def stop(self, job_id: UUID, *, idempotency_key: str, actor: str) -> CommandResult:
        job_id = UUID(str(job_id))

        def effect(_command_id):
            job = self._job(job_id)
            if job is None:
                return "REFUSED", "JOB_NOT_FOUND", {}
            if job["status"] != "PENDING":
                # A RUNNING/FETCHED job belongs to its Worker; terminal jobs cannot change.
                reason = "JOB_ALREADY_FINISHED" if job["status"] in ("FAILED", "COMPLETED", "CANCELLED") \
                    else "RUNNING_JOB_STOP_UNSUPPORTED"
                return "REFUSED", reason, {"status": job["status"]}
            if not self.keywords.transition(job_id, "PENDING", "CANCELLED"):  # pragma: no cover - row locked
                return "REFUSED", "JOB_STATE_CHANGED", {}
            return "ACCEPTED", "JOB_CANCELLED", {"job_id": str(job_id), "status": "CANCELLED"}

        return self._execute("STOP", f"job:{job_id}", {}, idempotency_key, actor, effect)

    def retry(self, job_id: UUID, *, idempotency_key: str, actor: str) -> CommandResult:
        job_id = UUID(str(job_id))

        def effect(command_id):
            job = self._job(job_id)
            if job is None:
                return "REFUSED", "JOB_NOT_FOUND", {}
            if job["status"] not in RETRYABLE_STATUSES:
                return "REFUSED", "JOB_NOT_RETRYABLE", {"status": job["status"]}
            outcome, reason, result = self._enqueue_fixture_job(job["keyword_id"], command_id)
            if outcome == "ACCEPTED":
                result["retry_of"] = str(job_id)
            return outcome, reason, result

        return self._execute("RETRY", f"job:{job_id}", {}, idempotency_key, actor, effect)

    def update_schedule(self, schedule_id: str, *, changes: dict, idempotency_key: str, actor: str) -> CommandResult:
        if not isinstance(schedule_id, str) or not _SCHEDULE_ID.match(schedule_id):
            raise ValueError("invalid schedule_id")
        allowed = {"local_time", "enabled", "mode"}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError("changes must contain local_time, enabled or mode")
        if "local_time" in changes and (not isinstance(changes["local_time"], str)
                                         or not _LOCAL_TIME.match(changes["local_time"])):
            raise ValueError("local_time must be HH:MM")
        if "enabled" in changes and type(changes["enabled"]) is not bool:
            raise ValueError("enabled must be bool")
        if "mode" in changes and changes["mode"] not in ("fixture", "live"):
            raise ValueError("mode must be fixture or live")

        def effect(_command_id):
            if changes.get("mode") == "live":
                return "REFUSED", live_gate_reason(self._clock()), {}
            if changes.get("enabled") is True:
                return "REFUSED", "SCHEDULE_ACTIVATION_REQUIRES_APPROVAL", {}
            row = self._one(
                """SELECT schedule_id,enabled,mode,local_time FROM crawler_training.schedules
                   WHERE schedule_id=%s FOR UPDATE""", (schedule_id,))
            if row is None:
                return "REFUSED", "SCHEDULE_NOT_FOUND", {}
            if row["enabled"] or row["mode"] != "fixture":
                return "REFUSED", "ACTIVE_SCHEDULE_CHANGE_REQUIRES_APPROVAL", {}
            before = row["local_time"].strftime("%H:%M")
            if "local_time" not in changes or changes["local_time"] == before:
                return "ACCEPTED", "NO_CHANGE", {"schedule_id": schedule_id, "local_time": before, "enabled": False}
            hh, mm = map(int, changes["local_time"].split(":"))
            new_time = time(hh, mm)
            next_run = next_local_run(new_time, self._clock())
            with self.connection.cursor() as cur:
                cur.execute(
                    """UPDATE crawler_training.schedules SET local_time=%s,next_run_at=%s,updated_at=now()
                       WHERE schedule_id=%s AND enabled=false AND mode='fixture'""",
                    (new_time, next_run, schedule_id))
            return "ACCEPTED", "SCHEDULE_TIME_UPDATED", {
                "schedule_id": schedule_id, "local_time_before": before, "local_time": changes["local_time"],
                "next_run_at": next_run.isoformat(), "enabled": False}

        return self._execute("SCHEDULE_UPDATE", f"schedule:{schedule_id}", dict(changes), idempotency_key,
                             actor, effect)
