#!/usr/bin/env python3
"""T08 — AI Career Platform PostgreSQL migration runner (DRAFT, PM review required).

Forward-only, versioned SQL migrations applied through ``psql``.

* Only files named ``NNNN_snake_case.sql`` in ``database/migrations`` are managed.
  ``DRAFT_*`` files are kept for verification and are never applied by this tool.
* Each migration runs in ONE transaction together with its ledger row in
  ``career_migration.schema_migrations``. A failure rolls back both.
* Applied files are protected by a SHA-256 checksum (CRLF normalised to LF so
  Windows and Linux checkouts agree). Editing an applied file is reported as drift.
* No database driver is required: SQL is piped to ``psql`` on stdin. Point the
  runner at any psql with ``--psql`` or ``MIGRATE_PSQL``, for example::

      MIGRATE_PSQL="docker exec -i career-dev-db psql -U dev_local -d career_dev"

Commands: ``lint``, ``status``, ``verify``, ``apply``. Run with ``-h`` for options.
Standard library only (Python 3.9+).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

RUNNER_VERSION = "0.1.0"
LEDGER = "career_migration.schema_migrations"
DEFAULT_DIR = Path(__file__).resolve().parent / "migrations"
STAGING_DB_NAME = "ai_career_poc"
ADVISORY_LOCK_KEY = 8_020_261_106  # arbitrary constant shared by every runner

FILE_RE = re.compile(r"^(\d{4})_([a-z0-9]+(?:_[a-z0-9]+)*)\.sql$")
APPROVAL_RE = re.compile(r"^[A-Za-z0-9#._-]{3,64}$")
HEADER_LINES = 20
REQUIRED_HEADERS = ("-- Purpose:", "-- Recovery:")
DESTRUCTIVE_HEADER = "-- Destructive-Approval:"

# (pattern, message). Checked on SQL with comments removed.
FORBIDDEN = [
    (re.compile(r"^\s*(BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION|SAVEPOINT)\b\s*(TRANSACTION|WORK)?\s*;",
                re.I | re.M),
     "transaction control is added by the runner; remove BEGIN/COMMIT/ROLLBACK"),
    (re.compile(r"^\s*\\", re.M), "psql meta-commands (\\...) are not allowed"),
    (re.compile(r"\bCONCURRENTLY\b", re.I), "CONCURRENTLY cannot run inside a transaction (not supported yet)"),
    (re.compile(r"\b(SET|RESET)\s+(SESSION\s+AUTHORIZATION|ROLE)\b", re.I),
     "role switching belongs to the runner (--role), not to migration files"),
    (re.compile(r"\bPASSWORD\b", re.I), "passwords must never be stored in migrations"),
    (re.compile(r"\b(DROP|CREATE)\s+DATABASE\b", re.I), "database-level DDL is out of scope"),
]
DESTRUCTIVE = re.compile(
    r"\b(DROP\s+(TABLE|SCHEMA|COLUMN|TYPE|VIEW)|TRUNCATE|ALTER\s+TABLE\s+\S+\s+DROP)\b", re.I)


class MigrationError(Exception):
    """Expected, user-facing failure. Exit code 1."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    checksum: str
    sql: str


# --------------------------------------------------------------------------- files

def _normalised_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"--[^\n]*", "", sql)


def lint_file(path: Path) -> List[str]:
    problems: List[str] = []
    text = _normalised_bytes(path).decode("utf-8")
    head = text.splitlines()[:HEADER_LINES]
    for header in REQUIRED_HEADERS:
        if not any(line.startswith(header) and line[len(header):].strip() for line in head):
            problems.append(f"missing header '{header} ...' in first {HEADER_LINES} lines")
    body = _strip_comments(text)
    if not body.strip():
        problems.append("file contains no SQL")
    for pattern, message in FORBIDDEN:
        if pattern.search(body):
            problems.append(message)
    if DESTRUCTIVE.search(body) and not any(
            line.startswith(DESTRUCTIVE_HEADER) and line[len(DESTRUCTIVE_HEADER):].strip() for line in head):
        problems.append(f"destructive statement needs '{DESTRUCTIVE_HEADER} <PM approval ref>' header")
    return problems


