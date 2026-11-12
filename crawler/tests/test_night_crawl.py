"""CRAWLER_NIGHT_01 pure policy: KST window, keyword pacing, retries, live gate, wiring, Slack text."""
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from crawler.jobs import night_crawl as nc
from crawler.jobs.dispatcher import night_step
from crawler.notifications.slack import format_night_job, format_night_summary, notify_night
from crawler.policy.source_approval_gate import SourceApproval

KST = ZoneInfo('Asia/Seoul')
KW = [(11, 'AX'), (12, '데이터 분석'), (13, '빅데이터'), (14, 'AI 엔지니어'), (15, '머신러닝'), (16, '딥러닝')]


def at(day, hh, mm=0):
    return datetime(2026, 11, day, hh, mm, tzinfo=KST)


def row(kid, attempt, outcome, code=None, ended=None):
    return dict(keyword_id=kid, attempt=attempt, outcome=outcome, error_code=code, ended_at=ended)


class WindowTests(unittest.TestCase):
    def test_boundaries_and_midnight(self):
        self.assertIsNone(nc.night_position(at(13, 20, 59)))
        self.assertEqual(nc.night_position(at(13, 21)), (date(2026, 11, 13), 0))
        self.assertEqual(nc.night_position(at(13, 23, 59)), (date(2026, 11, 13), 179))
        self.assertEqual(nc.night_position(at(14, 0, 0)), (date(2026, 11, 13), 180))
        self.assertEqual(nc.night_position(at(14, 7, 59)), (date(2026, 11, 13), 659))
        self.assertIsNone(nc.night_position(at(14, 8, 0)))
        with self.assertRaises(ValueError):
            nc.night_position(datetime(2026, 11, 13, 21))

    def test_no_new_job_after_0745(self):
        self.assertEqual(nc.plan_next(at(14, 7, 45), KW, [])[1], 'DUE')
        self.assertEqual(nc.plan_next(at(14, 7, 46), KW, []), (None, 'START_CUTOFF'))
        self.assertEqual(nc.plan_next(at(14, 8, 0), KW, []), (None, 'OUTSIDE_WINDOW'))
        self.assertEqual(nc.plan_next(at(13, 12, 0), KW, []), (None, 'OUTSIDE_WINDOW'))


class PlanTests(unittest.TestCase):
    def test_one_keyword_per_hour_in_order(self):
        choice, _ = nc.plan_next(at(13, 21, 5), KW, [])
        self.assertEqual((choice.keyword_id, choice.attempt), (11, 1))
        done = [row(11, 1, 'SUCCEEDED')]
        self.assertEqual(nc.plan_next(at(13, 21, 30), KW, done), (None, 'NOTHING_DUE'))
        self.assertEqual(nc.plan_next(at(13, 22, 0), KW, done)[0].keyword_id, 12)
        everything = [row(k, 1, 'SUCCEEDED') for k, _ in KW]
        self.assertEqual(nc.plan_next(at(14, 3, 0), KW, everything), (None, 'NOTHING_DUE'))

    def test_late_keyword_catches_up_in_order(self):
        # Timer was down until 01:10 -> AX first, then 데이터 분석 on the next poll.
        self.assertEqual(nc.plan_next(at(14, 1, 10), KW, [])[0].keyword_id, 11)
        self.assertEqual(nc.plan_next(at(14, 1, 15), KW, [row(11, 1, 'PARTIAL')])[0].keyword_id, 12)

    def test_running_blocks_and_stop_code_halts(self):
        self.assertEqual(nc.plan_next(at(13, 22), KW, [row(11, 1, 'RUNNING')]), (None, 'JOB_RUNNING'))
        halted = [row(11, 1, 'FAILED', 'RATE_LIMITED', at(13, 21, 1))]
        self.assertEqual(nc.plan_next(at(14, 2), KW, halted), (None, 'NIGHT_HALTED'))

    def test_bounded_retry_with_backoff(self):
        failed = [row(11, 1, 'FAILED', 'TEMPORARY_IO', at(13, 21, 0))]
        self.assertEqual(nc.plan_next(at(13, 21, 0, ) + timedelta(seconds=30), KW, failed), (None, 'NOTHING_DUE'))
        retry = nc.plan_next(at(13, 21, 5), KW, failed)[0]
        self.assertEqual((retry.keyword_id, retry.attempt), (11, 2))
        exhausted = [row(11, a, 'FAILED', 'TEMPORARY_IO', at(13, 21, a)) for a in (1, 2, 3)]
        self.assertEqual(nc.plan_next(at(13, 21, 30), KW, exhausted), (None, 'NOTHING_DUE'))
        crashed = [row(11, 1, 'FAILED', 'WORKER_CRASH', at(13, 21, 0))]
        self.assertEqual(nc.plan_next(at(13, 21, 30), KW, crashed), (None, 'NOTHING_DUE'))


def approval(**extra):
    values = dict(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='pm',
                  evidence_ref='ref', valid_from_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
                  review_due_utc=datetime(2027, 1, 1, tzinfo=timezone.utc), collection_method='WEB',
                  allowed_urls=('https://www.jobkorea.co.kr/Recruit/GI_Read/1',),
                  allowed_purposes=(nc.PURPOSE,), max_requests=10, retention_days=30, stop_on_block=True)
    values.update(extra)
    return SourceApproval(**values)


