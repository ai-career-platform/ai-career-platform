"""T63 STEP 03: end-to-end offline quality gate in the CLI Worker."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler.jobs.run_crawler import DEFAULT_FIXTURE, main, run
from crawler.storage.memory import MemoryPostingStore


class TestWorkerQualityIntegration(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))

    def execute_rows(self, rows, *, store=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rows.json"
            path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return run(source_id="jobkorea", run_id="t63-step03", fixture=path, store=store)

    def test_normal_fixture_has_no_reasons(self):
        result = self.execute_rows(self.rows)
        self.assertEqual((result["status"], result["normalized"], result["review"]), ("SUCCEEDED", 2, 0))
        self.assertEqual(result["reason_counts"], {})

    def test_invalid_record_never_written(self):
        store = MemoryPostingStore()
        result = self.execute_rows([self.rows[0], {**self.rows[1], "title": ""}], store=store)
        self.assertEqual((len(store), result["invalid"], result["inserted"]), (1, 1, 1))
        self.assertEqual(result["reason_counts"], {"INVALID_REQUIRED_FIELD": 1})
        self.assertEqual(result["status"], "PARTIAL")

    def test_duplicate_never_overwrites_first(self):
        store = MemoryPostingStore()
        result = self.execute_rows([self.rows[0], {**self.rows[0], "title": "변조 중복"}], store=store)
        self.assertEqual((result["duplicates"], result["inserted"], len(store)), (1, 1, 1))
        self.assertEqual(result["reason_counts"], {"DUPLICATE_IN_BATCH": 1})
        stored = store.get("jobkorea", self.rows[0]["external_posting_id"])
        self.assertEqual(stored.title, self.rows[0]["title"])

    def test_changed_source_url_is_held_and_existing_row_preserved(self):
        store = MemoryPostingStore()
        self.execute_rows(self.rows, store=store)
        different_url = {**self.rows[0], "source_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/999999"}
        result = self.execute_rows([different_url, self.rows[1]], store=store)
        self.assertEqual((result["review"], result["updated"], result["unchanged"]), (1, 0, 1))
        self.assertEqual(result["reason_counts"], {"REVIEW_IDENTITY_CHANGE": 1})
        stored = store.get("jobkorea", self.rows[0]["external_posting_id"])
        self.assertEqual(stored.source_url, self.rows[0]["source_url"])
        self.assertEqual(result["status"], "PARTIAL")

    def test_normal_title_change_still_updates(self):
        store = MemoryPostingStore()
        self.execute_rows(self.rows, store=store)
        changed = {**self.rows[0], "title": "합성 제목 변경"}
        result = self.execute_rows([changed, self.rows[1]], store=store)
        self.assertEqual((result["updated"], result["unchanged"], result["review"]), (1, 1, 0))
        self.assertEqual(result["status"], "SUCCEEDED")

    def test_repeated_fixture_stays_idempotent(self):
        store = MemoryPostingStore()
        first = self.execute_rows(self.rows, store=store)
        again = self.execute_rows(self.rows, store=store)
        self.assertEqual((first["inserted"], again["unchanged"], again["inserted"]), (2, 2, 0))
        self.assertEqual(len(store), 2)

    def test_issue_summary_has_no_raw_data_or_urls(self):
        bad = {**self.rows[0], "source_url": "https://unauthorized.example/test"}
        result = self.execute_rows([bad])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("unauthorized.example", serialized)
        self.assertNotIn(self.rows[0]["title"], serialized)
        self.assertEqual(result["reason_counts"], {"INVALID_URL": 1})

    def test_cli_partial_exit_one(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rows.json"
            path.write_text(json.dumps([self.rows[0], self.rows[0]], ensure_ascii=False), encoding="utf-8")
            import contextlib
            import io
            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                exit_code = main([
                    "--source-id", "jobkorea", "--run-id", "t63-step03-cli",
                    "--fixture", str(path),
                ])
        self.assertEqual(exit_code, 1)
        summary = json.loads(captured.getvalue())
        self.assertEqual(summary["reason_counts"], {"DUPLICATE_IN_BATCH": 1})

    def test_quality_check_happens_before_any_write(self):
        store = MemoryPostingStore()
        rows = [{**self.rows[0], "title": ""}]
        with patch.object(store, "upsert", side_effect=AssertionError("unexpected DB write")):
            result = self.execute_rows(rows, store=store)
        self.assertEqual((result["inserted"], result["invalid"]), (0, 1))


if __name__ == "__main__":
    unittest.main()
