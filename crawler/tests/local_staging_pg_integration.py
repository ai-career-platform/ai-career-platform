"""Explicit CI/local isolated PostgreSQL test of container DB opt-in. No remote IO."""
import os
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from uuid import uuid4
from fastapi.testclient import TestClient
from backend.training_jobs_api import app
from crawler.storage.staging import connect_staging_db
from crawler.storage.postgres import PostgresPostingStore
from crawler.jobs.import_jobkorea_html import import_pages
from crawler.tests.test_html_import import sample


class Rollback(Exception):
    pass


class ContainerDatabaseTests(unittest.TestCase):
    def test_dedicated_role_import_query_and_rollback(self):
        if os.environ.get('CRAWLER_STAGING_PG_TEST') != '1':
            self.skipTest('Explicit isolated staging-mode PostgreSQL opt-in required')
        dsn = 'postgresql://crawler_staging@db:5432/ai_career_crawler_training'
        url = 'https://www.jobkorea.co.kr/Recruit/GI_Read/' + str(uuid4().int)
        with patch('socket.gethostbyname', return_value='127.0.0.1'):
            with connect_staging_db(dsn) as connection:
                store = PostgresPostingStore(connection)
                try:
                    with connection.transaction():
                        self.assertEqual(import_pages([(url, sample())], store)['inserted'], 1)
                        self.assertEqual(import_pages([(url, sample())], store)['unchanged'], 1)
                        with patch.dict('os.environ', {'CRAWLER_DB_MODE': 'staging', 'CRAWLER_STAGING_DATABASE_URL': dsn}):
                            with patch('backend.training_jobs_api.connect_staging_db', return_value=nullcontext(connection)):
                                response = TestClient(app).get('/jobs/collected?title=Example%20job')
                        self.assertEqual(response.status_code, 200)
                        self.assertTrue(any(row['source_url'] == url for row in response.json()))
                        raise Rollback()
                except Rollback:
                    pass
                self.assertIsNone(store.get('jobkorea_imported', url.rsplit('/', 1)[-1]))
