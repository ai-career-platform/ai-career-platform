"""T61 STEP 09: verify no live collection side effects on any entrypoint."""
import unittest
from pathlib import Path
from unittest.mock import patch

from crawler.jobs import run_crawler

URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/50246410"


class TestWorkerCollectionBoundary(unittest.TestCase):
    def test_programmatic_live_mode_refused_before_fixture(self):
        with patch.object(run_crawler, "JobKoreaFixtureAdapter") as adapter:
            with self.assertRaisesRegex(ValueError, "Live collection is disabled"):
                run_crawler.run(source_id="jobkorea", run_id="trial", fixture=Path("missing.json"),
                                collection_mode="live_jobkorea")
            adapter.assert_not_called()

    def test_programmatic_unknown_mode_refused(self):
        with self.assertRaisesRegex(ValueError, "Live collection is disabled"):
            run_crawler.run(source_id="jobkorea", run_id="trial", fixture=Path("missing.json"),
                            collection_mode="external_api")

    def test_programmatic_live_refused_before_store(self):
        class TrapStore:
            def __init__(self):
                self.calls = 0
            def get(self, *args):
                self.calls += 1
                raise AssertionError("Never access store")
            def upsert(self, *args):
                self.calls += 1
                raise AssertionError("Never write")
        store = TrapStore()
        with self.assertRaises(ValueError):
            run_crawler.run(source_id="jobkorea", run_id="trial", fixture=Path("missing.json"),
                            store=store, collection_mode="live_jobkorea")
        self.assertEqual(store.calls, 0)

    def test_cli_live_memory_refused_before_adapter(self):
        with patch.object(run_crawler, "JobKoreaFixtureAdapter") as adapter:
            with self.assertRaises(SystemExit) as caught:
                run_crawler.main(["--source-id", "jobkorea", "--run-id", "trial",
                                  "--collection-mode", "live_jobkorea"])
            self.assertEqual(caught.exception.code, 2)
            adapter.assert_not_called()

    def test_cli_live_postgres_refused_before_db_connect(self):
        with patch.object(run_crawler, "connect_local_training_db") as connect:
            with self.assertRaises(SystemExit) as caught:
                run_crawler.main(["--source-id", "jobkorea", "--run-id", "trial",
                                  "--collection-mode", "live_jobkorea", "--store", "postgres"])
            self.assertEqual(caught.exception.code, 2)
            connect.assert_not_called()

    def test_cli_live_refused_even_with_valid_looking_fixture(self):
        with patch.object(run_crawler, "JobKoreaFixtureAdapter") as adapter:
            with self.assertRaises(SystemExit):
                run_crawler.main(["--source-id", "jobkorea", "--run-id", "trial",
                                  "--fixture", str(run_crawler.DEFAULT_FIXTURE),
                                  "--collection-mode", "live_jobkorea"])
            adapter.assert_not_called()

    def test_cli_unknown_mode_is_not_accepted(self):
        with patch.object(run_crawler, "JobKoreaFixtureAdapter") as adapter:
            with self.assertRaises(SystemExit) as caught:
                run_crawler.main(["--source-id", "jobkorea", "--run-id", "trial",
                                  "--collection-mode", "external_api"])
            self.assertEqual(caught.exception.code, 2)
            adapter.assert_not_called()

    def test_programmatic_default_synthetic_remains_usable(self):
        result = run_crawler.run(source_id="jobkorea", run_id="trial",
                                 fixture=run_crawler.DEFAULT_FIXTURE)
        self.assertEqual(result["mode"], "synthetic_fixture_only")
        self.assertEqual(result["external_requests"], 0)
        self.assertEqual(result["db_writes"], 0)

    def test_programmatic_explicit_synthetic_mode_works(self):
        result = run_crawler.run(source_id="jobkorea", run_id="trial",
                                 fixture=run_crawler.DEFAULT_FIXTURE,
                                 collection_mode="synthetic_fixture_only")
        self.assertEqual(result["mode"], "synthetic_fixture_only")

    def test_fake_policy_cannot_enable_live(self):
        # STEP08 synthetic APPROVED object MUST NOT unlock the worker.
        from crawler.tests.test_source_approval_gate import synthetic_approval
        policy = synthetic_approval()
        self.assertEqual(policy.approval_status, "APPROVED")
        with self.assertRaises(ValueError):
            run_crawler.run(source_id="jobkorea", run_id="trial",
                            fixture=run_crawler.DEFAULT_FIXTURE,
                            collection_mode="live_jobkorea")

if __name__ == "__main__":
    unittest.main()
