"""GOAL_2: GCP sync with the local Windows source, against real PostgreSQL (opt-in, throwaway server only).

CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN=<superuser DSN of a disposable server>.
Builds its own database with the real career schema and the production career_sync grants, plus the
crawler postings table and harvest provenance tables, then drops it. Proves that only postings of the
named LIVE harvest run are copied: fixture runs, runs without HTTP and test-polluted 'jobkorea_live'
rows outside the ledger are never selected.
"""
import os
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from crawler.jobs import gcp_sync as g
from crawler.tests.local_gcp_sync_pg import posting

ROOT = Path(__file__).resolve().parents[2]
ENABLED = os.environ.get('CRAWLER_GCP_SYNC_PG_TEST') == '1'
ADMIN_DSN = os.environ.get('CRAWLER_GCP_SYNC_ADMIN_DSN', '')
SYNC_PASSWORD = 'local-test-only'
NOON_KST = datetime(2026, 11, 14, 12, 0, tzinfo=g.KST)
SEEN = datetime(2026, 11, 12, 17, 4, tzinfo=timezone.utc)
LIVE, FIXTURE, NO_HTTP = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

HARVEST_TABLES = """
CREATE TABLE crawler_training.runs (status text NOT NULL);
CREATE TABLE crawler_training.keyword_jobs (status text NOT NULL);
CREATE TABLE crawler_training.night_job_results (outcome text NOT NULL);
CREATE TABLE crawler_training.harvest_runs (run_id uuid PRIMARY KEY, mode text NOT NULL, source_code text NOT NULL,
  status text NOT NULL, http_requests integer NOT NULL, ended_at timestamptz DEFAULT now());
CREATE TABLE crawler_training.harvest_items (run_id uuid NOT NULL REFERENCES crawler_training.harvest_runs,
  source_code text NOT NULL, external_posting_id text NOT NULL, outcome text,
  PRIMARY KEY (run_id, source_code, external_posting_id));
"""


