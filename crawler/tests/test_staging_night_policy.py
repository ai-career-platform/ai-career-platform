"""Operation transition regression. Synthetic clocks/HTTP only; never grants a live approval."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from crawler.jobs import night_crawl as night
from crawler.jobs import import_jobkorea_html as http
from crawler.jobs.scheduler import eligible
from crawler.notifications.slack import format_night_summary
from crawler.tests.test_live_http import allow, URL

KST = ZoneInfo('Asia/Seoul')


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=KST)


class ManualFixturePolicyTests(unittest.TestCase):
    def test_disabled_fixture_can_only_be_claimed_explicitly(self):
        schedule = {'enabled': False, 'mode': 'fixture'}
        self.assertEqual(eligible(schedule, at(14, 3)), (False, 'DISABLED'))
        self.assertEqual(eligible(schedule, at(14, 3), manual_fixture=True), (True, 'FIXTURE'))

    def test_manual_flag_cannot_enable_a_live_schedule(self):
        self.assertEqual(eligible({'enabled': False, 'mode': 'live'}, at(14, 3), manual_fixture=True),
                         (False, 'MANUAL_FIXTURE_ONLY'))


class NightLimitsTests(unittest.TestCase):
    def test_defaults_are_existing_bounds_not_five_minute_http_polling(self):
        limits = night.NightLimits.from_environ({})
        self.assertEqual((limits.interval_minutes, limits.max_requests_per_night), (60, 126))
        self.assertEqual(night.REQUESTS_PER_JOB, 7)

    def test_invalid_or_expanded_limits_are_rejected_before_db_access(self):
        for env in ({'CRAWLER_NIGHT_INTERVAL_MINUTES': '5'},
                    {'CRAWLER_NIGHT_MAX_REQUESTS': '127'},
                    {'CRAWLER_NIGHT_MAX_REQUESTS': '0'},
                    {'CRAWLER_NIGHT_INTERVAL_MINUTES': 'not-an-integer'}):
            with self.subTest(env=env):
                result = night.run_night_step(object(), environ={'CRAWLER_NIGHT_ENABLED': '1', **env}, now=at(13, 21))
                self.assertEqual(result, {'night': 'BLOCKED', 'reason': 'INVALID_NIGHT_LIMITS', 'external_requests': 0})

    def test_uncommitted_night_reservation_cannot_start_http(self):
        result = night.run_night_step(SimpleNamespace(autocommit=False),
                                      environ={'CRAWLER_NIGHT_ENABLED': '1'}, now=at(13, 21))
        self.assertEqual(result['reason'], 'AUTOCOMMIT_REQUIRED')

    def test_delayed_poll_does_not_burst_new_keywords(self):
        rows = [dict(keyword_id=1, attempt=1, outcome='SUCCEEDED', error_code=None,
                     started_at=at(13, 21, 30), ended_at=at(13, 21, 31))]
        keywords = [(1, 'AX'), (2, '데이터 분석')]
        self.assertEqual(night.plan_next(at(13, 22, 5), keywords, rows)[1], 'WAIT_INTERVAL')
        self.assertEqual(night.plan_next(at(13, 22, 30), keywords, rows)[0].keyword_id, 2)
        self.assertEqual(night.plan_next(at(13, 22, 30), keywords, rows,
                                        limits=night.NightLimits(120, 126))[1], 'NOTHING_DUE')

    def test_crashed_attempt_still_reserves_full_budget(self):
        rows = [dict(keyword_id=1, attempt=1, outcome='FAILED', error_code='WORKER_CRASH',
                     http_requests=0, started_at=at(13, 21), ended_at=at(13, 21, 1))]
        self.assertEqual(night.plan_next(at(13, 23), [(1, 'AX'), (2, '데이터 분석')], rows,
                                        limits=night.NightLimits(60, 7))[1], 'REQUEST_BUDGET')

    def test_midnight_and_next_night_window(self):
        for when, allowed in [(at(13, 20, 59), False), (at(13, 21), True), (at(13, 23, 59), True),
                              (at(14, 0), True), (at(14, 7, 59), True), (at(14, 8), False),
                              (at(14, 8, 1), False), (at(14, 21), True)]:
            with self.subTest(when=when):
                self.assertEqual(night.plan_next(when, [(1, 'AX')], [])[0] is not None, allowed)
        self.assertEqual(night.night_position(at(14, 0))[0], night.night_position(at(13, 21))[0])

    def test_request_guard_closes_at_window_or_job_deadline(self):
        guard = night.request_guard(stop_at=at(14, 8), deadline=100,
                                    now_utc=lambda: at(14, 7, 59), now_mono=lambda: 50)
        guard()
        for utc, mono in [(at(14, 8), 50), (at(14, 7, 59), 100)]:
            with self.subTest(utc=utc, mono=mono), self.assertRaises(http.FetchBlocked):
                night.request_guard(stop_at=at(14, 8), deadline=100,
                                    now_utc=lambda: utc, now_mono=lambda: mono)()

    def test_no_request_after_sleep_crosses_0800(self):
        current = [at(14, 7, 59)]
        guard = night.request_guard(stop_at=at(14, 8), deadline=float('inf'),
                                    now_utc=lambda: current[0])
        def advance(_seconds):
            current[0] = at(14, 8)
        with patch.object(http, '_get', return_value='User-agent: *\nAllow: /') as get, \
                patch.object(http.time, 'sleep', side_effect=advance):
            with self.assertRaises(http.FetchBlocked):
                list(http.fetch_pages([URL], approval=allow(URL), purpose='test', before_request=guard))
        self.assertEqual(get.call_count, 1)  # robots only; detail request never starts

    def test_no_request_when_guard_is_already_closed(self):
        with patch.object(http, '_get') as get, self.assertRaises(http.FetchBlocked):
            list(http.fetch_pages([URL], approval=allow(URL), purpose='test',
                                 before_request=lambda: (_ for _ in ()).throw(http.FetchBlocked('NIGHT_WINDOW_CLOSED'))))
        get.assert_not_called()

    def test_approval_expiry_is_rechecked_inside_running_job(self):
        guard = night.request_guard(stop_at=at(14, 8), deadline=float('inf'),
                                    approval_until=at(14, 1), now_utc=lambda: at(14, 1))
        with self.assertRaises(http.FetchBlocked) as caught:
            guard()
        self.assertEqual(caught.exception.reason, 'UNAPPROVED_SOURCE')

    def test_summary_exposes_conservative_budget_without_idle_spam(self):
        text = format_night_summary('2026-11-13', [], planned=[], missing=[],
                                    request_budget={'reserved': 7, 'limit': 7})['text']
        self.assertIn('Request budget reserved 7/7', text)
        self.assertIn('Limit reached: yes', text)

    def test_summary_marks_unusable_remainder_as_limit_reached(self):
        text = format_night_summary('2026-11-13', [], planned=[], missing=[],
                                    request_budget={'reserved': 7, 'limit': 10, 'per_job': 7})['text']
        self.assertIn('Limit reached: yes', text)


if __name__ == '__main__':
    unittest.main()