class GateTests(unittest.TestCase):
    def test_fail_closed_layers(self):
        now = at(13, 21)
        self.assertEqual(nc.live_gate(environ={}, keyword='AX', now=now), ('PM_ACTIVATION_REQUIRED', None))
        env = {'CRAWLER_LIVE_SCHEDULE_APPROVED': '1'}
        self.assertEqual(nc.live_gate(environ=env, keyword='AX', now=now), ('UNAPPROVED_SOURCE', None))
        env['CRAWLER_NIGHT_POLICY_FILE'] = '/nonexistent/policy.json'
        self.assertEqual(nc.live_gate(environ=env, keyword='AX', now=now), ('UNAPPROVED_SOURCE', None))

    def test_current_t61_scope_rejects_keyword_search_even_with_full_approval(self):
        env = {'CRAWLER_LIVE_SCHEDULE_APPROVED': '1', 'CRAWLER_NIGHT_POLICY_FILE': 'x'}
        self.assertEqual(nc.live_gate(environ=env, keyword='AX', now=at(13, 21),
                                      approval_loader=lambda p: approval()), ('OUT_OF_SCOPE', None))

    def test_search_url_is_the_existing_public_search_page(self):
        self.assertEqual(nc.search_url('데이터 분석'),
                         'https://www.jobkorea.co.kr/Search/?stext=%EB%8D%B0%EC%9D%B4%ED%84%B0%20%EB%B6%84%EC%84%9D&tabType=recruit')

    def test_policy_file_loader(self):
        import tempfile, os
        data = dict(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='pm',
                    evidence_ref='r', valid_from_utc='2026-01-01T00:00:00Z', review_due_utc='2027-01-01T00:00:00Z',
                    collection_method='WEB', allowed_urls=[], allowed_purposes=[nc.PURPOSE], max_requests=7,
                    retention_days=1, stop_on_block=True)
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(data, f)
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(nc.load_approval(f.name).max_requests, 7)
        self.assertIsNone(nc.load_approval(f.name + '.missing'))


class BoundedPagesTests(unittest.TestCase):
    def test_counts_requests_and_stops_at_deadline(self):
        counter = [0]
        pages = iter([('u1', '<html>'), ('u2', '<html>')])
        out = nc._bounded(pages, deadline=float('inf'), counter=counter)
        self.assertEqual([u for u, _ in out], ['u1', 'u2'])
        self.assertEqual(counter[0], 4)  # robots + list + 2 details
        with self.assertRaises(nc.FetchError):
            next(nc._bounded(iter([('u', 'h')]), deadline=0, counter=[0]))

    def test_first_pull_failure_is_counted_as_upper_bound(self):
        def pages():
            raise nc.FetchError('HTTP_429')
            yield
        counter = [0]
        with self.assertRaises(nc.FetchError):
            next(nc._bounded(pages(), deadline=float('inf'), counter=counter))
        self.assertEqual(counter[0], 3)  # robots + list + first detail: never under-count (F-08)


class WiringTests(unittest.TestCase):
    class Store:
        def __init__(self, free=True):
            self.free, self.calls, self.connection = free, [], object()

        def lock(self, key):
            self.calls.append(('lock', key)); return self.free

        def unlock(self, key):
            self.calls.append(('unlock', key))

    def test_disabled_by_default_without_lock_or_db(self):
        store = self.Store()
        self.assertEqual(night_step(store, environ={}), {'night': 'DISABLED'})
        self.assertEqual(store.calls, [])

    def test_runs_under_dispatcher_lock_and_swallows_errors(self):
        store = self.Store()
        with patch('crawler.jobs.night_crawl.run_night_step', side_effect=RuntimeError('boom')):
            self.assertEqual(night_step(store, environ={'CRAWLER_NIGHT_ENABLED': '1'})['night'], 'ERROR')
        self.assertEqual(store.calls, [('lock', 0), ('unlock', 0)])
        self.assertEqual(night_step(self.Store(free=False), environ={'CRAWLER_NIGHT_ENABLED': '1'}),
                         {'night': 'LOCKED'})


class SlackNightTests(unittest.TestCase):
    job = dict(job_id='j-1', keyword='AX', keyword_id=11, mode='live', attempt=1, outcome='SUCCEEDED',
               started_at=datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc),
               ended_at=datetime(2026, 11, 13, 12, 1, tzinfo=timezone.utc),
               http_requests=7, fetched=5, inserted=3, updated=1, unchanged=1, duplicates=0, failed=0, error_code=None)

    def test_job_message(self):
        text = format_night_job(self.job)['text']
        for part in ('SUCCEEDED', 'Keyword: AX', 'LIVE', 'j-1', '2026-11-13 21:00:00 KST', 'Requests 7',
                     'Inserted 3', 'Updated 1', 'Duplicate/unchanged 1', 'Failed 0'):
            self.assertIn(part, text)

    def test_summary_counts_and_unprocessed(self):
        rows = [self.job, dict(self.job, job_id='j-2', keyword='데이터 분석', keyword_id=12, outcome='FAILED',
                               inserted=0, updated=0, unchanged=0, failed=2, error_code='RATE_LIMITED')]
        text = format_night_summary(date(2026, 11, 13), rows, planned=['AX', '데이터 분석', '빅데이터'], missing=['딥러닝'])['text']
        for part in ('Jobs 2', 'Succeeded 1', 'Failed 1', 'Inserted 3', 'Updated 1', 'Failed items 2',
                     'Unprocessed keywords: 데이터 분석, 빅데이터, 딥러닝', '`RATE_LIMITED`'):
            self.assertIn(part, text)

    def test_notify_disabled_and_never_raises(self):
        self.assertIsNone(notify_night('job', None, [self.job], {}))
        hook = {'SLACK_WEBHOOK_URL': 'https://hooks.slack.com/services/T/B/SECRET'}
        self.assertEqual(notify_night('job', None, [self.job], hook, sender=lambda u, p: (True, 200, 'OK')), 200)
        self.assertIsNone(notify_night('job', None, [{}], hook, sender=lambda u, p: (True, 200, 'OK')))


if __name__ == '__main__':
    unittest.main()
