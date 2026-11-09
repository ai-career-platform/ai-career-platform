"""T62 STEP 08 — synthetic-only evidence tests for field accuracy scoring."""
import unittest

from crawler.adapters.jobkorea_html_offline import parse_jobkorea_html
from crawler.quality.offline_accuracy import (
    AccuracyStatus, FieldVerdict, GoldCase, aggregate, evaluate_extraction,
    evaluate_html,
)

URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/50246410"
HTML = """<html><script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "url":"https://www.jobkorea.co.kr/Recruit/GI_Read/50246410",
 "identifier":{"value":"50246410"},"title":"합성 공고",
 "hiringOrganization":{"name":"가상회사"},
 "employmentType":"CONTRACTOR",
 "datePosted":"2026-11-01"}
</script></html>"""


def gold(**expected):
    return GoldCase(source_url=URL, expected=expected)


def parsed():
    return parse_jobkorea_html(html=HTML, source_url=URL)


class TestOfflineAccuracy(unittest.TestCase):
    def test_three_matches_score_one(self):
        report = evaluate_extraction(gold(
            title="합성 공고", company_name="가상회사",
            external_posting_id="50246410",
        ), parsed())
        self.assertEqual((report.compared, report.matches), (3, 3))
        self.assertEqual(report.exact_match_rate, 1)
        self.assertEqual(report.status, AccuracyStatus.SYNTHETIC_ONLY)
        self.assertFalse(report.snapshot()["real_site_accuracy_verified"])

    def test_partial_match_and_mismatch(self):
        report = evaluate_extraction(gold(title="잘못된 기대값", company_name="가상회사"), parsed())
        self.assertEqual((report.compared, report.matches, report.mismatches), (2, 1, 1))
        self.assertEqual(report.exact_match_rate, .5)
        self.assertEqual(report.coverage_rate, 1.0)

    def test_missing_prediction_is_in_denominator(self):
        report = evaluate_extraction(gold(title="합성 공고", location_text="서울"), parsed())
        self.assertEqual((report.compared, report.missing), (2, 1))
        self.assertEqual(report.exact_match_rate, .5)
        self.assertEqual(report.coverage_rate, .5)

    def test_unknown_reference_is_not_scored(self):
        report = evaluate_extraction(gold(title=None, company_name="가상회사"), parsed())
        self.assertEqual(report.compared, 1)
        self.assertEqual(report.fields[1].verdict, FieldVerdict.NOT_VERIFIED)

    def test_unsupported_fields_explicitly_reported(self):
        report = evaluate_extraction(gold(title="합성 공고", salary="5000만원", education="대졸"), parsed())
        self.assertEqual(report.unsupported, 4)
        self.assertEqual(report.snapshot()["fields"]["salary"], "NOT_SUPPORTED")
        self.assertEqual(report.compared, 1)

    def test_no_reference_html_is_not_success(self):
        report = evaluate_html(case=gold(title="합성 공고"), html=None)
        self.assertEqual(report.missing, 1)
        self.assertEqual(report.exact_match_rate, 0.0)
        self.assertEqual(report.coverage_rate, 0.0)

    def test_no_verified_reference_yields_null_rate(self):
        report = evaluate_html(case=gold(title=None), html=None)
        self.assertIsNone(report.exact_match_rate)
        self.assertIsNone(report.coverage_rate)
        self.assertEqual(report.compared, 0)

    def test_bad_html_not_falsely_successful(self):
        report = evaluate_html(case=gold(title="합성 공고"), html="<h1>no json ld</h1>")
        self.assertEqual(report.missing, 1)
        self.assertEqual(report.matches, 0)

    def test_good_html_pipeline(self):
        report = evaluate_html(case=gold(title="합성 공고", employment_type="contract"), html=HTML)
        self.assertEqual((report.matches, report.compared), (2, 2))

    def test_wrong_source_url_refused(self):
        case = GoldCase(
            source_url="https://www.jobkorea.co.kr/Recruit/GI_Read/111",
            expected={"title": "합성 공고"},
        )
        with self.assertRaises(ValueError):
            evaluate_extraction(case, parsed())

    def test_invalid_provenance_refused(self):
        with self.assertRaises(ValueError):
            GoldCase(source_url=URL, expected={"title": "합성 공고"}, provenance="real")

    def test_real_evidence_reference_required(self):
        with self.assertRaises(ValueError):
            GoldCase(source_url=URL, expected={"title": "합성 공고"}, provenance="real_authorized")

    def test_real_reference_without_html_not_real_verified(self):
        case = GoldCase(
            source_url=URL, expected={"title": "합성 공고"},
            provenance="real_authorized", evidence_ref="approval-ref-in-test-only",
        )
        report = evaluate_html(case=case, html=None)
        self.assertEqual(report.status, AccuracyStatus.REAL_NOT_VERIFIED)
        self.assertEqual(report.matches, 0)
        self.assertFalse(report.snapshot()["real_site_accuracy_verified"])

    def test_real_unverified_when_reference_unknown(self):
        case = GoldCase(
            source_url=URL, expected={"title": None},
            provenance="real_authorized", evidence_ref="approval-ref-in-test-only",
        )
        report = evaluate_html(case=case, html=None)
        self.assertEqual(report.status, AccuracyStatus.REAL_NOT_VERIFIED)

    def test_snapshot_excludes_raw_values(self):
        report = evaluate_html(case=gold(title="합성 공고"), html=HTML)
        output = str(report.snapshot())
        self.assertNotIn("가상회사", output)
        self.assertNotIn("합성 공고", output)
        self.assertNotIn(URL, output)

    def test_aggregate_micro_average(self):
        a = evaluate_extraction(gold(title="합성 공고"), parsed())
        b = evaluate_extraction(gold(title="다름", company_name="가상회사"), parsed())
        output = aggregate((a, b))
        self.assertEqual((output["matches"], output["verified_fields"]), (2, 3))
        self.assertAlmostEqual(output["exact_match_rate"], 2 / 3)

    def test_aggregate_empty_is_not_measurable(self):
        output = aggregate(())
        self.assertEqual(output["cases"], 0)
        self.assertIsNone(output["exact_match_rate"])

    def test_aggregate_rejects_mixed_evidence(self):
        a = evaluate_html(case=gold(title="합성 공고"), html=HTML)
        b = evaluate_html(case=GoldCase(
            source_url=URL, expected={"title": None},
            provenance="real_authorized", evidence_ref="approval-ref-in-test-only",
        ), html=None)
        with self.assertRaises(ValueError):
            aggregate((a, b))

    def test_disallow_empty_reference(self):
        with self.assertRaises(ValueError):
            gold()

    def test_disallow_unknown_field(self):
        with self.assertRaises(ValueError):
            gold(ssn="sensitive")

    def test_disallow_blank_reference_value(self):
        with self.assertRaises(ValueError):
            gold(title="  ")


if __name__ == "__main__":
    unittest.main()
