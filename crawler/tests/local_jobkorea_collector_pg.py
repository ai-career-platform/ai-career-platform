"""JobKorea API collector -> real career schema with production grants (opt-in, throwaway server only).

CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN=<superuser DSN of a disposable server> (same as #337).
Creates its own database (database/migrations 0001-0003 + poc/staging/automation/gcp-sync/target_grants.sql),
writes as the non-superuser career_sync role, then drops the database. API pages are synthetic XML fixtures.
"""
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.jobs import jobkorea_collector as c
from crawler.jobs.jobkorea_api import ApiLimits, FixtureApiSource
from crawler.tests.jobkorea_api_fixture import item, page

ROOT = Path(__file__).resolve().parents[2]
ENABLED = os.environ.get('CRAWLER_GCP_SYNC_PG_TEST') == '1'
ADMIN_DSN = os.environ.get('CRAWLER_GCP_SYNC_ADMIN_DSN', '')
SYNC_PASSWORD = 'local-test-only'
NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)


@unittest.skipUnless(ENABLED and ADMIN_DSN, 'set CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN')
class CollectorPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        cls.psycopg = psycopg
        cls.db = f'jk_collector_test_{uuid.uuid4().hex[:8]}'
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE {cls.db}')
            if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'career_sync'").fetchone():
                admin.execute(f"CREATE ROLE career_sync LOGIN PASSWORD '{SYNC_PASSWORD}'")
        base = conninfo_to_dict(ADMIN_DSN)
        cls.owner_dsn = make_conninfo(**dict(base, dbname=cls.db))
        cls.sync_dsn = make_conninfo(**dict(base, dbname=cls.db, user='career_sync', password=SYNC_PASSWORD))
        try:
            with psycopg.connect(cls.owner_dsn, autocommit=True) as owner:
                owner.execute('CREATE SCHEMA career')
                for name in ('0001_initial_schema.sql', '0002_deletion_request_unscheduled.sql',
                             '0003_market_metric_skill_dimension.sql'):
                    owner.execute((ROOT / 'database/migrations' / name).read_text(encoding='utf-8'))
                owner.execute((ROOT / 'poc/staging/automation/gcp-sync/target_grants.sql').read_text(encoding='utf-8'))
                owner.execute("INSERT INTO career.data_sources (code, name) VALUES ('synthetic_seed', 'seed')")
                owner.execute("INSERT INTO career.data_sources (code, name, license_ref, retention_days)"
                              " VALUES ('jobkorea_api', 'JobKorea API', 'test only', 30)")
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        with cls.psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS {cls.db} WITH (FORCE)')

    def owner(self, sql, params=()):
        with self.psycopg.connect(self.owner_dsn, autocommit=True) as owner:
            cursor = owner.execute(sql, params)
            return cursor.fetchall() if cursor.description else None

    def run_collector(self, responses, *, mode='run', keywords=None, new=100, cap=1000,
                      source_code='jobkorea_api', now=NOW):
        keywords = keywords or list(dict.fromkeys(k for k, _ in responses))   # every keyword has a page 1
        source = FixtureApiSource(responses)
        target = self.psycopg.connect(self.sync_dsn)
        try:
            result = c.run_collector(target, source, mode=mode, keywords=list(keywords),
                                     limits=ApiLimits(target_new=new, page_size=100), source_code=source_code,
                                     cap=cap, now=now)
        finally:
            target.close()
        return result, source.requests

    def stored(self, ids):
        return {r[0]: r[1:] for r in self.owner(
            """SELECT r.external_id, p.title, p.location_text, p.status, c.name
               FROM career.job_posting_external_refs r JOIN career.job_postings p USING (job_posting_id)
               JOIN career.companies c ON c.company_id = p.company_id
               JOIN career.data_sources s ON s.source_id = r.source_id
               WHERE s.code = 'jobkorea_api' AND r.external_id = ANY(%s)""", ([str(i) for i in ids],))}

    def test_1_dry_run_writes_nothing(self):
        result, reads = self.run_collector({('AX', 1): page([item(101), item(102)])}, mode='dry-run')
        self.assertEqual((result['status'], result['inserted'], reads), ('DRY_RUN', 2, 1))   # one page = one read
        self.assertEqual(self.stored([101, 102]), {})
        self.assertEqual(self.owner('SELECT count(*) FROM career.ingestion_runs')[0][0], 0)

    def test_2_insert_dedupe_rerun_and_changed_fields_only(self):
        first, _ = self.run_collector({
            ('AX', 1): page([item(201), item(202), item(203)]),
            ('빅데이터', 1): page([item(202), item(204, company='')]),
        })
        self.assertEqual(first['status'], 'SUCCEEDED', first)
        self.assertEqual((first['inserted'], first['updated'], first['api']['cross_keyword_duplicates'],
                          first['api']['invalid']), (3, 0, 1, 1))
        rows = self.stored([201, 202, 203, 204])
        self.assertEqual(sorted(rows), ['201', '202', '203'])
        self.assertTrue(all(status == 'draft' for _, _, status, _ in rows.values()))
        run = self.owner("SELECT status, error_summary::json->>'source' FROM career.ingestion_runs"
                         " WHERE error_summary::json->>'source' = 'jobkorea_api' ORDER BY started_at DESC LIMIT 1")
        self.assertEqual(run[0], ('succeeded', 'jobkorea_api'))

        again, _ = self.run_collector({('AX', 1): page([item(201), item(202), item(203)])}, now=NOW + timedelta(hours=1))
        self.assertEqual((again['inserted'], again['updated'], again['duplicate']), (0, 0, 3), again)
        self.assertEqual(len(self.stored([201, 202, 203])), 3)

        changed, _ = self.run_collector({('AX', 1): page([item(201, title='제목 변경'), item(202, area='0'),
                                                         item(203)])}, now=NOW + timedelta(hours=2))
        self.assertEqual((changed['inserted'], changed['updated'], changed['duplicate']), (0, 1, 2), changed)
        rows = self.stored([201, 202])
        self.assertEqual(rows['201'][0], '제목 변경')
        self.assertEqual(rows['202'][1], '서울특별시, 경기도')          # empty API region kept the stored value
        count = self.owner("SELECT count(*) FROM career.job_posting_external_refs r JOIN career.data_sources s"
                           " USING (source_id) WHERE s.code='jobkorea_api' AND r.external_id IN ('201','202','203')")
        self.assertEqual(count[0][0], 3)

    def test_3_cumulative_cap_limits_inserts_then_stops_without_requests(self):
        stored = self.owner("SELECT count(*) FROM career.job_posting_external_refs r JOIN career.data_sources s"
                            " USING (source_id) WHERE s.code='jobkorea_api'")[0][0]
        result, _ = self.run_collector({('AX', 1): page([item(n) for n in range(301, 306)])}, cap=stored + 2)
        self.assertEqual((result['inserted'], result['insert_limit']), (2, 2), result)
        blocked, reads = self.run_collector({('AX', 1): page([item(399)])}, cap=stored + 2)
        self.assertEqual((blocked['status'], blocked['reason'], reads), ('STOPPED', 'CUMULATIVE_LIMIT', 0))

    def test_4_missing_data_source_stops_before_any_api_request(self):
        result, reads = self.run_collector({('AX', 1): page([item(401)])}, source_code='jobkorea_unknown')
        self.assertEqual((result['status'], result['error_code'], reads), ('FAILED', 'TARGET_SOURCE_MISSING', 0))

    def test_5_api_error_writes_nothing(self):
        result, _ = self.run_collector({('AX', 1): page([item(501)]), ('빅데이터', 1): b'<html>error</html>'})
        self.assertEqual((result['status'], result['reason']), ('STOPPED', 'UNEXPECTED_ROOT'), result)
        self.assertEqual(self.stored([501]), {})


if __name__ == '__main__':
    unittest.main()
