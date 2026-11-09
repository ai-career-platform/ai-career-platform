"""T63 STEP 01: deterministic, offline lifecycle classification tests."""
import unittest
from dataclasses import replace
from datetime import date, datetime

from crawler.jobs.run_crawler import DEFAULT_FIXTURE
from crawler.adapters.jobkorea_fixture import JobKoreaFixtureAdapter
from crawler.normalizer import normalize
from crawler.quality.lifecycle import Lifecycle, classify_posting


class TestLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = JobKoreaFixtureAdapter(DEFAULT_FIXTURE).fetch()[0]
        cls.posting = normalize(raw)
        cls.today = date(2026, 11, 7)

    def posting_with(self, **values):
        return replace(self.posting, **values)

    def test_published_with_no_expiration_is_active(self):
        item = self.posting_with(status="published", expires_on=None)
        self.assertEqual(classify_posting(item, as_of=self.today), Lifecycle.ACTIVE)

    def test_future_expiration_is_active(self):
        item = self.posting_with(status="published", expires_on="2026-11-08")
        self.assertEqual(classify_posting(item, as_of=self.today), Lifecycle.ACTIVE)

    def test_expiration_on_same_day_is_active(self):
        item = self.posting_with(status="published", expires_on="2026-11-07")
        self.assertEqual(classify_posting(item, as_of=self.today), Lifecycle.ACTIVE)

    def test_expiration_before_date_is_expired(self):
        item = self.posting_with(status="published", expires_on="2026-11-06")
        self.assertEqual(classify_posting(item, as_of=self.today), Lifecycle.EXPIRED)

    def test_source_closed_takes_priority(self):
        item = self.posting_with(status="closed", expires_on="2026-11-08")
        self.assertEqual(classify_posting(item, as_of=self.today), Lifecycle.CLOSED)

    def test_source_draft_takes_priority(self):
        item = self.posting_with(status="draft", expires_on="2026-11-06")
        self.assertEqual(classify_posting(item, as_of=self.today), Lifecycle.DRAFT)

    def test_repeated_evaluation_is_deterministic(self):
        item = self.posting_with(status="published", expires_on="2026-11-06")
        results = [classify_posting(item, as_of=self.today) for _ in range(3)]
        self.assertEqual(results, [Lifecycle.EXPIRED] * 3)

    def test_rejects_non_posting(self):
        with self.assertRaises(TypeError):
            classify_posting({}, as_of=self.today)

    def test_rejects_datetime_instead_of_date(self):
        with self.assertRaises(TypeError):
            classify_posting(self.posting, as_of=datetime(2026, 11, 7, 10, 0))

    def test_rejects_unknown_status(self):
        item = self.posting_with(status="removed")
        with self.assertRaises(ValueError):
            classify_posting(item, as_of=self.today)


if __name__ == "__main__":
    unittest.main()
