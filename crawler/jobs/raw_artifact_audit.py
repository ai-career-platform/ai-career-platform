"""T152 raw artifact reconciliation and retention plan — READ ONLY, never deletes.

Fills the T152.md item 4 gap ("보존기한·삭제·실패 시 고아 파일 복구 설계"):

- `reconcile()` compares the content-addressed store with `crawler_training.raw_artifacts` rows.
  It reports orphan files, missing files, size/hash mismatches, temp leftovers, unsafe entries and
  loose permissions. The store's own rule stands: orphans are never deleted automatically.
- `retention_plan()` lists which stored files would become *eligible for review* after `keep_days`.
  A file is shared by every row with the same sha256, so it is eligible only when **all** its rows are
  older than the cut-off. Rows referenced by a parse lineage row (0006) are reported separately
  because deleting their bytes breaks Raw→Parsed re-verification.
  The plan is advisory: there is no delete function here. Deleting needs a PM-approved retention
  period and a separate, reviewed operation.

Output contains storage keys, counts and sizes only — never HTML bytes, URLs or keywords.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Iterable

_KEY = re.compile(r"^([0-9a-f]{2})/([0-9a-f]{64})\.html$")


@dataclass(frozen=True)
class ArtifactRow:
    artifact_id: str
    sha256: str
    storage_key: str
    byte_size: int
    captured_at: datetime


@dataclass
class ReconcileReport:
    files_on_disk: int = 0
    rows: int = 0
    distinct_keys: int = 0
    ok: int = 0
    orphan_files: list[str] = field(default_factory=list)       # on disk, no row
    missing_files: list[str] = field(default_factory=list)      # row, no file
    hash_mismatch: list[str] = field(default_factory=list)      # bytes ≠ name / ≠ row sha
    size_mismatch: list[str] = field(default_factory=list)      # row byte_size ≠ file size
    invalid_rows: list[str] = field(default_factory=list)       # storage_key not derived from sha256
    temp_leftovers: list[str] = field(default_factory=list)     # interrupted writes (.tmp-*)
    unsafe_entries: list[str] = field(default_factory=list)     # symlinks, unexpected names/dirs
    loose_permissions: list[str] = field(default_factory=list)  # POSIX only: dir > 0700, file > 0600

    @property
    def clean(self) -> bool:
        return not any((self.orphan_files, self.missing_files, self.hash_mismatch, self.size_mismatch,
                        self.invalid_rows, self.temp_leftovers, self.unsafe_entries, self.loose_permissions))

    def to_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items()}
        data["clean"] = self.clean
        return data


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _loose(path: Path, limit: int) -> bool:
    if os.name != "posix":
        return False                                   # Windows has no POSIX mode bits; reported as not checked
    return bool(stat.S_IMODE(path.lstat().st_mode) & ~limit)


def reconcile(root: Path, rows: Iterable[ArtifactRow], *, verify_hash: bool = True) -> ReconcileReport:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("raw artifact root must be an existing, non-symlink directory")
    root = root.resolve()
    report = ReconcileReport()
    rows = list(rows)
    report.rows = len(rows)
    by_key: dict[str, list[ArtifactRow]] = {}
    for row in rows:
        if row.storage_key != f"{row.sha256[:2]}/{row.sha256}.html" or not _KEY.match(row.storage_key):
            report.invalid_rows.append(row.artifact_id)
            continue
        by_key.setdefault(row.storage_key, []).append(row)
    report.distinct_keys = len(by_key)
    if _loose(root, 0o700):
        report.loose_permissions.append(".")

    seen: set[str] = set()
    for entry in sorted(root.rglob("*")):
        rel = _rel(root, entry)
        if entry.is_symlink():
            report.unsafe_entries.append(rel)
            continue
        if entry.is_dir():
            if not re.fullmatch(r"[0-9a-f]{2}", rel):
                report.unsafe_entries.append(rel)
            elif _loose(entry, 0o700):
                report.loose_permissions.append(rel)
            continue
        if entry.name.startswith(".tmp-"):
            report.temp_leftovers.append(rel)
            continue
        match = _KEY.match(rel)
        if not match or match.group(1) != match.group(2)[:2]:
            report.unsafe_entries.append(rel)
            continue
        report.files_on_disk += 1
        seen.add(rel)
        if _loose(entry, 0o600):
            report.loose_permissions.append(rel)
        size = entry.stat().st_size
        owners = by_key.get(rel)
        if not owners:
            report.orphan_files.append(rel)
            continue
        problem = False
        if any(o.byte_size != size for o in owners):
            report.size_mismatch.append(rel)
            problem = True
        if verify_hash and sha256(entry.read_bytes()).hexdigest() != match.group(2):
            report.hash_mismatch.append(rel)
            problem = True
        if not problem:
            report.ok += 1
    report.missing_files = sorted(k for k in by_key if k not in seen)
    return report


@dataclass
class RetentionPlan:
    cutoff: str
    keep_days: int
    files_total: int = 0
    eligible_files: list[str] = field(default_factory=list)
    eligible_bytes: int = 0
    held_by_newer_row: list[str] = field(default_factory=list)     # same bytes captured again recently
    held_by_lineage: list[str] = field(default_factory=list)       # Raw→Parsed lineage depends on it

    def to_dict(self) -> dict:
        return dict(self.__dict__, eligible_count=len(self.eligible_files), action="REVIEW_ONLY_NO_DELETE")


def retention_plan(rows: Iterable[ArtifactRow], lineage_artifact_ids: Iterable[str], *, now: datetime,
                   keep_days: int) -> RetentionPlan:
    if not 1 <= keep_days <= 3650:
        raise ValueError("keep_days must be between 1 and 3650")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    cutoff = now - timedelta(days=keep_days)
    lineage = set(map(str, lineage_artifact_ids))
    by_key: dict[str, list[ArtifactRow]] = {}
    for row in rows:
        by_key.setdefault(row.storage_key, []).append(row)
    plan = RetentionPlan(cutoff=cutoff.isoformat(), keep_days=keep_days, files_total=len(by_key))
    for key in sorted(by_key):
        owners = by_key[key]
        if any(o.captured_at >= cutoff for o in owners):
            if any(o.captured_at < cutoff for o in owners):
                plan.held_by_newer_row.append(key)
            continue
        if any(str(o.artifact_id) in lineage for o in owners):
            plan.held_by_lineage.append(key)
            continue
        plan.eligible_files.append(key)
        plan.eligible_bytes += owners[0].byte_size
    return plan


# ---------------------------------------------------------------- PostgreSQL (read-only)
def load_rows(connection) -> tuple[list[ArtifactRow], list[str]]:
    """Reads metadata in a READ ONLY transaction. Requires SELECT on raw_artifacts and raw_parse_results."""
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        rows = [ArtifactRow(str(r[0]), r[1], r[2], r[3], r[4]) for r in connection.execute(
            "SELECT artifact_id, sha256, storage_key, byte_size, captured_at "
            "FROM crawler_training.raw_artifacts ORDER BY captured_at, artifact_id").fetchall()]
        lineage = [str(r[0]) for r in connection.execute(
            "SELECT DISTINCT artifact_id FROM crawler_training.raw_parse_results").fetchall()]
    return rows, lineage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T152 read-only raw artifact reconcile + retention plan")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--dsn-env", default="CRAWLER_LOCAL_DATABASE_URL",
                        help="name of the environment variable holding the DSN (the DSN is never printed)")
    parser.add_argument("--keep-days", type=int, default=30)
    parser.add_argument("--no-hash", action="store_true", help="skip SHA-256 re-hash (size check only)")
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        parser.error(f"{args.dsn_env} is not set")
    import psycopg
    with psycopg.connect(dsn) as connection:
        rows, lineage = load_rows(connection)
    report = reconcile(args.root, rows, verify_hash=not args.no_hash)
    plan = retention_plan(rows, lineage, now=datetime.now(timezone.utc), keep_days=args.keep_days)
    print(json.dumps({"reconcile": report.to_dict(), "retention": plan.to_dict()}, ensure_ascii=False, indent=1))
    return 0 if report.clean else 2


if __name__ == "__main__":
    raise SystemExit(main())
