"""Offline Batch Worker: reads a synthetic fixture, validates and summarizes it.

No web requests, database writes, file outputs or scheduling. Use from repo root:
python -m crawler.jobs.run_crawler --source-id jobkorea --run-id training-001
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from crawler.adapters.jobkorea_fixture import FixtureInputError, JobKoreaFixtureAdapter
from crawler.normalizer import InvalidPosting, normalize
from crawler.storage.memory import MemoryPostingStore, PostingStore
from crawler.storage.postgres import PostgresPostingStore, UnsafeDatabaseTarget, connect_local_training_db

DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "jobkorea_synthetic.json"


def run(*, source_id: str, run_id: str, fixture: Path, store: PostingStore | None = None) -> dict:
    if source_id != "jobkorea":
        raise ValueError("Only jobkorea is supported")
    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be blank")
    adapter = JobKoreaFixtureAdapter(fixture)
    normalized = []
    invalid = 0
    # In-memory only; callers can reuse a store across training runs.
    repository = store if store is not None else MemoryPostingStore()
    for raw in adapter.fetch():
        try:
            normalized.append(normalize(raw))
        except InvalidPosting:
            invalid += 1
    keys = [(item.source_code, item.external_posting_id) for item in normalized]
    unique = set(keys)
    inserted = updated = unchanged = 0
    seen_in_batch: set[tuple[str, str]] = set()
    for item in normalized:
        key = (item.source_code, item.external_posting_id)
        if key in seen_in_batch:
            # Duplicate raw rows never overwrite the first accepted row in this batch.
            continue
        seen_in_batch.add(key)
        outcome = repository.upsert(item)
        if outcome == "inserted":
            inserted += 1
        elif outcome == "updated":
            updated += 1
        elif outcome == "unchanged":
            unchanged += 1
        else:
            raise ValueError("Unsupported store result")
    return {
        "run_id": run_id,
        "source_id": adapter.source_code,
        "mode": "synthetic_fixture_only",
        "fetched": len(keys) + invalid,
        "normalized": len(unique),
        "duplicates": len(keys) - len(unique),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "store": "local_postgres" if isinstance(repository, PostgresPostingStore) else "in_memory_only",
        "invalid": invalid,
        "db_writes": inserted + updated if isinstance(repository, PostgresPostingStore) else 0,
        "external_requests": 0,
        "status": "SUCCEEDED" if invalid == 0 and len(keys) == len(unique) else "PARTIAL",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline crawler training worker")
    parser.add_argument("--source-id", required=True, choices=["jobkorea"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--store", choices=["memory", "postgres"], default="memory")
    args = parser.parse_args(argv)
    try:
        if args.store == "postgres":
            dsn = os.environ.get("CRAWLER_LOCAL_DATABASE_URL", "")
            with connect_local_training_db(dsn) as connection:
                repository = PostgresPostingStore(connection)
                summary = run(
                    source_id=args.source_id, run_id=args.run_id,
                    fixture=args.fixture, store=repository,
                )
        else:
            summary = run(source_id=args.source_id, run_id=args.run_id, fixture=args.fixture)
    except (FixtureInputError, ValueError, UnsafeDatabaseTarget) as exc:
        parser.exit(2, f"Fixture validation failed: {exc}\n")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
