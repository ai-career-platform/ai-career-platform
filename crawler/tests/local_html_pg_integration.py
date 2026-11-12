"""Explicit local DB test: constructed HTML, real PostgreSQL, rollback all rows."""
import os
import unittest
from contextlib import nullcontext
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from backend.training_jobs_api import app
from crawler.jobs.import_jobkorea_html import import_pages
from crawler.jobs import import_jobkorea_html as crawler
from crawler.storage.postgres import connect_local_training_db, PostgresPostingStore
from crawler.tests.test_html_import import sample



def allow(*urls):
    """T61 approval admitting exactly these detail URLs (test-only; never a real grant)."""
    from datetime import datetime, timezone
    from crawler.policy.source_approval_gate import SourceApproval
    return SourceApproval(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='test',
                          evidence_ref='test-only', valid_from_utc=datetime(2020, 1, 1, tzinfo=timezone.utc),
                          review_due_utc=datetime(2099, 1, 1, tzinfo=timezone.utc), collection_method='WEB',
                          allowed_urls=tuple(urls), allowed_purposes=('test',), max_requests=20,
                          retention_days=1, stop_on_block=True)

class Rollback(Exception):
    pass


class LocalHtmlPipeline(unittest.TestCase):
    def test_mock_http_live_source_postgres_and_api(self):
        if os.environ.get('CRAWLER_LOCAL_PG_TEST') != '1':
            self.skipTest('Explicit local PostgreSQL opt-in required')
        identifier = str(uuid4().int)
        url = 'https://www.jobkorea.co.kr/Recruit/GI_Read/' + identifier
        with connect_local_training_db(os.environ['CRAWLER_LOCAL_DATABASE_URL']) as connection:
            store = PostgresPostingStore(connection)
            try:
                with connection.transaction():
                    with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', sample()]):
                        with patch.object(crawler.time, 'sleep'):
                            report = import_pages(crawler.fetch_pages([url], approval=allow(url), purpose='test'), store, live=True)
                    self.assertEqual(report['inserted'], 1)
                    self.assertEqual(import_pages([(url, sample())], store, live=True)['unchanged'], 1)
                    with patch('backend.training_jobs_api.connect_local_training_db', return_value=nullcontext(connection)):
                        response = TestClient(app).get('/jobs/collected?title=Example%20job')
                    self.assertEqual(response.status_code, 200)
                    item = next(row for row in response.json() if row['external_posting_id'] == identifier)
                    self.assertEqual(item['evidence'], 'live_http')
                    raise Rollback()
            except Rollback:
                pass
            self.assertIsNone(store.get('jobkorea_live', identifier))

    def test_html_postgres_repeat_update_api(self):
        if os.environ.get('CRAWLER_LOCAL_PG_TEST') != '1':
            self.skipTest('Explicit local PostgreSQL opt-in required')
        identifier = str(uuid4().int)
        url = 'https://www.jobkorea.co.kr/Recruit/GI_Read/' + identifier
        dsn = os.environ['CRAWLER_LOCAL_DATABASE_URL']
        with connect_local_training_db(dsn) as connection:
            store = PostgresPostingStore(connection)
            try:
                with connection.transaction():
                    self.assertEqual(import_pages([(url, sample())], store)['inserted'], 1)
                    self.assertEqual(import_pages([(url, sample())], store)['unchanged'], 1)
                    self.assertEqual(import_pages([(url, sample('Changed local HTML test'))], store)['updated'], 1)
                    with patch('backend.training_jobs_api.connect_local_training_db', return_value=nullcontext(connection)):
                        response = TestClient(app).get('/jobs/collected?title=Changed%20local%20HTML%20test')
                    self.assertEqual(response.status_code, 200)
                    item = next(row for row in response.json() if row['external_posting_id'] == identifier)
                    self.assertEqual(item['evidence'], 'imported_html')
                    self.assertEqual(item['source_url'], url)
                    self.assertEqual(item['title'], 'Changed local HTML test')
                    raise Rollback()
            except Rollback:
                pass
            self.assertIsNone(store.get('jobkorea_imported', identifier))
