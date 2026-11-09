"""Opt-in LOCAL PostgreSQL integration tests; all test writes are rolled back.

NOT included in normal unittest discovery (filename starts with local_, not test_).
Run explicitly only against ai_career_crawler_training with a dedicated role.
Existing training rows are never updated: every test uses random synthetic IDs.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from crawler.jobs.run_crawler import DEFAULT_FIXTURE, run
from crawler.storage.postgres import (
    PostgresPostingStore,
    connect_local_training_db,
    validate_local_dsn,
)


class _RollbackTest(Exception):
    """Private sentinel: exit outer transaction with rollback."""


class TestLocalPostgresRollback(unittest.TestCase):
    def setUp(self):
        if os.environ.get("CRAWLER_LOCAL_PG_TEST") != "1":
            self.skipTest("Opt-in required: CRAWLER_LOCAL_PG_TEST=1")
        dsn = os.environ.get("CRAWLER_LOCAL_DATABASE_URL", "")
        # Reject unsafe targets *before* any DB connection or SQL.
        validate_local_dsn(dsn)
        self.dsn = dsn
        self.rows = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        token = uuid4().hex
        for i, row in enumerate(self.rows):
            row["external_posting_id"] = f"SYNTH-T63-PG-{token}-{i}"

    def execute(self, rows, repository):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "synthetic.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return run(
                source_id="jobkorea",
                run_id="t63-step04-rollback-validation",
                fixture=path,
                store=repository,
            )

    def test_insert_unchanged_update_all_rollback(self):
        with connect_local_training_db(self.dsn) as conn:
            store = PostgresPostingStore(conn)
            try:
                with conn.transaction():
                    first = self.execute(self.rows, store)
                    self.assertEqual((first["inserted"], first["db_writes"], first["status"]), (2, 2, "SUCCEEDED"))
                    again = self.execute(self.rows, store)
                    self.assertEqual((again["unchanged"], again["db_writes"]), (2, 0))
                    changed = [{**self.rows[0], "title": "합성 테스트 제목 변경"}, self.rows[1]]
                    updated = self.execute(changed, store)
                    self.assertEqual((updated["updated"], updated["unchanged"], updated["db_writes"]), (1, 1, 1))
                    raise _RollbackTest()
            except _RollbackTest:
                pass
            for row in self.rows:
                self.assertIsNone(store.get("jobkorea", row["external_posting_id"]))

    def test_invalid_duplicate_review_never_writes_and_rollback(self):
        with connect_local_training_db(self.dsn) as conn:
            store = PostgresPostingStore(conn)
            try:
                with conn.transaction():
                    inserted = self.execute(self.rows[:1], store)
                    self.assertEqual(inserted["inserted"], 1)
                    changed_url = {
                        **self.rows[0],
                        "source_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/999999",
                    }
                    invalid = {**self.rows[1], "title": ""}
                    mixed = self.execute([changed_url, invalid, invalid, self.rows[1], self.rows[1]], store)
                    self.assertEqual(
                        (mixed["review"], mixed["invalid"], mixed["duplicates"], mixed["inserted"]),
                        (1, 2, 1, 1),
                    )
                    self.assertEqual(mixed["db_writes"], 1)
                    self.assertEqual(mixed["reason_counts"], {
                        "DUPLICATE_IN_BATCH": 1,
                        "INVALID_REQUIRED_FIELD": 2,
                        "REVIEW_IDENTITY_CHANGE": 1,
                    })
                    original = store.get("jobkorea", self.rows[0]["external_posting_id"])
                    self.assertEqual(original.source_url, self.rows[0]["source_url"])
                    raise _RollbackTest()
            except _RollbackTest:
                pass
            for row in self.rows:
                self.assertIsNone(store.get("jobkorea", row["external_posting_id"]))


if __name__ == "__main__":
    unittest.main()
