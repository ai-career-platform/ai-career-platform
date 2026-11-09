"""Minimal link markup matching the user-supplied saved search page."""
import unittest
from pathlib import Path
from crawler.adapters import jobkorea_html_offline as parser


class ListHtmlTests(unittest.TestCase):
    def test_user_supplied_detail_jsonld_fields(self):
        html = (Path(__file__).resolve().parents[1] / 'fixtures' / 'jobkorea_user_detail_jsonld.html').read_text(encoding='utf-8')
        posting = parser.parse_jobkorea_html(html=html, source_url='https://www.jobkorea.co.kr/Recruit/GI_Read/50242499').normalized()
        self.assertEqual(posting.external_posting_id, '50242499')
        self.assertEqual(posting.title, '2027 쿠도커뮤니케이션㈜ 신입/경력 공개채용')
        self.assertEqual(posting.company_name, '쿠도커뮤니케이션㈜')
        self.assertEqual(posting.location_text, '경기 과천시 과천대로7나길 9 (갈현동, DX타워) 12~15층')
        self.assertEqual(posting.employment_type, 'full_time')
        self.assertEqual((posting.published_on, posting.expires_on), ('2026-11-01', '2026-11-15'))

    def test_tracking_links_are_canonicalized_and_deduplicated(self):
        html = '''<a href="https://www.jobkorea.co.kr/Recruit/GI_Read/50242499?Oem_Code=C1&amp;logpath=1">logo</a>
        <a href="https://www.jobkorea.co.kr/Recruit/GI_Read/50242499?listno=2">title</a>
        <a href="/Recruit/GI_Read/50309869?stext=ax">title</a>
        <a href="https://evil.example/Recruit/GI_Read/123">ignore</a>'''
        self.assertEqual(parser.parse_jobkorea_list_html(html), [
            'https://www.jobkorea.co.kr/Recruit/GI_Read/50242499',
            'https://www.jobkorea.co.kr/Recruit/GI_Read/50309869'])

    def test_limit_and_invalid_links(self):
        html = ''.join(f'<a href="/Recruit/GI_Read/{i}">title</a>' for i in range(20))
        self.assertEqual(len(parser.parse_jobkorea_list_html(html)), 10)
        self.assertEqual(parser.parse_jobkorea_list_html('<a href="javascript:alert(1)">bad</a>'), [])
        with self.assertRaises(ValueError):
            parser.parse_jobkorea_list_html(html, limit=11)
