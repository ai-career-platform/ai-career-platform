"""JobKorea XML API runner against real PostgreSQL (opt-in, disposable DB only). No network.

CRAWLER_API_PG_TEST=1 and CRAWLER_LOCAL_DATABASE_URL=<training DB with local_training_schema.sql and migration
0013>. Refuses port 5432 (the PC's main crawler DB) unless CRAWLER_API_PG_ALLOW_MAIN=1 (CI's throwaway service).
Responses are synthetic XML; the live-mode test uses a fake HTTP function and writes ``jobkorea_api`` rows into
the disposable DB only.
"""
import json
import os
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote_to_bytes, urlsplit

from crawler.jobs import jobkorea_api as api
from crawler.tests.jobkorea_api_fixture import item, page

ENABLED = os.environ.get('CRAWLER_API_PG_TEST') == '1'
DSN = os.environ.get('CRAWLER_LOCAL_DATABASE_URL', '')
MAIN_REFUSED = (urlsplit(DSN).port or 5432) == 5432 and os.environ.get('CRAWLER_API_PG_ALLOW_MAIN') != '1'
KEYWORDS = ['AX', '데이터 분석', '빅데이터']


def connect():
    import psycopg
    connection = psycopg.connect(DSN, connect_timeout=5)
    connection.autocommit = True
    return connection


@unittest.skipUnless(ENABLED and DSN and not MAIN_REFUSED,
                     'set CRAWLER_API_PG_TEST=1 and a disposable CRAWLER_LOCAL_DATABASE_URL')
