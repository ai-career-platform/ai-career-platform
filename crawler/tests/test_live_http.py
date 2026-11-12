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



def allow(*urls):
    """T61 approval admitting exactly these detail URLs (test-only; never a real grant)."""
    from datetime import datetime, timezone
    from crawler.policy.source_approval_gate import SourceApproval
    return SourceApproval(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='test',
                          evidence_ref='test-only', valid_from_utc=datetime(2020, 1, 1, tzinfo=timezone.utc),
                          review_due_utc=datetime(2099, 1, 1, tzinfo=timezone.utc), collection_method='WEB',
                          allowed_urls=tuple(urls), allowed_purposes=('test',), max_requests=20,
                          retention_days=1, stop_on_block=True)

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
        # List mechanics only: the T61 gate is covered by GateTests below.
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', listing, HTML]) as get:
            with patch.object(crawler.time, 'sleep'), patch.object(crawler, '_permit'):
                store = MemoryPostingStore()
                report = crawler.import_pages(crawler.fetch_pages(list_url='https://www.jobkorea.co.kr/Search/?stext=ax', limit=1), store, live=True)
        self.assertEqual(report['inserted'], 1)
        self.assertEqual(get.call_count, 3)
        self.assertIsNotNone(store.get('jobkorea_live', '50242499'))

    def test_list_block_stops_before_details(self):
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', crawler.FetchBlocked('HTTP_403', http_status=403)]) as get:
            with patch.object(crawler.time, 'sleep'), patch.object(crawler, '_permit'):
                report = crawler.import_pages(crawler.fetch_pages(list_url='https://www.jobkorea.co.kr/Search/?stext=ax'), MemoryPostingStore(), live=True)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(report['stopped']['http_status'], 403)
        self.assertEqual(report['inserted'], 0)

    def test_failed_detail_reason_is_not_lost_and_next_page_continues(self):
        urls = [URL + '1', URL]
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', crawler.FetchError('HTTP_404', http_status=404), HTML]):
            with patch.object(crawler.time, 'sleep'):
                report = crawler.import_pages(crawler.fetch_pages(urls, approval=allow(*urls), purpose='test'), MemoryPostingStore(), live=True)
        self.assertEqual((report['invalid'], report['inserted']), (1, 1))
        self.assertEqual(report['errors'][0]['http_status'], 404)
        self.assertEqual(report['errors'][0]['stage'], 'fetch')

    def test_non_search_list_url_fails_before_network(self):
        for url in ('https://evil.example/Search/', 'https://www.jobkorea.co.kr/Login/', 'http://www.jobkorea.co.kr/Search/'):
            with patch.object(crawler, '_get') as get:
                with self.assertRaises(ValueError):
                    list(crawler.fetch_pages(list_url=url))
            get.assert_not_called()


class GateTests(unittest.TestCase):
    """STEP 03: every live HTTP path is checked against T61 before any request."""
    SEARCH = 'https://www.jobkorea.co.kr/Search/?stext=ax'

    def blocked(self, call):
        with patch.object(crawler, '_get') as get:
            report = crawler.import_pages(call(), MemoryPostingStore(), live=True)
        get.assert_not_called()
        self.assertEqual(report['stopped']['reason'], 'UNAPPROVED_SOURCE')
        return report

    def test_no_or_wrong_approval_sends_nothing(self):
        self.blocked(lambda: crawler.fetch_pages([URL]))
        self.blocked(lambda: crawler.fetch_pages([URL], approval=allow(URL)))  # purpose missing
        self.blocked(lambda: crawler.fetch_pages([URL], approval=allow(URL + '1'), purpose='test'))
        disabled = allow(URL).__class__(**{**allow(URL).__dict__, 'enabled': False})
        self.blocked(lambda: crawler.fetch_pages([URL], approval=disabled, purpose='test'))

    def test_keyword_search_is_outside_current_t61_scope(self):
        self.blocked(lambda: crawler.fetch_pages(list_url=self.SEARCH, approval=allow(URL), purpose='test'))

    def test_discovered_detail_must_also_be_approved(self):
        other = 'https://www.jobkorea.co.kr/Recruit/GI_Read/1'
        listing = f'<a href="{other}">x</a>'
        real = crawler._permit
        permit = lambda approval, purpose, url, calls, now: None if url == self.SEARCH else real(approval, purpose, url, calls, now)
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', listing]) as get:
            with patch.object(crawler.time, 'sleep'), patch.object(crawler, '_permit', side_effect=permit):
                report = crawler.import_pages(crawler.fetch_pages(list_url=self.SEARCH, approval=allow(URL), purpose='test'),
                                              MemoryPostingStore(), live=True)
        self.assertEqual(get.call_count, 2)  # robots + list, never the unapproved detail
        self.assertEqual(report['stopped']['reason'], 'UNAPPROVED_SOURCE')

    def test_approved_url_is_fetched(self):
        with patch.object(crawler, '_get', side_effect=['User-agent: *\nAllow: /', HTML]) as get:
            with patch.object(crawler.time, 'sleep'):
                report = crawler.import_pages(crawler.fetch_pages([URL], approval=allow(URL), purpose='test'),
                                              MemoryPostingStore(), live=True)
        self.assertEqual((get.call_count, report['inserted']), (2, 1))

    def test_cli_live_without_policy_file_is_blocked_before_network(self):
        import contextlib
        output = io.StringIO()
        with patch('sys.argv', ['import_jobkorea_html', '--url', URL]), patch.object(crawler, '_get') as get, \
                patch.object(crawler, 'connect_configured_database', return_value=contextlib.nullcontext(None)), \
                patch.object(crawler, 'PostgresPostingStore', return_value=MemoryPostingStore()), \
                contextlib.redirect_stdout(output):
            self.assertEqual(crawler.main(), 2)
        get.assert_not_called()
        self.assertIn('UNAPPROVED_SOURCE', output.getvalue())

    def test_policy_file_loader(self):
        import json, os, tempfile
        data = dict(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='t', evidence_ref='r',
                    valid_from_utc='2020-01-01T00:00:00Z', review_due_utc='2099-01-01T00:00:00Z', collection_method='WEB',
                    allowed_urls=[URL], allowed_purposes=['manual_collection'], max_requests=3, retention_days=1,
                    stop_on_block=True)
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(data, f)
        self.addCleanup(os.unlink, f.name)
        approval = crawler.load_approval_file(f.name)
        self.assertEqual(approval.allowed_urls, (URL,))
        self.assertIsNone(crawler.load_approval_file(f.name + '.missing'))
