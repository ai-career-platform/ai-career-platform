"""T64 STEP 03: deterministic heartbeat and retry policy tests, no I/O."""
import unittest
from datetime import datetime, timedelta, timezone

from crawler.jobs.offline_recovery import (
    OfflineHeartbeatMonitor, RecoveryDecision, RecoveryPolicy, retry_decision,
)
from crawler.jobs.run_claims import InMemoryRunClaims, RunTrigger, UnknownRun
from crawler.jobs.run_state import RunStatus


class TestOfflineRecovery(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
        self.claims = InMemoryRunClaims()
        self.claims.claim(
            run_id="a", source_id="jobkorea", trigger=RunTrigger.SCHEDULED,
            requested_at=self.t0, started_at=self.t0 + timedelta(seconds=1),
        )
        self.policy = RecoveryPolicy(heartbeat_timeout=timedelta(seconds=10), max_attempts=3)
        self.monitor = OfflineHeartbeatMonitor(self.claims, self.policy)

    def at(self, seconds):
        return self.t0 + timedelta(seconds=seconds)

    def test_fresh_run_waits(self):
        self.assertEqual(self.monitor.inspect(run_id="a", at=self.at(9)), RecoveryDecision.WAIT)
        self.assertEqual(self.claims.active_run("jobkorea"), "a")

    def test_at_exact_timeout_expires(self):
        result = self.monitor.inspect(run_id="a", at=self.at(11))
        self.assertEqual(result, RecoveryDecision.RETRY_ELIGIBLE)
        self.assertEqual(self.claims.get("a").status, RunStatus.FAILED)
        self.assertEqual(self.claims.get("a").error_code, "HEARTBEAT_TIMEOUT")
        self.assertIsNone(self.claims.active_run("jobkorea"))

    def test_heartbeat_extends_deadline(self):
        self.monitor.heartbeat(run_id="a", at=self.at(8))
        self.assertEqual(self.monitor.inspect(run_id="a", at=self.at(17)), RecoveryDecision.WAIT)
        self.assertEqual(self.monitor.inspect(run_id="a", at=self.at(18)), RecoveryDecision.RETRY_ELIGIBLE)

    def test_inspection_does_not_change_running_before_timeout(self):
        self.monitor.inspect(run_id="a", at=self.at(10))
        self.assertEqual(self.claims.get("a").status, RunStatus.RUNNING)

    def test_stale_inspect_twice_no_double_finish(self):
        self.monitor.inspect(run_id="a", at=self.at(11))
        self.assertEqual(self.monitor.inspect(run_id="a", at=self.at(12)), RecoveryDecision.NO_ACTION)

    def test_new_run_after_expiry_uses_distinct_id(self):
        self.monitor.inspect(run_id="a", at=self.at(11))
        second = self.claims.claim(
            run_id="b", source_id="jobkorea", trigger=RunTrigger.MANUAL,
            requested_at=self.at(12), started_at=self.at(12),
        )
        self.assertEqual(second.status, RunStatus.RUNNING)

    def test_heartbeat_unknown_run_rejected(self):
        with self.assertRaises(UnknownRun):
            self.monitor.heartbeat(run_id="unknown", at=self.at(2))

    def test_inspect_unknown_run_rejected(self):
        with self.assertRaises(UnknownRun):
            self.monitor.inspect(run_id="unknown", at=self.at(2))

    def test_heartbeat_on_terminal_run_rejected(self):
        self.claims.finish(run_id="a", target=RunStatus.SUCCEEDED, at=self.at(3))
        with self.assertRaises(ValueError):
            self.monitor.heartbeat(run_id="a", at=self.at(4))

    def test_inspect_finished_run_no_action(self):
        self.claims.finish(run_id="a", target=RunStatus.SUCCEEDED, at=self.at(3))
        self.assertEqual(self.monitor.inspect(run_id="a", at=self.at(99)), RecoveryDecision.NO_ACTION)

    def test_backdated_heartbeat_rejected(self):
        with self.assertRaises(ValueError):
            self.monitor.heartbeat(run_id="a", at=self.at(0))

    def test_regressing_heartbeat_rejected(self):
        self.monitor.heartbeat(run_id="a", at=self.at(6))
        with self.assertRaises(ValueError):
            self.monitor.heartbeat(run_id="a", at=self.at(5))

    def test_backdated_inspection_rejected(self):
        self.monitor.heartbeat(run_id="a", at=self.at(7))
        with self.assertRaises(ValueError):
            self.monitor.inspect(run_id="a", at=self.at(6))

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            self.monitor.inspect(run_id="a", at=datetime(2026, 11, 7))

    def test_retry_after_transient_timeout(self):
        self.assertEqual(
            retry_decision(error_code="WORKER_TIMEOUT", attempt=1, policy=self.policy),
            RecoveryDecision.RETRY_ELIGIBLE,
        )

    def test_heartbeat_timeout_can_retry(self):
        self.assertEqual(
            retry_decision(error_code="HEARTBEAT_TIMEOUT", attempt=2, policy=self.policy),
            RecoveryDecision.RETRY_ELIGIBLE,
        )

    def test_transient_io_can_retry(self):
        self.assertEqual(
            retry_decision(error_code="TEMPORARY_IO", attempt=1, policy=self.policy),
            RecoveryDecision.RETRY_ELIGIBLE,
        )

    def test_retry_budget_exhausted(self):
        self.assertEqual(
            retry_decision(error_code="WORKER_TIMEOUT", attempt=3, policy=self.policy),
            RecoveryDecision.STOP_LIMIT,
        )

    def test_access_forbidden_never_retry(self):
        self.assertEqual(
            retry_decision(error_code="ACCESS_FORBIDDEN", attempt=1, policy=self.policy),
            RecoveryDecision.STOP_NONRETRYABLE,
        )

    def test_rate_limit_never_retry(self):
        self.assertEqual(
            retry_decision(error_code="RATE_LIMITED", attempt=1, policy=self.policy),
            RecoveryDecision.STOP_NONRETRYABLE,
        )

    def test_unapproved_source_never_retry(self):
        self.assertEqual(
            retry_decision(error_code="UNAPPROVED_SOURCE", attempt=1, policy=self.policy),
            RecoveryDecision.STOP_NONRETRYABLE,
        )

    def test_unknown_failure_never_retry(self):
        self.assertEqual(
            retry_decision(error_code="SOMETHING_ELSE", attempt=1, policy=self.policy),
            RecoveryDecision.STOP_NONRETRYABLE,
        )

    def test_invalid_attempt_rejected(self):
        for attempt in (0, 4, True):
            with self.subTest(attempt=attempt), self.assertRaises(ValueError):
                retry_decision(error_code="WORKER_TIMEOUT", attempt=attempt, policy=self.policy)

    def test_invalid_policy_rejected(self):
        for kwargs in (
            {"max_attempts": 0},
            {"max_attempts": 6},
            {"max_attempts": True},
            {"heartbeat_timeout": timedelta(0)},
            {"heartbeat_timeout": timedelta(hours=2)},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RecoveryPolicy(**kwargs)

    def test_kst_heartbeat_boundary(self):
        kst = timezone(timedelta(hours=9))
        at_kst = datetime(2026, 11, 7, 9, 0, 8, tzinfo=kst)
        self.monitor.heartbeat(run_id="a", at=at_kst)
        self.assertEqual(self.monitor.inspect(run_id="a", at=self.at(17)), RecoveryDecision.WAIT)


if __name__ == "__main__":
    unittest.main()
