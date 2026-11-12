"""CRAWLER_NIGHT_04: whole-night E2E of the night keyword crawler on an ISOLATED PostgreSQL.

Opt-in only (``CRAWLER_NIGHT_E2E=1``). Everything here is SYNTHETIC:
- the clock is injected (virtual nights in 2031+); the server clock and timers are untouched;
- JobKorea HTTP is mocked at ``import_jobkorea_html._get`` (robots, search list, detail pages),
  so the real fetch_pages -> parser -> normaliser -> upsert -> discovery -> checkpoint path runs
  with ZERO network requests;
- Slack goes to a capturing sender; every captured message is labelled ``[STAGING E2E TEST]``.

The T61 evaluator is not changed or bypassed for detail pages: each detail URL is checked by the
real gate against a test-only approval listing exactly those URLs. Only the keyword search page,
which today's T61 scope cannot express, is let through in this harness (documented, test-only).

Refuses to run against the operational crawler DB (CRAWLER_DB_MODE=staging, or an enabled
schedule). Results are left in the isolated DB as evidence and summarised to
``CRAWLER_NIGHT_E2E_OUT`` (JSON) when set.
"""
import json
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from crawler.jobs import import_jobkorea_html as importer
from crawler.jobs import night_crawl as nc
from crawler.jobs.dispatcher import dispatch, night_step
from crawler.jobs.keyword_management import KeywordStore, normalize_keyword
from crawler.jobs.scheduler import SchedulerStore
from crawler.notifications import slack
from crawler.policy.source_approval_gate import SourceApproval
from crawler.storage.staging import connect_configured_database
from crawler.tests.local_night_integration import page

KST = ZoneInfo('Asia/Seoul')
ENV = {'CRAWLER_NIGHT_ENABLED': '1', 'SLACK_WEBHOOK_URL': 'https://hooks.slack.com/services/E2E/TEST/NOT-A-REAL-HOOK'}
LABEL = '[STAGING E2E TEST]'
RUN_ID = 'e2e-' + os.urandom(4).hex()
BASE = date(2031, 1, 1) + timedelta(days=int.from_bytes(os.urandom(2), 'big') % 3000)
EVIDENCE = {'run_id': RUN_ID, 'mode': 'FIXTURE_MOCK_HTTP', 'synthetic': True, 'scenarios': {}, 'slack': []}


def kst(night, hh, mm=0):
    day = night if hh >= 12 else night + timedelta(days=1)
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=KST)


RUN_SEED = int.from_bytes(os.urandom(2), 'big') % 10000  # distinct synthetic IDs per harness run


def ids_for(night_index, keyword_index):
    return [9800000000 + RUN_SEED * 100000 + night_index * 1000 + keyword_index * 10 + i for i in range(2)]


class Web:
    """Mocked JobKorea: robots, one search page per keyword, detail pages. Counts every call."""

    def __init__(self, listings, details=None, fail=None):
        self.listings, self.details, self.fail, self.calls = listings, details or {}, fail or {}, []

    def __call__(self, url):
        self.calls.append(url)
        for marker, error in self.fail.items():
            if marker in url:
                raise error
        if url.endswith('/robots.txt'):
            return 'User-agent: *\nAllow: /'
        if '/Search/' in url:
            return ''.join(f'<a href="https://www.jobkorea.co.kr/Recruit/GI_Read/{i}">p</a>' for i in self.listings[url])
        posting_id = int(url.rsplit('/', 1)[1])
        return self.details.get(posting_id) or page(posting_id)[1]


