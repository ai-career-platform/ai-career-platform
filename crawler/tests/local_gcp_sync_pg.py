"""#337 GCP posting sync against real PostgreSQL (opt-in, throwaway server only).

CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN=<superuser DSN of a disposable server>.
Creates its own database with the real career schema (database/migrations 0001-0003) and the
production grants (poc/staging/automation/gcp-sync/target_grants.sql), then drops it.
The source side uses the real crawler postings table plus minimal status tables.
"""
import os
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from crawler.jobs import gcp_sync as g

ROOT = Path(__file__).resolve().parents[2]
ENABLED = os.environ.get('CRAWLER_GCP_SYNC_PG_TEST') == '1'
ADMIN_DSN = os.environ.get('CRAWLER_GCP_SYNC_ADMIN_DSN', '')
SYNC_PASSWORD = 'local-test-only'
NOON_KST = datetime(2026, 11, 14, 12, 0, tzinfo=g.KST)
SEEN = datetime(2026, 11, 12, 17, 4, tzinfo=timezone.utc)


def posting(n, **over):
    body = {'source_code': 'jobkorea', 'external_posting_id': str(n),
            'source_url': f'https://www.jobkorea.co.kr/Recruit/GI_Read/{n}', 'title': f'데이터 엔지니어 {n}',
            'company_name': f'회사{n % 3}', 'location_text': '서울', 'employment_type': 'full_time',
            'published_on': None, 'expires_on': '2027-01-31', 'status': 'published'}
    body.update(over)
    return body


