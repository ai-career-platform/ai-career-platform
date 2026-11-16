"""MIGRATION_UNBLOCK: Staging-source provenance filter and the single-writer rule, on real PostgreSQL.

CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN=<superuser DSN of a disposable server>.
Builds its own database (real career schema + production career_sync grants + the crawler tables the
filter reads) and drops it. Synthetic rows only.

Staging rows: A1/A2 found by an approved night job (inside its night), D refreshed by such a job,
B written without any job (like the 2026-11-08 CLI imports), C linked to a clock-injected test job,
E linked to a FAILED job. Only A1, A2, D may reach the target.
"""
import json
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
LIVE = str(uuid.uuid4())

TABLES = """
CREATE TABLE crawler_training.runs (status text NOT NULL);
CREATE TABLE crawler_training.keyword_jobs (status text NOT NULL);
CREATE TABLE crawler_training.search_keywords (keyword_id bigint PRIMARY KEY, keyword text NOT NULL);
CREATE TABLE crawler_training.night_job_results (job_id uuid PRIMARY KEY, keyword_id bigint NOT NULL,
  night_date date NOT NULL, outcome text NOT NULL, http_requests integer, started_at timestamptz NOT NULL,
  ended_at timestamptz, attempt smallint DEFAULT 1, inserted integer DEFAULT 0);
CREATE TABLE crawler_training.keyword_posting_discoveries (keyword_id bigint NOT NULL, source_code text NOT NULL,
  external_posting_id text NOT NULL, first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL);
CREATE TABLE crawler_training.harvest_runs (run_id uuid PRIMARY KEY, mode text NOT NULL, source_code text NOT NULL,
  status text NOT NULL, http_requests integer NOT NULL, ended_at timestamptz DEFAULT now());
CREATE TABLE crawler_training.harvest_items (run_id uuid NOT NULL, source_code text NOT NULL,
  external_posting_id text NOT NULL, outcome text);
"""


