"""Network-free validation of synthetic JobKorea-shaped inputs."""
import json
import unittest
from pathlib import Path

from crawler.normalizer import InvalidPosting, normalize

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "jobkorea_synthetic.json"


class TestNormalizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_normalizes_all_fixture_rows(self):
        actual = [normalize(item) for item in self.rows]
        self.assertEqual(len(actual), 2)
        self.assertEqual([x.source_code for x in actual], ["jobkorea", "jobkorea"])
        self.assertEqual(actual[0].title, "AI 데이터 분석 실습 개발자")

    def test_missing_title_rejected(self):
        row = {**self.rows[0], "title": ""}
        with self.assertRaises(InvalidPosting):
            normalize(row)

    def test_invalid_date_rejected(self):
        row = {**self.rows[0], "expires_on": "2026-99-99"}
        with self.assertRaises(InvalidPosting):
            normalize(row)

    def test_backward_dates_rejected(self):
        row = {**self.rows[0], "expires_on": "2026-01-01"}
        with self.assertRaises(InvalidPosting):
            normalize(row)

    def test_external_domain_rejected(self):
        row = {**self.rows[0], "source_url": "https://example.com/Recruit/123"}
        with self.assertRaises(InvalidPosting):
            normalize(row)

    def test_status_rejected(self):
        row = {**self.rows[0], "status": "unknown"}
        with self.assertRaises(InvalidPosting):
            normalize(row)

    def test_optional_fields(self):
        row = {**self.rows[0], "location_text": None, "employment_type": None}
        actual = normalize(row)
        self.assertIsNone(actual.location_text)
        self.assertIsNone(actual.employment_type)


if __name__ == "__main__":
    unittest.main()
