"""Offline read-only API tests; no PostgreSQL connection or external network."""
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.training_jobs_api import app, read_training_jobs


class TrainingJobsApiTests(unittest.TestCase):
    def test_schema_and_docs_route(self):
        spec = app.openapi()
        self.assertIn("/jobs", spec["paths"])
        self.assertIn("get", spec["paths"]["/jobs"])

    def test_read_only_select_and_synthetic_scope(self):
        cursor = MagicMock()
        cursor.fetchall.return_value = [
            ("SYNTH-AX-001", "jobkorea", "가상 공고", "가상 회사", "서울", "full_time")
        ]
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch.dict("os.environ", {"CRAWLER_LOCAL_DATABASE_URL":
                        "postgresql://crawler_student@127.0.0.1/ai_career_crawler_training"}):
            with patch("backend.training_jobs_api.connect_local_training_db",
                       return_value=connection) as connect:
                rows = read_training_jobs(limit=20)
        connect.assert_called_once()
        self.assertEqual(rows[0]["title"], "가상 공고")
        sql, params = cursor.execute.call_args.args
        self.assertTrue(sql.strip().upper().startswith("SELECT"))
        self.assertEqual(params, ("jobkorea", "SYNTH-%", 20))
        self.assertNotIn("UPDATE ", sql.upper())
        self.assertNotIn("INSERT ", sql.upper())

    def test_disallow_nonlocal_database_without_connect(self):
        with patch.dict("os.environ", {"CRAWLER_LOCAL_DATABASE_URL":
                        "postgresql://crawler_student@remote.example.com/ai_career_crawler_training"}):
            with patch("backend.training_jobs_api.connect_local_training_db") as connect:
                with self.assertRaises(ValueError):
                    read_training_jobs(limit=5)
                connect.assert_not_called()

    def test_missing_database_returns_sanitized_503(self):
        with patch.dict("os.environ", {"CRAWLER_LOCAL_DATABASE_URL": ""}):
            with TestClient(app) as client:
                response = client.get("/jobs")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"detail": "Training database unavailable"})

    def test_mocked_get_jobs_json(self):
        with patch("backend.training_jobs_api.read_training_jobs",
                   return_value=[{
                       "external_posting_id": "SYNTH-AX-001",
                       "source_code": "jobkorea",
                       "title": "가상 공고",
                       "company_name": "가상 회사",
                       "location_text": "서울",
                       "employment_type": "full_time",
                   }]):
            with TestClient(app) as client:
                response = client.get("/jobs?limit=2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["external_posting_id"], "SYNTH-AX-001")

    def test_limit_validation(self):
        with TestClient(app) as client:
            self.assertEqual(client.get("/jobs?limit=0").status_code, 422)
            self.assertEqual(client.get("/jobs?limit=101").status_code, 422)


if __name__ == "__main__":
    unittest.main()
