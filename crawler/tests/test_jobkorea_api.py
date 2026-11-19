"""JobKorea official XML API: parsing, field mapping, T61 API gate, live-source guards. No network, no DB."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from crawler.adapters import jobkorea_api_xml as x
from crawler.jobs import jobkorea_api as api
from crawler.jobs.import_jobkorea_html import FetchBlocked, live_permission_reason
from crawler.normalizer import InvalidPosting
from crawler.policy import source_approval_gate as gate
from crawler.tests.jobkorea_api_fixture import item, page
from crawler.tests.provider_fixture import provider

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
ENDPOINT = 'https://api.jobkorea.co.kr/Service/JK_GI_XML_List.asp'
PRIVATE_URL = ENDPOINT + '?api=SECRET-TOKEN&Oem_Code=C900'


def approval(**over):
    base = dict(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='PM',
                evidence_ref='private:API-APPROVAL', valid_from_utc=NOW - timedelta(days=1),
                review_due_utc=NOW + timedelta(days=1), collection_method='API', allowed_urls=(ENDPOINT,),
                allowed_purposes=(gate.API_PURPOSE,), max_requests=30, retention_days=30, stop_on_block=True,
                max_harvest_details=100,
                provider_permission=provider(permission_type='API_CONTRACT', allowed_methods=('API',),
                                             allowed_purposes=(gate.API_PURPOSE,),
                                             allowed_url_prefixes=(ENDPOINT,), max_requests_per_day=1000))
    base.update(over)
    return gate.SourceApproval(**base)


def api_intent(url=ENDPOINT, *, method='API', purpose=gate.API_PURPOSE, calls=30):
    return gate.CollectionIntent('jobkorea', url, method, purpose, calls, NOW)


CONFIG = api.ApiConfig(PRIVATE_URL, ('203.0.113.7',))


class ParseTest(unittest.TestCase):
    def test_euc_kr_page_parses_counts_and_items(self):
        parsed = x.parse_api_response(page([item(50000001), item(50000002)], total=320))
        self.assertEqual((parsed.total_results, parsed.page_count, len(parsed.items)), (320, 2, 2))
        self.assertEqual(parsed.encoding, 'euc-kr')
        self.assertEqual(parsed.items[0]['GI_Subject'], '데이터 엔지니어 채용 50000001')
        self.assertEqual(parsed.items[0]['C_Name'], '합성회사' + str(50000001 % 97))

    def test_extended_hangul_outside_ks_x_1001_decodes(self):
        data = page([item(50000003, title='똠양꿍 데이터팀')])
        self.assertEqual(x.parse_api_response(data).items[0]['GI_Subject'], '똠양꿍 데이터팀')

    def test_empty_result_page(self):
        parsed = x.parse_api_response(page([], total=0))
        self.assertEqual((parsed.total_results, parsed.page_count, parsed.items), (0, 0, ()))

    def test_starter_xml_has_no_total(self):
        data = page([item(50000004)], with_total=False)
        with self.assertRaises(x.ApiResponseError) as ctx:
            x.parse_api_response(data)
        self.assertEqual(ctx.exception.code, 'MISSING_TOTALSUMCNT')
        self.assertIsNone(x.parse_api_response(data, require_total=False).total_results)

    def test_invalid_responses_are_refused_with_a_code(self):
        cases = {
            b'': 'EMPTY_RESPONSE',
            b'<?xml version="1.0" encoding="euc-kr"?><DataList><TotalCnt>1</TotalCnt><Items>': 'INVALID_XML',
            '<html><body>인증 오류</body></html>'.encode('cp949'): 'UNEXPECTED_ROOT',
            b'<?xml version="1.0" encoding="shift_jis"?><DataList/>': 'UNSUPPORTED_ENCODING',
            b'<?xml version="1.0" encoding="euc-kr"?><DataList><TotalSumCnt>1</TotalSumCnt></DataList>':
                'MISSING_TOTALCNT',
            b'<?xml version="1.0" encoding="euc-kr"?><DataList><TotalSumCnt>x</TotalSumCnt>'
            b'<TotalCnt>0</TotalCnt></DataList>': 'INVALID_TOTALSUMCNT',
            b'<?xml version="1.0" encoding="euc-kr"?><DataList><TotalSumCnt>900</TotalSumCnt>'
            b'<TotalCnt>0</TotalCnt></DataList>': 'COUNT_OUT_OF_RANGE',
            b'<?xml version="1.0" encoding="euc-kr"?><DataList><TotalSumCnt>0</TotalSumCnt>'
            b'<TotalCnt>\xff\xff</TotalCnt></DataList>': 'INVALID_ENCODING',
            b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaa">]><DataList>&a;</DataList>': 'DTD_NOT_ALLOWED',
        }
        for data, code in cases.items():
            with self.subTest(code=code), self.assertRaises(x.ApiResponseError) as ctx:
                x.parse_api_response(data)
            self.assertEqual(ctx.exception.code, code)


class MappingTest(unittest.TestCase):
    def posting(self, **kw):
        parsed = x.parse_api_response(page([item(50000010, **kw)]))
        return x.to_posting(parsed.items[0], source_code='jobkorea_api')

    def test_fields_map_onto_the_existing_posting_model(self):
        p = self.posting()
        self.assertEqual(p.source_code, 'jobkorea_api')
        self.assertEqual(p.external_posting_id, '50000010')
        self.assertEqual(p.title, '데이터 엔지니어 채용 50000010')
        self.assertEqual(p.location_text, '서울특별시, 경기도')
        self.assertEqual(p.employment_type, 'full_time')
        self.assertEqual((p.published_on, p.expires_on, p.status), ('2026-11-10', '2026-12-31', 'published'))

    def test_api_identifier_never_reaches_the_stored_url(self):
        p = self.posting()
        self.assertEqual(p.source_url, 'https://www.jobkorea.co.kr/Recruit/GI_Read/50000010')
        self.assertNotIn('SECRET', json.dumps(p.to_dict()))

    def test_unknown_codes_stay_empty_rather_than_guessed(self):
        p = self.posting(area='0', job_type='5,1', end_date='상시채용')
        self.assertEqual((p.location_text, p.employment_type, p.expires_on), (None, None, None))

    def test_detail_url_falls_back_to_gi_no_for_foreign_links(self):
        self.assertEqual(self.posting(jk_url='https://evil.example/Recruit/GI_Read/1').source_url,
                         'https://www.jobkorea.co.kr/Recruit/GI_Read/50000010')

    def test_missing_required_fields_are_invalid(self):
        with self.assertRaises(InvalidPosting):
            self.posting(company='')
        with self.assertRaises(InvalidPosting):
            x.to_posting({'GI_No': 'abc', 'GI_Subject': 't', 'C_Name': 'c'}, source_code='jobkorea_api')


class ApiGateTest(unittest.TestCase):
    def test_api_approval_admits_the_listed_endpoint_only(self):
        self.assertEqual(live_permission_reason(approval(), api_intent()), 'ALLOWED')
        other = 'https://api.jobkorea.co.kr/Service/JK_Starter_XML_List.asp'
        self.assertEqual(live_permission_reason(approval(), api_intent(other)), 'OUT_OF_SCOPE')

    def test_api_and_web_permissions_are_separate(self):
        web_page = 'https://www.jobkorea.co.kr/Recruit/GI_Read/1'
        self.assertEqual(live_permission_reason(approval(), api_intent(web_page, method='WEB')),
                         'METHOD_NOT_ALLOWED')
        web_approval = approval(collection_method='WEB', allowed_urls=(web_page,), allowed_purposes=('manual',))
        self.assertEqual(live_permission_reason(web_approval, api_intent()), 'METHOD_NOT_ALLOWED')
        web_provider = approval(provider_permission=provider(allowed_methods=('WEB',),
                                                             allowed_url_prefixes=(ENDPOINT,)))
        self.assertEqual(live_permission_reason(web_provider, api_intent()), 'PROVIDER_OUT_OF_SCOPE')

    def test_endpoint_form_is_strict(self):
        for url in (PRIVATE_URL, 'https://jobkorea.co.kr.evil.example/JK_GI_XML_List.asp',
                    'https://api.jobkorea.co.kr/other.asp', 'https://user@api.jobkorea.co.kr/JK_GI_XML_List.asp',
                    'https://api.jobkorea.co.kr:8443/JK_GI_XML_List.asp'):
            with self.subTest(url=url):
                self.assertFalse(gate.public_api_endpoint(url))
        self.assertTrue(gate.public_api_endpoint(ENDPOINT))

    def test_purpose_budget_usage_and_provider_are_required(self):
        self.assertEqual(live_permission_reason(approval(), api_intent(purpose='harvest_collection')), 'OUT_OF_SCOPE')
        self.assertEqual(live_permission_reason(approval(), api_intent(calls=31)), 'OUT_OF_SCOPE')
        self.assertEqual(live_permission_reason(approval(stop_on_block=False), api_intent()), 'MISSING_USAGE_POLICY')
        self.assertEqual(live_permission_reason(approval(max_harvest_details=0), api_intent()), 'OUT_OF_SCOPE')
        self.assertEqual(live_permission_reason(approval(provider_permission=None), api_intent()),
                         'PROVIDER_PERMISSION_MISSING')
        self.assertEqual(live_permission_reason(approval(max_harvest_details=1001), api_intent()), 'ITEM_LIMIT')
        self.assertEqual(live_permission_reason(approval(approval_status='HOLD'), api_intent()), 'NOT_APPROVED')


class ConfigAndRequestTest(unittest.TestCase):
    def test_request_url_encodes_keyword_in_euc_kr(self):
        url = CONFIG.request_url(keyword='데이터 분석', page=2, size=100, order='1')
        expected = ''.join('%%%02X' % b for b in '데이터 분석'.encode('cp949'))   # EUC-KR bytes, space as %20
        self.assertEqual(url, PRIVATE_URL + '&Size=100&Page=2&Ob=1&Keyword=' + expected)
        self.assertEqual(CONFIG.public_url, ENDPOINT)

    def test_load_config_keeps_secrets_private_and_refuses_bad_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp, 'api.json')
            good.write_text(json.dumps({'endpoints': {'all': PRIVATE_URL}, 'registered_ips': ['1.2.3.4']}))
            config = api.load_api_config(good)
            self.assertEqual((config.public_url, config.registered_ips), (ENDPOINT, ('1.2.3.4',)))
            for data in ({'endpoints': {'all': 'https://evil.example/JK_GI_XML_List.asp?a=1'},
                          'registered_ips': ['1.2.3.4']},
                         {'endpoints': {'all': PRIVATE_URL}, 'registered_ips': []}, {}):
                bad = Path(tmp, 'bad.json')
                bad.write_text(json.dumps(data))
                self.assertIsNone(api.load_api_config(bad))
            self.assertIsNone(api.load_api_config(Path(tmp, 'missing.json')))

    def test_limits_are_bounded(self):
        for over in ({'target_new': 0}, {'target_new': 1001}, {'page_size': 101}, {'max_requests': 0},
                     {'deadline_seconds': 10}, {'order': '9'}):
            with self.subTest(over=over), self.assertRaises(ValueError):
                api.ApiLimits(**over)


class LiveSourceTest(unittest.TestCase):
    def source(self, *, appr=None, ip='203.0.113.7', responses=None, limits=None):
        calls, sleeps, clock = [], [], [100.0]

        def get(url):
            calls.append(url)
            if responses:
                result = responses.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result
            return page([])

        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds

        source = api.LiveApiSource(appr or approval(), CONFIG, limits or api.ApiLimits(max_requests=30),
                                   get=get, sleep=sleep, now_mono=lambda: clock[0], now_utc=lambda: NOW,
                                   ip_lookup=lambda: ip)
        return source, calls, sleeps

    def test_unregistered_ip_sends_no_api_request(self):
        source, calls, _ = self.source(ip='1.1.1.1')
        with self.assertRaises(FetchBlocked) as ctx:
            source.fetch('AX', 1, 5, '1')
        self.assertEqual((ctx.exception.reason, calls), ('SOURCE_IP_NOT_REGISTERED', []))

    def test_missing_provider_permission_sends_nothing(self):
        source, calls, _ = self.source(appr=approval(provider_permission=None))
        with self.assertRaises(FetchBlocked) as ctx:
            source.fetch('AX', 1, 5, '1')
        self.assertEqual((ctx.exception.reason, calls), ('PROVIDER_PERMISSION_MISSING', []))

    def test_requests_are_spaced_two_seconds_and_budgeted(self):
        source, calls, sleeps = self.source(limits=api.ApiLimits(max_requests=2))
        source.fetch('AX', 1, 100, '1')
        source.fetch('AX', 2, 100, '1')
        self.assertEqual(sleeps, [2.0])
        with self.assertRaises(FetchBlocked) as ctx:
            source.fetch('AX', 3, 100, '1')
        self.assertEqual((ctx.exception.reason, len(calls)), ('REQUEST_BUDGET', 2))

    def test_expired_approval_stops_before_the_request(self):
        source, calls, _ = self.source(appr=approval(review_due_utc=NOW))
        with self.assertRaises(FetchBlocked):
            source.fetch('AX', 1, 5, '1')
        self.assertEqual(calls, [])

    def test_probe_reads_one_small_page(self):
        source, calls, _ = self.source(responses=[page([item(50000020)], total=42)])
        result = api.probe(source, 'AX')
        self.assertEqual((result['total_results'], result['items'], result['encoding']), (42, 1, 'euc-kr'))
        self.assertEqual(len(calls), 1)
        self.assertIn('Size=5', calls[0])

    def test_http_errors_never_expose_the_url(self):
        from urllib.error import HTTPError
        from unittest import mock
        error = HTTPError(PRIVATE_URL, 403, 'Forbidden', {}, None)
        with mock.patch.object(api, 'build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(FetchBlocked) as ctx:
                api._http_get(PRIVATE_URL)
        self.assertEqual((ctx.exception.reason, ctx.exception.http_status), ('HTTP_403', 403))
        self.assertNotIn('SECRET', repr(ctx.exception) + str(ctx.exception.__cause__) + str(ctx.exception.__context__))

    def test_redirect_target_is_reported_without_its_query(self):
        from urllib.error import HTTPError
        from unittest import mock
        error = HTTPError(PRIVATE_URL, 302, 'Found', {'Location': '/Error/IpDenied.asp?api=SECRET-TOKEN'}, None)
        with mock.patch.object(api, 'build_opener') as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaises(FetchBlocked) as ctx:
                api._http_get(PRIVATE_URL)
        self.assertEqual(ctx.exception.redirect_to, 'https://api.jobkorea.co.kr/Error/IpDenied.asp')


def probe_approval(**over):
    """PM probe approval with a provider record that does NOT allow storage (storage_allowed=False)."""
    base = dict(allowed_purposes=(gate.API_PROBE_PURPOSE, gate.API_PURPOSE), max_requests=1, max_harvest_details=5,
                provider_permission=provider(permission_type='API_CONTRACT', allowed_methods=('API',),
                                             allowed_purposes=(gate.API_PROBE_PURPOSE, gate.API_PURPOSE),
                                             allowed_url_prefixes=(ENDPOINT,), max_requests_per_day=1,
                                             storage_allowed=False))
    base.update(over)
    return approval(**base)


class ReadOnlyProbeTest(unittest.TestCase):
    """PM decision 2026-11-19: a read-only probe (1 request, <= 5 postings, no storage) without storage permission."""

    def probe_source(self, appr=None, *, ip='203.0.113.7', responses=None, limits=None):
        calls = []

        def get(url):
            calls.append(url)
            return (responses or [page([item(50000030)], total=7)]).pop(0)

        limits = limits or api.ApiLimits(**api.PROBE_LIMITS)
        return api.LiveApiSource(appr or probe_approval(), CONFIG, limits, get=get, sleep=lambda s: None,
                                 now_mono=lambda: 0.0, now_utc=lambda: NOW, ip_lookup=lambda: ip,
                                 read_only=True), calls

    def test_probe_is_allowed_without_storage_permission(self):
        self.assertEqual(live_permission_reason(probe_approval(), api_intent(purpose=gate.API_PROBE_PURPOSE, calls=1)),
                         'ALLOWED')
        source, calls = self.probe_source()
        result = api.probe(source, 'AX')
        self.assertEqual((result['items'], result['total_results'], len(calls)), (1, 7, 1))
        self.assertIn('Size=5', calls[0])

    def test_collection_still_needs_storage_permission(self):
        appr = probe_approval(max_requests=30, max_harvest_details=100)
        self.assertEqual(live_permission_reason(appr, api_intent(calls=30)), 'PROVIDER_STORAGE_NOT_ALLOWED')
        self.assertEqual(live_permission_reason(appr, api_intent(purpose=gate.API_PROBE_PURPOSE, calls=30)),
                         'OUT_OF_SCOPE')
        # a probe-sized approval cannot be used for collection either
        source = api.LiveApiSource(probe_approval(), CONFIG, api.ApiLimits(**api.PROBE_LIMITS),
                                   get=lambda url: self.fail('no request expected'), sleep=lambda s: None,
                                   now_utc=lambda: NOW, ip_lookup=lambda: '203.0.113.7')
        with self.assertRaises(FetchBlocked) as ctx:
            source.fetch('AX', 1, 5, '1')
        self.assertEqual(ctx.exception.reason, 'PROVIDER_STORAGE_NOT_ALLOWED')

    def test_probe_without_api_permission_is_refused(self):
        for appr in (probe_approval(provider_permission=None),
                     probe_approval(allowed_purposes=(gate.API_PURPOSE,)),
                     probe_approval(approval_status='HOLD')):
            source, calls = self.probe_source(appr)
            with self.subTest(appr=appr.approval_status), self.assertRaises(FetchBlocked):
                source.fetch('AX', 1, 5, '1')
            self.assertEqual(calls, [])

    def test_probe_from_an_unregistered_ip_is_refused(self):
        source, calls = self.probe_source(ip='198.51.100.1')
        with self.assertRaises(FetchBlocked) as ctx:
            source.fetch('AX', 1, 5, '1')
        self.assertEqual((ctx.exception.reason, calls), ('SOURCE_IP_NOT_REGISTERED', []))

    def test_probe_is_limited_to_one_request_of_five_postings(self):
        source, calls = self.probe_source(responses=[page([]), page([])])
        source.fetch('AX', 1, 5, '1')
        with self.assertRaises(FetchBlocked) as ctx:
            source.fetch('AX', 2, 5, '1')
        self.assertEqual((ctx.exception.reason, len(calls)), ('PROBE_LIMIT', 1))
        bigger, calls = self.probe_source()
        with self.assertRaises(FetchBlocked):
            bigger.fetch('AX', 1, 6, '1')
        wider, calls2 = self.probe_source(limits=api.ApiLimits(max_requests=2, page_size=5))
        with self.assertRaises(FetchBlocked):
            wider.fetch('AX', 1, 5, '1')
        self.assertEqual(calls + calls2, [])
        self.assertEqual(live_permission_reason(probe_approval(max_harvest_details=6),
                                                api_intent(purpose=gate.API_PROBE_PURPOSE, calls=1)), 'OUT_OF_SCOPE')
        with self.assertRaises(ValueError):
            api.probe(self.probe_source()[0], 'AX', size=6)

    def test_probe_source_cannot_write_to_the_database(self):
        class NoDb:
            def __getattr__(self, name):
                raise AssertionError('database touched')

        source, calls = self.probe_source()
        result = api.run_api_collection(NoDb(), source, keywords=['AX'], limits=api.ApiLimits(**api.PROBE_LIMITS))
        self.assertEqual((result['status'], result['reason'], calls), ('BLOCKED', 'READ_ONLY_PROBE', []))


class CliTest(unittest.TestCase):
    def test_live_without_files_is_refused_without_any_request(self):
        import io
        from contextlib import redirect_stdout
        from unittest import mock
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(out), \
                mock.patch.object(api, '_http_get', side_effect=AssertionError('no request expected')):
            code = api.main(['live', '--policy-file', str(Path(tmp, 'none.json')),
                             '--api-config', str(Path(tmp, 'none.json'))], environ={})
        report = json.loads(out.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report['problems'], ['APPROVAL_FILE_MISSING_OR_INVALID', 'API_CONFIG_MISSING_OR_INVALID'])
        self.assertEqual(report['jobkorea_requests'], 0)


if __name__ == '__main__':
    unittest.main()
