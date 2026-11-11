"""T155 isolated PostgreSQL integration for the admin write/command store.

Runs only under explicit CRAWLER_NIGHT_PG_TEST=1 against the disposable crawler
DB (migrations 0002..0011) as the non-owner runtime role ``crawler_staging``.
No HTTP, no Worker, no Timer, no Staging access. Each test uses unique synthetic
keyword names because the runtime role cannot DELETE (append-only design).
"""
import os
import unittest
from datetime import datetime, timezone
from unittest import mock
from uuid import uuid4

from crawler.admin.commands import (
    CrawlerAdminWriteStore, IdempotencyConflict, KeywordConflict, next_local_run,
)

FIXED_NOW = datetime(2026, 11, 11, 3, 0, tzinfo=timezone.utc)  # 12:00 KST


def _no_network(*_args, **_kwargs):
    raise AssertionError("T155 admin commands must not open network connections")


@unittest.skipUnless(os.environ.get("CRAWLER_NIGHT_PG_TEST") == "1",
                     "Only in opt-in disposable PostgreSQL CI")
class T155AdminWritePostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.connection = psycopg.connect(os.environ["CRAWLER_NIGHT_TEST_DSN"], autocommit=True)
        identity = self.connection.execute("SELECT current_database(),current_user").fetchone()
        self.assertEqual(identity, ("ai_career_crawler_training", "crawler_staging"))
        self.store = CrawlerAdminWriteStore(self.connection, clock=lambda: FIXED_NOW)
        self.actor = f"admin:{uuid4()}"
        self.tag = uuid4().hex[:8]
        patcher = mock.patch("socket.create_connection", _no_network)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.connection.close()

    def _protected_counts(self):
        return tuple(self.connection.execute(f"SELECT count(*) FROM crawler_training.{t}").fetchone()[0]
                     for t in ("postings", "raw_artifacts", "raw_parse_results", "runs", "run_events",
                               "fixture_job_payloads", "fixture_job_attempts", "fixture_night_slots"))

    def _key(self, name):
        return f"t155-{self.tag}-{name}"

    def _ledger(self, key):
        return self.connection.execute(
            "SELECT outcome,reason,actor FROM crawler_training.admin_commands WHERE idempotency_key=%s",
            (key,)).fetchone()

    def test_keyword_crud_audit_and_conflicts(self):
        before = self._protected_counts()
        row = self.store.create_keyword(f"  T155 합성 {self.tag}  ", priority=50, actor=self.actor)
        kid = row["keyword_id"]
        self.assertEqual(row["keyword"], f"T155 합성 {self.tag}")
        with self.assertRaises(KeywordConflict):
            self.store.create_keyword(f"t155 합성 {self.tag.upper()}", priority=50, actor=self.actor)
        other = self.store.create_keyword(f"T155 other {self.tag}", priority=60, actor=self.actor)
        with self.assertRaises(KeywordConflict):
            self.store.update_keyword(other["keyword_id"], f"T155 합성 {self.tag}", priority=60, actor=self.actor)
        updated = self.store.update_keyword(kid, f"T155 수정 {self.tag}", priority=40, actor=self.actor)
        self.assertEqual((updated["keyword"], updated["priority"]), (f"T155 수정 {self.tag}", 40))
        self.assertFalse(self.store.set_keyword_enabled(kid, False, actor=self.actor)["enabled"])
        self.assertTrue(self.store.delete_keyword(kid, actor=self.actor))
        self.assertFalse(self.store.delete_keyword(kid, actor=self.actor))
        self.assertIsNone(self.store.update_keyword(kid, "again", priority=1, actor=self.actor))
        self.assertIsNone(self.store.update_keyword(10**12, "none", priority=1, actor=self.actor))
        audit = self.store.keyword_audit(kid)
        self.assertEqual([a["action"] for a in audit], ["SOFT_DELETE", "SET_ENABLED", "EDIT", "CREATE"])
        self.assertTrue(all(a["actor"] == self.actor for a in audit))
        for bad in (lambda: self.store.create_keyword("", priority=1, actor=self.actor),
                    lambda: self.store.create_keyword("x" * 101, priority=1, actor=self.actor),
                    lambda: self.store.create_keyword("ok", priority=0, actor=self.actor),
                    lambda: self.store.create_keyword("ok", priority=1, actor=" spaced ")):
            with self.assertRaises(ValueError):
                bad()
        self.assertEqual(self._protected_counts(), before)

    def test_run_is_idempotent_metadata_only_and_blocks_duplicates(self):
        before = self._protected_counts()
        kid = self.store.create_keyword(f"T155 run {self.tag}", priority=70, actor=self.actor)["keyword_id"]
        first = self.store.run(kid, mode="fixture", idempotency_key=self._key("run"), actor=self.actor)
        self.assertEqual((first.outcome, first.reason, first.replayed), ("ACCEPTED", "FIXTURE_JOB_PENDING", False))
        job_id = first.result["job_id"]
        status = self.connection.execute(
            "SELECT status,started_at FROM crawler_training.keyword_jobs WHERE job_id=%s", (job_id,)).fetchone()
        self.assertEqual(status, ("PENDING", None))
        replay = self.store.run(kid, mode="fixture", idempotency_key=self._key("run"), actor=self.actor)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.result["job_id"], job_id)
        with self.assertRaises(IdempotencyConflict):
            self.store.run(kid, mode="live", idempotency_key=self._key("run"), actor=self.actor)
        dup = self.store.run(kid, mode="fixture", idempotency_key=self._key("run2"), actor=self.actor)
        self.assertEqual((dup.outcome, dup.reason), ("REFUSED", "ACTIVE_JOB_EXISTS"))
        jobs = self.connection.execute(
            "SELECT count(*) FROM crawler_training.keyword_jobs WHERE keyword_id=%s", (kid,)).fetchone()[0]
        self.assertEqual(jobs, 1)
        # stop the pending job, stop again is refused, then retry creates a new pending job
        stop = self.store.stop(job_id, idempotency_key=self._key("stop"), actor=self.actor)
        self.assertEqual((stop.outcome, stop.reason), ("ACCEPTED", "JOB_CANCELLED"))
        again = self.store.stop(job_id, idempotency_key=self._key("stop2"), actor=self.actor)
        self.assertEqual((again.outcome, again.reason), ("REFUSED", "JOB_ALREADY_FINISHED"))
        retry = self.store.retry(job_id, idempotency_key=self._key("retry"), actor=self.actor)
        self.assertEqual(retry.outcome, "ACCEPTED")
        self.assertEqual(retry.result["retry_of"], job_id)
        pending = self.store.retry(retry.result["job_id"], idempotency_key=self._key("retry2"), actor=self.actor)
        self.assertEqual((pending.outcome, pending.reason), ("REFUSED", "JOB_NOT_RETRYABLE"))
        missing = self.store.stop(uuid4(), idempotency_key=self._key("stop3"), actor=self.actor)
        self.assertEqual(missing.reason, "JOB_NOT_FOUND")
        self.store.set_keyword_enabled(kid, False, actor=self.actor)
        disabled = self.store.run(kid, mode="fixture", idempotency_key=self._key("run3"), actor=self.actor)
        self.assertEqual(disabled.reason, "KEYWORD_DISABLED")
        self.assertEqual(self._ledger(self._key("run"))[2], self.actor)
        self.assertEqual(self._protected_counts(), before)

    def test_live_and_schedule_activation_refused_and_recorded(self):
        before = self._protected_counts()
        schedule_before = self.connection.execute(
            "SELECT enabled,mode,target_urls,approval FROM crawler_training.schedules "
            "WHERE schedule_id='jobkorea-daily'").fetchone()
        kid = self.store.create_keyword(f"T155 live {self.tag}", priority=80, actor=self.actor)["keyword_id"]
        live = self.store.run(kid, mode="live", idempotency_key=self._key("live"), actor=self.actor)
        self.assertEqual((live.outcome, live.reason), ("REFUSED", "LIVE_NOT_APPROVED:NOT_APPROVED"))
        self.assertEqual(self._ledger(self._key("live"))[:2], ("REFUSED", "LIVE_NOT_APPROVED:NOT_APPROVED"))
        for changes, reason in (({"enabled": True}, "SCHEDULE_ACTIVATION_REQUIRES_APPROVAL"),
                                ({"mode": "live"}, "LIVE_NOT_APPROVED:NOT_APPROVED"),
                                ({"local_time": "04:30", "enabled": True}, "SCHEDULE_ACTIVATION_REQUIRES_APPROVAL")):
            result = self.store.update_schedule("jobkorea-daily", changes=changes,
                                                idempotency_key=self._key(f"sch-{reason}-{len(changes)}"),
                                                actor=self.actor)
            self.assertEqual((result.outcome, result.reason), ("REFUSED", reason))
        unknown = self.store.update_schedule("no-such", changes={"local_time": "01:00"},
                                             idempotency_key=self._key("sch-missing"), actor=self.actor)
        self.assertEqual(unknown.reason, "SCHEDULE_NOT_FOUND")
        current = self.connection.execute(
            "SELECT to_char(local_time,'HH24:MI') FROM crawler_training.schedules "
            "WHERE schedule_id='jobkorea-daily'").fetchone()[0]
        target = "04:30" if current != "04:30" else "05:00"
        changed = self.store.update_schedule("jobkorea-daily", changes={"local_time": target},
                                             idempotency_key=self._key("sch-time"), actor=self.actor)
        self.assertEqual((changed.outcome, changed.reason), ("ACCEPTED", "SCHEDULE_TIME_UPDATED"))
        self.assertEqual(changed.result["next_run_at"],
                         next_local_run(datetime.strptime(target, "%H:%M").time(), FIXED_NOW).isoformat())
        restore = self.store.update_schedule("jobkorea-daily", changes={"local_time": current},
                                             idempotency_key=self._key("sch-restore"), actor=self.actor)
        self.assertEqual(restore.outcome, "ACCEPTED")
        schedule_after = self.connection.execute(
            "SELECT enabled,mode,target_urls,approval FROM crawler_training.schedules "
            "WHERE schedule_id='jobkorea-daily'").fetchone()
        self.assertEqual(schedule_after, schedule_before)
        self.assertFalse(schedule_after[0])
        settings = self.store.settings()
        self.assertEqual(settings["live_collection"], "HOLD")
        self.assertFalse(settings["night_window"]["editable"])
        self.assertTrue(all("target_urls" not in s and "approval" not in s for s in settings["schedules"]))
        self.assertTrue(any(c["reason"].startswith("LIVE_NOT_APPROVED") for c in self.store.commands(limit=100)))
        self.assertEqual(self._protected_counts(), before)

    def test_concurrent_same_key_creates_one_job(self):
        import psycopg
        import threading
        kid = self.store.create_keyword(f"T155 race {self.tag}", priority=90, actor=self.actor)["keyword_id"]
        results, errors = [], []
        barrier = threading.Barrier(4)

        def worker():
            try:
                with psycopg.connect(os.environ["CRAWLER_NIGHT_TEST_DSN"], autocommit=True) as conn:
                    store = CrawlerAdminWriteStore(conn, clock=lambda: FIXED_NOW)
                    barrier.wait()
                    results.append(store.run(kid, mode="fixture", idempotency_key=self._key("race"),
                                             actor=self.actor))
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(r.replayed for r in results), [False, True, True, True])
        self.assertEqual(len({r.result["job_id"] for r in results}), 1)
        jobs = self.connection.execute(
            "SELECT count(*) FROM crawler_training.keyword_jobs WHERE keyword_id=%s", (kid,)).fetchone()[0]
        self.assertEqual(jobs, 1)

    def test_ledger_is_append_only_for_runtime_role(self):
        import psycopg
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.connection.execute("UPDATE crawler_training.admin_commands SET outcome='ACCEPTED'")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.connection.execute("DELETE FROM crawler_training.admin_commands")
        for bad in (lambda: self.store.run(1, mode="fixture", idempotency_key=" x", actor=self.actor),
                    lambda: self.store.run(0, mode="fixture", idempotency_key="k", actor=self.actor),
                    lambda: self.store.run(1, mode="other", idempotency_key="k", actor=self.actor),
                    lambda: self.store.update_schedule("jobkorea-daily", changes={"local_time": "25:00"},
                                                       idempotency_key="k", actor=self.actor),
                    lambda: self.store.update_schedule("jobkorea-daily", changes={"target_urls": []},
                                                       idempotency_key="k", actor=self.actor),
                    lambda: self.store.commands(limit=0)):
            with self.assertRaises(ValueError):
                bad()


class NextLocalRunTests(unittest.TestCase):
    def test_next_local_run_rolls_to_next_day(self):
        from datetime import time
        self.assertEqual(next_local_run(time(13, 0), FIXED_NOW).isoformat(), "2026-11-11T13:00:00+09:00")
        self.assertEqual(next_local_run(time(12, 0), FIXED_NOW).isoformat(), "2026-11-12T12:00:00+09:00")
        self.assertEqual(next_local_run(time(3, 0), FIXED_NOW).isoformat(), "2026-11-12T03:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
