"""CRAWLER_NIGHT_01 against a real isolated PostgreSQL (opt-in, never an active scheduler DB).

The T61 gate is patched to ALLOWED and the fetcher returns the bundled JobKorea detail HTML
with substituted posting IDs, so the real parser/normalizer/upsert/discovery/checkpoint code runs
without any network request. Needs migrations 0002, 0003, 0007 and 0012.
"""
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from crawler.jobs import night_crawl as nc
from crawler.jobs.dispatcher import night_step
from crawler.jobs.import_jobkorea_html import FetchBlocked
from crawler.jobs.keyword_management import KeywordStore, normalize_keyword
from crawler.jobs.scheduler import SchedulerStore
from crawler.storage.staging import connect_configured_database

KST = ZoneInfo('Asia/Seoul')
HTML = (Path(__file__).resolve().parents[1] / 'fixtures' / 'jobkorea_user_detail_jsonld.html').read_text(encoding='utf-8')
ENV = {'CRAWLER_NIGHT_ENABLED': '1'}
ROBOTS = 'User-agent: *\nAllow: /'
GATED_ENV = {**ENV, 'CRAWLER_LIVE_SCHEDULE_APPROVED': '1', 'CRAWLER_NIGHT_POLICY_FILE': 'in-memory-test-approval'}


def page(posting_id, title_suffix=''):
    html = HTML.replace('50242499', str(posting_id))
    if title_suffix:
        html = html.replace('"title": "', '"title": "' + title_suffix, 1)
    return f'https://www.jobkorea.co.kr/Recruit/GI_Read/{posting_id}', html


class NightIntegrationTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('CRAWLER_T64_ISOLATED_TEST') != '1':
            self.skipTest('Isolated database opt-in required')
        self.connection = connect_configured_database()
        self.connection.autocommit = True
        self.night = date(2030, 1, 1) + timedelta(days=int.from_bytes(os.urandom(2), 'big'))
        self.ids = [9900000000 + int.from_bytes(os.urandom(3), 'big') * 10 + i for i in range(3)]
        keywords = KeywordStore(self.connection)
        existing = {k['keyword'] for k in keywords.list_keywords(include_deleted=True)}
        for word in nc.NIGHT_KEYWORDS:
            if word not in existing and normalize_keyword(word)[0] not in existing:
                keywords.add_keyword(word, priority=50)
        self.schedule_before = SchedulerStore(self.connection).schedule()
        self.sent = []
        self.addCleanup(self.cleanup)

    def cleanup(self):
        c = self.connection
        jobs = [r[0] for r in c.execute('SELECT job_id FROM crawler_training.night_job_results WHERE night_date=%s',
                                        (self.night,)).fetchall()]
        c.execute('DELETE FROM crawler_training.night_summaries WHERE night_date=%s', (self.night,))
        c.execute('DELETE FROM crawler_training.keyword_checkpoints WHERE last_completed_job_id = ANY(%s)', (jobs,))
        c.execute('DELETE FROM crawler_training.night_job_results WHERE job_id = ANY(%s)', (jobs,))
        c.execute('DELETE FROM crawler_training.keyword_jobs WHERE job_id = ANY(%s)', (jobs,))
        ids = [str(i) for i in self.ids]
        c.execute('DELETE FROM crawler_training.keyword_posting_discoveries WHERE external_posting_id = ANY(%s)', (ids,))
        c.execute("DELETE FROM crawler_training.postings WHERE source_code='jobkorea_live' AND external_posting_id = ANY(%s)", (ids,))
        c.close()

    def at(self, minutes):
        return datetime.combine(self.night, datetime.min.time(), KST).replace(hour=21) + timedelta(minutes=minutes)

    def step(self, minutes, pages=None, *, error=None):
        def fetcher(*, list_url, limit, **kw):
            self.assertIn('/Search/?stext=', list_url)
            if error:
                raise error
            yield from pages
        notify = lambda kind, night_date, rows, environ, **kw: self.sent.append((kind, [r['job_id'] for r in rows])) or 200
        with patch.object(nc, 'live_gate', return_value=('ALLOWED', None)):
            return nc.run_night_step(self.connection, environ=ENV, now=self.at(minutes), fetcher=fetcher, notify=notify)

    def result(self, job_id):
        return next(r for r in nc.NightStore(self.connection).results(self.night) if str(r['job_id']) == job_id)

    def test_keyword_jobs_insert_update_duplicate_discovery_checkpoint_and_slack(self):
        first = self.step(5, [page(self.ids[0]), page(self.ids[1])])
        self.assertEqual(first['night'], 'SUCCEEDED')
        row = self.result(first['job_id'])
        self.assertEqual((row['keyword'], row['inserted'], row['updated'], row['unchanged'], row['failed']), ('AX', 2, 0, 0, 0))
        self.assertEqual(row['http_requests'], 4)
        status = self.connection.execute('SELECT status FROM crawler_training.keyword_jobs WHERE job_id=%s',
                                         (row['job_id'],)).fetchone()[0]
        self.assertEqual(status, 'COMPLETED')
        self.assertIsNotNone(KeywordStore(self.connection) and self.connection.execute(
            'SELECT 1 FROM crawler_training.keyword_checkpoints WHERE last_completed_job_id=%s', (row['job_id'],)).fetchone())
        # Same hour: AX done, next keyword not yet due. No new job, no new notice.
        self.assertEqual(self.step(30, []), {'night': 'IDLE', 'reason': 'NOTHING_DUE'})
        # 22:05 데이터 분석 sees one unchanged and one changed posting.
        second = self.step(65, [page(self.ids[0]), page(self.ids[1], 'Changed ')])
        row2 = self.result(second['job_id'])
        self.assertEqual((row2['keyword'], row2['inserted'], row2['updated'], row2['unchanged']), ('데이터 분석', 0, 1, 1))
        linked = self.connection.execute("""SELECT count(DISTINCT keyword_id) FROM crawler_training.keyword_posting_discoveries
            WHERE source_code='jobkorea_live' AND external_posting_id=%s""", (str(self.ids[0]),)).fetchone()[0]
        self.assertEqual(linked, 2)
        total = self.connection.execute("""SELECT count(*) FROM crawler_training.postings
            WHERE source_code='jobkorea_live' AND external_posting_id = ANY(%s)""", ([str(i) for i in self.ids],)).fetchone()[0]
        self.assertEqual(total, 2)
        self.assertEqual([k for k, _ in self.sent], ['job', 'job'])
        self.assertEqual(nc.NightStore(self.connection).mark_notified(row['job_id']), False)
        # Morning summary exactly once.
        morning = datetime.combine(self.night + timedelta(days=1), datetime.min.time(), KST).replace(hour=8, minute=5)
        with patch.object(nc, 'live_gate', side_effect=AssertionError('no gate outside window')):
            notify = lambda kind, d, rows, environ, **kw: self.sent.append((kind, len(rows), kw['missing'])) or 200
            self.assertEqual(nc.run_night_step(self.connection, environ=ENV, now=morning, notify=notify)['night'], 'SUMMARY_SENT')
            self.assertEqual(nc.run_night_step(self.connection, environ=ENV, now=morning, notify=notify)['night'], 'IDLE')
        self.assertEqual(self.sent[-1], ('summary', 2, []))
        # The 03:00 fixture schedule is untouched by night work.
        after = SchedulerStore(self.connection).schedule()
        self.assertEqual((after['next_run_at'], after['mode'], after['enabled']),
                         (self.schedule_before['next_run_at'], self.schedule_before['mode'], self.schedule_before['enabled']))

    def test_block_stops_the_night_and_partial_detail_failure(self):
        blocked = self.step(5, error=FetchBlocked('HTTP_429', http_status=429))
        self.assertEqual((blocked['night'], blocked['error_code']), ('FAILED', 'RATE_LIMITED'))
        self.assertEqual(self.step(70, [page(self.ids[2])]), {'night': 'IDLE', 'reason': 'NIGHT_HALTED'})
        self.assertEqual(self.result(blocked['job_id'])['inserted'], 0)

    def test_partial_when_one_detail_is_unparseable(self):
        result = self.step(5, [page(self.ids[0]), ('https://www.jobkorea.co.kr/Recruit/GI_Read/1', '<html>no</html>')])
        row = self.result(result['job_id'])
        self.assertEqual((result['night'], row['inserted'], row['failed']), ('PARTIAL', 1, 1))

    def test_gate_blocked_and_disabled_write_nothing(self):
        def count():
            return self.connection.execute('SELECT (SELECT count(*) FROM crawler_training.keyword_jobs),'
                                           '(SELECT count(*) FROM crawler_training.night_job_results)').fetchone()
        before = count()
        fetcher = lambda **kw: self.fail('no HTTP when blocked')
        result = nc.run_night_step(self.connection, environ=ENV, now=self.at(5), fetcher=fetcher)
        self.assertEqual(result, {'night': 'BLOCKED', 'reason': 'PM_ACTIVATION_REQUIRED', 'external_requests': 0})
        self.assertEqual(nc.run_night_step(self.connection, environ={}, now=self.at(5)), {'night': 'DISABLED'})
        self.assertEqual(count(), before)

    def test_stale_running_job_is_recovered_and_retried(self):
        store = nc.NightStore(self.connection)
        keywords, _ = store.night_keywords()
        job_id = store.start(nc.Choice(keywords[0][0], keywords[0][1], 1), self.night)
        self.connection.execute('UPDATE crawler_training.night_job_results SET started_at=%s WHERE job_id=%s',
                                (self.at(0), job_id))
        self.assertEqual(self.step(5, [])['reason'], 'JOB_RUNNING')
        retried = self.step(20, [page(self.ids[0])])
        self.assertEqual((retried['night'], retried['attempt']), ('SUCCEEDED', 2))
        self.assertEqual(self.result(str(job_id))['error_code'], 'HEARTBEAT_TIMEOUT')

    def test_dispatcher_lock_excludes_night_step(self):
        other = connect_configured_database()
        try:
            holder = SchedulerStore(other)
            self.assertTrue(holder.lock(0))
            self.assertEqual(night_step(SchedulerStore(self.connection), environ=ENV), {'night': 'LOCKED'})
            holder.unlock(0)
        finally:
            other.close()


    def mocked_http(self, responses, approve=(), discover=0):
        """Real live_gate + fetch_pages + per-URL T61 checks; only HTTP is mocked (CRAWLER_NIGHT_09).
        Test-only, in-memory approval: every night keyword search page, plus either exactly listed
        details (``approve``) or bounded discovery (``discover``)."""
        from crawler.jobs import import_jobkorea_html as importer
        from crawler.policy.source_approval_gate import SourceApproval
        approval = SourceApproval(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='test',
                                  evidence_ref='test-only', valid_from_utc=datetime(2020, 1, 1, tzinfo=timezone.utc),
                                  review_due_utc=datetime(9000, 1, 1, tzinfo=timezone.utc), collection_method='WEB',
                                  allowed_urls=tuple(nc.search_url(k) for k in nc.NIGHT_KEYWORDS) + tuple(approve),
                                  allowed_purposes=(nc.PURPOSE,), max_requests=nc.DETAIL_LIMIT + 2,
                                  retention_days=1, stop_on_block=True, max_discovered_details=discover)
        kwargs = dict(environ=GATED_ENV, approval_loader=lambda path: approval)
        return kwargs, patch.object(importer, '_get', side_effect=responses), patch.object(importer.time, 'sleep')

    def test_full_pipeline_with_mocked_http_responses(self):
        """AX search -> 2 discovered details -> parse -> PostgreSQL -> keyword links, through the real gate."""
        urls = [page(i)[0] for i in self.ids[:2]]
        listing = ''.join(f'<a href="{u}">p</a>' for u in urls) + '<a href="https://evil.example/Recruit/GI_Read/1">x</a>'
        responses = [ROBOTS, listing, page(self.ids[0])[1], page(self.ids[1])[1]]
        gate, get_patch, sleep_patch = self.mocked_http(responses, discover=nc.DETAIL_LIMIT)
        notify = lambda kind, night_date, rows, environ, **kw: self.sent.append((kind, rows[0]['inserted'])) or 200
        with get_patch as get, sleep_patch:
            result = nc.run_night_step(self.connection, now=self.at(5), notify=notify, **gate)
        self.assertEqual([c.args[0] for c in get.call_args_list],
                         ['https://www.jobkorea.co.kr/robots.txt', nc.search_url(nc.NIGHT_KEYWORDS[0])] + urls)
        row = self.result(result['job_id'])
        self.assertEqual((result['night'], row['http_requests'], row['fetched'], row['inserted'], row['failed']),
                         ('SUCCEEDED', 4, 2, 2, 0))
        self.assertEqual(self.sent, [('job', 2)])
        linked = self.connection.execute("""SELECT count(*) FROM crawler_training.keyword_posting_discoveries
            WHERE keyword_id=%s AND external_posting_id = ANY(%s)""", (row['keyword_id'], [str(i) for i in self.ids[:2]])).fetchone()[0]
        self.assertEqual(linked, 2)
        checkpoint = self.connection.execute("""SELECT count(*) FROM crawler_training.keyword_checkpoints
            WHERE keyword_id=%s""", (row['keyword_id'],)).fetchone()[0]
        self.assertEqual(checkpoint, 1)

    def test_mocked_429_on_detail_and_unapproved_detail_stop_without_further_requests(self):
        from crawler.jobs.import_jobkorea_html import FetchBlocked
        urls = [page(i)[0] for i in self.ids[:2]]
        listing = ''.join(f'<a href="{u}">p</a>' for u in urls)
        responses = [ROBOTS, listing, FetchBlocked('HTTP_429', http_status=429)]
        gate, get_patch, sleep_patch = self.mocked_http(responses, approve=urls)
        with get_patch as get, sleep_patch:
            result = nc.run_night_step(self.connection, now=self.at(5), notify=lambda *a, **k: 200, **gate)
        self.assertEqual((result['night'], result['error_code'], get.call_count), ('FAILED', 'RATE_LIMITED', 3))
        # Next keyword hour: with discovery off, a detail URL not listed exactly is never requested.
        responses = [ROBOTS, ''.join(f'<a href="{page(self.ids[2])[0]}">p</a>')]
        gate, get_patch, sleep_patch = self.mocked_http(responses, approve=urls)
        self.connection.execute("UPDATE crawler_training.night_job_results SET error_code='TEMPORARY_IO' WHERE job_id=%s",
                                (result['job_id'],))  # lift the night halt to exercise the next job
        with get_patch as get, sleep_patch:
            second = nc.run_night_step(self.connection, now=self.at(65), notify=lambda *a, **k: 200, **gate)
        self.assertEqual((second['night'], second['error_code'], get.call_count), ('FAILED', 'UNAPPROVED_SOURCE', 2))


if __name__ == '__main__':
    unittest.main()