@unittest.skipUnless(ENABLED and ADMIN_DSN, 'set CRAWLER_GCP_SYNC_PG_TEST=1 and CRAWLER_GCP_SYNC_ADMIN_DSN')
class GcpSyncPostgresTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        cls.psycopg = psycopg
        cls.db = f'gcp_sync_test_{uuid.uuid4().hex[:8]}'
        try:
            cls._build()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def _build(cls):
        psycopg = cls.psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE {cls.db}')
            if not admin.execute("SELECT 1 FROM pg_roles WHERE rolname = 'career_sync'").fetchone():
                admin.execute(f"CREATE ROLE career_sync LOGIN PASSWORD '{SYNC_PASSWORD}'")
        base = conninfo_to_dict(ADMIN_DSN)
        cls.owner_dsn = make_conninfo(**dict(base, dbname=cls.db))
        cls.sync_dsn = make_conninfo(**dict(base, dbname=cls.db, user='career_sync', password=SYNC_PASSWORD))
        with psycopg.connect(cls.owner_dsn, autocommit=True) as owner:
            owner.execute('CREATE SCHEMA career')
            for name in ('0001_initial_schema.sql', '0002_deletion_request_unscheduled.sql',
                         '0003_market_metric_skill_dimension.sql'):
                owner.execute((ROOT / 'database/migrations' / name).read_text(encoding='utf-8'))
            owner.execute((ROOT / 'poc/staging/automation/gcp-sync/target_grants.sql').read_text(encoding='utf-8'))
            owner.execute((ROOT / 'crawler/storage/local_training_schema.sql').read_text(encoding='utf-8'))
            owner.execute("CREATE TABLE crawler_training.runs (status text NOT NULL);"
                          "CREATE TABLE crawler_training.keyword_jobs (status text NOT NULL);"
                          "CREATE TABLE crawler_training.night_job_results (outcome text NOT NULL)")
            seed = owner.execute("INSERT INTO career.data_sources (code, name) VALUES ('synthetic_seed', 'seed')"
                                 ' RETURNING source_id').fetchone()[0]
            owner.execute("INSERT INTO career.data_sources (code, name, license_ref, retention_days)"
                          " VALUES ('jobkorea_live', 'JobKorea live', 'test approval', 30)")
            company = owner.execute("INSERT INTO career.companies (name, source_id) VALUES ('회사0', %s)"
                                    ' RETURNING company_id', (seed,)).fetchone()[0]
            cls.seed_posting = owner.execute(
                "INSERT INTO career.job_postings (company_id, source_id, title, source_url, status, published_at)"
                " VALUES (%s, %s, '[Seed] 공고', 'https://www.jobkorea.co.kr/Recruit/GI_Read/900', 'published', now())"
                ' RETURNING job_posting_id', (company, seed)).fetchone()[0]
            rows = [('jobkorea_live', str(n), posting(n)) for n in range(1, 7)]
            rows += [('jobkorea_imported', '880', posting(880)), ('jobkorea', 'SYNTH-1', posting(1, external_posting_id='SYNTH-1')),
                     ('jobkorea_live', '7', posting(7, title=''))]
            for code, key, body in rows:
                owner.execute('INSERT INTO crawler_training.postings (source_code, external_posting_id, payload, updated_at)'
                              ' VALUES (%s, %s, %s, %s)', (code, key, psycopg.types.json.Jsonb(body), SEEN))

    @classmethod
    def tearDownClass(cls):
        with cls.psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS {cls.db} WITH (FORCE)')

    # -- helpers
    def connections(self):
        source = self.psycopg.connect(self.owner_dsn)
        source.read_only = True
        return source, self.psycopg.connect(self.sync_dsn)

    def sync(self, mode='run', publish=False, now=NOON_KST):
        source, target = self.connections()
        try:
            return g.run_sync(source, target, mode=mode, publish=publish, now=now)
        finally:
            source.close()
            target.close()

    def owner(self, sql, params=()):
        with self.psycopg.connect(self.owner_dsn, autocommit=True) as owner:
            cursor = owner.execute(sql, params)
            return cursor.fetchall() if cursor.description else None

    def fingerprint(self):
        return self.owner(
            "SELECT md5(string_agg(t::text, '|' ORDER BY t::text COLLATE \"C\")) FROM ("
            ' SELECT p::text FROM career.job_postings p UNION ALL SELECT c::text FROM career.companies c'
            ' UNION ALL SELECT r::text FROM career.job_posting_external_refs r) t(t)')[0][0]

    def source_fingerprint(self):
        return self.owner("SELECT md5(string_agg(p::text, '|' ORDER BY p::text COLLATE \"C\")) FROM crawler_training.postings p")[0][0]

    # -- tests run in name order on one database
    def test_01_dry_run_writes_nothing(self):
        before, source_before = self.fingerprint(), self.source_fingerprint()
        result = self.sync(mode='dry-run')
        self.assertEqual((result['status'], result['inserted'], result['skipped'], result['failed']), ('DRY_RUN', 6, 3, 0))
        self.assertEqual(result['skipped_reasons'], {'SOURCE_NOT_SELECTED': 2, 'INVALID: Missing or invalid field: title': 1})
        self.assertEqual((self.fingerprint(), self.source_fingerprint()), (before, source_before))
        self.assertEqual(self.owner('SELECT count(*) FROM career.ingestion_runs')[0][0], 0)

    def test_02_first_run_inserts_with_integrity(self):
        source_before = self.source_fingerprint()
        result = self.sync()
        self.assertEqual((result['status'], result['inserted'], result['updated'], result['duplicate']), ('SUCCEEDED', 6, 0, 0))
        self.assertEqual(result['companies_created'], 3)  # 회사0 of the seed source is not reused
        live = self.owner("SELECT count(*), count(*) FILTER (WHERE p.status = 'draft'), count(DISTINCT r.external_id)"
                          ' FROM career.job_postings p JOIN career.data_sources s ON s.source_id = p.source_id'
                          " JOIN career.job_posting_external_refs r ON r.job_posting_id = p.job_posting_id WHERE s.code = 'jobkorea_live'")
        self.assertEqual(live, [(6, 6, 6)])
        self.assertEqual(self.owner("SELECT count(*) FROM career.job_postings p JOIN career.companies c USING (company_id)"
                                    ' WHERE c.source_id <> p.source_id')[0][0], 0)
        run = self.owner("SELECT status, fetched_count, error_summary::jsonb->>'inserted' FROM career.ingestion_runs")
        self.assertEqual(run, [('succeeded', 9, '6')])
        self.assertEqual(self.source_fingerprint(), source_before)

    def test_03_rerun_is_idempotent(self):
        before = self.fingerprint()
        result = self.sync()
        self.assertEqual((result['inserted'], result['updated'], result['duplicate']), (0, 0, 6))
        self.assertEqual(self.fingerprint(), before)

    def test_04_changed_source_updates_only_that_field(self):
        self.owner("UPDATE crawler_training.postings SET payload = jsonb_set(payload, '{title}', '\"바뀐 제목\"'),"
                   " updated_at = updated_at + interval '1 day' WHERE external_posting_id = '2'")
        before = dict(self.owner("SELECT r.external_id, p.updated_at FROM career.job_postings p"
                                 ' JOIN career.job_posting_external_refs r USING (job_posting_id)'))
        result = self.sync()
        self.assertEqual((result['inserted'], result['updated'], result['duplicate']), (0, 1, 5))
        after = dict(self.owner("SELECT r.external_id, p.updated_at FROM career.job_postings p"
                                ' JOIN career.job_posting_external_refs r USING (job_posting_id)'))
        self.assertEqual([k for k in after if after[k] != before[k]], ['2'])
        self.assertEqual(self.owner("SELECT title FROM career.job_postings p JOIN career.job_posting_external_refs r"
                                    " USING (job_posting_id) WHERE r.external_id = '2'"), [('바뀐 제목',)])

    def test_05_failure_rolls_back_everything(self):
        self.owner("INSERT INTO crawler_training.postings VALUES ('jobkorea_live', '8', %s, %s)",
                   (self.psycopg.types.json.Jsonb(posting(8)), SEEN))
        before = self.fingerprint()
        original = g.apply_plan

        def broken(cursor, result, **kwargs):
            original(cursor, result, **kwargs)  # writes the new posting, then fails
            raise RuntimeError('simulated crash')

        g.apply_plan = broken
        try:
            result = self.sync()
        finally:
            g.apply_plan = original
        self.assertEqual((result['status'], result['error_code']), ('FAILED', 'APPLY_RuntimeError'))
        self.assertEqual(self.fingerprint(), before)
        self.assertEqual(self.owner("SELECT status FROM career.ingestion_runs ORDER BY started_at DESC LIMIT 1"), [('failed',)])

    def test_06_seed_url_conflict_is_reported_not_overwritten(self):
        self.owner("INSERT INTO crawler_training.postings VALUES ('jobkorea_live', '900', %s, %s)",
                   (self.psycopg.types.json.Jsonb(posting(900)), SEEN))
        seed_before = self.owner('SELECT p::text FROM career.job_postings p WHERE job_posting_id = %s', (self.seed_posting,))
        result = self.sync()
        self.assertEqual((result['status'], result['inserted'], result['failed']), ('PARTIAL', 1, 1))  # 8 inserted, 900 refused
        self.assertEqual(result['failed_items'], ['900:URL_CONFLICT'])
        self.assertEqual(self.owner('SELECT p::text FROM career.job_postings p WHERE job_posting_id = %s', (self.seed_posting,)), seed_before)
        self.owner("DELETE FROM crawler_training.postings WHERE external_posting_id = '900'")

    def test_07_publish_and_backend_repository_visibility(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from app.repositories.job_postings import PostingFilter, SqlJobPostingRepository
        engine = create_engine('postgresql+psycopg://', creator=lambda: self.psycopg.connect(self.owner_dsn))
        query = PostingFilter(q=None, company_id=None, job_role_id=None, include_closed=False, sort='-published_at')
        now = datetime.now(timezone.utc)

        def visible():
            with Session(engine) as session:
                rows = SqlJobPostingRepository(session).list_postings(query, None, 100, now)
            return {r.title for r in rows if not r.title.startswith('[Seed]')}

        self.assertEqual(visible(), set())  # draft: stored but never exposed
        result = self.sync(publish=True)
        self.assertEqual((result['updated'], result['inserted']), (7, 0))
        self.assertEqual(len(visible()), 7)
        engine.dispose()

    def test_08_scheduled_guards(self):
        night = self.sync(mode='scheduled', now=datetime(2026, 11, 15, 2, 0, tzinfo=g.KST))
        self.assertEqual(night['reason'], 'NIGHT_WINDOW_OPEN')
        # Pin the latest succeeded run to 2026-11-14 08:06 KST to test the once-a-day guard.
        self.owner("UPDATE career.ingestion_runs SET started_at = '2026-11-14 08:06+09', ended_at = '2026-11-14 08:07+09'"
                   " WHERE ingestion_run_id = (SELECT ingestion_run_id FROM career.ingestion_runs"
                   " WHERE status = 'succeeded' ORDER BY started_at DESC LIMIT 1)")
        same_day = self.sync(mode='scheduled', now=datetime(2026, 11, 14, 20, 0, tzinfo=g.KST))
        self.assertEqual(same_day['reason'], 'ALREADY_SYNCED_TODAY')
        next_day = self.sync(mode='scheduled', publish=True, now=datetime(2026, 11, 16, 8, 5, tzinfo=g.KST))
        self.assertEqual((next_day['status'], next_day['inserted'], next_day['updated']), ('SUCCEEDED', 0, 0))
        self.owner("INSERT INTO crawler_training.keyword_jobs VALUES ('RUNNING')")
        busy = self.sync()
        self.assertEqual((busy['status'], busy['reason'], busy['busy']['keyword_jobs']), ('SKIPPED', 'CRAWLER_BUSY', 1))
        self.owner('DELETE FROM crawler_training.keyword_jobs')
        holder = self.psycopg.connect(self.sync_dsn, autocommit=True)
        try:
            holder.execute('SELECT pg_advisory_lock(%s)', (g.LOCK_KEY,))
            self.assertEqual(self.sync()['reason'], 'SYNC_IN_PROGRESS')
        finally:
            holder.close()

    def test_09_sync_role_cannot_delete_or_touch_other_tables(self):
        with self.psycopg.connect(self.sync_dsn, autocommit=True) as sync:
            for sql in ('DELETE FROM career.job_postings', 'UPDATE career.companies SET name = name',
                        'TRUNCATE career.job_posting_external_refs', 'SELECT count(*) FROM career.users',
                        "UPDATE career.data_sources SET name = 'x'", 'CREATE TABLE career.x (id int)',
                        'DELETE FROM career.ingestion_runs'):
                with self.subTest(sql=sql), self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                    sync.execute(sql)


if __name__ == '__main__':
    unittest.main()
