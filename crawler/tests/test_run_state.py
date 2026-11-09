"""T64 STEP 01 deterministic offline run lifecycle tests (no database)."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from crawler.jobs.run_state import InvalidRunTransition, RunRecord, RunStatus


class TestRunState(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 11, 7, 0, 0, tzinfo=timezone.utc)
        self.pending = RunRecord.pending(run_id="synthetic-01", source_id="jobkorea", requested_at=self.t0)

    def running(self):
        return self.pending.transition(RunStatus.RUNNING, at=self.t0 + timedelta(seconds=1))

    def test_pending_initial_fields(self):
        self.assertEqual(self.pending.status, RunStatus.PENDING)
        self.assertIsNone(self.pending.started_at)
        self.assertIsNone(self.pending.ended_at)

    def test_complete_success(self):
        finished = self.running().transition(
            RunStatus.SUCCEEDED, at=self.t0 + timedelta(seconds=2),
            counters={"fetched": 2, "inserted": 2},
        )
        self.assertEqual(finished.snapshot()["status"], "SUCCEEDED")
        self.assertEqual(finished.snapshot()["counters"], {"fetched": 2, "inserted": 2})
        self.assertEqual(finished.snapshot()["ended_at"], "2026-11-07T00:00:02Z")

    def test_partial(self):
        item = self.running().transition(RunStatus.PARTIAL, at=self.t0 + timedelta(seconds=2))
        self.assertEqual(item.status, RunStatus.PARTIAL)

    def test_failed_safe_code(self):
        item = self.running().transition(
            RunStatus.FAILED, at=self.t0 + timedelta(seconds=2), error_code="WORKER_TIMEOUT"
        )
        self.assertEqual(item.error_code, "WORKER_TIMEOUT")

    def test_pending_cancel(self):
        item = self.pending.transition(RunStatus.CANCELLED, at=self.t0)
        self.assertIsNone(item.started_at)
        self.assertEqual(item.ended_at, self.t0)

    def test_running_cancel(self):
        item = self.running().transition(RunStatus.CANCELLED, at=self.t0 + timedelta(seconds=2))
        self.assertEqual(item.status, RunStatus.CANCELLED)

    def test_reject_invalid_direct_success(self):
        with self.assertRaises(InvalidRunTransition):
            self.pending.transition(RunStatus.SUCCEEDED, at=self.t0)

    def test_reject_repeated_start(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(RunStatus.RUNNING, at=self.t0 + timedelta(seconds=3))

    def test_reject_terminal_restart(self):
        terminal = self.running().transition(RunStatus.SUCCEEDED, at=self.t0 + timedelta(seconds=2))
        with self.assertRaises(InvalidRunTransition):
            terminal.transition(RunStatus.RUNNING, at=self.t0 + timedelta(seconds=3))

    def test_reject_backdated_transition(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(RunStatus.SUCCEEDED, at=self.t0)

    def test_reject_naive_datetime(self):
        with self.assertRaises(ValueError):
            RunRecord.pending(run_id="a", source_id="jobkorea", requested_at=datetime(2026, 11, 7))

    def test_kst_input_converts_to_utc(self):
        kst = timezone(timedelta(hours=9))
        item = RunRecord.pending(
            run_id="local", source_id="jobkorea",
            requested_at=datetime(2026, 11, 7, 9, 0, tzinfo=kst),
        )
        self.assertEqual(item.snapshot()["requested_at"], "2026-11-07T00:00:00Z")

    def test_reject_blank_run_id(self):
        with self.assertRaises(ValueError):
            RunRecord.pending(run_id=" ", source_id="jobkorea", requested_at=self.t0)

    def test_reject_other_source(self):
        with self.assertRaises(ValueError):
            RunRecord.pending(run_id="a", source_id="other", requested_at=self.t0)

    def test_reject_negative_counter(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(
                RunStatus.SUCCEEDED, at=self.t0 + timedelta(seconds=2), counters={"fetched": -1},
            )

    def test_reject_bool_counter(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(
                RunStatus.SUCCEEDED, at=self.t0 + timedelta(seconds=2), counters={"fetched": True},
            )

    def test_reject_unapproved_counter(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(
                RunStatus.SUCCEEDED, at=self.t0 + timedelta(seconds=2),
                counters={"password": 10},
            )

    def test_reject_failed_without_code(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(RunStatus.FAILED, at=self.t0 + timedelta(seconds=2))

    def test_reject_unsafe_error_string(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(
                RunStatus.FAILED, at=self.t0 + timedelta(seconds=2),
                error_code="password=secret",
            )

    def test_reject_non_failed_error_code(self):
        with self.assertRaises(InvalidRunTransition):
            self.running().transition(
                RunStatus.SUCCEEDED, at=self.t0 + timedelta(seconds=2),
                error_code="WORKER_TIMEOUT",
            )

    def test_immutable_transition(self):
        running = self.running()
        self.assertEqual(self.pending.status, RunStatus.PENDING)
        self.assertNotEqual(running, self.pending)

    def test_json_safe_snapshot(self):
        result = self.running().transition(
            RunStatus.SUCCEEDED, at=self.t0 + timedelta(seconds=2),
            counters={"inserted": 2},
        )
        record = json.dumps(result.snapshot())
        self.assertNotIn("password", record)
        self.assertIn('"inserted": 2', record)


if __name__ == "__main__":
    unittest.main()
