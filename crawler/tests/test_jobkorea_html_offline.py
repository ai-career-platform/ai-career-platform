"""T62 STEP 07: only synthetic HTML; no live web or proprietary copies."""
import json
import unittest

from crawler.adapters.jobkorea_html_offline import (
    HtmlPostingError, parse_jobkorea_html,
)

URL = "https://www.jobkorea.co.kr/Recruit/GI_Read/50246410"


def document(*, title="합성 테스트 공고", company="가상기업", extras=None):
    item = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "hiringOrganization": {"@type": "Organization", "name": company},
        "url": URL,
        "identifier": {"value": "50246410"},
        "jobLocation": {"address": {
            "addressRegion": "서울", "addressLocality": "송파구",
        }},
        "employmentType": "CONTRACTOR",
        "datePosted": "2026-11-01",
        "validThrough": "2026-11-30T23:59:59+09:00",
    }
    if extras:
        item.update(extras)
    return '<html><script type="application/ld+json">' + json.dumps(item, ensure_ascii=False) + '</script></html>'


class TestJobKoreaOfflineHtml(unittest.TestCase):
    def test_synthetic_fields_and_normalization(self):
        result = parse_jobkorea_html(html=document(), source_url=URL)
        self.assertEqual(result.raw_record["external_posting_id"], "50246410")
        self.assertEqual(result.normalized().title, "합성 테스트 공고")
        self.assertEqual(result.normalized().company_name, "가상기업")
        self.assertEqual(result.normalized().employment_type, "contract")
        self.assertEqual(result.normalized().location_text, "서울 송파구")
        self.assertEqual(result.normalized().expires_on, "2026-11-30")

    def test_no_job_metadata_fails_closed(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html="<h1>아무 공고나 추측 금지</h1>", source_url=URL)

    def test_missing_required_title_fails(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(title=" "), source_url=URL)

    def test_missing_required_company_fails(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(company=" "), source_url=URL)

    def test_no_location_is_unknown_not_employer_address(self):
        result = parse_jobkorea_html(
            html=document(extras={"jobLocation": None, "hiringOrganization": {
                "name": "가상기업", "address": "기업 주소를 근무지로 오인 금지",
            }}),
            source_url=URL,
        )
        self.assertIsNone(result.normalized().location_text)
        self.assertIn("location_text", result.unknown_fields)

    def test_missing_dates_remain_unknown(self):
        result = parse_jobkorea_html(
            html=document(extras={"datePosted": None, "validThrough": None}), source_url=URL
        )
        self.assertIsNone(result.normalized().published_on)
        self.assertIsNone(result.normalized().expires_on)

    def test_unrecognized_employment_remains_unknown(self):
        result = parse_jobkorea_html(
            html=document(extras={"employmentType": "UNSUPPORTED"}), source_url=URL
        )
        self.assertIsNone(result.normalized().employment_type)

    def test_url_mismatch_fails(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(extras={"url": URL + "1"}), source_url=URL)

    def test_identifier_mismatch_fails(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(extras={"identifier": {"value": "999"}}), source_url=URL)

    def test_disallow_other_domains(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(), source_url="https://example.org/Recruit/GI_Read/50246410")

    def test_disallow_redirectish_path(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(), source_url=URL + "/next")

    def test_multiple_postings_ambiguous(self):
        item = json.loads(document().split('">', 1)[1].split("</script>", 1)[0])
        html = '<script type="application/ld+json">' + json.dumps([item, item], ensure_ascii=False) + '</script>'
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=html, source_url=URL)

    def test_graph_metadata_supported(self):
        item = json.loads(document().split('">', 1)[1].split("</script>", 1)[0])
        html = '<script type="application/ld+json">' + json.dumps({
            "@context": "https://schema.org", "@graph": [
                {"@type": "WebPage", "name": "가짜 SEO 제목"}, item
            ],
        }, ensure_ascii=False) + '</script>'
        result = parse_jobkorea_html(html=html, source_url=URL)
        self.assertEqual(result.normalized().title, "합성 테스트 공고")

    def test_malformed_ld_json_fails(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html='<script type="application/ld+json">{invalid</script>', source_url=URL)

    def test_invalid_date_fails(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(extras={"validThrough": "2026-99-99"}), source_url=URL)

    def test_expiry_before_posting_fails(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=document(extras={"validThrough": "2026-10-01"}), source_url=URL)

    def test_input_size_limit(self):
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html="A" * 2_000_001, source_url=URL)

    def test_seo_title_does_not_override_json_ld(self):
        html = document().replace("</html>", "<title>공고 무관 SEO</title><h1>무관한 제목</h1></html>")
        self.assertEqual(parse_jobkorea_html(html=html, source_url=URL).normalized().title, "합성 테스트 공고")

    def test_conflicting_script_nodes_rejected(self):
        html = document() + document(title="서로 다른 공고")
        with self.assertRaises(HtmlPostingError):
            parse_jobkorea_html(html=html, source_url=URL)


if __name__ == "__main__":
    unittest.main()
