"""GOAL_3 harvest: gate scope, limits, result-page parsing, live-source gating and GCP local-source guards.

No network: every HTTP function is replaced by a fake that fails the test when it is not expected.
"""
from crawler.tests.provider_fixture import provider as _provider
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest import mock

from crawler.adapters import jobkorea_html_offline as parser
from crawler.jobs import gcp_sync as g
from crawler.jobs import harvest as h
from crawler.jobs import import_jobkorea_html as ij
from crawler.policy import source_approval_gate as gate

NOW = datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc)
AX = 'https://www.jobkorea.co.kr/Search/?stext=AX&tabType=recruit'
DETAIL = 'https://www.jobkorea.co.kr/Recruit/GI_Read/50300001'


def approval(**over):
    base = dict(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='PM',
                evidence_ref='private:REF-1', valid_from_utc=NOW - timedelta(days=1),
                review_due_utc=NOW + timedelta(days=1), collection_method='WEB', allowed_urls=(AX,),
                allowed_purposes=(gate.HARVEST_PURPOSE,), max_requests=500, retention_days=30,
                stop_on_block=True, max_search_pages=5, max_harvest_details=300, provider_permission=_provider())
    base.update(over)
    return gate.SourceApproval(**base)


def intent(url, *, purpose=gate.HARVEST_PURPOSE, calls=300, discovered_from=None):
    return gate.CollectionIntent('jobkorea', url, 'WEB', purpose, calls, NOW, discovered_from=discovered_from)


def decide(appr, url, **kw):
    return gate.check_collection_permission(appr, intent(url, **kw)).reason


class HarvestGateTest(unittest.TestCase):
    def test_pages_within_approval_are_allowed(self):
        for page in (1, 2, 5):
            self.assertEqual(decide(approval(), gate.paged_search_url(AX, page)), gate.GateReason.ALLOWED)
        self.assertEqual(gate.paged_search_url(AX, 3), AX + '&Page_No=3')

    def test_page_beyond_approval_or_malformed_is_refused(self):
        for url in (gate.paged_search_url(AX, 6), AX + '&Page_No=1', AX + '&Page_No=02', AX + '&Page_No=2x',
                    AX + '&Page_No=', AX + '&Page_No=2&x=1', AX.replace('&tabType=recruit', '') + '&Page_No=2',
                    AX + '&page=2', AX + '&Page_No=%32', AX + '&Page_No=2#'):
            self.assertEqual(decide(approval(), url), gate.GateReason.OUT_OF_SCOPE, url)

    def test_unlisted_keyword_is_refused(self):
        other = 'https://www.jobkorea.co.kr/Search/?stext=Python&tabType=recruit'
        self.assertEqual(decide(approval(), other), gate.GateReason.OUT_OF_SCOPE)
        self.assertEqual(decide(approval(), other + '&Page_No=2'), gate.GateReason.OUT_OF_SCOPE)

    def test_discovered_detail_needs_an_approved_page(self):
        page3 = gate.paged_search_url(AX, 3)
        self.assertEqual(decide(approval(), DETAIL, discovered_from=page3), gate.GateReason.ALLOWED)
        self.assertEqual(decide(approval(), DETAIL, discovered_from=gate.paged_search_url(AX, 6)),
                         gate.GateReason.OUT_OF_SCOPE)
        self.assertEqual(decide(approval(), DETAIL), gate.GateReason.OUT_OF_SCOPE)  # not discovered
        for bad in ('https://jobkorea.co.kr/Recruit/GI_Read/1', DETAIL + '?x=1', 'https://www.jobkorea.co.kr/Recruit/X/1'):
            self.assertEqual(decide(approval(), bad, discovered_from=AX), gate.GateReason.OUT_OF_SCOPE)

    def test_harvest_is_off_by_default_and_needs_its_purpose(self):
        self.assertEqual(decide(approval(max_harvest_details=0), AX), gate.GateReason.OUT_OF_SCOPE)
        self.assertEqual(decide(approval(), AX, purpose='night_keyword_collection'), gate.GateReason.OUT_OF_SCOPE)
        # a night approval (no harvest fields) is not a harvest approval
        night = approval(allowed_purposes=('night_keyword_collection',), max_search_pages=1, max_harvest_details=0,
                         max_discovered_details=5, max_requests=7)
        self.assertEqual(decide(night, AX), gate.GateReason.OUT_OF_SCOPE)
        self.assertEqual(decide(night, AX, purpose='night_keyword_collection', calls=7), gate.GateReason.ALLOWED)
        self.assertEqual(decide(night, AX + '&Page_No=2', purpose='night_keyword_collection', calls=7),
                         gate.GateReason.OUT_OF_SCOPE)

    def test_request_cap_and_invalid_fields(self):
        self.assertEqual(decide(approval(), AX, calls=501), gate.GateReason.OUT_OF_SCOPE)
        # the run must fit robots + approved pages x listed searches + approved details (1 + 5 + 300)
        self.assertEqual(decide(approval(), AX, calls=306), gate.GateReason.ALLOWED)
        self.assertEqual(decide(approval(), AX, calls=307), gate.GateReason.OUT_OF_SCOPE)
        self.assertEqual(decide(approval(max_harvest_details=5), DETAIL, calls=307, discovered_from=AX),
                         gate.GateReason.OUT_OF_SCOPE)
        self.assertEqual(decide(approval(), AX + '&Page_No=' + '9' * 5000), gate.GateReason.OUT_OF_SCOPE)
        for over in ({'max_search_pages': 0}, {'max_search_pages': 51}, {'max_search_pages': True},
                     {'max_harvest_details': 2001}, {'max_harvest_details': '5'}, {'max_harvest_details': -1}):
            self.assertEqual(decide(approval(**over), AX), gate.GateReason.INVALID_POLICY, over)
        self.assertEqual(decide(approval(review_due_utc=NOW), AX), gate.GateReason.EXPIRED)
        self.assertEqual(decide(approval(approval_status='HOLD'), AX), gate.GateReason.NOT_APPROVED)