class StagingNightE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('CRAWLER_NIGHT_E2E') != '1':
            raise unittest.SkipTest('Isolated E2E opt-in required (CRAWLER_NIGHT_E2E=1)')
        if os.environ.get('CRAWLER_DB_MODE', 'local') == 'staging':
            raise RuntimeError('Refusing: E2E must never use the operational Staging crawler DB')
        cls.connection = connect_configured_database()
        cls.connection.autocommit = True
        cls.store = SchedulerStore(cls.connection)
        schedule = cls.store.schedule()
        if schedule is None or schedule['enabled']:
            raise RuntimeError('Refusing: isolated DB must hold the disabled seed schedule')
        cls.schedule_before = dict(schedule)
        keywords = KeywordStore(cls.connection)
        have = {normalize_keyword(k['keyword'])[1] for k in keywords.list_keywords(include_deleted=True)}
        for word in nc.NIGHT_KEYWORDS:
            if normalize_keyword(word)[1] not in have:
                keywords.add_keyword(word, priority=100, actor='test:crawler_night_04_e2e')
        cls.keywords, missing = nc.NightStore(cls.connection).night_keywords()
        assert not missing and len(cls.keywords) == 6, missing
        cls.slack_calls = []

    @classmethod
    def tearDownClass(cls):
        if not hasattr(cls, 'connection'):
            return
        c = cls.connection
        s = cls.schedule_before
        c.execute('''UPDATE crawler_training.schedules SET enabled=%s,mode=%s,local_time=%s,next_run_at=%s,
            last_run_at=%s WHERE schedule_id=%s''',
                  (s['enabled'], s['mode'], s['local_time'], s['next_run_at'], s['last_run_at'], s['schedule_id']))
        nights = [BASE + timedelta(days=i) for i in range(10)]
        rows = c.execute('''SELECT r.night_date::text, k.keyword, r.attempt, r.outcome, r.error_code, r.http_requests,
                r.fetched, r.inserted, r.updated, r.unchanged, r.duplicates, r.failed,
                to_char(r.started_at AT TIME ZONE 'Asia/Seoul','YYYY-MM-DD HH24:MI:SS') started_kst_wallclock
            FROM crawler_training.night_job_results r JOIN crawler_training.search_keywords k USING (keyword_id)
            WHERE r.night_date = ANY(%s) ORDER BY r.night_date, r.started_at, r.attempt''', (nights,)).fetchall()
        cols = ['night_date', 'keyword', 'attempt', 'outcome', 'error_code', 'http_requests', 'fetched', 'inserted',
                'updated', 'unchanged', 'duplicates', 'failed', 'started_kst_wallclock']
        EVIDENCE['db_rows'] = [dict(zip(cols, r)) for r in rows]
        EVIDENCE['db_summaries'] = [r[0] for r in c.execute(
            'SELECT night_date::text FROM crawler_training.night_summaries WHERE night_date = ANY(%s) ORDER BY 1',
            (nights,)).fetchall()]
        EVIDENCE['slack'] = cls.slack_calls
        out = os.environ.get('CRAWLER_NIGHT_E2E_OUT')
        if out:
            with open(out, 'w', encoding='utf-8') as f:
                json.dump(EVIDENCE, f, ensure_ascii=False, indent=1, default=str)
        c.close()

    # ---- helpers -------------------------------------------------------------------------
    def approval(self, urls):
        return SourceApproval(source_code='jobkorea', approval_status='APPROVED', enabled=True, approved_by='test-only',
                              evidence_ref='CRAWLER_NIGHT_04 synthetic E2E', valid_from_utc=datetime(2020, 1, 1, tzinfo=timezone.utc),
                              review_due_utc=datetime(2099, 1, 1, tzinfo=timezone.utc), collection_method='WEB',
                              allowed_urls=tuple(urls), allowed_purposes=(nc.PURPOSE,), max_requests=20,
                              retention_days=1, stop_on_block=True)

    def notify(self, kind, night_date, rows, environ, **kw):
        def sender(url, payload):
            text = f"{LABEL} run={RUN_ID}\n" + payload['text']
            self.__class__.slack_calls.append({'kind': kind, 'night': str(night_date), 'text': text})
            return True, 200, 'OK'
        return slack.notify_night(kind, night_date, rows, environ, sender=sender, **kw)

    def poll(self, at, web, approved_ids):
        """One dispatcher poll at a virtual time: the daily dispatch first, the night step only if it was IDLE."""
        urls = [f'https://www.jobkorea.co.kr/Recruit/GI_Read/{i}' for i in approved_ids]
        real = importer._permit
        permit = lambda a, p, url, calls, now: None if '/Search/' in url else real(a, p, url, calls, now)
        with patch.object(importer, '_get', side_effect=web), patch.object(importer.time, 'sleep'), \
                patch.object(importer, '_permit', side_effect=permit), \
                patch.object(nc, 'live_gate', return_value=('ALLOWED', self.approval(urls))):
            return night_step(self.store, environ=ENV, now=at, notify=self.notify)

    def rows(self, night):
        return nc.NightStore(self.connection).results(night)

    def listing(self, night_index, overrides=None):
        listings = {}
        for k, (_, word) in enumerate(self.keywords):
            listings[nc.search_url(word)] = (overrides or {}).get(k, ids_for(night_index, k))
        return listings

    def all_ids(self, night_index):
        return [i for k in range(6) for i in ids_for(night_index, k)]

    # ---- scenarios -----------------------------------------------------------------------
    def test_1_full_night_window_pacing_fixture_coexistence_and_summary(self):
        night = BASE
        # Keyword 1 (데이터 분석) also lists one AX posting: a cross-keyword repeat, no duplicate insert.
        overlap = {1: [ids_for(0, 0)[0], ids_for(0, 1)[1]]}
        web = Web(self.listing(0, overlap))
        trace, t = [], kst(night, 20, 50)
        while t <= kst(night, 8, 10):
            if t == kst(night, 3, 0):
                # The 03:00 daily fixture run takes this poll (same lock); the night step is not run.
                self.connection.execute('''UPDATE crawler_training.schedules SET enabled=true,mode='fixture',
                    next_run_at=now()-interval '1 second' WHERE schedule_id='jobkorea-daily' ''')
                daily = dispatch(self.store, environ={})
                self.connection.execute("UPDATE crawler_training.schedules SET enabled=false WHERE schedule_id='jobkorea-daily'")
                trace.append((t.strftime('%H:%M'), 'DAILY_' + daily['status']))
                self.assertEqual(daily['status'], 'SUCCEEDED')
            else:
                result = self.poll(t, web, self.all_ids(0))
                trace.append((t.strftime('%H:%M'), result['night'] + ('/' + result.get('reason', '') if result.get('reason') else '')))
            t += timedelta(minutes=5)
        rows = self.rows(night)
        # DB timestamps are real wall-clock (correct in production); pacing is checked on the virtual poll trace.
        self.assertEqual([r['keyword'] for r in rows], ['AX', '데이터 분석', '빅데이터', 'AI 엔지니어', '머신러닝', '딥러닝'])
        self.assertEqual([h for h, s in trace if s == 'SUCCEEDED'], ['21:00', '22:00', '23:00', '00:00', '01:00', '02:00'])
        self.assertTrue(all(r['outcome'] == 'SUCCEEDED' and r['attempt'] == 1 for r in rows))
        self.assertTrue(all(r['night_date'] == night for r in rows))  # 00:00-02:00 jobs belong to the same night
        self.assertEqual([r['inserted'] for r in rows], [2, 1, 2, 2, 2, 2])
        self.assertEqual(rows[1]['unchanged'], 1)
        before_21 = [s for h, s in trace if h < '21:00' and h >= '12:00']
        self.assertTrue(before_21 and all(s == 'IDLE/OUTSIDE_WINDOW' for s in before_21))
        self.assertIn(('07:50', 'IDLE/START_CUTOFF'), trace)
        self.assertIn(('08:00', 'SUMMARY_SENT'), trace)          # first poll after the window
        self.assertIn(('08:05', 'IDLE/OUTSIDE_WINDOW'), trace)   # summary not sent twice
        self.assertIn(('08:10', 'IDLE/OUTSIDE_WINDOW'), trace)
        self.assertIn(('03:05', 'IDLE/NOTHING_DUE'), trace)      # all six done before 03:00; no extra work
        self.assertEqual(len([s for _, s in trace if s == 'SUCCEEDED']), 6)
        self.assertEqual(len(web.calls), 6 * 4)  # robots + list + 2 details per keyword, all mocked
        linked = self.connection.execute('''SELECT count(DISTINCT keyword_id) FROM crawler_training.keyword_posting_discoveries
            WHERE source_code='jobkorea_live' AND external_posting_id=%s''', (str(ids_for(0, 0)[0]),)).fetchone()[0]
        self.assertEqual(linked, 2)
        checkpoints = self.connection.execute('''SELECT count(*) FROM crawler_training.keyword_checkpoints
            WHERE keyword_id = ANY(%s)''', ([k for k, _ in self.keywords],)).fetchone()[0]
        self.assertEqual(checkpoints, 6)
        night_slack = [m for m in self.slack_calls if m['night'] == str(night)]
        self.assertEqual([m['kind'] for m in night_slack], ['job'] * 6 + ['summary'])
        summary = night_slack[-1]['text']
        for part in (LABEL, 'Jobs 6', 'Succeeded 6', 'Failed 0', 'Inserted 11', 'Updated 0', 'Duplicate/unchanged 1',
                     'Unprocessed keywords: none'):
            self.assertIn(part, summary)
        EVIDENCE['scenarios']['full_night'] = {'night': str(night), 'trace': trace, 'mocked_http_calls': len(web.calls)}

    def test_2_next_night_duplicates_updates_and_checkpoint_advance(self):
        night = BASE + timedelta(days=1)
        ax_id, ax_ids = self.keywords[0][0], ids_for(0, 0)
        before = self.connection.execute('SELECT last_success_at FROM crawler_training.keyword_checkpoints WHERE keyword_id=%s',
                                         (ax_id,)).fetchone()[0]
        web = Web(self.listing(0), details={ax_ids[1]: page(ax_ids[1], 'Changed ')[1]})
        result = self.poll(kst(night, 21, 0), web, self.all_ids(0))
        row = self.rows(night)[0]
        self.assertEqual((result['night'], row['inserted'], row['updated'], row['unchanged']), ('SUCCEEDED', 0, 1, 1))
        total = self.connection.execute('''SELECT count(*) FROM crawler_training.postings WHERE source_code='jobkorea_live'
            AND external_posting_id = ANY(%s)''', ([str(i) for i in self.all_ids(0)],)).fetchone()[0]
        self.assertEqual(total, 11)  # no duplicate insert across nights
        after = self.connection.execute('SELECT last_success_at FROM crawler_training.keyword_checkpoints WHERE keyword_id=%s',
                                        (ax_id,)).fetchone()[0]
        self.assertGreater(after, before)
        EVIDENCE['scenarios']['next_night_dup_update'] = {'night': str(night), 'inserted': 0, 'updated': 1, 'unchanged': 1}

    def failure_night(self, offset, fail=None, details=None, at=(21, 0)):
        night = BASE + timedelta(days=offset)
        web = Web(self.listing(offset), details=details, fail=fail)
        return night, web, self.poll(kst(night, *at), web, self.all_ids(offset))

    def test_3_blocks_stop_the_night(self):
        for offset, marker, error, code, calls in (
                (2, '/Search/', importer.FetchBlocked('HTTP_403', http_status=403), 'ACCESS_FORBIDDEN', 2),
                (3, '/GI_Read/', importer.FetchBlocked('HTTP_429', http_status=429), 'RATE_LIMITED', 3)):
            night, web, result = self.failure_night(offset, fail={marker: error})
            self.assertEqual((result['night'], result['error_code'], len(web.calls)), ('FAILED', code, calls))
            later = self.poll(kst(night, 22, 5), Web(self.listing(offset)), self.all_ids(offset))
            self.assertEqual(later, {'night': 'IDLE', 'reason': 'NIGHT_HALTED'})
            EVIDENCE['scenarios'][f'block_{code}'] = {'night': str(night), 'http_calls_before_stop': calls}

    def test_4_timeout_retries_are_bounded(self):
        night = BASE + timedelta(days=4)
        web = Web(self.listing(4), fail={'/Search/': importer.FetchError('TIMEOUT')})
        outcomes = []
        for minute in (0, 1, 3, 6, 10):  # backoff 60 s then 120 s; at most 3 attempts
            outcomes.append(self.poll(kst(night, 21, minute), web, self.all_ids(4)))
        attempts = sorted((r['attempt'], r['outcome'], r['error_code']) for r in self.rows(night))
        self.assertEqual(attempts, [(1, 'FAILED', 'WORKER_TIMEOUT'), (2, 'FAILED', 'WORKER_TIMEOUT'), (3, 'FAILED', 'WORKER_TIMEOUT')])
        self.assertEqual(outcomes[-1], {'night': 'IDLE', 'reason': 'NOTHING_DUE'})
        EVIDENCE['scenarios']['timeout_retry_limit'] = {'night': str(night), 'attempts': attempts}

    def test_5_parse_and_db_save_failures_are_recorded_safely(self):
        night, _, result = self.failure_night(5, details={i: '<html>broken</html>' for i in ids_for(5, 0)})
        self.assertEqual((result['night'], result['error_code']), ('FAILED', 'INVALID_CONTRACT'))
        self.assertEqual(self.rows(night)[0]['failed'], 2)
        night6 = BASE + timedelta(days=6)
        with patch('crawler.storage.postgres.PostgresPostingStore.upsert', side_effect=RuntimeError('db down: secret')):
            web = Web(self.listing(6))
            saved = self.poll(kst(night6, 21, 0), web, self.all_ids(6))
        row = self.rows(night6)[0]
        self.assertEqual((saved['night'], row['failed'], row['inserted']), ('FAILED', 2, 0))
        self.assertNotIn('secret', json.dumps(saved, default=str) + str(row['error_code']))
        EVIDENCE['scenarios']['parse_failure'] = {'night': str(night), 'error_code': result['error_code']}
        EVIDENCE['scenarios']['db_save_failure'] = {'night': str(night6), 'error_code': saved['error_code']}

    def test_6_duplicate_execution_and_worker_abort(self):
        night = BASE + timedelta(days=7)
        other = connect_configured_database()
        try:
            holder = SchedulerStore(other)
            self.assertTrue(holder.lock(0))
            locked = self.poll(kst(night, 21, 0), Web(self.listing(7)), self.all_ids(7))
            holder.unlock(0)
        finally:
            other.close()
        self.assertEqual(locked, {'night': 'LOCKED'})
        store = nc.NightStore(self.connection)
        job = store.start(nc.Choice(self.keywords[0][0], self.keywords[0][1], 1), night)
        self.connection.execute('UPDATE crawler_training.night_job_results SET started_at=%s WHERE job_id=%s',
                                (kst(night, 21, 0), job))
        running = self.poll(kst(night, 21, 5), Web(self.listing(7)), self.all_ids(7))
        self.assertEqual(running, {'night': 'IDLE', 'reason': 'JOB_RUNNING'})
        with self.assertRaises(Exception):
            store.start(nc.Choice(self.keywords[0][0], self.keywords[0][1], 1), night)  # same attempt twice
        recovered = self.poll(kst(night, 21, 20), Web(self.listing(7)), self.all_ids(7))
        attempts = sorted((r['attempt'], r['outcome'], r['error_code']) for r in self.rows(night))
        self.assertEqual(attempts, [(1, 'FAILED', 'HEARTBEAT_TIMEOUT'), (2, 'SUCCEEDED', None)])
        self.assertEqual(recovered['night'], 'SUCCEEDED')
        EVIDENCE['scenarios']['duplicate_and_abort'] = {'night': str(night), 'attempts': attempts}

    def test_7_slack_messages_are_labelled_and_not_duplicated(self):
        texts = [m['text'] for m in self.slack_calls]
        self.assertTrue(texts and all(t.startswith(LABEL) for t in texts))
        self.assertNotIn('NOT-A-REAL-HOOK', json.dumps(self.slack_calls))
        keys = [(m['kind'], m['night'], m['text'].split('Job ID: ')[-1][:40]) for m in self.slack_calls]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == '__main__':
    unittest.main()
