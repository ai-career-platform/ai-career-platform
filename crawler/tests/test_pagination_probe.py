"""Pagination probe: no network (the fetch function is replaced), no DB."""
import unittest
from unittest import mock

from crawler.jobs import harvest as h
from crawler.jobs import pagination_probe as pp
from crawler.jobs.import_jobkorea_html import FetchBlocked


def page_html(ids, total=None):
    links = ''.join(f'<a href="/Recruit/GI_Read/{i}?logpath=1">t</a>' for i in ids)
    return (f'<p>총 <strong>{total:,}</strong>건</p>' if total else '') + links


class FakeSource:
    def __init__(self):
        self.requests = 0

    def _permit(self, url):
        pass

    def robots(self):
        return None

    def _before_request(self):
        self.requests += 1


def run(pages, keywords=('AX', 'BI'), known=lambda ids: set()):
    def fetch(url, robots, before):
        before()
        result = pages[url]
        if isinstance(result, Exception):
            raise result
        return result
    with mock.patch.object(pp, '_fetch_allowed', side_effect=fetch):
        return pp.probe(FakeSource(), list(keywords), known)


def url(k, p):
    return pp.paged_search_url(h.search_url(k), p)


class ProbeTest(unittest.TestCase):
    def test_working_pagination_cross_duplicates_and_db_known(self):
        pages = {url('AX', 1): page_html(range(1, 21), total=1234), url('AX', 2): page_html(range(21, 41)),
                 url('BI', 1): page_html(range(35, 55), total=80), url('BI', 2): page_html(range(55, 75))}
        r = run(pages, known=lambda ids: {'1', '2'})
        self.assertEqual(r['pagination_live'], 'PASS')
        self.assertEqual((r['http_requests'], r['ids_seen'], r['unique_ids'], r['cross_keyword_duplicates']),
                         (4, 80, 74, 6))
        self.assertEqual((r['already_in_db'], r['new_candidates']), (2, 72))
        self.assertEqual((r['keywords']['AX']['total_shown'], r['keywords']['AX']['overlap_page1_page2']), (1234, 0))

    def test_ignored_page_parameter_is_reported_as_fail(self):
        same = page_html(range(1, 21))
        r = run({url('AX', 1): same, url('AX', 2): same}, keywords=('AX',))
        self.assertEqual((r['pagination_live'], r['keywords']['AX']['page_repeated']), ('FAIL', True))

    def test_block_signal_stops_everything(self):
        pages = {url('AX', 1): page_html(range(1, 21)), url('AX', 2): FetchBlocked('HTTP_429')}
        r = run(pages)
        self.assertEqual(r['stop_reason'], 'HTTP_429')
        self.assertNotIn('BI', r['keywords'])
        self.assertEqual(r['http_requests'], 2)

    def test_request_budget_is_one_robots_plus_two_pages_per_keyword(self):
        self.assertEqual(pp.limits_for(['a'] * 6).max_requests, 13)
        self.assertEqual(pp.limits_for(['a'] * 6).max_new_details, 0)

    def test_cli_without_approval_sends_nothing(self):
        with mock.patch.object(pp, '_fetch_allowed') as fetch, mock.patch('builtins.print'):
            self.assertEqual(pp.main(['--policy-file', 'missing.json']), 2)
        fetch.assert_not_called()

    def test_total_shown_is_best_effort(self):
        self.assertEqual(pp.extract_total('<span>총 <em>3,210</em> 건</span>'), 3210)
        self.assertIsNone(pp.extract_total('<div>no count</div>'))


if __name__ == '__main__':
    unittest.main()