class ResultPageTest(unittest.TestCase):
    def test_full_page_is_read_in_order_with_ids(self):
        html = ''.join(f'<a href="/Recruit/GI_Read/{5000 + i}?logpath=1">t</a>' for i in range(40))
        urls = parser.parse_jobkorea_result_page(html + '<a href="/Recruit/GI_Read/5000">dup</a>')
        self.assertEqual(len(urls), 40)
        self.assertEqual([h.posting_id(u) for u in urls[:2]], ['5000', '5001'])
        self.assertEqual(parser.parse_jobkorea_result_page(''), [])
        self.assertEqual(len(parser.parse_jobkorea_result_page(
            ''.join(f'<a href="/Recruit/GI_Read/{i}">t</a>' for i in range(300)))), 200)


class LimitsAndPreflightTest(unittest.TestCase):
    def test_limits_are_bounded(self):
        h.HarvestLimits()
        for over in ({'max_pages': 0}, {'max_pages': 51}, {'max_new_details': 2001}, {'max_requests': 0},
                     {'max_new_details': 1500, 'max_revisits': 600}, {'deadline_seconds': 10}, {'max_pages': 1.5}):
            with self.assertRaises(ValueError, msg=over):
                h.HarvestLimits(**over)

    def test_preflight_matches_limits_to_approval_without_network(self):
        limits = h.HarvestLimits(max_pages=5, max_new_details=250, max_revisits=50, max_requests=300)
        with mock.patch.object(ij, '_get', side_effect=AssertionError('network')):
            ok, problems, urls = h.preflight(approval(), limits, ['AX'], now=NOW)
            self.assertEqual((ok, problems, urls), (True, [], [AX]))
            ok, problems, _ = h.preflight(approval(), replace(limits, max_pages=6), ['AX'], now=NOW)
            self.assertIn('PAGES_EXCEED_APPROVAL', problems)
            ok, problems, _ = h.preflight(approval(), limits, ['AX', 'Python'], now=NOW)
            self.assertFalse(ok)
            self.assertIn('OUT_OF_SCOPE:Python:p1', problems)
            self.assertEqual(h.preflight(None, limits, ['AX']), (False, ['APPROVAL_FILE_MISSING_OR_INVALID'], []))
            _, problems, _ = h.preflight(approval(max_harvest_details=100), limits, ['AX'], now=NOW)
            self.assertIn('DETAILS_EXCEED_APPROVAL', problems)


