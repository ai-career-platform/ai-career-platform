"""HTTP transport and list pipeline tests. All remote responses are mocked."""
import io
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from crawler.jobs import import_jobkorea_html as crawler
from crawler.storage.memory import MemoryPostingStore

URL = 'https://www.jobkorea.co.kr/Recruit/GI_Read/50242499'
HTML = (Path(__file__).resolve().parents[1] / 'fixtures/jobkorea_user_detail_jsonld.html').read_text(encoding='utf-8')


class LiveHttpTests(unittest.TestCase):
    def test_http_success_has_timeout_user_agent_and_no_redirects(self):
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.headers.get_content_type.return_value = 'text/html'
        response.headers.get_content_charset.return_value = 'utf-8'
        response.read.return_value = HTML.encode('utf-8')
        with patch.object(crawler, 'build_opener', return_value=opener) as build:
            self.assertEqual(crawler._get(URL), HTML)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header('User-agent'), crawler.USER_AGENT)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 15)
        self.assertIsInstance(build.call_args.args[0], crawler._NoRedirect)

    def test_http_status_errors_are_explicit(self):
        for code in (403, 404, 429, 500, 302):
            with self.subTest(code=code):
                opener = MagicMock()
                opener.open.side_effect = HTTPError(URL, code, 'do not expose response body', {}, io.BytesIO())
                with patch.object(crawler, 'build_opener', return_value=opener):
                    with self.assertRaises(crawler.FetchError) as raised:
                        crawler._get(URL)
                self.assertEqual(raised.exception.http_status, code)
                self.assertEqual(isinstance(raised.exception, crawler.FetchBlocked), code in (403, 429, 302))

    def test_timeout_is_explicit(self):
        for error in (TimeoutError(), URLError(TimeoutError())):
            opener = MagicMock()
            opener.open.side_effect = error
            with patch.object(crawler, 'build_opener', return_value=opener):
                with self.assertRaises(crawler.FetchError) as raised:
                    crawler._get(URL)
            self.assertEqual(raised.exception.reason, 'TIMEOUT')

    def test_list_to_detail_pipeline_uses_one_robots_request_and_dedup(self):
        listing = f'<a href="{URL}?tracking=1">a</a><a href="{URL}">b</a>'
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', listing, HTML]) as get:
            with patch.object(crawler.time, 'sleep'):
                store = MemoryPostingStore()
                report = crawler.import_pages(crawler.fetch_pages(list_url='https://www.jobkorea.co.kr/Search/?stext=ax', limit=1), store, live=True)
        self.assertEqual(report['inserted'], 1)
        self.assertEqual(get.call_count, 3)
        self.assertIsNotNone(store.get('jobkorea_live', '50242499'))

    def test_list_block_stops_before_details(self):
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', crawler.FetchBlocked('HTTP_403', http_status=403)]) as get:
            with patch.object(crawler.time, 'sleep'):
                report = crawler.import_pages(crawler.fetch_pages(list_url='https://www.jobkorea.co.kr/Search/?stext=ax'), MemoryPostingStore(), live=True)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(report['stopped']['http_status'], 403)
        self.assertEqual(report['inserted'], 0)

    def test_failed_detail_reason_is_not_lost_and_next_page_continues(self):
        urls = [URL + '1', URL]
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', crawler.FetchError('HTTP_404', http_status=404), HTML]):
            with patch.object(crawler.time, 'sleep'):
                report = crawler.import_pages(crawler.fetch_pages(urls), MemoryPostingStore(), live=True)
        self.assertEqual((report['invalid'], report['inserted']), (1, 1))
        self.assertEqual(report['errors'][0]['http_status'], 404)
        self.assertEqual(report['errors'][0]['stage'], 'fetch')

    def test_non_search_list_url_fails_before_network(self):
        for url in ('https://evil.example/Search/', 'https://www.jobkorea.co.kr/Login/', 'http://www.jobkorea.co.kr/Search/'):
            with patch.object(crawler, '_get') as get:
                with self.assertRaises(ValueError):
                    list(crawler.fetch_pages(list_url=url))
            get.assert_not_called()
