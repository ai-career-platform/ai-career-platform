"""T155 admin command store: offline checks (no DB, no network)."""
import unittest
from datetime import datetime, time, timezone
from pathlib import Path

from crawler.admin.commands import CrawlerAdminWriteStore, _request_hash, live_gate_reason, next_local_run

ROOT = Path(__file__).resolve().parents[1]


class ExplodingConnection:
    """Any DB use fails the test: validation must happen before touching the DB."""

    def __getattr__(self, name):
        raise AssertionError(f"database used before validation: {name}")


class T155AdminCommandOfflineTests(unittest.TestCase):
    def setUp(self):
        self.store = CrawlerAdminWriteStore.__new__(CrawlerAdminWriteStore)
        self.store.connection = ExplodingConnection()
        self.store.keywords = None
        self.store._clock = lambda: datetime(2026, 11, 11, tzinfo=timezone.utc)

    def test_live_gate_always_refuses_without_approval_record(self):
        for at in (datetime(2026, 11, 11, tzinfo=timezone.utc), datetime(2030, 1, 1, tzinfo=timezone.utc)):
            self.assertEqual(live_gate_reason(at), "LIVE_NOT_APPROVED:NOT_APPROVED")

    def test_validation_happens_before_database(self):
        actor = "admin:test"
        cases = [
            lambda: self.store.run(0, mode="fixture", idempotency_key="k", actor=actor),
            lambda: self.store.run(True, mode="fixture", idempotency_key="k", actor=actor),
            lambda: self.store.run(1, mode="proxy", idempotency_key="k", actor=actor),
            lambda: self.store.run(1, mode="fixture", idempotency_key="", actor=actor),
            lambda: self.store.run(1, mode="fixture", idempotency_key="k ", actor=actor),
            lambda: self.store.run(1, mode="fixture", idempotency_key="k", actor=""),
            lambda: self.store.stop("not-a-uuid", idempotency_key="k", actor=actor),
            lambda: self.store.update_schedule("Bad ID", changes={"local_time": "01:00"},
                                               idempotency_key="k", actor=actor),
            lambda: self.store.update_schedule("jobkorea-daily", changes={}, idempotency_key="k", actor=actor),
            lambda: self.store.update_schedule("jobkorea-daily", changes={"approval": {}},
                                               idempotency_key="k", actor=actor),
            lambda: self.store.update_schedule("jobkorea-daily", changes={"enabled": "true"},
                                               idempotency_key="k", actor=actor),
            lambda: self.store.update_schedule("jobkorea-daily", changes={"local_time": "7:00"},
                                               idempotency_key="k", actor=actor),
            lambda: self.store.commands(limit=101),
        ]
        for case in cases:
            with self.assertRaises(ValueError):
                case()

    def test_request_hash_distinguishes_requests(self):
        a = _request_hash("RUN", "keyword:1", {"mode": "fixture"})
        self.assertEqual(a, _request_hash("RUN", "keyword:1", {"mode": "fixture"}))
        self.assertNotEqual(a, _request_hash("RUN", "keyword:1", {"mode": "live"}))
        self.assertNotEqual(a, _request_hash("RUN", "keyword:2", {"mode": "fixture"}))
        self.assertRegex(a, r"^[0-9a-f]{64}$")

    def test_next_local_run_is_kst(self):
        now = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)  # 05:00 KST on 11-11
        self.assertEqual(next_local_run(time(3, 0), now).isoformat(), "2026-11-12T03:00:00+09:00")
        self.assertEqual(next_local_run(time(6, 0), now).isoformat(), "2026-11-11T06:00:00+09:00")

    def test_no_network_worker_or_timer_code(self):
        code = (ROOT / "admin" / "commands.py").read_text(encoding="utf-8")
        for forbidden in ("import requests", "urllib.request", "http.client", "subprocess", "systemctl",
                          "Timer(", "sleep(", "fetch_", "dispatch("):
            self.assertNotIn(forbidden, code)

    def test_migration_guards_and_append_only_grant(self):
        sql = (ROOT / "storage" / "migrations" / "0011_admin_commands.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'", sql)
        self.assertIn("GRANT SELECT,INSERT ON crawler_training.admin_commands TO crawler_staging", sql)
        self.assertNotIn("UPDATE ON crawler_training.admin_commands", sql)
        self.assertNotIn("DELETE ON", sql)
        self.assertIn("idempotency_key text NOT NULL UNIQUE", sql)


if __name__ == "__main__":
    unittest.main()
