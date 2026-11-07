import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from backend.training_jobs_api import app, read_collected_jobs


class CollectedJobsTests(unittest.TestCase):
    def test_sql_source_isolation_and_parameterized_filters(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [({'source_code': 'jobkorea_imported'}, '2026-11-07')]
        with patch.dict('os.environ', {'CRAWLER_LOCAL_DATABASE_URL': 'postgresql://crawler_student@127.0.0.1/ai_career_crawler_training'}):
            with patch('backend.training_jobs_api.connect_local_training_db', return_value=conn):
                rows = read_collected_jobs(limit=10, title="' OR 1=1 --", location='Seoul', employment_type='intern')
        sql, params = cur.execute.call_args.args
        self.assertEqual(params, ('jobkorea_live', 'jobkorea_imported', "' OR 1=1 --", 'Seoul', 'intern', 10))
        self.assertNotIn('OR 1=1', sql)
        self.assertTrue(sql.startswith('SELECT'))
        self.assertIn("strpos(payload->>'location_text', %s) = 1", sql)
        self.assertEqual(rows[0]['evidence'], 'imported_html')

    def test_collected_endpoint_is_separate(self):
        with patch('backend.training_jobs_api.read_collected_jobs', return_value=[]) as read:
            response = TestClient(app).get('/jobs/collected?title=Python')
        self.assertEqual(response.status_code, 200)
        read.assert_called_once_with(limit=20, title='Python', location=None, employment_type=None)

    def test_collected_database_failure_is_sanitized(self):
        with patch('backend.training_jobs_api.read_collected_jobs', side_effect=RuntimeError('secret')):
            response = TestClient(app).get('/jobs/collected')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.text)