class LiveSourceTest(unittest.TestCase):
    def source(self, appr, **limits):
        return h.LiveSource(appr, h.HarvestLimits(**{'max_pages': 5, 'max_new_details': 10, 'max_requests': 10, **limits}),
                            now_utc=lambda: NOW, now_mono=lambda: 0.0, deadline=100.0)

    def test_unapproved_search_sends_nothing(self):
        with mock.patch.object(ij, '_get', side_effect=AssertionError('network')), \
                mock.patch.object(h, '_get', side_effect=AssertionError('network')):
            for appr in (approval(approval_status='HOLD'), approval(max_harvest_details=0), approval(allowed_urls=())):
                src = self.source(appr)
                with self.assertRaises(ij.FetchBlocked):
                    src.search('AX', 1)
                self.assertEqual(src.requests, 0)

    def test_robots_once_spacing_budget_and_block(self):
        pages = {'https://www.jobkorea.co.kr/robots.txt': 'User-agent: *\nDisallow: /Login\n',
                 AX: '<a href="/Recruit/GI_Read/50300001">a</a><a href="/Recruit/GI_Read/50300002">b</a>',
                 AX + '&Page_No=2': '<a href="/Recruit/GI_Read/50300003">c</a>',
                 DETAIL: '<html>detail</html>'}
        calls = []

        def fake_get(url):
            calls.append(url)
            if url.endswith('50300002'):
                raise ij.FetchBlocked('HTTP_403', http_status=403)
            return pages[url]

        sleeps = []
        with mock.patch.object(ij, '_get', side_effect=fake_get), mock.patch.object(h, '_get', side_effect=fake_get), \
                mock.patch.object(ij.time, 'sleep', side_effect=sleeps.append):
            src = self.source(approval(), max_requests=4)
            self.assertEqual(src.search('AX', 1)[1], [DETAIL, DETAIL[:-1] + '2'])
            self.assertEqual(src.search('AX', 2)[1], [DETAIL[:-1] + '3'])
            self.assertEqual(src.detail(DETAIL, AX), '<html>detail</html>')
            with self.assertRaises(ij.FetchBlocked) as budget:
                src.detail(DETAIL[:-1] + '2', AX)
            self.assertEqual(budget.exception.reason, 'REQUEST_BUDGET')
            src = self.source(approval(), max_requests=10)
            with self.assertRaises(ij.FetchBlocked) as blocked:
                src.detail(DETAIL[:-1] + '2', AX)
            self.assertEqual(blocked.exception.reason, 'HTTP_403')
        self.assertEqual(calls.count('https://www.jobkorea.co.kr/robots.txt'), 2)  # once per source
        self.assertTrue(all(s >= 2 for s in sleeps))

    def test_runtime_detail_cap_follows_the_approval(self):
        robots = 'User-agent: *\n'
        with mock.patch.object(ij, '_get', side_effect=lambda url: robots if url.endswith('robots.txt') else 'x'), \
                mock.patch.object(h, '_get', side_effect=lambda url: robots), mock.patch.object(ij.time, 'sleep'):
            src = self.source(approval(max_harvest_details=2), max_requests=8)  # bound 1 + 5 pages + 2
            src.detail(DETAIL, AX)
            src.detail(DETAIL[:-1] + '2', AX)
            with self.assertRaises(ij.FetchBlocked) as capped:
                src.detail(DETAIL[:-1] + '3', AX)
        self.assertEqual((capped.exception.reason, src.details), ('DETAIL_BUDGET', 2))

    def test_expired_approval_stops_before_request(self):
        src = h.LiveSource(approval(), h.HarvestLimits(max_requests=10), now_utc=lambda: NOW + timedelta(days=2),
                           now_mono=lambda: 0.0, deadline=100.0)
        with mock.patch.object(h, '_get', side_effect=AssertionError('network')):
            with self.assertRaises(ij.FetchBlocked):
                src.robots()


