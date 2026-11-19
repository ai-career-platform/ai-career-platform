"""JobKorea API -> Cloud SQL collector: row collection, planning options, CLI guards. No network, no DB."""
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone

from crawler.jobs import gcp_sync as g
from crawler.jobs import jobkorea_collector as c
from crawler.jobs.import_jobkorea_html import FetchBlocked
from crawler.jobs.jobkorea_api import ApiLimits, FixtureApiSource
from crawler.tests.jobkorea_api_fixture import item, page

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)


def collect(responses, *, want=100, known=(), keywords=('AX', '빅데이터'), size=100, pages=5):
    source = FixtureApiSource(responses)
    rows, stats = c.collect_rows(source, keywords=list(keywords), limits=ApiLimits(page_size=size, max_pages=pages),
                                 known_ids=set(known), want=want, source_code='jobkorea_api', seen_at=NOW)
    return rows, stats, source


class CollectRowsTest(unittest.TestCase):
    def test_one_row_per_posting_across_keywords_with_target_duplicates_counted(self):
        rows, stats, source = collect({
            ('AX', 1): page([item(1), item(2), item(3)]),
            ('빅데이터', 1): page([item(2), item(4), item(5, company='')]),
        }, known=('3',))
        self.assertEqual([r.external_posting_id for r in rows], ['1', '2', '3', '4'])
        self.assertEqual((stats.received, stats.parsed, stats.invalid, stats.cross_keyword_duplicates),
                         (6, 4, 1, 1))
        self.assertEqual((stats.known_in_target, stats.new_candidates, stats.stop_reason), (1, 3, 'SUPPLY_EXHAUSTED'))
        self.assertTrue(all(r.source_code == 'jobkorea_api' and r.updated_at == NOW for r in rows))
        self.assertEqual(rows[0].payload['source_url'], 'https://www.jobkorea.co.kr/Recruit/GI_Read/1')
        self.assertNotIn('SECRET', json.dumps([r.payload for r in rows]))
        self.assertEqual(source.requests, 2)

    def test_paging_stops_once_enough_new_postings_were_seen(self):
        rows, stats, source = collect({
            ('AX', 1): page([item(i) for i in range(1, 3)], total=6),
            ('빅데이터', 1): page([item(i) for i in range(3, 5)], total=2),
            ('AX', 2): page([item(i) for i in range(5, 7)], total=6),
        }, want=2, size=2)
        self.assertEqual((stats.new_candidates, source.requests, stats.stop_reason), (2, 1, None))
        self.assertEqual(len(rows), 2)

    def test_more_pages_only_while_needed_and_total_results_bound_paging(self):
        rows, stats, source = collect({
            ('AX', 1): page([item(1), item(2)], total=3), ('AX', 2): page([item(3)], total=3),
        }, keywords=('AX',), size=2)
        self.assertEqual((source.requests, stats.pages, len(rows)), (2, 2, 3))

    def test_a_repeated_page_ends_the_keyword(self):
        same = page([item(1), item(2)], total=10)
        rows, stats, source = collect({('AX', 1): same, ('AX', 2): same}, keywords=('AX',), size=2)
        self.assertEqual((source.requests, len(rows)), (2, 2))

    def test_a_non_xml_answer_stops_the_run(self):
        with self.assertRaises(FetchBlocked) as ctx:
            collect({('AX', 1): '<html>오류</html>'.encode('cp949')})
        self.assertEqual(ctx.exception.reason, 'UNEXPECTED_ROOT')


class PlanOptionsTest(unittest.TestCase):
    def row(self, n, **over):
        body = {'source_code': 'jobkorea_api', 'external_posting_id': str(n),
                'source_url': f'https://www.jobkorea.co.kr/Recruit/GI_Read/{n}', 'title': f'공고 {n}',
                'company_name': '회사', 'location_text': '서울특별시', 'employment_type': 'full_time',
                'published_on': '2026-11-10', 'expires_on': '2026-12-31', 'status': 'published'}
        body.update(over)
        return g.SourceRow('jobkorea_api', str(n), body, NOW)

    def existing(self, row):
        values = g.map_row(row, publish=False)
        return g.Existing('posting-1', 'src', values)

    def test_empty_api_values_never_clear_stored_values(self):
        stored = self.row(1)
        fresh = self.row(1, location_text=None, employment_type=None, title='새 제목')
        refs = {'1': self.existing(stored)}
        kept = g.plan([fresh], source_code='jobkorea_api', source_id='src', refs=refs, url_owners={}, publish=False,
                      preserve_on_null=True)
        self.assertEqual([changes for _, changes, _ in kept.updates], [{'title': '새 제목'}])
        cleared = g.plan([fresh], source_code='jobkorea_api', source_id='src', refs=refs, url_owners={},
                         publish=False)
        self.assertEqual(set(cleared.updates[0][1]), {'title', 'location_text', 'employment_type'})

    def test_insert_limit_skips_the_rest_and_keeps_the_accounting(self):
        rows = [self.row(n) for n in range(1, 6)]
        result = g.plan(rows, source_code='jobkorea_api', source_id='src', refs={}, url_owners={}, publish=False,
                        max_inserts=2)
        self.assertEqual((len(result.inserts), [r for _, r in result.skipped]), (2, ['INSERT_LIMIT'] * 3))
        self.assertTrue(g.check_accounting(len(rows), result))
        self.assertTrue(all(v['status'] == 'draft' for _, v, _ in result.inserts))


class CliTest(unittest.TestCase):
    def run_cli(self, argv, environ=None):
        out = io.StringIO()
        with redirect_stdout(out):
            code = c.main(argv, environ=environ or {},
                          connect_target=lambda env: (_ for _ in ()).throw(AssertionError('no DB expected')))
        return code, json.loads(out.getvalue())

    def test_fixture_data_is_never_written_to_the_target(self):
        code, result = self.run_cli(['run', '--fixture-dir', 'unused'])
        self.assertEqual((code, result['error_code'], result['api_requests']), (2, 'FIXTURE_WRITE_REFUSED', 0))

    def test_live_mode_without_approval_or_config_sends_nothing(self):
        code, result = self.run_cli(['run'])
        self.assertEqual((code, result['status'], result['api_requests']), (2, 'BLOCKED', 0))
        self.assertEqual(result['problems'], ['APPROVAL_FILE_MISSING_OR_INVALID', 'API_CONFIG_MISSING_OR_INVALID'])


if __name__ == '__main__':
    unittest.main()
