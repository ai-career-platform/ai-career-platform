"""Training frontend smoke checks; no DB connection or external requests."""
import unittest

from fastapi.testclient import TestClient

from backend.training_jobs_api import app


class TestTrainingFrontend(unittest.TestCase):
    def test_page_is_served_on_local_training_app(self):
        with TestClient(app) as client:
            response = client.get("/training")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("합성 채용공고 조회 실습", response.text)

    def test_frontend_fetches_same_origin_readonly_endpoint(self):
        with TestClient(app) as client:
            page = client.get("/training").text
        self.assertIn('fetch("/jobs?" + params.toString()', page)
        self.assertIn('new URLSearchParams({ limit: "20" })', page)
        self.assertIn('params.set("title", title)', page)
        self.assertIn('params.set("location", location)', page)
        self.assertIn('params.set("employment_type", employmentType)', page)
        self.assertIn('filters.addEventListener("submit"', page)
        self.assertIn('reload.addEventListener("click", load)', page)
        self.assertIn("document.createElement", page)
        self.assertIn("textContent =", page)

    def test_page_isolation_and_security_headers(self):
        with TestClient(app) as client:
            response = client.get("/training")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("connect-src 'self'", response.headers["content-security-policy"])
        self.assertNotIn("DATABASE_URL", response.text)
        self.assertNotIn("PGPASSWORD", response.text)
        self.assertNotIn("innerHTML", response.text)

    def test_page_is_not_a_production_api_route(self):
        spec = app.openapi()
        self.assertNotIn("/training", spec["paths"])
        self.assertIn("/jobs", spec["paths"])


if __name__ == "__main__":
    unittest.main()