def load_migrations(directory: Path) -> List[Migration]:
    """Return managed migrations sorted by version, or raise with every lint problem."""
    if not directory.is_dir():
        raise MigrationError(f"migration directory not found: {directory}")
    problems: List[str] = []
    found: Dict[str, Migration] = {}
    for path in sorted(directory.iterdir()):
        if path.is_dir() or path.name.startswith("DRAFT_") or path.name.lower() == "readme.md":
            continue
        match = FILE_RE.match(path.name)
        if not match:
            problems.append(f"{path.name}: name must look like 0001_short_description.sql")
            continue
        version, name = match.groups()
        if version == "0000":
            problems.append(f"{path.name}: versions start at 0001")
        if version in found:
            problems.append(f"{path.name}: duplicate version {version} (also {found[version].path.name})")
            continue
        problems.extend(f"{path.name}: {p}" for p in lint_file(path))
        data = _normalised_bytes(path)
        found[version] = Migration(version, name, path, hashlib.sha256(data).hexdigest(), data.decode("utf-8"))
    if problems:
        raise MigrationError("lint failed:\n  - " + "\n  - ".join(problems))
    return [found[v] for v in sorted(found)]


# --------------------------------------------------------------------------- psql

class Psql:
    def __init__(self, command: str, role: Optional[str]):
        self.base = shlex.split(command) + ["-X", "-q", "-v", "ON_ERROR_STOP=1"]
        self.role = role

    def _prefix(self) -> str:
        return f'SET ROLE "{self.role}";\n' if self.role else ""

    def run_script(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(self.base + ["-f", "-"], input=self._prefix() + script,
                              capture_output=True, text=True, encoding="utf-8")

    def query(self, sql: str) -> List[List[str]]:
        result = subprocess.run(self.base + ["-At", "-F", "\x1f", "-f", "-"], input=self._prefix() + sql,
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            raise MigrationError(f"psql query failed: {result.stderr.strip() or result.stdout.strip()}")
        return [line.split("\x1f") for line in result.stdout.splitlines() if line]


def _quote(value: Optional[str]) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


# --------------------------------------------------------------------------- state

@dataclass
class State:
    database: str
    applied: Dict[str, str]  # version -> checksum
    files: List[Migration]

    @property
    def drift(self) -> List[str]:
        by_version = {m.version: m for m in self.files}
        out = []
        for version, checksum in sorted(self.applied.items()):
            if version not in by_version:
                out.append(f"{version}: applied in DB but file is missing")
            elif by_version[version].checksum != checksum:
                out.append(f"{version}: file changed after it was applied ({by_version[version].path.name})")
        return out

    @property
    def pending(self) -> List[Migration]:
        return [m for m in self.files if m.version not in self.applied]

    @property
    def out_of_order(self) -> List[Migration]:
        top = max(self.applied, default="0000")
        return [m for m in self.pending if m.version < top]


def read_state(psql: Psql, directory: Path) -> State:
    files = load_migrations(directory)
    rows = psql.query(
        "SELECT current_database(), to_regclass('career_migration.schema_migrations') IS NOT NULL;")
    database, ledger_exists = rows[0]
    if ledger_exists != "t":
        raise MigrationError(
            "ledger table career_migration.schema_migrations not found (or no privilege). "
            "An administrator must run database/security/DRAFT_00_create_roles_schema.sql and "
            "DRAFT_01_migration_history.sql first.")
    applied = {v.strip(): c for v, c in psql.query(f"SELECT version, checksum FROM {LEDGER} ORDER BY version;")}
    return State(database, applied, files)


def guard_target(args: argparse.Namespace, database: str) -> None:
    if args.target == "staging":
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            raise MigrationError("refusing staging migration from CI: automatic deploys must not run migrations")
        if not args.approval or not APPROVAL_RE.match(args.approval):
            raise MigrationError("staging requires --approval <Redmine/PR approval id>")
        if args.confirm_db != database:
            raise MigrationError(f"staging requires --confirm-db {database!r} (connected database name)")
    elif database == STAGING_DB_NAME:
        raise MigrationError(f"connected to {STAGING_DB_NAME!r} but --target is {args.target!r}; use --target staging")


# --------------------------------------------------------------------------- commands

def cmd_lint(args: argparse.Namespace) -> int:
    migrations = load_migrations(args.dir)
    print(f"LINT=PASS files={len(migrations)}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = read_state(Psql(args.psql, args.role), args.dir)
    print(f"database={state.database} applied={len(state.applied)} pending={len(state.pending)}")
    for m in state.files:
        mark = "applied" if m.version in state.applied else "pending"
        print(f"  {m.version} {mark:8} {m.path.name}")
    for problem in state.drift:
        print(f"  DRIFT {problem}")
    for m in state.out_of_order:
        print(f"  OUT-OF-ORDER {m.path.name}")
    return 1 if state.drift or state.out_of_order else 0


def cmd_verify(args: argparse.Namespace) -> int:
    state = read_state(Psql(args.psql, args.role), args.dir)
    if state.drift or state.out_of_order:
        for problem in state.drift:
            print(f"DRIFT {problem}", file=sys.stderr)
        for m in state.out_of_order:
            print(f"OUT-OF-ORDER {m.path.name}", file=sys.stderr)
        print("VERIFY=FAIL")
        return 1
    print(f"VERIFY=PASS applied={len(state.applied)} pending={len(state.pending)}")
    return 0


def build_apply_script(m: Migration, target: str, approval: Optional[str]) -> str:
    return "\n".join([
        "BEGIN;",
        "SET LOCAL lock_timeout = '10s';",
        "SET LOCAL statement_timeout = '15min';",
        f"SELECT pg_advisory_xact_lock({ADVISORY_LOCK_KEY});",
        "DO $guard$ BEGIN",
        f"  IF EXISTS (SELECT 1 FROM {LEDGER} WHERE version = {_quote(m.version)}) THEN",
        f"    RAISE EXCEPTION 'migration {m.version} is already applied';",
        "  END IF;",
        "END $guard$;",
        f"-- >>> {m.path.name}",
        m.sql.rstrip(),
        f"-- <<< {m.path.name}",
        ";",
        f"INSERT INTO {LEDGER} (version, name, checksum, target_env, approval_ref, execution_ms, runner_version)",
        f"VALUES ({_quote(m.version)}, {_quote(m.name)}, {_quote(m.checksum)}, {_quote(target)}, "
        f"{_quote(approval)}, (extract(epoch FROM clock_timestamp() - now()) * 1000)::integer, "
        f"{_quote(RUNNER_VERSION)});",
        "COMMIT;",
        "",
    ])


def cmd_apply(args: argparse.Namespace) -> int:
    psql = Psql(args.psql, args.role)
    state = read_state(psql, args.dir)
    guard_target(args, state.database)
    if state.drift:
        raise MigrationError("drift detected, nothing applied:\n  - " + "\n  - ".join(state.drift))
    if state.out_of_order:
        names = ", ".join(m.path.name for m in state.out_of_order)
        raise MigrationError(f"out-of-order migration(s) below latest applied version: {names}. "
                             "Renumber them after the latest applied version.")
    todo = [m for m in state.pending if args.to is None or m.version <= args.to]
    if not todo:
        print(f"APPLY=PASS nothing to apply (database={state.database})")
        return 0
    for m in todo:
        if args.dry_run:
            print(f"DRY-RUN would apply {m.path.name} checksum={m.checksum[:12]}")
            continue
        result = psql.run_script(build_apply_script(m, args.target, args.approval))
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise MigrationError(f"{m.path.name} failed and was rolled back; later migrations skipped.\n{detail}")
        print(f"APPLIED {m.path.name}")
    print(f"APPLY=PASS count={0 if args.dry_run else len(todo)} database={state.database}")
    return 0


# --------------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="migration directory")
    parser.add_argument("--psql", default=os.environ.get("MIGRATE_PSQL", "psql"),
                        help="psql command (env MIGRATE_PSQL). Connection via PG* env vars or flags.")
    parser.add_argument("--role", default=os.environ.get("MIGRATE_ROLE", "career_migrator"),
                        help="role to SET before running SQL; '' to disable (env MIGRATE_ROLE)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("lint", help="validate file names and SQL rules (no DB)")
    sub.add_parser("status", help="list applied / pending migrations")
    sub.add_parser("verify", help="fail on checksum drift or out-of-order files")
    apply = sub.add_parser("apply", help="apply pending migrations in order")
    apply.add_argument("--target", required=True, choices=["local", "ci", "staging"])
    apply.add_argument("--to", help="apply up to and including this version (e.g. 0003)")
    apply.add_argument("--approval", help="approval reference, required for staging (e.g. REDMINE-1522)")
    apply.add_argument("--confirm-db", help="must equal the connected database name for staging")
    apply.add_argument("--dry-run", action="store_true", help="show what would run")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    args.role = args.role or None
    if getattr(args, "to", None) and not re.fullmatch(r"\d{4}", args.to):
        print("ERROR --to must be a 4-digit version", file=sys.stderr)
        return 2
    handlers = {"lint": cmd_lint, "status": cmd_status, "verify": cmd_verify, "apply": cmd_apply}
    try:
        return handlers[args.command](args)
    except MigrationError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
