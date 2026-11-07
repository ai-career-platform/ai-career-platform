
"""Offline Batch Worker for synthetic JobKorea fixture training."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from crawler.adapters.jobkorea_fixture import (
    FixtureInputError,
    JobKoreaFixtureAdapter,
)
from crawler.normalizer import InvalidPosting, normalize
from crawler.quality.batch_gate import check_synthetic_batch
from crawler.storage.memory import MemoryPostingStore, PostingStore
from crawler.storage.postgres import (
    PostgresPostingStore,
    UnsafeDatabaseTarget,
    connect_local_training_db,
)

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "jobkorea_synthetic.json"
)


def run(
    *,
    source_id: str,
    run_id: str,
    fixture: Path,
    store: PostingStore | None = None,
) -> dict:
    if source_id != "jobkorea":
        raise ValueError("Only jobkorea is supported")

    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be blank")

    adapter = JobKoreaFixtureAdapter(fixture)
    repository = store if store is not None else MemoryPostingStore()
    rows = adapter.fetch()

    # Quality checks run before *any* insert/update. A changed source URL for
    # an existing external ID must be reviewed, not silently overwritten.
    previous = {}
    for raw in rows:
        try:
            candidate = normalize(raw)
        except InvalidPosting:
            continue
        key = (candidate.source_code, candidate.external_posting_id)
        if key not in previous:
            old = repository.get(*key)
            if old is not None:
                previous[key] = old

    quality = check_synthetic_batch(rows, previous=previous)
    inserted = updated = unchanged = 0
    for item in quality.accepted:
        outcome = repository.upsert(item)
        if outcome == "inserted":
            inserted += 1
        elif outcome == "updated":
            updated += 1
        elif outcome == "unchanged":
            unchanged += 1
        else:
            raise ValueError("Unsupported store result")

    reasons: dict[str, int] = {}
    for issue in quality.issues:
        reasons[issue.reason.value] = reasons.get(issue.reason.value, 0) + 1

    is_postgres = isinstance(repository, PostgresPostingStore)
    return {
        "run_id": run_id,
        "source_id": adapter.source_code,
        "mode": "synthetic_fixture_only",
        "fetched": quality.fetched,
        "normalized": len(quality.accepted),
        "duplicates": quality.duplicate,
        "review": quality.review,
        "reason_counts": dict(sorted(reasons.items())),
        "inserted": inserted,
        "updated": updated,
        "unchanged": unchanged,
        "store": "local_postgres" if is_postgres else "in_memory_only",
        "invalid": quality.invalid,
        "db_writes": inserted + updated if is_postgres else 0,
        "external_requests": 0,
        "status": (
            "SUCCEEDED"
            if quality.invalid == 0 and quality.duplicate == 0 and quality.review == 0
            else "PARTIAL"
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline crawler training worker"
    )

    parser.add_argument(
        "--source-id",
        required=True,
        choices=["jobkorea"],
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
    )
    parser.add_argument(
        "--store",
        choices=["memory", "postgres"],
        default="memory",
    )

    args = parser.parse_args(argv)

    try:
        if args.store == "postgres":
            # 기본 memory 실행에는 psycopg 설치가 필요하지 않음
            import psycopg

            dsn = os.environ.get(
                "CRAWLER_LOCAL_DATABASE_URL",
                "",
            )

            try:
                with connect_local_training_db(dsn) as connection:
                    repository = PostgresPostingStore(connection)

                    summary = run(
                        source_id=args.source_id,
                        run_id=args.run_id,
                        fixture=args.fixture,
                        store=repository,
                    )

            except UnsafeDatabaseTarget as exc:
                parser.exit(
                    2,
                    f"Database configuration error: {exc}\n",
                )

            except psycopg.Error:
                # 접속 문자열, SQL, 인증정보 등을 출력하지 않음
                parser.exit(
                    3,
                    "PostgreSQL connection or operation failed\n",
                )

        else:
            summary = run(
                source_id=args.source_id,
                run_id=args.run_id,
                fixture=args.fixture,
            )

    except FixtureInputError as exc:
        parser.exit(
            2,
            f"Fixture validation failed: {exc}\n",
        )

    except ValueError as exc:
        parser.exit(
            2,
            f"Worker validation failed: {exc}\n",
        )

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
        )
    )

    return 0 if summary["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
