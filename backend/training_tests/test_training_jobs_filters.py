"""Search/filter contract tests; all DB operations are mocked."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.training_jobs_api import app, read_training_jobs


class TrainingJobFilterTests(unittest.TestCase):
    def test_parameterized_combined_filters(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        with patch.dict("os.environ", {"CRAWLER_LOCAL_DATABASE_URL":
                        "postgresql://crawler_student@127.0.0.1/ai_career_crawler_training"}):
            with patch("backend.training_jobs_api.connect_local_training_db", return_value=conn):
                self.assertEqual(
                    read_training_jobs(limit=10, title="Python", location="경기",
                                       employment_type="contract"), []
                )
        sql, params = cursor.execute.call_args.args
        self.assertEqual(params, ("jobkorea", "SYNTH-%", "Python", "경기", "contract", 10))
        self.assertIn("strpos(lower(payload->>'title'), lower(%s)) > 0", sql)
        self.assertIn("payload->>'location_text' = %s", sql)
        self.assertIn("payload->>'employment_type' = %s", sql)
        self.assertTrue(sql.strip().upper().startswith("SELECT"))
        self.assertNotIn("Python", sql)
        self.assertNotIn("경기", sql)

    def test_title_sql_injection_remains_a_value(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor
        malicious = "' OR 1=1 --"
        with patch.dict("os.environ", {"CRAWLER_LOCAL_DATABASE_URL":
                        "postgresql://crawler_student@127.0.0.1/ai_career_crawler_training"}):
            with patch("backend.training_jobs_api.connect_local_training_db", return_value=conn):
                read_training_jobs(limit=20, title=malicious)
        sql, params = cursor.execute.call_args.args
        self.assertNotIn(malicious, sql)
        self.assertEqual(params, ("jobkorea", "SYNTH-%", malicious, 20))

    def test_api_forwards_all_filters(self):
        with patch("backend.training_jobs_api.read_training_jobs", return_value=[]) as read:
            with TestClient(app) as client:
                res = client.get("/jobs", params={
                    "title": "Python", "location": "경기",
                    "employment_type": "contract", "limit": 2,
                })
        self.assertEqual(res.status_code, 200)
        read.assert_called_once_with(
            limit=2, title="Python", location="경기", employment_type="contract"
        )

    def test_default_without_filters_preserves_existing_contract(self):
        with patch("backend.training_jobs_api.read_training_jobs", return_value=[]) as read:
            with TestClient(app) as client:
                res = client.get("/jobs")
        self.assertEqual(res.status_code, 200)
        read.assert_called_once_with(limit=20)

    def test_invalid_employment_type_is_422(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/jobs?employment_type=unknown").status_code, 422)

    def test_overlong_title_is_422(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/jobs", params={"title": "a" * 81}).status_code, 422)

    def test_blank_title_is_422(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/jobs?title=").status_code, 422)

    def test_location_too_long_is_422(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/jobs", params={"location": "A" * 41}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
