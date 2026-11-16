"""GOAL_3 harvest against real PostgreSQL with 1,000+ synthetic postings (opt-in, disposable DB only).

CRAWLER_HARVEST_PG_TEST=1 and CRAWLER_LOCAL_DATABASE_URL=<training DB with migrations 0002-0013>.
Refuses port 5432 (the PC's main crawler DB) unless CRAWLER_HARVEST_PG_ALLOW_MAIN=1.
Writes only source_code 'jobkorea_harvest_fixture'. No HTTP: pages come from a temp fixture dir.

This proves INSERT throughput, deduplication and pagination logic locally. It is NOT evidence
that the live site supplies 1,000 new postings a day.
"""
import json
import os
import random
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from crawler.jobs import harvest as h

ENABLED = os.environ.get('CRAWLER_HARVEST_PG_TEST') == '1'
DSN = os.environ.get('CRAWLER_LOCAL_DATABASE_URL', '')
MAIN_REFUSED = (urlsplit(DSN).port or 5432) == 5432 and os.environ.get('CRAWLER_HARVEST_PG_ALLOW_MAIN') != '1'
KEYWORDS = ['AX', '데이터 분석', '빅데이터', 'AI 엔지니어', '머신러닝', '딥러닝']
PAGES, PER_PAGE = 10, 20
# A fresh id range per run: the runtime role has no DELETE, so earlier runs' rows simply stay.
BASE_ID = 70_000_000 + random.randrange(1, 900) * 10_000_000


def detail_html(external_id, title_suffix=''):
    url = f'https://www.jobkorea.co.kr/Recruit/GI_Read/{external_id}'
    doc = {'@context': 'https://schema.org', '@type': 'JobPosting', 'title': f'데이터 엔지니어 {external_id}{title_suffix}',
           'hiringOrganization': {'@type': 'Organization', 'name': f'합성회사{external_id % 97}'},
           'datePosted': '2026-11-10', 'validThrough': '2026-12-31', 'employmentType': 'FULL_TIME',
           'jobLocation': {'@type': 'Place', 'address': {'addressRegion': '서울'}},
           'identifier': {'value': str(external_id)}, 'url': url}
    return f'<html><script type="application/ld+json">{json.dumps(doc, ensure_ascii=False)}</script></html>'


def build_fixture(root, *, base=None, overlap_every=7):
    """6 keywords x 10 pages x 20 links; every 7th slot of keywords 2..6 repeats keyword 1's id."""
    root = Path(root)
    (root / 'search').mkdir(parents=True)
    (root / 'detail').mkdir()
    (root / 'keywords.json').write_text(json.dumps(KEYWORDS, ensure_ascii=False), encoding='utf-8')
    next_id, first, unique = BASE_ID if base is None else base, {}, set()
    for k, _ in enumerate(KEYWORDS):
        for page in range(1, PAGES + 1):
            links = []
            for slot in range(PER_PAGE):
                if k and slot % overlap_every == 0:
                    external_id = first[(page, slot)]
                else:
                    next_id += 1
                    external_id = next_id
                if k == 0:
                    first[(page, slot)] = external_id
                unique.add(external_id)
                links.append(f'<a href="/Recruit/GI_Read/{external_id}?logpath=1&listno={slot}">t</a>')
            (root / 'search' / f'{k}-p{page}.html').write_text(''.join(links), encoding='utf-8')
    for external_id in unique:
        (root / 'detail' / f'{external_id}.html').write_text(detail_html(external_id), encoding='utf-8')
    return unique


@unittest.skipUnless(ENABLED and DSN and not MAIN_REFUSED,
                     'set CRAWLER_HARVEST_PG_TEST=1 and a disposable CRAWLER_LOCAL_DATABASE_URL')
class HarvestPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.psycopg = psycopg
        cls.tmp = tempfile.TemporaryDirectory()
        cls.unique = build_fixture(cls.tmp.name)
        cls.connection = psycopg.connect(DSN, autocommit=True)
        cls.results = {}

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        cls.tmp.cleanup()

    @classmethod
    def sql(cls, text, params=()):
        cursor = cls.connection.execute(text, params)
        return cursor.fetchall() if cursor.description else cursor.rowcount

    def harvest(self, root=None, **limits):
        keywords, source = h.FixtureSource.from_dir(root or self.tmp.name)
        limits = h.HarvestLimits(**{'max_pages': PAGES, 'max_new_details': 1500, 'max_requests': 2000, **limits})
        return h.run_harvest(self.connection, source, keywords=keywords, limits=limits), source

    def fixture_count(self):
        return self.sql("SELECT count(*) FROM crawler_training.postings WHERE source_code = 'jobkorea_harvest_fixture'"
                        ' AND external_posting_id::bigint BETWEEN %s AND %s', (BASE_ID, BASE_ID + 9_999_999))[0][0]

    # tests run in name order on one database
    def test_01_first_run_inserts_every_unique_posting_once(self):
        self.assertGreaterEqual(len(self.unique), 1000)
        result, source = self.harvest()
        self.__class__.results['first'] = result
        links = len(KEYWORDS) * PAGES * PER_PAGE
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual((result['links'], result['pages']), (links, len(KEYWORDS) * PAGES))
        self.assertEqual(result['new'], len(self.unique))
        self.assertEqual(result['cross_dup'], links - len(self.unique))
        self.assertEqual((result['inserted'], result['updated'], result['failed']), (len(self.unique), 0, 0))
        self.assertEqual(self.fixture_count(), len(self.unique))
        self.assertEqual(result['http_requests'], 0)  # fixture mode never counts as HTTP
        self.assertEqual(source.requests, len(KEYWORDS) * PAGES + len(self.unique))
        # per-page and per-keyword supply metrics
        pages = self.sql('SELECT count(*), sum(links), sum(new_ids), sum(cross_duplicates) FROM crawler_training.harvest_pages'
                         ' WHERE run_id = %s', (result['run_id'],))[0]
        self.assertEqual(pages, (60, links, len(self.unique), links - len(self.unique)))
        self.assertEqual(result['keywords']['AX']['new_rate'], 1.0)
        self.assertLess(result['keywords']['딥러닝']['new_rate'], 1.0)
        items = self.sql("SELECT decision, outcome, count(*) FROM crawler_training.harvest_items WHERE run_id = %s"
                         ' GROUP BY 1, 2', (result['run_id'],))
        self.assertEqual(items, [('new', 'inserted', len(self.unique))])
        run = self.sql('SELECT status, inserted, new_found, http_requests, ended_at IS NOT NULL'
                       ' FROM crawler_training.harvest_runs WHERE run_id = %s', (result['run_id'],))[0]
        self.assertEqual(run, ('SUCCEEDED', len(self.unique), len(self.unique), 0, True))  # fixture: no HTTP
        print(f"\nHARVEST_1000 inserted={result['inserted']} elapsed={result['elapsed_seconds']}s "
              f"rate={result['inserts_per_second']}/s cross_dup={result['cross_dup']}")

    def test_02_rerun_skips_known_postings_without_detail_requests(self):
        result, source = self.harvest(known_page_stop=2)
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual((result['new'], result['planned'], result['inserted'], result['updated']), (0, 0, 0, 0))
        # every keyword stops after two pages with nothing new: 6 x 2 search pages, zero details
        self.assertEqual((result['pages'], source.requests), (12, 12))
        self.assertEqual(self.fixture_count(), len(self.unique))

    def test_03_new_postings_on_page_one_are_found_and_fetched_first(self):
        fresh = [BASE_ID + 900_001, BASE_ID + 900_002]
        root = Path(self.tmp.name)
        page = root / 'search' / '2-p1.html'
        page.write_text(''.join(f'<a href="/Recruit/GI_Read/{i}">n</a>' for i in fresh) + page.read_text(encoding='utf-8'),
                        encoding='utf-8')
        for i in fresh:
            (root / 'detail' / f'{i}.html').write_text(detail_html(i), encoding='utf-8')
        result, source = self.harvest(max_revisits=5, revisit_after_hours=1)
        self.assertEqual((result['new'], result['inserted'], result['planned']), (2, 2, 2))  # nothing due for revisit
        self.assertEqual(result['keywords']['빅데이터']['inserted'], 2)

    def test_04_stale_known_postings_are_rechecked_and_changes_counted_as_updates(self):
        changed = BASE_ID + 1
        (Path(self.tmp.name) / 'detail' / f'{changed}.html').write_text(detail_html(changed, ' (수정)'), encoding='utf-8')
        self.sql("UPDATE crawler_training.postings SET updated_at = now() - interval '10 days'"
                 " WHERE source_code = 'jobkorea_harvest_fixture' AND external_posting_id::bigint BETWEEN %s AND %s",
                 (BASE_ID, BASE_ID + 9_999_999))
        self.sql("UPDATE crawler_training.harvest_items SET checked_at = now() - interval '10 days'"
                 ' WHERE external_posting_id::bigint BETWEEN %s AND %s', (BASE_ID, BASE_ID + 9_999_999))
        result, _ = self.harvest(max_new_details=0, max_revisits=30, revisit_after_hours=24, known_page_stop=1)
        self.assertEqual(result['status'], 'SUCCEEDED')
        self.assertEqual((result['inserted'], result['updated'], result['unchanged']), (0, 1, 29))
        decisions = self.sql("SELECT decision, outcome, count(*) FROM crawler_training.harvest_items WHERE run_id = %s"
                             ' GROUP BY 1, 2 ORDER BY 2', (result['run_id'],))
        self.assertEqual(decisions, [('revisit', 'unchanged', 29), ('revisit', 'updated', 1)])
        title = self.sql("SELECT payload->>'title' FROM crawler_training.postings WHERE source_code = 'jobkorea_harvest_fixture'"
                         ' AND external_posting_id = %s', (str(changed),))[0][0]
        self.assertTrue(title.endswith('(수정)'))

    def test_05_failed_detail_makes_run_partial_and_is_recorded(self):
        missing = BASE_ID + 900_003
        page = Path(self.tmp.name) / 'search' / '0-p1.html'
        page.write_text(f'<a href="/Recruit/GI_Read/{missing}">x</a>' + page.read_text(encoding='utf-8'), encoding='utf-8')
        result, _ = self.harvest()
        self.assertEqual((result['status'], result['failed'], result['inserted']), ('PARTIAL', 1, 0))
        self.assertEqual(self.sql("SELECT outcome, error_code FROM crawler_training.harvest_items WHERE run_id = %s",
                                  (result['run_id'],)), [('failed', 'HTTP_404')])

    def test_06_dispatcher_lock_prevents_overlap(self):
        with self.psycopg.connect(DSN, autocommit=True) as other:
            other.execute('SELECT pg_advisory_lock(642, 0)')
            result, source = self.harvest()
            other.execute('SELECT pg_advisory_unlock(642, 0)')
        self.assertEqual((result['status'], result['reason'], source.requests), ('SKIPPED', 'DISPATCHER_LOCKED', 0))

    def test_07_budget_keeps_room_for_planned_details(self):
        with tempfile.TemporaryDirectory() as other:
            build_fixture(other, base=BASE_ID + 5_000_000)  # every posting new again
            result, source = self.harvest(other, max_requests=60, max_new_details=50, known_page_stop=10)
        self.assertLessEqual(source.requests, 60)
        self.assertEqual(source.requests, result['pages'] + result['planned'])  # every planned detail fetched
        self.assertEqual(result['inserted'] + result['failed'], result['planned'])
        self.assertGreater(result['inserted'], 0)

    def test_07b_supply_measurement_reads_pages_only(self):
        with tempfile.TemporaryDirectory() as other:
            unique = build_fixture(other, base=BASE_ID + 7_000_000)
            result, source = self.harvest(other, max_new_details=0, max_revisits=0, known_page_stop=10)
        self.assertEqual((result['pages'], result['new'], result['planned'], result['inserted']),
                         (len(KEYWORDS) * PAGES, len(unique), 0, 0))
        self.assertEqual(source.requests, len(KEYWORDS) * PAGES)  # search pages only, no detail request

    def test_08_daily_report_counts_by_mode(self):
        report = h.daily_report(self.connection, days=1)
        fixture = [r for r in report['harvest_by_day'] if r['mode'] == 'fixture']
        self.assertTrue(fixture)
        self.assertGreaterEqual(sum(r['inserted'] for r in fixture), len(self.unique))
        self.assertFalse([r for r in report['harvest_by_day'] if r['mode'] == 'live'])


if __name__ == '__main__':
    unittest.main()
