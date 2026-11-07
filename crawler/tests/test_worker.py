"""Offline Adapter and Batch Worker contract tests."""
import json
import tempfile
import unittest
from pathlib import Path

from crawler.adapters.jobkorea_fixture import FixtureInputError, JobKoreaFixtureAdapter
from crawler.jobs.run_crawler import DEFAULT_FIXTURE, main, run


class TestFixtureAdapterAndWorker(unittest.TestCase):
    def test_fixture_adapter_loads_two_postings(self):
        adapter = JobKoreaFixtureAdapter(DEFAULT_FIXTURE)
        self.assertEqual(adapter.source_code, "jobkorea")
        self.assertEqual(len(adapter.fetch()), 2)

    def test_worker_summary(self):
        result = run(source_id="jobkorea", run_id="test-run-001", fixture=DEFAULT_FIXTURE)
        self.assertEqual(
            (result["fetched"], result["normalized"], result["duplicates"], result["invalid"]),
            (2, 2, 0, 0),
        )
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual((result["external_requests"], result["db_writes"]), (0, 0))

    def test_reject_other_source(self):
        with self.assertRaises(ValueError):
            run(source_id="other", run_id="test", fixture=DEFAULT_FIXTURE)

    def test_reject_blank_run_id(self):
        with self.assertRaises(ValueError):
            run(source_id="jobkorea", run_id=" ", fixture=DEFAULT_FIXTURE)

    def test_invalid_json_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{bad", encoding="utf-8")
            with self.assertRaises(FixtureInputError):
                JobKoreaFixtureAdapter(path).fetch()

    def test_invalid_fixture_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text('{"not":"a list"}', encoding="utf-8")
            with self.assertRaises(FixtureInputError):
                JobKoreaFixtureAdapter(path).fetch()

    def test_duplicate_and_invalid_summary(self):
        original = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))
        original += [original[0], {**original[0], "title": ""}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            result = run(source_id="jobkorea", run_id="test", fixture=path)
        self.assertEqual(
            (result["fetched"], result["normalized"], result["duplicates"], result["invalid"]),
            (4, 2, 1, 1),
        )
        self.assertEqual(result["status"], "PARTIAL")

    def test_main_success(self):
        from contextlib import redirect_stdout
        from io import StringIO
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = main(["--source-id", "jobkorea", "--run-id", "test"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(buffer.getvalue())["mode"], "synthetic_fixture_only")


if __name__ == "__main__":
    unittest.main()
