"""T155 isolated PostgreSQL integration for private read-only admin metadata.

Runs only under explicit CRAWLER_NIGHT_PG_TEST=1, after migrations 0002..0010
in the disposable GitHub Actions PostgreSQL service. No HTTP, fixtures, writes,
or staging access. Preserves all table counts through the read operations.
"""
import os
import unittest
from uuid import uuid4

from crawler.admin.read_models import CrawlerAdminReadStore


@unittest.skipUnless(os.environ.get("CRAWLER_NIGHT_PG_TEST") == "1",
                     "Only in opt-in disposable PostgreSQL CI")
class T155ReadOnlyPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        self.connection = psycopg.connect(os.environ["CRAWLER_NIGHT_TEST_DSN"])
        self.connection.autocommit = True
        identity = self.connection.execute(
            "SELECT current_database(),current_user").fetchone()
        self.assertEqual(identity,
                         ("ai_career_crawler_training", "crawler_staging"))
        self.store = CrawlerAdminReadStore(self.connection)

    def tearDown(self):
        self.connection.close()

    def _counts(self):
        return tuple(self.connection.execute(f"SELECT count(*) FROM crawler_training.{table}").fetchone()[0]
                     for table in ("search_keywords", "keyword_jobs",
                                   "keyword_posting_discoveries", "fixture_job_attempts",
                                   "fixture_night_slots", "schedules", "runs", "run_events"))

    def test_existing_seed_and_schedule_metadata(self):
        before = self._counts()
        keywords = self.store.keywords()
        from crawler.jobs.keyword_management import DEFAULT_KEYWORDS
        names = {row["keyword"] for row in keywords}
        self.assertTrue(set(DEFAULT_KEYWORDS).issubset(names))
        self.assertGreaterEqual(len(keywords), 6)
        self.assertTrue(all("keyword_id" in k and "keyword" in k for k in keywords))
        self.assertEqual([k["keyword"] for k in self.store.keywords(limit=2, offset=1)],
                         [k["keyword"] for k in keywords[1:3]])
        schedules = self.store.schedules()
        self.assertTrue(any(s["schedule_id"] == "jobkorea-daily" for s in schedules))
        self.assertTrue(all("approval" not in s and "target_urls" not in s for s in schedules))
        stats = self.store.keyword_stats()
        self.assertEqual(len(stats), len(keywords))
        self.assertTrue(all(row["job_count"] >= 0 for row in stats))
        self.assertEqual(self._counts(), before)

    def test_empty_jobs_runs_events_and_filtered_queries(self):
        before = self._counts()
        self.assertEqual(self.store.jobs(keyword_id=1,status="PENDING"), [])
        self.assertEqual(self.store.runs(), [])
        self.assertEqual(self.store.events(run_id=uuid4()), [])
        self.assertEqual(self._counts(),before)

    def test_bad_inputs_cannot_change_database(self):
        before = self._counts()
        for invoke in (
            lambda: self.store.keywords(limit=101),
            lambda: self.store.jobs(keyword_id=-1),
            lambda: self.store.jobs(status="PENDING' OR TRUE"),
            lambda: self.store.events(run_id="bad-uuid"),
            lambda: self.store.schedules(offset=-1),
        ):
            with self.assertRaises(ValueError):
                invoke()
        self.assertEqual(self._counts(),before)


if __name__ == "__main__":
    unittest.main()
