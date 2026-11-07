"""T64 STEP 04: end-to-end synthetic claim, worker, report, recovery tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.jobs.offline_recovery import (
    OfflineHeartbeatMonitor, RecoveryDecision, RecoveryPolicy, retry_decision,
)
from crawler.jobs.offline_run_report import finish_from_worker
from crawler.jobs.run_claims import ClaimRejected, InMemoryRunClaims, RunTrigger
from crawler.jobs.run_state import RunStatus
from crawler.jobs.run_crawler import DEFAULT_FIXTURE, run
from crawler.storage.memory import MemoryPostingStore


class TestOfflineRunIntegration(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 11, 7, tzinfo=timezone.utc)
        self.claims = InMemoryRunClaims()
        self.store = MemoryPostingStore()
        self.rows = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))

    def at(self, sec):
        return self.t0 + timedelta(seconds=sec)

    def claim(self, run_id="trial-1", at=1, trigger=RunTrigger.MANUAL):
        return self.claims.claim(
            run_id=run_id, source_id="jobkorea", trigger=trigger,
            requested_at=self.t0, started_at=self.at(at),
        )

    def execute(self, run_id, rows=None):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / "synthetic.json"
            fixture.write_text(json.dumps(self.rows if rows is None else rows, ensure_ascii=False), encoding="utf-8")
            return run(
                source_id="jobkorea", run_id=run_id, fixture=fixture, store=self.store,
            )

    def complete(self, run_id, summary, at=3):
        return finish_from_worker(
            self.claims, run_id=run_id, summary=summary, finished_at=self.at(at),
        )

    def test_successful_claim_worker_and_report(self):
        self.claim()
        snapshot = self.complete("trial-1", self.execute("trial-1"))
        self.assertEqual(snapshot["status"], "SUCCEEDED")
        self.assertEqual(snapshot["counters"]["inserted"], 2)
        self.assertEqual(snapshot["counters"]["external_requests"], 0)
        self.assertEqual(snapshot["started_at"], "2026-11-07T00:00:01Z")
        self.assertIsNone(snapshot["error_code"])
        self.assertIsNone(self.claims.active_run("jobkorea"))

    def test_replay_new_id_no_duplicate_insert(self):
        self.claim()
        self.complete("trial-1", self.execute("trial-1"))
        self.claim("trial-2", at=4, trigger=RunTrigger.SCHEDULED)
        snapshot = self.complete("trial-2", self.execute("trial-2"), at=5)
        self.assertEqual((snapshot["counters"]["inserted"], snapshot["counters"]["unchanged"]), (0, 2))
        self.assertEqual(len(self.store), 2)

    def test_same_id_reuse_rejected_after_completion(self):
        self.claim()
        self.complete("trial-1", self.execute("trial-1"))
        with self.assertRaises(ClaimRejected):
            self.claim("trial-1", at=5)

    def test_scheduled_run_during_manual_run_rejected(self):
        self.claim()
        with self.assertRaises(ClaimRejected):
            self.claim("trial-2", trigger=RunTrigger.SCHEDULED)

    def test_partial_worker_report(self):
        self.claim()
        rows = [self.rows[0], self.rows[0], {**self.rows[1], "title": ""}]
        summary = self.execute("trial-1", rows)
        snapshot = self.complete("trial-1", summary)
        self.assertEqual(snapshot["status"], "PARTIAL")
        self.assertEqual((snapshot["counters"]["duplicates"], snapshot["counters"]["invalid"]), (1, 1))
        self.assertEqual(len(self.store), 1)

    def test_summary_run_id_mismatch_blocks_finish(self):
        self.claim()
        summary = self.execute("trial-1")
        summary["run_id"] = "another-run"
        with self.assertRaises(ValueError):
            self.complete("trial-1", summary)
        self.assertEqual(self.claims.active_run("jobkorea"), "trial-1")

    def test_summary_source_mismatch_blocks_finish(self):
        self.claim()
        summary = self.execute("trial-1")
        summary["source_id"] = "another_source"
        with self.assertRaises(ValueError):
            self.complete("trial-1", summary)
        self.assertEqual(self.claims.get("trial-1").status, RunStatus.RUNNING)

    def test_summary_non_offline_blocks_finish(self):
        self.claim()
        summary = self.execute("trial-1")
        summary["external_requests"] = 1
        with self.assertRaises(ValueError):
            self.complete("trial-1", summary)

    def test_counter_mismatch_blocks_finish(self):
        self.claim()
        summary = self.execute("trial-1")
        summary["fetched"] = 50
        with self.assertRaises(ValueError):
            self.complete("trial-1", summary)
        self.assertEqual(self.claims.active_run("jobkorea"), "trial-1")

    def test_summary_negative_counter_blocks_finish(self):
        self.claim()
        summary = self.execute("trial-1")
        summary["inserted"] = -1
        with self.assertRaises(ValueError):
            self.complete("trial-1", summary)

    def test_unexpected_status_blocks_finish(self):
        self.claim()
        summary = self.execute("trial-1")
        summary["status"] = "SUCCEEDED_BUT_UNVERIFIED"
        with self.assertRaises(ValueError):
            self.complete("trial-1", summary)

    def test_success_with_invalid_quality_count_blocks_finish(self):
        self.claim()
        summary = self.execute("trial-1")
        summary["invalid"] = 1
        summary["fetched"] = 3
        with self.assertRaises(ValueError):
            self.complete("trial-1", summary)

    def test_stale_claim_releases_in_simulation_but_not_auto_retried(self):
        self.claim()
        monitor = OfflineHeartbeatMonitor(
            self.claims, RecoveryPolicy(heartbeat_timeout=timedelta(seconds=10), max_attempts=2)
        )
        result = monitor.inspect(run_id="trial-1", at=self.at(11))
        self.assertEqual(result, RecoveryDecision.EXPIRED)
        self.assertEqual(self.claims.get("trial-1").error_code, "HEARTBEAT_TIMEOUT")
        self.assertIsNone(self.claims.active_run("jobkorea"))
        decision = retry_decision(
            error_code="HEARTBEAT_TIMEOUT", attempt=1, policy=monitor.policy,
        )
        self.assertEqual(decision, RecoveryDecision.RETRY_ELIGIBLE)
        self.assertIsNone(self.claims.get("trial-2"))

    def test_stale_then_new_id_replay_preserves_existing_data(self):
        self.claim()
        monitor = OfflineHeartbeatMonitor(self.claims, RecoveryPolicy(
            heartbeat_timeout=timedelta(seconds=10), max_attempts=2,
        ))
        self.execute("trial-1")
        self.assertEqual(monitor.inspect(run_id="trial-1", at=self.at(11)), RecoveryDecision.EXPIRED)
        self.claim("trial-2", at=12)
        second = self.complete("trial-2", self.execute("trial-2"), at=13)
        self.assertEqual((second["counters"]["inserted"], second["counters"]["unchanged"]), (0, 2))

    def test_error_code_does_not_include_exception_text(self):
        self.claim()
        finished = self.claims.finish(
            run_id="trial-1", target=RunStatus.FAILED,
            at=self.at(2), error_code="WORKER_TIMEOUT",
        )
        output = json.dumps(finished.snapshot())
        self.assertIn("WORKER_TIMEOUT", output)
        self.assertNotIn("password=", output)


if __name__ == "__main__":
    unittest.main()
