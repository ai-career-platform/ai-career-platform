"""Nightly orchestration against real PostgreSQL (opt-in, disposable DB only). No HTTP.

CRAWLER_HARVEST_PG_TEST=1 and CRAWLER_LOCAL_DATABASE_URL=<training DB with migrations 0002-0013, a role that
may write harvest/posting rows>. Refuses port 5432 (the PC's main crawler DB).

1. The real harvest (FixtureSource, 1,000+ synthetic postings) runs in chunks inside ``run_night``: chunked
   inserts, cross-keyword and existing-row deduplication, and a second night with nothing new.
2. The LIVE NEW INSERT counter never counts fixture rows, HTTP-0 runs, updates, rows outside the window
   or ledger rows whose posting row is missing.
3. ``test_run`` writes nothing.
Fixture rows prove the storage path only; they are never evidence of real supply.
"""
import os
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from urllib.parse import urlsplit

from crawler.jobs import harvest as h
from crawler.jobs import nightly as n
from crawler.tests.local_harvest_pg import KEYWORDS, build_fixture

ENABLED = os.environ.get('CRAWLER_HARVEST_PG_TEST') == '1'
DSN = os.environ.get('CRAWLER_LOCAL_DATABASE_URL', '')
MAIN = (urlsplit(DSN).port or 5432) == 5432