@unittest.skipUnless(ENABLED and ADMIN_DSN, 'set CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN')
class GcpSyncLocalSourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        cls.psycopg = psycopg
        cls.db = f'gcp_sync_local_{uuid.uuid4().hex[:8]}'
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
                owner.execute((ROOT / 'crawler/storage/local_training_schema.sql').read_text(encoding='utf-8'))
                owner.execute(HARVEST_TABLES)
                owner.execute("INSERT INTO career.data_sources (code, name, license_ref, retention_days)"
                              " VALUES ('jobkorea_live', 'JobKorea live', 'test approval', 30)")
                # 1-6: 'jobkorea_live' rows written by mocked-HTTP tests (no ledger entry) -> never copied
                # 101-103: the LIVE run (103 failed -> not copied); 201: fixture run; 301: run without HTTP
                for n in (1, 2, 3, 4, 5, 6, 101, 102, 103, 201, 301):
                    owner.execute('INSERT INTO crawler_training.postings VALUES (%s, %s, %s, %s)',
                                  ('jobkorea_live', str(n), psycopg.types.json.Jsonb(posting(n)), SEEN))
                owner.execute("INSERT INTO crawler_training.harvest_runs VALUES"
                              " (%s, 'live', 'jobkorea_live', 'SUCCEEDED', 12), (%s, 'fixture', 'jobkorea_live', 'SUCCEEDED', 0),"
                              " (%s, 'live', 'jobkorea_live', 'SUCCEEDED', 0)", (LIVE, FIXTURE, NO_HTTP))
                owner.execute("INSERT INTO crawler_training.harvest_items VALUES"
                              " (%s, 'jobkorea_live', '101', 'inserted'), (%s, 'jobkorea_live', '102', 'unchanged'),"
                              " (%s, 'jobkorea_live', '103', 'failed'), (%s, 'jobkorea_live', '201', 'inserted'),"
                              " (%s, 'jobkorea_live', '301', 'inserted')", (LIVE, LIVE, LIVE, FIXTURE, NO_HTTP))
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        with cls.psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS {cls.db} WITH (FORCE)')

    def sync(self, mode, run_ids):
        source = self.psycopg.connect(self.owner_dsn)
        source.read_only = True
        target = self.psycopg.connect(self.sync_dsn)
        try:
            return g.run_sync(source, target, mode=mode, now=NOON_KST, live_run_ids=run_ids)
        finally:
            source.close()
            target.close()

    def owner(self, sql, params=()):
        with self.psycopg.connect(self.owner_dsn, autocommit=True) as owner:
            cursor = owner.execute(sql, params)
            return cursor.fetchall() if cursor.description else None

    def target_ids(self):
        return sorted(r[0] for r in self.owner('SELECT external_id FROM career.job_posting_external_refs'))

    def test_01_ineligible_runs_are_refused_before_any_target_write(self):
        for run_ids in ([FIXTURE], [NO_HTTP], [str(uuid.uuid4())], [LIVE, FIXTURE], []):
            with self.assertRaises(g.SyncError) as error:
                self.sync('dry-run', run_ids)
            self.assertIn(error.exception.code, ('LIVE_RUN_NOT_ELIGIBLE', 'LIVE_RUN_ID_REQUIRED'))
        self.assertEqual(self.sync('scheduled', [LIVE])['error_code'], 'LOCAL_SOURCE_ONE_SHOT_ONLY')
        self.assertEqual(self.target_ids(), [])

    def test_02_dry_run_selects_only_the_live_run_ledger(self):
        result = self.sync('dry-run', [LIVE])
        self.assertEqual((result['status'], result['fetched'], result['inserted'], result['failed']), ('DRY_RUN', 2, 2, 0))
        self.assertEqual(self.target_ids(), [])
        self.assertEqual(self.owner('SELECT count(*) FROM career.ingestion_runs')[0][0], 0)

    def test_03_run_inserts_drafts_and_reports_ids_for_rollback(self):
        result = self.sync('run', [LIVE])
        self.assertEqual((result['status'], result['inserted'], result['failed']), ('SUCCEEDED', 2, 0))
        self.assertEqual(sorted(result['inserted_external_ids']), ['101', '102'])
        self.assertEqual(self.target_ids(), ['101', '102'])
        self.assertEqual(self.owner("SELECT DISTINCT status FROM career.job_postings"), [('draft',)])
        self.assertEqual(self.owner("SELECT status FROM career.ingestion_runs"), [('succeeded',)])

    def test_04_verify_matches_source_and_target(self):
        result = self.sync('verify', [LIVE])
        self.assertEqual((result['status'], result['source_rows'], result['target_matched'], result['source_target_match']),
                         ('VERIFIED', 2, 2, True))

    def test_05_rerun_is_idempotent_and_verify_detects_drift(self):
        result = self.sync('run', [LIVE])
        self.assertEqual((result['inserted'], result['updated'], result['duplicate']), (0, 0, 2))
        self.owner("UPDATE crawler_training.postings SET payload = jsonb_set(payload, '{title}', '\"바뀐 제목\"')"
                   " WHERE external_posting_id = '101'")
        drift = self.sync('verify', [LIVE])
        self.assertEqual((drift['target_mismatched'], drift['source_target_match']), (1, False))
        self.assertEqual(drift['mismatched_items'], ['101:title'])

    def test_06_running_harvest_blocks_the_sync(self):
        self.owner("INSERT INTO crawler_training.harvest_runs VALUES (%s, 'live', 'jobkorea_live', 'RUNNING', 1, NULL)",
                   (str(uuid.uuid4()),))
        result = self.sync('run', [LIVE])
        self.assertEqual((result['status'], result['reason'], result['busy']['harvest_runs']), ('SKIPPED', 'CRAWLER_BUSY', 1))

    def test_07_rows_rewritten_after_the_run_are_not_selected(self):
        self.owner("DELETE FROM crawler_training.harvest_runs WHERE status = 'RUNNING'")
        self.owner("UPDATE crawler_training.postings SET updated_at = now() + interval '1 day'"
                   " WHERE external_posting_id = '102'")
        result = self.sync('dry-run', [LIVE])
        self.assertEqual(result['fetched'], 1)  # only 101 remains this run's data


if __name__ == '__main__':
    unittest.main()