class ApiPostgresTest(unittest.TestCase):
    def setUp(self):
        self.base = 80_000_000 + random.randrange(1, 9_000) * 1_000
        self.connection = connect()

    def tearDown(self):
        self.connection.close()

    def rows(self, source_code, ids):
        return self.connection.execute(
            """SELECT external_posting_id, payload FROM crawler_training.postings
               WHERE source_code=%s AND external_posting_id = ANY(%s)""",
            (source_code, [str(i) for i in ids])).fetchall()

    def ledger(self, run_id):
        run = self.connection.execute(
            """SELECT status, stop_reason, http_requests, search_pages, links_seen, new_found, known_found,
                      cross_duplicates, inserted, failed FROM crawler_training.harvest_runs WHERE run_id=%s""",
            (run_id,)).fetchone()
        items = self.connection.execute(
            "SELECT outcome, count(*) FROM crawler_training.harvest_items WHERE run_id=%s GROUP BY 1", (run_id,)).fetchall()
        return run, dict(items)

    def fixture_dir(self, tmp, responses):
        root = Path(tmp)
        (root / 'pages').mkdir()
        (root / 'keywords.json').write_text(json.dumps(KEYWORDS, ensure_ascii=False), encoding='utf-8')
        for (k, p), data in responses.items():
            (root / 'pages' / f'{k}-p{p}.xml').write_bytes(data)
        return root

    def test_fixture_run_dedupes_stops_at_target_and_reruns_insert_nothing(self):
        b = self.base
        # keyword 0: 4 postings; keyword 1 repeats two of them (cross-keyword duplicates) and adds 3;
        # keyword 2 has one posting with no company (invalid) and 2 valid. Target 8 of 9 valid new postings.
        responses = {
            (0, 1): page([item(b + i) for i in range(1, 5)], total=4),
            (1, 1): page([item(b + 1), item(b + 2)] + [item(b + i) for i in range(5, 8)], total=5),
            (2, 1): page([item(b + 8, company=''), item(b + 9), item(b + 10)], total=3),
        }
        with tempfile.TemporaryDirectory() as tmp:
            keywords, source = api.FixtureApiSource.from_dir(self.fixture_dir(tmp, responses))
            limits = api.ApiLimits(target_new=8, page_size=100, max_requests=10)
            first = api.run_api_collection(self.connection, source, keywords=keywords, limits=limits)
            self.assertEqual(first['status'], 'PARTIAL', first)
            self.assertEqual((first['inserted'], first['failed'], first['cross_dup']), (8, 1, 2))
            self.assertEqual(first['fixture_reads'], 3)
            stored = self.rows('jobkorea_api_fixture', range(b + 1, b + 11))
            self.assertEqual(len(stored), 8)
            self.assertNotIn(str(b + 8), {r[0] for r in stored})
            self.assertFalse(any('SECRET' in json.dumps(r[1]) for r in stored))
            run, items = self.ledger(first['run_id'])
            self.assertEqual(run[0], 'PARTIAL')
            self.assertEqual(run[2], 0)                      # fixture reads are not HTTP requests
            self.assertEqual(items, {'inserted': 8, 'failed': 1})

            # Re-run: the 8 stored postings are duplicates now. Posting 10 was found but not stored the first time
            # (target reached), so it is the only insert; the invalid posting fails again and is never stored.
            _, again = api.FixtureApiSource.from_dir(Path(tmp))
            second = api.run_api_collection(self.connection, again, keywords=keywords, limits=limits)
            self.assertEqual((second['inserted'], second['known'], second['failed']), (1, 8, 1), second)
            _, third = api.FixtureApiSource.from_dir(Path(tmp))
            third = api.run_api_collection(self.connection, third, keywords=keywords, limits=limits)
            self.assertEqual((third['inserted'], third['known']), (0, 9), third)
            stored = self.rows('jobkorea_api_fixture', range(b + 1, b + 11))
            self.assertEqual(len(stored), 9)
            self.assertEqual(len({r[0] for r in stored}), 9)   # one row per posting id

    def live_source(self, responses, limits, sent):
        from crawler.tests.test_jobkorea_api import approval
        now = datetime.now(timezone.utc)

        def get(url):
            sent.append(url)
            return responses.pop(0)

        return api.LiveApiSource(approval(valid_from_utc=now - timedelta(hours=1),
                                          review_due_utc=now + timedelta(hours=1), max_harvest_details=100),
                                 api.ApiConfig('https://api.jobkorea.co.kr/Service/JK_GI_XML_List.asp?api=SECRET',
                                               ('203.0.113.7',)),
                                 limits, get=get, sleep=lambda s: None, ip_lookup=lambda: '203.0.113.7')

    def test_live_run_counts_existing_html_rows_as_duplicates_and_paginates_only_when_needed(self):
        b = self.base
        self.connection.execute(
            """INSERT INTO crawler_training.postings (source_code, external_posting_id, payload)
               VALUES ('jobkorea_live', %s, '{}'::jsonb)""", (str(b + 1),))
        responses = [page([item(b + i) for i in range(1, 3)], total=4),     # AX p1 (size 2): 1 known, 1 new
                     page([item(b + i) for i in range(3, 5)], total=4),     # 데이터 분석 p1: 2 new -> target 3 met
                     page([item(b + 99)], total=1)]                         # never requested
        sent = []
        limits = api.ApiLimits(target_new=3, page_size=2, max_pages=2, max_requests=10)
        source = self.live_source(responses, limits, sent)
        result = api.run_api_collection(self.connection, source, keywords=['AX', '데이터 분석'], limits=limits)
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertEqual((result['inserted'], result['known'], result['api_requests']), (3, 1, 2))
        self.assertEqual(len(sent), 2)
        query = parse_qs(urlsplit(sent[1]).query)
        self.assertEqual(unquote_to_bytes(sent[1].rsplit('Keyword=', 1)[1]).decode('cp949'), '데이터 분석')
        self.assertEqual((query['Size'], query['Page'], query['Ob']), (['2'], ['1'], ['1']))
        self.assertEqual(len(self.rows('jobkorea_api', [b + 2, b + 3, b + 4])), 3)
        self.assertEqual(self.rows('jobkorea_api', [b + 1]), [])
        run, _ = self.ledger(result['run_id'])
        self.assertEqual(run[:3], ('SUCCEEDED', None, 2))

    def test_live_run_stops_at_once_on_a_non_xml_answer(self):
        sent = []
        limits = api.ApiLimits(target_new=5, max_requests=10)
        source = self.live_source(['<html>인증되지 않은 요청</html>'.encode('cp949'), page([])], limits, sent)
        result = api.run_api_collection(self.connection, source, keywords=['AX', '빅데이터'], limits=limits)
        self.assertEqual((result['status'], result['stop_reason'], result['api_requests']),
                         ('STOPPED', 'UNEXPECTED_ROOT', 1))
        self.assertEqual(len(sent), 1)

    def test_zz_cumulative_cap_of_1000_jobkorea_postings(self):
        """Runs last and removes its own rows (the disposable DB's owner may DELETE), so reruns still work."""
        total = api.stored_total(self.connection)
        if total > 998:
            self.skipTest('disposable DB already holds more than 998 JobKorea postings')
        filler = 990_000_000 + random.randrange(1, 9_000) * 1_000
        b = self.base
        mine = [str(filler + i) for i in range(998 - total)] + [str(b + i) for i in range(1, 6)]
        try:
            for external_id in mine[:998 - total]:
                self.connection.execute(
                    """INSERT INTO crawler_training.postings (source_code, external_posting_id, payload)
                       VALUES ('jobkorea_api', %s, '{}'::jsonb)""", (external_id,))
            sent = []
            limits = api.ApiLimits(target_new=100, max_requests=10)
            source = self.live_source([page([item(b + i) for i in range(1, 6)], total=5)], limits, sent)
            result = api.run_api_collection(self.connection, source, keywords=['AX'], limits=limits)
            self.assertEqual((result['target_new'], result['inserted']), (2, 2), result)
            self.assertEqual(api.stored_total(self.connection), 1000)
            blocked_sent = []
            again = self.live_source([page([item(b + 50)])], limits, blocked_sent)
            blocked = api.run_api_collection(self.connection, again, keywords=['AX'], limits=limits)
            self.assertEqual((blocked['status'], blocked['stop_reason'], blocked['api_requests']),
                             ('STOPPED', 'CUMULATIVE_LIMIT', 0))
            self.assertEqual(blocked_sent, [])
        finally:
            self.connection.execute("""DELETE FROM crawler_training.postings
                                       WHERE source_code='jobkorea_api' AND external_posting_id = ANY(%s)""", (mine,))


if __name__ == '__main__':
    unittest.main()
