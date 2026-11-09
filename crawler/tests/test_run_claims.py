"""T64 STEP 02: atomic offline run claim and collision tests."""
import concurrent.futures
import unittest
from datetime import datetime, timedelta, timezone
from threading import Barrier

from crawler.jobs.run_claims import ClaimRejected, InMemoryRunClaims, RunTrigger, UnknownRun
from crawler.jobs.run_state import InvalidRunTransition, RunStatus


class TestOfflineRunClaims(unittest.TestCase):
    def setUp(self):
        self.registry = InMemoryRunClaims()
        self.t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)

    def claim(self, run_id="run-a", trigger=RunTrigger.MANUAL):
        return self.registry.claim(
            run_id=run_id, source_id="jobkorea", trigger=trigger,
            requested_at=self.t0, started_at=self.t0 + timedelta(seconds=1),
        )

    def finish(self, run_id="run-a", target=RunStatus.SUCCEEDED, **kwargs):
        return self.registry.finish(
            run_id=run_id, target=target, at=self.t0 + timedelta(seconds=2), **kwargs,
        )

    def test_manual_claim_running(self):
        record = self.claim()
        self.assertEqual(record.status, RunStatus.RUNNING)
        self.assertEqual(self.registry.trigger_for("run-a"), RunTrigger.MANUAL)
        self.assertEqual(self.registry.active_run("jobkorea"), "run-a")

    def test_scheduled_claim_running(self):
        self.claim(trigger=RunTrigger.SCHEDULED)
        self.assertEqual(self.registry.trigger_for("run-a"), RunTrigger.SCHEDULED)

    def test_duplicate_run_id_rejected(self):
        self.claim()
        with self.assertRaises(ClaimRejected):
            self.claim()

    def test_different_id_same_source_rejected(self):
        self.claim(trigger=RunTrigger.MANUAL)
        with self.assertRaises(ClaimRejected):
            self.claim(run_id="run-b", trigger=RunTrigger.SCHEDULED)

    def test_scheduled_then_manual_rejected(self):
        self.claim(trigger=RunTrigger.SCHEDULED)
        with self.assertRaises(ClaimRejected):
            self.claim(run_id="run-b", trigger=RunTrigger.MANUAL)

    def test_finish_releases_source(self):
        self.claim()
        result = self.finish(counters={"fetched": 2, "inserted": 2})
        self.assertEqual(result.status, RunStatus.SUCCEEDED)
        self.assertIsNone(self.registry.active_run("jobkorea"))
        self.assertEqual(self.claim(run_id="run-b").status, RunStatus.RUNNING)

    def test_finished_run_id_never_reused(self):
        self.claim()
        self.finish()
        with self.assertRaises(ClaimRejected):
            self.claim(run_id="run-a")

    def test_partial_releases_source(self):
        self.claim()
        self.finish(target=RunStatus.PARTIAL)
        self.assertIsNone(self.registry.active_run("jobkorea"))

    def test_failed_releases_source(self):
        self.claim()
        self.finish(target=RunStatus.FAILED, error_code="WORKER_TIMEOUT")
        self.assertIsNone(self.registry.active_run("jobkorea"))

    def test_cancelled_releases_source(self):
        self.claim()
        self.finish(target=RunStatus.CANCELLED)
        self.assertIsNone(self.registry.active_run("jobkorea"))

    def test_missing_failure_code_keeps_claim(self):
        self.claim()
        with self.assertRaises(InvalidRunTransition):
            self.finish(target=RunStatus.FAILED)
        self.assertEqual(self.registry.active_run("jobkorea"), "run-a")
        self.assertEqual(self.registry.get("run-a").status, RunStatus.RUNNING)

    def test_out_of_order_finish_keeps_claim(self):
        self.claim()
        with self.assertRaises(InvalidRunTransition):
            self.registry.finish(run_id="run-a", target=RunStatus.SUCCEEDED, at=self.t0)
        self.assertEqual(self.registry.active_run("jobkorea"), "run-a")

    def test_finish_unknown_run(self):
        with self.assertRaises(UnknownRun):
            self.finish()

    def test_finish_twice_rejected(self):
        self.claim()
        self.finish()
        with self.assertRaises(InvalidRunTransition):
            self.finish()

    def test_invalid_trigger_no_claim(self):
        with self.assertRaises(ValueError):
            self.claim(trigger="manual")
        self.assertIsNone(self.registry.active_run("jobkorea"))

    def test_invalid_id_no_claim(self):
        with self.assertRaises(ValueError):
            self.claim(run_id=" ")
        self.assertIsNone(self.registry.active_run("jobkorea"))

    def test_bad_time_no_claim(self):
        with self.assertRaises(InvalidRunTransition):
            self.registry.claim(
                run_id="run-a", source_id="jobkorea", trigger=RunTrigger.MANUAL,
                requested_at=self.t0, started_at=self.t0 - timedelta(seconds=1),
            )
        self.assertIsNone(self.registry.active_run("jobkorea"))

    def test_get_absent_returns_none(self):
        self.assertIsNone(self.registry.get("missing"))
        self.assertIsNone(self.registry.trigger_for("missing"))

    def test_threads_competing_same_source_exactly_one_wins(self):
        barrier = Barrier(8)

        def attempt(index):
            barrier.wait(timeout=5)
            try:
                self.claim(run_id=f"parallel-{index}", trigger=(
                    RunTrigger.SCHEDULED if index % 2 else RunTrigger.MANUAL
                ))
                return True
            except ClaimRejected:
                return False

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(attempt, range(8)))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 7)


if __name__ == "__main__":
    unittest.main()