@unittest.skipUnless(ENABLED and DSN and not MAIN, 'set CRAWLER_HARVEST_PG_TEST=1 and a disposable DB (not 5432)')
class NightlyPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.connection = psycopg.connect(DSN, autocommit=True)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = 300_000_000 + uuid.uuid4().int % 50_000_000
        cls.unique = build_fixture(cls.tmp.name, base=cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        cls.tmp.cleanup()

    def window_now(self):
        """A window around the real clock: harvest rows carry real now() timestamps."""
        now = datetime.now(timezone.utc)
        return n.Window(date.today(), now - timedelta(hours=1), now + timedelta(hours=2), True)

    def run_fixture_night(self, ledger_dir, config):
        keywords, _ = h.FixtureSource.from_dir(self.tmp.name)
        window = self.window_now()
        self.live_before = n.new_inserts(self.connection, window.start, window.end)   # earlier test runs may leave some
        with mock.patch.object(n, 'night_window', lambda now: window):
            return n.run_night(self.connection, source_factory=lambda limits: h.FixtureSource.from_dir(self.tmp.name)[1],
                               config=config, environ={}, ledger=n.SlackLedger(ledger_dir, window.night_date),
                               keywords=keywords, mode='fixture')

    def test_1_chunked_fixture_night_stores_every_unique_posting_once_and_counts_none_as_live(self):
        before = self.connection.execute("SELECT count(*) FROM crawler_training.postings"
                                          " WHERE source_code = 'jobkorea_harvest_fixture'").fetchone()[0]
        cfg = n.NightConfig(target=1000, chunk_new=400, pages=10, max_requests=2000, night_max_requests=100000)
        with tempfile.TemporaryDirectory() as ledger:
            out = self.run_fixture_night(ledger, cfg)
        inserted = sum(c['inserted'] or 0 for c in out['chunks'])
        after = self.connection.execute("SELECT count(*) FROM crawler_training.postings"
                                         " WHERE source_code = 'jobkorea_harvest_fixture'").fetchone()[0]
        self.assertGreaterEqual(len(self.unique), 1000)
        self.assertEqual(inserted, len(self.unique))                  # every unique fixture posting exactly once
        self.assertEqual(after - before, len(self.unique))            # rows really written
        self.assertGreater(len(out['chunks']), 2)                     # chunked (400 new per run)
        self.assertEqual(out['reason'], 'NO_NEW_SUPPLY')              # fixture never counts toward the LIVE target
        self.assertEqual(out['totals']['verified_new_inserts'], self.live_before)   # +0 LIVE from 1,050 fixture rows
        dup = self.connection.execute(
            "SELECT count(*) FROM (SELECT external_posting_id FROM crawler_training.harvest_items i"
            " JOIN crawler_training.harvest_runs r USING (run_id) WHERE r.mode = 'fixture' AND i.outcome = 'inserted'"
            " AND i.external_posting_id::bigint >= %s GROUP BY 1 HAVING count(*) > 1) d", (self.base,)).fetchone()[0]
        self.assertEqual(dup, 0)                                      # no posting inserted twice across chunks
        # second night over the same supply: nothing new, nothing inserted
        with tempfile.TemporaryDirectory() as ledger:
            again = self.run_fixture_night(ledger, cfg)
        self.assertEqual((sum(c['inserted'] or 0 for c in again['chunks']), again['reason']), (0, 'NO_NEW_SUPPLY'))

    def test_2_live_counter_counts_only_verified_live_inserts_in_the_window(self):
        # simulated LIVE ledger rows live only inside this transaction (rolled back): other suites on the same
        # disposable DB (local_harvest_pg.test_08) require that no LIVE run exists
        import psycopg
        with psycopg.connect(DSN) as c:
            try:
                self._live_counter_checks(c)
            finally:
                c.rollback()

    def _live_counter_checks(self, c):
        now = datetime.now(timezone.utc)
        ids = [str(900_000_000 + uuid.uuid4().int % 90_000_000 + k) for k in range(6)]

        def run(mode, http, status='SUCCEEDED'):
            return c.execute("INSERT INTO crawler_training.harvest_runs (mode, source_code, limits, status, ended_at,"
                             " http_requests) VALUES (%s, %s, '{}'::jsonb, %s, now(), %s) RETURNING run_id",
                             (mode, 'jobkorea_live' if mode == 'live' else 'jobkorea_harvest_fixture', status,
                              http)).fetchone()[0]

        def item(run_id, ext, outcome, source='jobkorea_live', checked=None, posting=True):
            if posting:
                c.execute("INSERT INTO crawler_training.postings (source_code, external_posting_id, payload)"
                          " VALUES (%s, %s, '{}'::jsonb) ON CONFLICT DO NOTHING", (source, ext))
            c.execute("INSERT INTO crawler_training.harvest_items (run_id, source_code, external_posting_id, keyword,"
                      " page_no, decision, outcome, checked_at) VALUES (%s,%s,%s,'AX',1,'new',%s,%s)",
                      (run_id, source, ext, outcome, checked or now))
        live, nohttp, fixture = run('live', 7), run('live', 0), run('fixture', 0)
        item(live, ids[0], 'inserted')                                       # counted
        item(live, ids[1], 'updated')                                        # update: no
        item(live, ids[2], 'inserted', checked=now - timedelta(hours=30))    # outside window: no
        item(live, ids[3], 'inserted', posting=False)                        # no posting row: no
        item(nohttp, ids[4], 'inserted')                                     # HTTP-0 run: no
        item(fixture, ids[5], 'inserted', source='jobkorea_harvest_fixture')  # fixture: no
        got = n.new_inserts(c, now - timedelta(hours=24), now + timedelta(seconds=1))
        base = n.new_inserts(c, now - timedelta(hours=24), now - timedelta(seconds=1))
        self.assertEqual(got - base, 1)

    def test_4_a_page_parameter_the_site_ignores_stops_the_keyword_after_one_wasted_page(self):
        # page 2..10 of keyword 0 return page 1 again (what a wrong Page_No would look like on the live site)
        import shutil
        from pathlib import Path
        tmp = tempfile.mkdtemp()
        try:
            build_fixture(tmp, base=700_000_000 + uuid.uuid4().int % 50_000_000)
            first = Path(tmp, 'search', '0-p1.html').read_text(encoding='utf-8')
            for page in range(2, 11):
                Path(tmp, 'search', f'0-p{page}.html').write_text(first, encoding='utf-8')
            keywords, source = h.FixtureSource.from_dir(tmp)
            limits = h.HarvestLimits(max_pages=10, max_new_details=0, known_page_stop=10, max_requests=2000)
            out = h.run_harvest(self.connection, source, keywords=keywords[:1], limits=limits)
            pages = self.connection.execute(
                "SELECT page_no, coalesce(error_code, '') FROM crawler_training.harvest_pages WHERE run_id = %s"
                " ORDER BY page_no", (out['run_id'],)).fetchall()
            self.assertEqual(pages, [(1, ''), (2, 'PAGE_REPEATED')])      # not 10 pages
            self.assertEqual(source.requests, 2)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_3_test_mode_writes_nothing(self):
        counts = ("SELECT (SELECT count(*) FROM crawler_training.harvest_runs),"
                  " (SELECT count(*) FROM crawler_training.harvest_items), (SELECT count(*) FROM crawler_training.postings)")
        before = self.connection.execute(counts).fetchone()
        out = n.test_run(self.connection, now=datetime.now(timezone.utc))
        self.assertEqual(self.connection.execute(counts).fetchone(), before)
        self.assertEqual((out['external_requests'], out['db_writes'], out['harvest_lock_free']), (0, 0, True))


if __name__ == '__main__':
    unittest.main()
