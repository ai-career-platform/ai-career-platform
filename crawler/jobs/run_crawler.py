"""Offline Batch Worker: reads a synthetic fixture, validates and summarizes it.

No web requests, database writes, file outputs or scheduling. Use from repo root:
python -m crawler.jobs.run_crawler --source-id jobkorea --run-id training-001
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from crawler.adapters.jobkorea_fixture import FixtureInputError, JobKoreaFixtureAdapter
from crawler.normalizer import InvalidPosting, normalize

DEFAULT_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "jobkorea_synthetic.json"


def run(*, source_id: str, run_id: str, fixture: Path) -> dict:
    if source_id != "jobkorea":
        raise ValueError("Only jobkorea is supported")
    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be blank")
    adapter = JobKoreaFixtureAdapter(fixture)
    normalized = []
    invalid = 0
    for raw in adapter.fetch():
        try:
            normalized.append(normalize(raw))
        except InvalidPosting:
            invalid += 1
    keys = [(item.source_code, item.external_posting_id) for item in normalized]
    unique = set(keys)
    return {
        "run_id": run_id,
        "source_id": adapter.source_code,
        "mode": "synthetic_fixture_only",
        "fetched": len(keys) + invalid,
        "normalized": len(unique),
        "duplicates": len(keys) - len(unique),
        "invalid": invalid,
        "db_writes": 0,
        "external_requests": 0,
        "status": "SUCCEEDED" if invalid == 0 and len(keys) == len(unique) else "PARTIAL",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline crawler training worker")
    parser.add_argument("--source-id", required=True, choices=["jobkorea"])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    args = parser.parse_args(argv)
    try:
        summary = run(source_id=args.source_id, run_id=args.run_id, fixture=args.fixture)
    except (FixtureInputError, ValueError) as exc:
        parser.exit(2, f"Fixture validation failed: {exc}\n")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if summary["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