@unittest.skipUnless(ENABLED and ADMIN_DSN, 'set CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN')
class StagingProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        cls.psycopg = psycopg
        cls.db = f'gcp_sync_prov_{uuid.uuid4().hex[:8]}'
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE {cls.db}')
            if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'career_sync'").fetchone():
                admin.execute(f"CREATE ROLE career_sync LOGIN PASSWORD '{SYNC_PASSWORD}'")
        base = conninfo_to_dict(ADMIN_DSN)
        cls.owner_dsn = make_conninfo(**dict(base, dbname=cls.db))
        cls.sync_dsn = make_conninfo(**dict(base, dbname=cls.db, user='career_sync', password=SYNC_PASSWORD))
        try:
            cls._build()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def _build(cls):
        J = cls.psycopg.types.json.Jsonb
        with cls.psycopg.connect(cls.owner_dsn, autocommit=True) as owner:
            owner.execute('CREATE SCHEMA career')
            for name in ('0001_initial_schema.sql', '0002_deletion_request_unscheduled.sql',
                         '0003_market_metric_skill_dimension.sql'):
                owner.execute((ROOT / 'database/migrations' / name).read_text(encoding='utf-8'))
            owner.execute((ROOT / 'poc/staging/automation/gcp-sync/target_grants.sql').read_text(encoding='utf-8'))
            owner.execute((ROOT / 'crawler/storage/local_training_schema.sql').read_text(encoding='utf-8'))
            owner.execute(TABLES)
            owner.execute("INSERT INTO career.data_sources (code, name, license_ref, retention_days)"
                          " VALUES ('jobkorea_live', 'JobKorea live', 'test approval', 30)")
            owner.execute("INSERT INTO crawler_training.search_keywords VALUES (1, 'AX'), (2, '딥러닝')")
            ok_job, test_job, failed_job = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            owner.execute("INSERT INTO crawler_training.night_job_results VALUES"
                          " (%s, 1, '2026-11-12', 'SUCCEEDED', 7, '2026-11-12 22:00+09', '2026-11-12 22:00:40+09'),"
                          " (%s, 2, '2034-02-15', 'SUCCEEDED', 4, '2026-11-16 12:59:30+09', '2026-11-16 12:59:31+09'),"
                          " (%s, 2, '2026-11-12', 'FAILED', 3, '2026-11-12 23:00+09', '2026-11-12 23:00:20+09')",
                          (ok_job, test_job, failed_job))
            rows = {'101': '2026-11-12 22:00:30+09', '102': '2026-11-12 22:00:31+09', '103': '2026-11-08 09:50:48+09',
                    '104': '2026-11-16 12:59:31+09', '105': '2026-11-12 23:00:10+09', '106': '2026-11-08 09:50:48+09'}
            for n, at in rows.items():
                owner.execute('INSERT INTO crawler_training.postings VALUES (%s, %s, %s, %s)',
                              ('jobkorea_live', n, J(posting(int(n))), at))
            owner.execute("INSERT INTO crawler_training.postings VALUES ('jobkorea_imported', '880', %s, now())",
                          (J(posting(880)),))
            disc = [(1, '101', '2026-11-12 22:00:30+09', '2026-11-12 22:00:30+09'),   # A1
                    (1, '102', '2026-11-12 22:00:31+09', '2026-11-12 22:00:31+09'),   # A2
                    (2, '104', '2026-11-16 12:59:31+09', '2026-11-16 12:59:31+09'),   # C test clock
                    (2, '105', '2026-11-12 23:00:10+09', '2026-11-12 23:00:10+09'),   # E failed job
                    (1, '106', '2026-11-08 09:50:48+09', '2026-11-12 22:00:35+09')]   # D refreshed by A's job
            for k, n, first, last in disc:
                owner.execute('INSERT INTO crawler_training.keyword_posting_discoveries VALUES (%s, %s, %s, %s, %s)',
                              (k, 'jobkorea_live', n, first, last))
            # this PC's LIVE run ledger: 101 (shared with Staging) and 201 (only here)
            owner.execute("INSERT INTO crawler_training.postings VALUES ('jobkorea_live', '201', %s, '2026-11-16 17:21+09')",
                          (J(posting(201)),))
            owner.execute("INSERT INTO crawler_training.harvest_runs VALUES (%s, 'live', 'jobkorea_live', 'SUCCEEDED', 7, now())",
                          (LIVE,))
            owner.execute("INSERT INTO crawler_training.harvest_items VALUES (%s, 'jobkorea_live', '101', 'inserted'),"
                          " (%s, 'jobkorea_live', '201', 'inserted')", (LIVE, LIVE))

    @classmethod
    def tearDownClass(cls):
        with cls.psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS {cls.db} WITH (FORCE)')

    def sync(self, mode, *, local=False, cutover=False):
        source = self.psycopg.connect(self.owner_dsn)
        source.read_only = True
        target = self.psycopg.connect(self.sync_dsn)
        try:
            if local:
                return g.run_sync(source, target, mode=mode, live_run_ids=[LIVE], cutover_confirmed=cutover)
            return g.run_sync(source, target, mode=mode, require_provenance=True, cutover_confirmed=cutover)
        finally:
            source.close()
            target.close()

    def owner(self, sql, params=()):
        with self.psycopg.connect(self.owner_dsn, autocommit=True) as owner:
            cursor = owner.execute(sql, params)
            return cursor.fetchall() if cursor.description else None

    def target_ids(self):
        return sorted(r[0] for r in self.owner('SELECT external_id FROM career.job_posting_external_refs'))

    def test_01_staging_dry_run_keeps_proven_rows_and_skips_unproven(self):
        result = self.sync('dry-run')
        self.assertEqual((result['status'], result['source'], result['inserted']), ('DRY_RUN', 'staging', 3))
        self.assertEqual(result['skipped_reasons'], {'PROVENANCE_UNVERIFIED': 4, 'SOURCE_NOT_SELECTED': 1})
        self.assertEqual(self.target_ids(), [])

    def test_02_staging_run_copies_only_proven_rows_and_records_its_writer(self):
        result = self.sync('run')
        self.assertEqual((result['status'], result['inserted']), ('SUCCEEDED', 3))
        self.assertEqual(self.target_ids(), ['101', '102', '106'])  # 103 no job, 104 test clock, 105 failed, 201 no job
        summary = json.loads(self.owner('SELECT error_summary FROM career.ingestion_runs')[0][0])
        self.assertEqual((summary['source'], summary['skipped_reasons']['PROVENANCE_UNVERIFIED']), ('staging', 4))

    def test_03_second_writer_is_refused_until_cutover_is_confirmed(self):
        dry = self.sync('dry-run', local=True)
        self.assertEqual(dry['status'], 'DRY_RUN')
        self.assertIn('staging', dry['other_writers'])
        self.assertEqual((dry['inserted'], dry['duplicate'], dry['already_in_target']), (1, 1, 1))  # 101 shared
        run = self.sync('run', local=True)
        self.assertEqual((run['status'], run['error_code']), ('FAILED', 'OTHER_SYNC_SOURCE_ACTIVE'))
        self.assertEqual(self.target_ids(), ['101', '102', '106'])

    def test_04_confirmed_cutover_then_the_old_writer_is_refused(self):
        run = self.sync('run', local=True, cutover=True)
        self.assertEqual((run['status'], run['inserted'], run['duplicate']), ('SUCCEEDED', 1, 1))  # 201 new, 101 no duplicate insert
        self.assertEqual(self.target_ids(), ['101', '102', '106', '201'])
        back = self.sync('run')
        self.assertEqual((back['status'], back['error_code']), ('FAILED', 'OTHER_SYNC_SOURCE_ACTIVE'))
        self.assertIn('local', back['other_writers'])
        self.assertEqual(self.owner("SELECT count(*), count(*) FILTER (WHERE status <> 'draft') FROM career.job_postings"),
                         [(4, 0)])

    def test_00_staging_check_script_classifies_like_the_sync_filter(self):
        """The read-only check script (8b) and STAGING_PROVENANCE_SQL must agree row by row."""
        lines = (ROOT / 'poc/staging/automation/safety/staging_readonly_check.sh').read_text(encoding='utf-8').split('\n')
        start = next(i for i, l in enumerate(lines) if l.startswith('sec "8b'))
        begin = next(i for i in range(start, len(lines)) if lines[i] == 'BEGIN READ ONLY;')
        end = next(i for i in range(begin, len(lines)) if lines[i].endswith('ORDER BY l.updated_at, l.external_posting_id;'))
        script_sql = '\n'.join(lines[begin + 1:end + 1])
        rows = self.owner(script_sql)
        evidence = {r[0]: r[15] for r in rows}
        self.assertEqual(sorted(k for k, v in evidence.items() if v == 'LIVE_JOB_LINKED'), ['101', '102', '106'])
        self.assertEqual((evidence['103'], evidence['104'], evidence['105'], evidence['201']),
                         ('NO_DISCOVERY', 'JOB_LINKED_SYNTHETIC_CLOCK', 'JOB_LINKED_FAILED', 'NO_DISCOVERY'))
        self.assertEqual(sum(1 for _ in rows), 7)
        sync_ok = {r[1] for r in self.owner(g.STAGING_PROVENANCE_SQL) if r[0] == 'jobkorea_live' and r[4]}
        self.assertEqual(sync_ok, {'101', '102', '106'})

    def test_05_runs_of_the_old_deployed_code_count_as_staging(self):
        self.owner("UPDATE career.ingestion_runs SET error_summary = '{\"mode\": \"scheduled\"}'"
                   " WHERE error_summary::jsonb->>'source' = 'staging'")
        self.owner("DELETE FROM career.ingestion_runs WHERE error_summary::jsonb->>'source' = 'local'")
        run = self.sync('run', local=True)
        self.assertEqual((run['status'], run['error_code'], list(run['other_writers'])),
                         ('FAILED', 'OTHER_SYNC_SOURCE_ACTIVE', ['staging']))


if __name__ == '__main__':
    unittest.main()