class LiveCliTest(unittest.TestCase):
    def test_live_cli_needs_preflight_and_pm_activation_before_any_io(self):
        import io
        import json
        import os
        import tempfile
        from contextlib import redirect_stdout
        now = datetime.now(timezone.utc)
        record = dict(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='PM',
                      evidence_ref='private:REF-1', valid_from_utc=(now - timedelta(hours=1)).isoformat(),
                      review_due_utc=(now + timedelta(hours=1)).isoformat(), collection_method='WEB',
                      allowed_urls=[AX], allowed_purposes=[gate.HARVEST_PURPOSE], max_requests=50,
                      retention_days=30, stop_on_block=True, max_search_pages=2, max_harvest_details=10)
        with tempfile.TemporaryDirectory() as tmp:
            from crawler.tests.provider_fixture import provider_json
            # PM approval only (no provider permission file): preflight refuses, nothing is sent
            pm_only = os.path.join(tmp, 'pm-only.json')
            with open(pm_only, 'w', encoding='utf-8') as handle:
                json.dump(record, handle)
            out = io.StringIO()
            with redirect_stdout(out), mock.patch.object(ij, '_get', side_effect=AssertionError('network')):
                self.assertEqual(h.main(['live', '--policy-file', pm_only, '--keyword', 'AX', '--pages', '2', '--new',
                                         '10', '--max-requests', '13', '--check']), 2)
            refused = json.loads(out.getvalue())
            self.assertIn('PROVIDER_PERMISSION_MISSING:AX:p1', refused['problems'])
            self.assertEqual(refused['external_requests'], 0)
            record['provider_permission_file'] = provider_json(os.path.join(tmp, 'provider.json'))
            path = os.path.join(tmp, 'approval.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(record, handle)
            argv = ['live', '--policy-file', path, '--keyword', 'AX', '--pages', '2', '--new', '10', '--max-requests', '13']
            with mock.patch.object(h, '_connect', side_effect=AssertionError('db')), \
                    mock.patch.object(ij, '_get', side_effect=AssertionError('network')), \
                    mock.patch.object(h, '_get', side_effect=AssertionError('network')):
                for extra, environ, code, key in ((['--check'], {}, 0, 'ok'), ([], {}, 2, 'reason'),
                                                  (['--pages', '3'], {'CRAWLER_LIVE_SCHEDULE_APPROVED': '1'}, 2, 'problems'),
                                                  ([], {'CRAWLER_NIGHT_ENABLED': '1'}, 2, 'reason')):
                    out = io.StringIO()
                    with redirect_stdout(out):
                        self.assertEqual(h.main(argv + extra, environ=environ), code, extra)
                    result = json.loads(out.getvalue())
                    self.assertIn(key, result)
                    self.assertEqual(result.get('external_requests'), 0)
                    if key == 'reason':
                        self.assertEqual(result['reason'], 'PM_ACTIVATION_REQUIRED')
                    if key == 'problems':
                        self.assertEqual(result['problems'], ['OUT_OF_SCOPE:AX:p3', 'PAGES_EXCEED_APPROVAL'])


class RequestTemplateTest(unittest.TestCase):
    def test_repository_request_form_is_refused_until_the_pm_fills_it(self):
        import json
        import os
        import tempfile
        from pathlib import Path
        form = Path(__file__).resolve().parents[2] / 'scripts/windows/templates/t61-harvest-approval.REQUEST.json'
        loaded = ij.load_approval_file(form)
        self.assertIsNotNone(loaded)  # parses (annotation keys ignored) ...
        at = loaded.valid_from_utc + timedelta(minutes=1)
        url = loaded.allowed_urls[0]
        self.assertEqual(gate.check_collection_permission(loaded, gate.CollectionIntent(
            'jobkorea', url, 'WEB', gate.HARVEST_PURPOSE, 7, at)).reason, gate.GateReason.NOT_APPROVED)  # ... but HOLD
        record = json.loads(form.read_text(encoding='utf-8'))
        record.update(approval_status='APPROVED', enabled=True, approved_by='PM', evidence_ref='private:REF')
        with tempfile.TemporaryDirectory() as tmp:
            filled = os.path.join(tmp, 'a.json')
            Path(filled).write_text(json.dumps(record), encoding='utf-8')
            approved = ij.load_approval_file(filled)
            self.assertEqual(gate.check_collection_permission(approved, gate.CollectionIntent(
                'jobkorea', url, 'WEB', gate.HARVEST_PURPOSE, 7, at)).reason, gate.GateReason.ALLOWED)
            self.assertEqual(gate.check_collection_permission(approved, gate.CollectionIntent(
                'jobkorea', url, 'WEB', gate.HARVEST_PURPOSE, 8, at)).reason, gate.GateReason.OUT_OF_SCOPE)
            record['unexpected'] = 1
            Path(filled).write_text(json.dumps(record), encoding='utf-8')
            self.assertIsNone(ij.load_approval_file(filled))


class GcpLocalSourceGuardTest(unittest.TestCase):
    def run_execute(self, mode, environ, ids):
        def never(*_):
            raise AssertionError('must not connect')
        return g.execute(mode, environ, connect_src=never, connect_tgt=never, live_run_ids=ids)

    def test_local_source_needs_valid_live_run_ids_and_is_one_shot(self):
        local = {'GCP_SYNC_SOURCE': 'local'}
        run_id = '9a4f1f0e-6c1e-4d5b-9a55-2f6f0c7c1b11'
        self.assertEqual(self.run_execute('run', local, None)['error_code'], 'LIVE_RUN_ID_REQUIRED')
        self.assertEqual(self.run_execute('run', local, ['not-a-uuid'])['error_code'], 'LIVE_RUN_ID_INVALID')
        self.assertEqual(self.run_execute('scheduled', local, [run_id])['error_code'], 'LOCAL_SOURCE_ONE_SHOT_ONLY')
        self.assertEqual(self.run_execute('verify', {}, None)['error_code'], 'LIVE_RUN_ID_NEEDS_LOCAL_SOURCE')
        self.assertEqual(self.run_execute('run', {}, [run_id])['error_code'], 'LIVE_RUN_ID_NEEDS_LOCAL_SOURCE')
        self.assertEqual(self.run_execute('run', {'GCP_SYNC_SOURCE': 'x'}, None)['error_code'], 'SOURCE_KIND_INVALID')

    def test_local_source_refuses_staging_mode(self):
        with mock.patch.dict('os.environ', {'CRAWLER_DB_MODE': 'staging'}):
            with self.assertRaises(g.SyncError) as error:
                g.connect_local_source({'CRAWLER_LOCAL_DATABASE_URL': 'postgresql://crawler_local@127.0.0.1/x'})
        self.assertEqual(error.exception.code, 'SOURCE_NOT_LOCAL')

    def test_run_ids_are_normalized(self):
        a = '9A4F1F0E-6C1E-4D5B-9A55-2F6F0C7C1B11'
        self.assertEqual(g._parse_run_ids([a + ',' + a.lower()]), [a.lower()])


if __name__ == '__main__':
    unittest.main()
