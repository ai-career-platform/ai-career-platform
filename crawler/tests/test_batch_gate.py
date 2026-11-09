"""Offline T63 batch validation: reason codes, duplication, identity review."""
import json
import unittest
from copy import deepcopy

from crawler.jobs.run_crawler import DEFAULT_FIXTURE
from crawler.normalizer import normalize
from crawler.quality.batch_gate import ReasonCode, check_synthetic_batch


class TestSyntheticBatchGate(unittest.TestCase):
    def setUp(self):
        self.rows = json.loads(DEFAULT_FIXTURE.read_text(encoding="utf-8"))

    def check_one_bad(self, patch, expected):
        row = deepcopy(self.rows[0])
        row.update(patch)
        result = check_synthetic_batch([row])
        self.assertEqual(result.summary(), {
            "fetched": 1, "accepted": 0, "invalid": 1, "duplicate": 0, "review": 0
        })
        self.assertEqual(result.issues[0].reason, expected)
        self.assertEqual(result.issues[0].index, 0)

    def test_valid_rows_pass(self):
        result = check_synthetic_batch(self.rows)
        self.assertEqual(result.summary(), {
            "fetched": 2, "accepted": 2, "invalid": 0, "duplicate": 0, "review": 0
        })
        self.assertEqual(result.issues, ())

    def test_missing_external_id(self):
        self.check_one_bad({"external_posting_id": ""}, ReasonCode.MISSING_EXTERNAL_ID)

    def test_blank_title(self):
        self.check_one_bad({"title": "   "}, ReasonCode.INVALID_REQUIRED_FIELD)

    def test_missing_company(self):
        self.check_one_bad({"company_name": None}, ReasonCode.INVALID_REQUIRED_FIELD)

    def test_bad_url(self):
        self.check_one_bad({"source_url": "https://example.org/a"}, ReasonCode.INVALID_URL)

    def test_invalid_date(self):
        self.check_one_bad({"expires_on": "2026-99-44"}, ReasonCode.INVALID_DATE)

    def test_expiry_before_publication(self):
        self.check_one_bad({"expires_on": "2020-01-01"}, ReasonCode.INVALID_DATE)

    def test_invalid_status(self):
        self.check_one_bad({"status": "removed"}, ReasonCode.INVALID_STATUS)

    def test_invalid_employment_type(self):
        self.check_one_bad({"employment_type": "other"}, ReasonCode.INVALID_EMPLOYMENT)

    def test_duplicate_in_batch_first_wins(self):
        first = deepcopy(self.rows[0])
        altered = {**first, "title": "후속 레코드"}
        result = check_synthetic_batch([first, altered])
        self.assertEqual(result.summary(), {
            "fetched": 2, "accepted": 1, "invalid": 0, "duplicate": 1, "review": 0
        })
        self.assertEqual(result.accepted[0].title, first["title"])
        self.assertEqual(result.issues[0].reason, ReasonCode.DUPLICATE_IN_BATCH)

    def test_same_title_different_id_not_merged(self):
        second = {**self.rows[0], "external_posting_id": "ANOTHER-ID"}
        result = check_synthetic_batch([self.rows[0], second])
        self.assertEqual(len(result.accepted), 2)
        self.assertEqual(result.duplicate, 0)

    def test_changed_url_for_existing_id_requires_review(self):
        old = normalize(self.rows[0])
        changed = {**self.rows[0], "source_url": "https://www.jobkorea.co.kr/Recruit/GI_Read/999999"}
        result = check_synthetic_batch([changed], previous={(old.source_code, old.external_posting_id): old})
        self.assertEqual((result.review, len(result.accepted)), (1, 0))
        self.assertEqual(result.issues[0].reason, ReasonCode.REVIEW_IDENTITY_CHANGE)

    def test_updated_title_same_id_and_url_accepted(self):
        old = normalize(self.rows[0])
        changed = {**self.rows[0], "title": "수정된 가상 제목"}
        result = check_synthetic_batch([changed], previous={(old.source_code, old.external_posting_id): old})
        self.assertEqual((result.review, len(result.accepted)), (0, 1))

    def test_previous_absent_item_not_deemed_deleted(self):
        old = normalize(self.rows[0])
        result = check_synthetic_batch([], previous={(old.source_code, old.external_posting_id): old})
        self.assertEqual(result.summary(), {
            "fetched": 0, "accepted": 0, "invalid": 0, "duplicate": 0, "review": 0
        })

    def test_mixed_totals_and_safe_issues(self):
        invalid = {**self.rows[0], "title": ""}
        result = check_synthetic_batch([self.rows[0], self.rows[0], invalid, self.rows[1]])
        self.assertEqual(result.summary(), {
            "fetched": 4, "accepted": 2, "invalid": 1, "duplicate": 1, "review": 0
        })
        self.assertEqual([issue.index for issue in result.issues], [1, 2])
        self.assertFalse(hasattr(result.issues[0], "payload"))

    def test_rejects_non_batch(self):
        with self.assertRaises(TypeError):
            check_synthetic_batch({"not": "a list"})

    def test_rejects_bad_previous_entry(self):
        key = ("jobkorea", self.rows[0]["external_posting_id"])
        with self.assertRaises(TypeError):
            check_synthetic_batch([self.rows[0]], previous={key: {}})


if __name__ == "__main__":
    unittest.main()
