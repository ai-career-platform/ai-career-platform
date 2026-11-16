"""Nightly orchestration (crawler/jobs/nightly.py): window, Slack reports, chunk loop. No DB, no network."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from crawler.jobs import nightly as n

KST = timezone(timedelta(hours=9))
HOOK = 'https://hooks.slack.com/services/T000/B000/secretpart'
ENV = {'SLACK_WEBHOOK_RUL': HOOK}


def kst(*args):
    return datetime(*args, tzinfo=KST)


class WindowTest(unittest.TestCase):
    def test_night_spans_midnight(self):
        cases = {
            kst(2026, 11, 17, 20, 59): (date(2026, 11, 17), False),
            kst(2026, 11, 17, 21, 0): (date(2026, 11, 17), True),
            kst(2026, 11, 17, 23, 59): (date(2026, 11, 17), True),
            kst(2026, 11, 18, 0, 0): (date(2026, 11, 17), True),
            kst(2026, 11, 18, 7, 59, 59): (date(2026, 11, 17), True),
            kst(2026, 11, 18, 8, 0): (date(2026, 11, 18), False),      # closed; next night is the 18th
            kst(2026, 11, 18, 12, 0): (date(2026, 11, 18), False),
        }
        for now, (night, inside) in cases.items():
            w = n.night_window(now)
            self.assertEqual((w.night_date, w.inside), (night, inside), now)
            self.assertEqual((w.start.hour, w.end.hour, (w.end - w.start).total_seconds()), (21, 8, 11 * 3600))

    def test_utc_input_and_seconds_left(self):
        w = n.night_window(datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc))   # 07:00 KST on the 18th
        self.assertEqual((w.night_date, w.inside), (date(2026, 11, 17), True))
        self.assertEqual(w.seconds_left(datetime(2026, 11, 17, 22, 0, tzinfo=timezone.utc)), 3600)


class MessageTest(unittest.TestCase):
    w = n.night_window(kst(2026, 11, 17, 23, 0))

    def test_unmeasured_values_are_not_zero(self):
        text = n.format_report('start', window=self.w)['text']
        self.assertIn('NOT_RUN', text)
        self.assertNotIn(' 0건', text)
        self.assertIn('달성률: UNVERIFIED', text)

    def test_measured_report(self):
        totals = dict(http_requests=520, links_seen=1250, new_found=1100, known_found=150, cross_duplicates=40,
                      inserted=1030, updated=3, unchanged=0, failed=0, verified_new_inserts=1030,
                      runs=[{'run_id': 'abcdef12-0000', 'status': 'SUCCEEDED', 'stop_reason': None}])
        text = n.format_report('end', window=self.w, totals=totals, status='PASS')['text']
        for part in ('야간 크롤링 결과', '1,030건', '달성률: 103.0%', 'abcdef12', 'GCP 이관: NOT_RUN',
                     '웹사이트 표시: NOT_RUN', '최종 상태: PASS', '2026-11-17 21:00 ~ 2026-11-18 08:00 KST'):
            self.assertIn(part, text)

    def test_test_message_says_nothing_ran(self):
        text = n.format_report('test', window=self.w)['text']
        self.assertIn('유형: TEST', text)
        self.assertIn('실제 크롤링 실행: 없음', text)


class GcpMessageTest(unittest.TestCase):
    w = n.night_window(kst(2026, 11, 17, 23, 0))

    def test_blocked_step_shows_reason_and_no_counts(self):
        text = n.format_gcp(self.w, {'status': 'BLOCKED', 'reason': 'GCP_CA_MISSING'})['text']
        self.assertIn('상태: BLOCKED', text)
        self.assertIn('사유: GCP_CA_MISSING', text)
        self.assertNotIn('신규 INSERT', text)

    def test_sync_result_counts(self):
        res = {'status': 'SUCCEEDED', 'live_run_ids': ['8e54090d-34ce'], 'fetched': 5, 'inserted': 2, 'updated': 0,
               'duplicate': 3, 'skipped': 0, 'failed': 0, 'publish': False}
        text = n.format_gcp(self.w, res)['text']
        for part in ('GCP 신규 INSERT: 2건', '중복: 3건', '8e54090d', 'draft (웹사이트 비노출)'):
            self.assertIn(part, text)

    def test_notify_cli_sends_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp, 'r.json')
            f.write_text(json.dumps({'status': 'NOT_RUN', 'reason': 'NO_LIVE_RUNS'}), encoding='utf-8')
            with mock.patch('crawler.notifications.slack.send', return_value=(True, 200, 'OK')) as send, \
                    mock.patch('builtins.print'):
                for _ in range(2):
                    n.main(['notify', '--kind', 'gcp', '--night', '2026-11-17', '--result-file', str(f),
                            '--state-dir', tmp], environ=ENV)
            self.assertEqual(send.call_count, 1)


class SiteCheckTest(unittest.TestCase):
    EXP = [{'external_id': '501', 'title': 'A 채용', 'company_name': '가사', 'source_url': 'https://www.jobkorea.co.kr/Recruit/GI_Read/501'},
           {'external_id': '502', 'title': 'B 채용', 'company_name': '나사', 'source_url': 'https://www.jobkorea.co.kr/Recruit/GI_Read/502'}]

    def api(self, pages, details):
        calls = []

        def get_json(url):
            calls.append(url)
            if '/job-postings/' in url:
                return 200, details[url.rsplit('/', 1)[1]]
            return 200, pages['cursor=' in url and url.split('cursor=')[1] or None]
        return get_json, calls

    def test_trace_needs_list_match_and_own_source_url_across_pages(self):
        pages = {None: {'items': [{'job_posting_id': 'u1', 'title': 'A 채용', 'company': {'name': '가사'}},
                                  {'job_posting_id': 'u9', 'title': '[Seed] x', 'company': {'name': 's'}}], 'next_cursor': 'c2'},
                 'c2': {'items': [{'job_posting_id': 'u2', 'title': 'B 채용', 'company': {'name': '나사'}}], 'next_cursor': None}}
        details = {'u1': {'source_url': self.EXP[0]['source_url']},
                   'u2': {'source_url': 'https://www.jobkorea.co.kr/Recruit/GI_Read/999'}}   # same title, other posting
        get_json, calls = self.api(pages, details)
        r = n.site_check(self.EXP, get_json=get_json)
        self.assertEqual((r['status'], r['found'], r['expected'], r['api_items_scanned']), ('PARTIAL', 1, 2, 3))
        self.assertEqual(r['matches'], {'501': 'u1'})
        self.assertNotIn('u9', ''.join(calls))                  # seed rows are never opened

    def test_nothing_transferred_is_not_run(self):
        get_json, _ = self.api({None: {'items': [], 'next_cursor': None}}, {})
        self.assertEqual(n.site_check([], get_json=get_json)['status'], 'NOT_RUN')

    def test_site_message(self):
        w = n.night_window(kst(2026, 11, 17, 23, 0))
        text = n.format_site(w, {'status': 'NOT_RUN', 'reason': 'DRAFT_NOT_PUBLIC'})['text']
        self.assertIn('사유: DRAFT_NOT_PUBLIC', text)
        text = n.format_site(w, {'status': 'PASS', 'expected': 2, 'found': 2, 'api_items_scanned': 92})['text']
        self.assertIn('웹사이트 확인: 2건', text)


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = n.SlackLedger(self.tmp.name, date(2026, 11, 17))

    def tearDown(self):
        self.tmp.cleanup()

    def test_not_configured_sends_nothing(self):
        sender = mock.Mock()
        self.assertEqual(self.ledger.notify('start', {'text': 'x'}, {}, sender=sender)['slack'], 'NOT_CONFIGURED')
        sender.assert_not_called()

    def test_one_message_per_key_and_no_url_anywhere(self):
        sender = mock.Mock(return_value=(True, 200, 'OK'))
        first = self.ledger.notify('end', {'text': 'x'}, ENV, sender=sender)
        again = n.SlackLedger(self.tmp.name, date(2026, 11, 17)).notify('end', {'text': 'x'}, ENV, sender=sender)
        self.assertEqual((first['slack'], first['http_status'], again['slack']), ('SENT', 200, 'DUPLICATE_SKIPPED'))
        self.assertEqual(sender.call_count, 1)
        stored = Path(self.tmp.name, 'nightly-slack-2026-11-17.json').read_text(encoding='utf-8')
        self.assertNotIn('secretpart', stored + json.dumps(first) + json.dumps(again))

    @mock.patch('crawler.jobs.nightly.clock.sleep')
    def test_one_retry_on_transient_failure_only(self, _sleep):
        sender = mock.Mock(side_effect=[(False, 503, 'HTTP_ERROR'), (True, 200, 'OK')])
        self.assertEqual(self.ledger.notify('a', {'text': 'x'}, ENV, sender=sender)['slack'], 'SENT')
        sender = mock.Mock(return_value=(False, 400, 'HTTP_ERROR'))
        self.assertEqual(self.ledger.notify('b', {'text': 'x'}, ENV, sender=sender)['slack'], 'FAILED')
        self.assertEqual(sender.call_count, 1)

    def test_invalid_webhook_is_refused(self):
        sender = mock.Mock()
        res = self.ledger.notify('a', {'text': 'x'}, {'SLACK_WEBHOOK_URL': 'https://example.com/x'}, sender=sender)
        self.assertEqual(res['slack'], 'INVALID_WEBHOOK')
        sender.assert_not_called()


class FakeDB:
    """Stands in for the two read-only counters; the harvest fake moves them."""
    def __init__(self):
        self.inserted, self.requests = 0, 0

    def totals(self, *_a, **_k):
        return dict(http_requests=self.requests, links_seen=0, new_found=0, known_found=0, cross_duplicates=0,
                    inserted=self.inserted, updated=0, unchanged=0, failed=0, verified_new_inserts=self.inserted,
                    runs=[])


class RunNightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = FakeDB()
        patches = [mock.patch.object(n, 'new_inserts', lambda *a, **k: self.db.inserted),
                   mock.patch.object(n, 'night_totals', self.db.totals)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.sender = mock.Mock(return_value=(True, 200, 'OK'))
        patcher = mock.patch('crawler.notifications.slack.send', self.sender)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = kst(2026, 11, 17, 23, 0)

    def tearDown(self):
        self.tmp.cleanup()

    def run_night(self, results, config=n.NightConfig(target=1000, chunk_new=400), now=None):
        calls = []

        def harvest(connection, source, *, keywords, limits):
            calls.append(limits)
            r = results.pop(0) if results else {'status': 'SUCCEEDED', 'new': 0}
            self.db.inserted += r.get('inserted', 0)
            self.db.requests += r.get('http_requests', 0)
            return r
        ledger = n.SlackLedger(self.tmp.name, date(2026, 11, 17))
        out = n.run_night(None, source_factory=lambda limits: object(), config=config, environ=ENV, ledger=ledger,
                          keywords=['AX'], now_utc=lambda: now or self.now, harvest=harvest)
        return out, calls

    def keys(self):
        return [c.args[1]['text'].splitlines()[0] for c in self.sender.call_args_list]

    def test_outside_window_does_nothing(self):
        out, calls = self.run_night([], now=kst(2026, 11, 17, 12, 0))
        self.assertEqual((out['status'], out['reason'], calls), ('SKIPPED', 'OUTSIDE_NIGHT_WINDOW', []))
        self.sender.assert_not_called()

    def test_chunks_until_target_then_target_and_end_reports_once(self):
        ok = {'status': 'SUCCEEDED', 'new': 400, 'http_requests': 300}
        out, calls = self.run_night([dict(ok, inserted=400), dict(ok, inserted=400), dict(ok, inserted=400)])
        self.assertEqual((out['status'], out['reason'], len(calls)), ('SUCCEEDED', 'TARGET_REACHED', 3))
        self.assertEqual([c.max_new_details for c in calls], [400, 400, 200])     # never more than still needed
        self.assertTrue(all(c.known_page_stop == c.max_pages for c in calls))     # later chunks reach deeper pages
        self.assertTrue(all(c.deadline_seconds <= 9 * 3600 for c in calls))        # 23:00 -> 08:00
        self.assertEqual(self.keys(), ['[AI Career Platform] 야간 크롤링 시작', '[AI Career Platform] 신규 1,000건 목표 달성',
                                       '[AI Career Platform] 야간 크롤링 결과'])
        self.run_night([])                                                        # a re-run of the same night
        self.assertEqual(self.sender.call_count, 3)                               # no duplicate messages

    def test_blocking_signal_stops_with_failure_report(self):
        out, calls = self.run_night([{'status': 'STOPPED', 'stop_reason': 'HTTP_429', 'new': 3, 'inserted': 3,
                                      'http_requests': 9}])
        self.assertEqual((out['status'], out['reason'], len(calls)), ('FAILED', 'HTTP_429', 1))
        self.assertIn('[AI Career Platform] 야간 크롤링 비정상 종료', self.keys())

    def test_deadline_inside_chunk_ends_the_night_normally(self):
        out, _ = self.run_night([{'status': 'STOPPED', 'stop_reason': 'TIMEOUT', 'new': 5, 'inserted': 5}])
        self.assertEqual((out['status'], out['reason']), ('SUCCEEDED', 'WINDOW_ENDED'))

    def test_chunk_budget_continues_and_night_budget_stops(self):
        cfg = n.NightConfig(target=1000, chunk_new=100, max_requests=250, night_max_requests=500)
        res = [{'status': 'STOPPED', 'stop_reason': 'REQUEST_BUDGET', 'new': 100, 'inserted': 100,
                'http_requests': 250}] * 3
        out, calls = self.run_night(list(res), config=cfg)
        self.assertEqual((out['reason'], len(calls)), ('NIGHT_REQUEST_BUDGET', 2))
        self.assertEqual([c.max_requests for c in calls], [250, 250])

    def test_no_supply_and_last_minute(self):
        out, _ = self.run_night([{'status': 'SUCCEEDED', 'new': 0}])
        self.assertEqual(out['reason'], 'NO_NEW_SUPPLY')
        out, calls = self.run_night([], now=kst(2026, 11, 18, 7, 59, 30))
        self.assertEqual((out['reason'], calls), ('WINDOW_ENDED', []))

    def test_progress_comes_from_its_own_thread_once_per_hour_slot(self):
        import contextlib
        import time

        def slow_harvest(connection, source, *, keywords, limits):
            time.sleep(0.3)
            self.db.inserted += 10
            return {'status': 'SUCCEEDED', 'new': 0, 'inserted': 10}
        ledger = n.SlackLedger(self.tmp.name, date(2026, 11, 17))
        out = n.run_night(None, source_factory=lambda limits: object(),
                          config=n.NightConfig(progress_minutes=0.001), environ=ENV, ledger=ledger, keywords=['AX'],
                          now_utc=lambda: self.now, harvest=slow_harvest,
                          progress_connect=lambda: contextlib.nullcontext(None))
        progress = [s for s in out['slack'] if s['key'].startswith('progress-')]
        self.assertEqual(progress[0]['slack'], 'SENT')                    # several ticks, one message per hour slot
        self.assertTrue(all(s['slack'] == 'DUPLICATE_SKIPPED' for s in progress[1:]))
        self.assertIn('[AI Career Platform] 야간 크롤링 진행', self.keys())

    def test_crash_is_reported(self):
        def boom(*a, **k):
            raise RuntimeError('db gone')
        ledger = n.SlackLedger(self.tmp.name, date(2026, 11, 17))
        out = n.run_night(None, source_factory=lambda limits: object(), config=n.NightConfig(), environ=ENV,
                          ledger=ledger, keywords=['AX'], now_utc=lambda: self.now, harvest=boom)
        self.assertEqual((out['status'], out['reason']), ('FAILED', 'WORKER_RUNTIMEERROR'))
        self.assertIn('[AI Career Platform] 야간 크롤링 비정상 종료', self.keys())


class CliTest(unittest.TestCase):
    def test_live_without_approval_is_blocked_before_any_request(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(n, '_connect') as connect, \
                mock.patch('crawler.jobs.harvest.run_harvest') as harvest, \
                mock.patch('crawler.notifications.slack.send') as send, mock.patch('builtins.print'):
            connect.return_value.__enter__.return_value = object()
            code = n.main(['run', '--mode', 'live', '--state-dir', tmp, '--now', '2026-11-17T23:00:00+09:00'],
                          environ={'CRAWLER_LIVE_SCHEDULE_APPROVED': '1'})
        self.assertEqual(code, 2)
        harvest.assert_not_called()
        send.assert_not_called()       # webhook not configured in this environ

    def test_window_command(self):
        with mock.patch('builtins.print') as out:
            self.assertEqual(n.main(['window', '--now', '2026-11-18T07:00:00+09:00']), 0)
        self.assertEqual(json.loads(out.call_args.args[0])['night_date'], '2026-11-17')


if __name__ == '__main__':
    unittest.main()
