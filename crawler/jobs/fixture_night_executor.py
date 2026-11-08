"""Explicit synthetic one-shot supervisor. No scheduler/timer installation.

The deadline includes TERM grace and is at most 120 seconds or next 08:00 KST.
Only the prepared synthetic Raw payload is consumed; this module cannot fetch.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, time as daytime, timedelta
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import threading
import urllib.request
from uuid import UUID, uuid4

from crawler.jobs.fixture_night_window import KST, night_slot, execute_night_fixture_once
from crawler.jobs.raw_artifact_store import RawArtifactStore
from crawler.storage.staging import connect_configured_database

WORKER_LOCK = 154230001


def execution_budget(now: datetime, maximum: float = 120, grace: float = 2):
    slot = night_slot(now)
    if slot is None:
        return None
    end = datetime.combine(slot.night_date + timedelta(days=1), daytime(8), KST)
    remaining = min(maximum, (end - now).total_seconds())
    return remaining if remaining > grace else None


@dataclass(frozen=True)
class Supervision:
    started: bool
    returncode: int | None
    terminated: bool
    killed: bool
    elapsed: float
    stdout: str = ""
    interrupted: bool = False


def supervise(command, *, deadline: float, grace: float = 2, stop_event=None) -> Supervision:
    """Run a real direct child; TERM before deadline, KILL/reap if unresponsive.

    Child is the synchronous Worker, not a shell/launcher, and creates no children.
    Monotonic absolute deadline includes spawn overhead and termination grace.
    """
    started = time.monotonic()
    if not math.isfinite(grace) or grace <= 0:
        raise ValueError("Positive finite termination grace required")
    if deadline - started <= grace:
        return Supervision(False, None, False, False, 0)
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
    terminated = killed = interrupted = False
    output = ""
    try:
        try:
            while True:
                interrupted = bool(stop_event and stop_event.is_set())
                remaining = deadline - grace - time.monotonic()
                if interrupted or remaining <= 0:
                    raise subprocess.TimeoutExpired(command, 0)
                try:
                    output, _ = child.communicate(timeout=min(.1, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() < deadline - grace and not (stop_event and stop_event.is_set()):
                        continue
                    raise
        except subprocess.TimeoutExpired:
            interrupted = bool(stop_event and stop_event.is_set())
            terminated = True
            child.terminate()
            try:
                output, _ = child.communicate(timeout=max(.001, min(grace, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                killed = True
                child.kill()
                output, _ = child.communicate()
        except KeyboardInterrupt:
            interrupted = terminated = killed = True
            child.kill()
            output, _ = child.communicate()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
    return Supervision(True, child.returncode, terminated, killed,
                       time.monotonic() - started, output, interrupted)


def _connections(stack, connector):
    cs = [stack.enter_context(connector()) for _ in range(3)]
    identities = []
    for c in cs:
        c.autocommit = True
        identities.append(c.execute("SELECT current_database(),inet_server_addr()::text,inet_server_port(),pg_backend_pid()").fetchone())
    if (any(i[0] != "ai_career_crawler_training" for i in identities)
            or len({i[:3] for i in identities}) != 1
            or len({i[3] for i in identities}) != 3):
        raise ValueError("Three independent connections to same training database required")
    return cs, [i[3] for i in identities]


def _block_external_network():
    """Defense in depth: the dedicated child may connect only to DB addresses.

    Install after DB connections are established. Fixture file reading/parse
    needs no additional sockets. No HTTP path exists in the Worker.
    """
    def denied(*args, **kwargs):
        raise RuntimeError("EXTERNAL_HTTP_FORBIDDEN")
    urllib.request.OpenerDirector.open = denied
    socket.socket.connect = denied
    socket.socket.connect_ex = denied


def child_once(job_id, raw_root, *, connector=connect_configured_database, now=None):
    """Internal child entry; returns no exception text, SQL, DSN or Raw HTML."""
    with ExitStack() as stack:
        cs, pids = _connections(stack, connector)
        slot_db, attempt_db, worker_db = cs
        application = "t154-night:" + uuid4().hex
        for c in cs:
            c.execute("SELECT set_config('application_name',%s,false)", (application,))
        print(json.dumps({"event": "connected", "backend_pids": pids,
                          "application": application}), flush=True)
        # Session lock lives on actual Worker connection; disconnect releases it.
        if not worker_db.execute("SELECT pg_try_advisory_lock(%s)", (WORKER_LOCK,)).fetchone()[0]:
            return {"status": "REJECTED", "error_code": "WORKER_BUSY"}
        _block_external_network()
        try:
            out = execute_night_fixture_once(
                slot_connection=slot_db, attempt_connection=attempt_db,
                worker_connection=worker_db, files=RawArtifactStore(Path(raw_root)),
                job_id=job_id, now=now or datetime.now(KST),
            )
            return {"status": out.status, "attempt_count": out.attempt,
                    "processed_postings": out.valid_count, "error_code": None}
        except Exception as exc:
            from crawler.jobs.fixture_night_window import NightSlotUnavailable
            from crawler.jobs.fixture_manual_retry import AttemptUnavailable
            if isinstance(exc, (NightSlotUnavailable, AttemptUnavailable)):
                return {"status": "REJECTED", "error_code": "NO_ELIGIBLE_SLOT_ATTEMPT"}
            # Unknown failure intentionally leaves durable Attempt IN_PROGRESS.
            # Only a validated SQLSTATE is safe to report; no arbitrary messages.
            code = getattr(exc, "sqlstate", None)
            return {"status": "UNRESOLVED", "error_code": code if isinstance(code,str) and len(code)==5 and code.isalnum() else "WORKER_ERROR"}


def _database_result(job_id, pids, connector, application=None, *, connection=None):
    with ExitStack() as stack:
        c = connection if connection is not None else stack.enter_context(connector())
        c.autocommit = True
        c.execute("SET statement_timeout=200")
        c.execute("SET lock_timeout=100")
        # Killing a client process need not interrupt a PostgreSQL backend that
        # is still in a long query. Terminate only the emitted PIDs belonging to
        # our role AND unique application token; never touch other sessions.
        terminated = []
        if pids and application:
            for pid, in c.execute("""SELECT pid FROM pg_stat_activity
                    WHERE pid=ANY(%s) AND usename=current_user AND application_name=%s""",
                    (pids, application)).fetchall():
                if c.execute("SELECT pg_terminate_backend(%s,100)", (pid,)).fetchone()[0]:
                    terminated.append(pid)
        row = c.execute("""SELECT j.status,a.state,a.attempt_count FROM crawler_training.keyword_jobs j
            LEFT JOIN crawler_training.fixture_job_attempts a USING(job_id) WHERE j.job_id=%s""", (job_id,)).fetchone()
        alive = c.execute("SELECT count(*) FROM pg_stat_activity WHERE pid=ANY(%s)", (pids,)).fetchone()[0] if pids else None
        locks = c.execute("SELECT count(*) FROM pg_locks WHERE pid=ANY(%s)", (pids,)).fetchone()[0] if pids else None
        return {"job_status": row[0] if row else None, "attempt_status": row[1] if row else None,
                "attempt_count": row[2] if row else None, "backend_terminations": len(terminated),
                "db_cleanup": "PASS" if alive == locks == 0 else "NOT_VERIFIED",
                "state_mismatch": bool(row and ((row[0]=="COMPLETED") != (row[1]=="COMPLETED")))}


@contextmanager
def _termination_signals():
    """SIGTERM/SIGINT route through child reap and scoped DB cleanup."""
    handlers = {}
    stopped = threading.Event()
    def stop(signum, frame):
        # Do not interrupt the finally/DB cleanup path on repeated signals.
        stopped.set()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            handlers[sig] = signal.signal(sig, stop)
    try:
        yield stopped
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def run_once(*, job_id, raw_root, log_file, now=None, maximum=120, grace=2,
             connector=connect_configured_database, command=None, cleanup_budget=2):
    """One invocation for a prepared job, no catch-up or automatic retry.

    A future external timer may invoke this command once per slot. Nothing here
    installs one. `now`/`command` support isolated tests; CLI has no clock override.
    """
    job_id = str(UUID(str(job_id)))
    current = now or datetime.now(KST)
    slot = night_slot(current)
    budget = execution_budget(current, maximum, grace)
    result = {"night_date": str(slot.night_date) if slot else None,
              "slot_index": slot.slot_index if slot else None, "job_id": job_id,
              "started_at": current.isoformat(), "ended_at": None,
              "status": "REJECTED", "attempt_count": None, "processed_postings": 0,
              "error_code": None, "termination_reason": None,
              "external_http_requests": 0, "db_cleanup": "NOT_APPLICABLE"}
    if budget is None or budget <= grace + cleanup_budget:
        result["termination_reason"] = "OUTSIDE_WINDOW_OR_INSUFFICIENT_TIME"
    else:
        deadline = time.monotonic() + budget
        argv = command or [sys.executable, "-m", "crawler.jobs.fixture_night_executor", "_worker",
                           "--job-id", job_id, "--raw-root", str(raw_root)]
        # Establish diagnostic DB connection BEFORE starting useful work.
        # Child TERM/KILL and bounded DB cleanup both fit inside final deadline.
        try:
            with _termination_signals() as stopped, connector() as diagnostic:
                diagnostic.autocommit = True
                supervision = supervise(argv, deadline=deadline-cleanup_budget, grace=grace, stop_event=stopped)
                return _finish(result, supervision, job_id, diagnostic, connector, deadline, log_file)
        except Exception:
            result.update(status="UNRESOLVED", error_code="SUPERVISOR_SETUP_ERROR",
                          db_cleanup="NOT_VERIFIED", requires_manual_review=True)
    return _write_summary(result, log_file)


def _finish(result, supervision, job_id, diagnostic, connector, deadline, log_file):
    pids = []
    application = None
    for line in supervision.stdout.splitlines():
        try:
            msg = json.loads(line)
            if msg.get("event") == "connected":
                pids = [int(p) for p in msg["backend_pids"]]
                application = msg.get("application")
            if msg.get("event") == "result":
                for k in ("status", "attempt_count", "processed_postings", "error_code"):
                    if k in msg: result[k] = msg[k]
        except (ValueError, TypeError, KeyError):
            continue
    if supervision.terminated:
        result.update(status="INTERRUPTED", error_code="SUPERVISOR_INTERRUPTED" if supervision.interrupted else "DEADLINE_REACHED",
                      termination_reason="KILL" if supervision.killed else "TERM")
    elif supervision.returncode != 0:
        result.update(status="UNRESOLVED", error_code="CHILD_EXIT")
    try:
        result.update(_database_result(job_id, pids, connector, application, connection=diagnostic))
        result["cleanup_before_deadline"] = time.monotonic() <= deadline
        if not result["cleanup_before_deadline"]:
            result["db_cleanup"] = "NOT_VERIFIED"
        if result.get("attempt_status") == "IN_PROGRESS":
            result["requires_manual_review"] = True
    except Exception:
        result.update(db_cleanup="NOT_VERIFIED", requires_manual_review=True)
    result["child_exit_code"] = supervision.returncode
    return _write_summary(result, log_file)

def _write_summary(result, log_file):
    result["ended_at"] = datetime.now(KST).isoformat()
    # Append a single allowlisted record, never child stderr or exception text.
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(result, ensure_ascii=True) + "\n")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["once", "_worker"])
    parser.add_argument("--job-id", required=True, type=UUID)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--log-file", type=Path)
    args = parser.parse_args(argv)
    if args.action == "_worker":
        result = child_once(args.job_id, args.raw_root)
        print(json.dumps({"event":"result", **result}), flush=True)
        return 0
    if args.log_file is None:
        parser.error("once requires --log-file")
    result = run_once(job_id=args.job_id, raw_root=args.raw_root, log_file=args.log_file)
    print(json.dumps(result))
    return 0 if (result["status"] in ("COMPLETED", "REJECTED")
                 and result["db_cleanup"] in ("PASS", "NOT_APPLICABLE")
                 and not result.get("state_mismatch")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
