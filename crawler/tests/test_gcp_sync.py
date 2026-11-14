"""#337 GCP posting sync: mapping, plan decisions, settings guard, retry policy (no database)."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from crawler.jobs import gcp_sync as g

UTC = timezone.utc
SEEN = datetime(2026, 11, 12, 17, 4, tzinfo=UTC)
SOURCE_ID = uuid.uuid4()


def payload(n, **over):
    base = {'source_code': 'jobkorea', 'external_posting_id': str(n),
            'source_url': f'https://www.jobkorea.co.kr/Recruit/GI_Read/{n}', 'title': f'AI 엔지니어 {n}',
            'company_name': '테스트기업', 'location_text': '서울', 'employment_type': 'full_time',
            'published_on': None, 'expires_on': '2026-11-30', 'status': 'published'}
    base.update(over)
    return base


def row(n, code='jobkorea_live', seen=SEEN, **over):
    return g.SourceRow(code, str(n), payload(n, **over), seen)


def plan(rows, refs=None, owners=None, publish=False):
    return g.plan(rows, source_code='jobkorea_live', source_id=SOURCE_ID, refs=refs or {},
                  url_owners=owners or {}, publish=publish)


def existing_from(n, *, publish=False, source_id=SOURCE_ID, seen=SEEN, **over):
    values = g.map_row(row(n, **over), publish=publish)
    values['published_at'] = values['published_at'] or seen
    return g.Existing(uuid.uuid4(), source_id, values)


class MappingTest(unittest.TestCase):
    def test_dates_are_kst_day_bounds(self):
        values = g.map_row(row(1, published_on='2026-11-01', expires_on='2026-11-30'), publish=True)
        self.assertEqual(values['published_at'], datetime(2026, 10, 31, 15, 0, tzinfo=UTC))
        self.assertEqual(values['expires_at'], datetime(2026, 11, 30, 15, 0, tzinfo=UTC))  # 12-01 00:00 KST
        self.assertEqual(values['status'], 'published')

    def test_unpublished_by_default_and_missing_dates(self):
        values = g.map_row(row(1, expires_on=None), publish=False)
        self.assertEqual(values['status'], 'draft')
        self.assertIsNone(values['published_at'])
        self.assertIsNone(values['expires_at'])

    def test_reuses_normalizer_validation(self):
        for bad in ({'title': ''}, {'source_url': 'http://evil.example/1'}, {'employment_type': 'freelance'},
                    {'status': 'deleted'}, {'expires_on': '2026-13-01'}):
            with self.subTest(bad=bad), self.assertRaises(g.InvalidPosting):
                g.map_row(row(1, **bad), publish=True)

    def test_length_limits_follow_target_columns(self):
        with self.assertRaises(g.InvalidPosting):
            g.map_row(row(1, location_text='가' * 121), publish=True)
        g.map_row(row(1, location_text='가' * 120), publish=True)

    def test_key_mismatch_rejected(self):
        bad = g.SourceRow('jobkorea_live', '999', payload(1), SEEN)
        with self.assertRaises(g.InvalidPosting):
            g.map_row(bad, publish=True)


class PlanTest(unittest.TestCase):
    def test_new_rows_insert_with_first_seen_publish_time(self):
        result = plan([row(1), row(2)])
        self.assertEqual(result.counts(), {'inserted': 2, 'updated': 0, 'duplicate': 0, 'skipped': 0, 'failed': 0})
        self.assertEqual(result.inserts[0][1]['published_at'], SEEN)

    def test_other_source_codes_are_skipped_not_copied(self):
        result = plan([row(1, code='jobkorea'), row(2, code='jobkorea_imported'), row(3)])
        self.assertEqual(result.counts()['inserted'], 1)
        self.assertEqual([r for _, r in result.skipped], ['SOURCE_NOT_SELECTED'] * 2)

    def test_identical_row_is_duplicate_and_not_written(self):
        ex = existing_from(1)
        result = plan([row(1, seen=SEEN + timedelta(days=1))], refs={'1': ex},
                      owners={ex.values['source_url']: [(ex.job_posting_id, SOURCE_ID)]})
        self.assertEqual(result.counts()['duplicate'], 1)
        self.assertEqual(result.updates, [])

    def test_only_changed_fields_update_and_publish_time_kept(self):
        ex = existing_from(1)
        result = plan([row(1, title='바뀐 제목', seen=SEEN + timedelta(days=1))], refs={'1': ex},
                      owners={ex.values['source_url']: [(ex.job_posting_id, SOURCE_ID)]})
        self.assertEqual(len(result.updates), 1)
        self.assertEqual(result.updates[0][1], {'title': '바뀐 제목'})

    def test_publish_flag_changes_only_status(self):
        ex = existing_from(1, publish=False)
        result = plan([row(1)], refs={'1': ex}, publish=True,
                      owners={ex.values['source_url']: [(ex.job_posting_id, SOURCE_ID)]})
        self.assertEqual(result.updates[0][1], {'status': 'published'})

    def test_invalid_rows_skipped_with_reason(self):
        result = plan([row(1, title=' '), row(2, published_on='2026-11-20', expires_on='2026-11-10')])
        self.assertEqual(result.counts()['skipped'], 2)
        self.assertTrue(all(reason.startswith('INVALID') for _, reason in result.skipped))

    def test_expiry_before_first_seen_is_skipped(self):
        result = plan([row(1, expires_on='2026-11-01')])  # first seen 11-12, expired 11-02 00:00 KST
        self.assertEqual(result.skipped, [('1', 'INVALID: Expiry precedes publish time')])

    def test_other_source_or_url_owner_is_never_overwritten(self):
        foreign = existing_from(1, source_id=uuid.uuid4())
        url_taken = plan([row(2)], owners={payload(2)['source_url']: [(uuid.uuid4(), uuid.uuid4())]})
        source_clash = plan([row(1)], refs={'1': foreign})
        self.assertEqual(url_taken.failed, [('2', 'URL_CONFLICT')])
        self.assertEqual(source_clash.failed, [('1', 'SOURCE_CONFLICT')])
        self.assertEqual(url_taken.inserts + source_clash.updates, [])

    def test_duplicate_url_inside_source_is_skipped(self):
        result = plan([row(1), g.SourceRow('jobkorea_live', '2', payload(2, source_url=payload(1)['source_url']), SEEN)])
        self.assertEqual(result.counts()['inserted'], 1)
        self.assertEqual(result.skipped, [('2', 'DUPLICATE_URL_IN_SOURCE')])


ENV = {'GCP_SYNC_TARGET_HOST': 'x.asia-northeast3.sql.goog', 'GCP_SYNC_TARGET_HOSTADDR': '192.0.2.10',
       'GCP_SYNC_TARGET_USER': 'career_sync', 'GCP_SYNC_TARGET_PASSWORD': 'pw',
       'GCP_SYNC_TARGET_SSLROOTCERT_PEM': '-----BEGIN CERTIFICATE-----\nAA\n-----END CERTIFICATE-----\n'}


class SettingsTest(unittest.TestCase):
    def test_valid_settings_force_verify_full(self):
        settings = g.target_settings(dict(ENV, PGSSLMODE='disable', GCP_SYNC_TARGET_SSLMODE='disable'))
        self.assertEqual(settings['sslmode'], 'verify-full')

    def test_unsafe_settings_refused(self):
        cases = {'TARGET_HOST_MUST_BE_CERT_NAME': {'GCP_SYNC_TARGET_HOST': '192.0.2.10'},
                 'TARGET_HOSTADDR_REQUIRED': {'GCP_SYNC_TARGET_HOSTADDR': 'db.example'},
                 'TARGET_DB_MISMATCH': {'GCP_SYNC_TARGET_DB': 'redmine'},
                 'TARGET_USER_NOT_ALLOWED': {'GCP_SYNC_TARGET_USER': 'postgres'},
                 'TARGET_PASSWORD_MISSING': {'GCP_SYNC_TARGET_PASSWORD': ''},
                 'TARGET_CA_MISSING': {'GCP_SYNC_TARGET_SSLROOTCERT_PEM': ''}}
        for code, override in cases.items():
            with self.subTest(code=code), self.assertRaises(g.SyncError) as caught:
                g.target_settings(dict(ENV, **override))
            self.assertEqual(caught.exception.code, code)

    def test_connect_passes_verify_full_and_removes_temp_ca(self):
        seen = {}

        def fake_connect(**kwargs):
            seen.update(kwargs)
            seen['ca_existed'] = __import__('os').path.exists(kwargs['sslrootcert'])
            raise RuntimeError('SSL error: certificate verify failed for host 192.0.2.10 password=pw')

        with self.assertRaises(g.SyncError) as caught:
            g.connect_target(ENV, connect=fake_connect)
        self.assertEqual(caught.exception.code, 'TARGET_TLS_FAILED')
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn('pw', str(caught.exception))
        self.assertEqual((seen['sslmode'], seen['host'], seen['hostaddr']), ('verify-full', ENV['GCP_SYNC_TARGET_HOST'], '192.0.2.10'))
        self.assertTrue(seen['ca_existed'])
        self.assertFalse(__import__('os').path.exists(seen['sslrootcert']))

    def test_network_error_is_retryable(self):
        def fake_connect(**kwargs):
            raise RuntimeError('timeout expired')
        with self.assertRaises(g.SyncError) as caught:
            g.connect_target(ENV, connect=fake_connect)
        self.assertEqual((caught.exception.code, caught.exception.retryable), ('TARGET_CONNECT_FAILED', True))


class ScheduleTest(unittest.TestCase):
    def test_night_window_is_21_to_08_kst(self):
        kst = lambda h, m=0: datetime(2026, 11, 14, h, m, tzinfo=g.KST)
        self.assertTrue(g.in_night_window(kst(21)))
        self.assertTrue(g.in_night_window(kst(7, 59)))
        self.assertFalse(g.in_night_window(kst(8)))
        self.assertFalse(g.in_night_window(kst(8, 5)))
        self.assertFalse(g.in_night_window(kst(20, 59)))

    def test_scheduled_skips_inside_night_window_before_touching_db(self):
        result = g.run_sync(None, None, mode='scheduled', now=datetime(2026, 11, 14, 2, 0, tzinfo=g.KST))
        self.assertEqual((result['status'], result['reason']), ('SKIPPED', 'NIGHT_WINDOW_OPEN'))

    def test_scheduled_retries_connect_failures_at_most_three_times(self):
        calls, sleeps = [], []

        def failing_source():
            calls.append(1)
            raise g.SyncError('SOURCE_CONNECT_FAILED', retryable=True)

        result = g.execute('scheduled', {}, connect_src=failing_source, sleep=sleeps.append)
        self.assertEqual((len(calls), sleeps, result['attempts']), (3, [60, 120], 3))
        self.assertEqual(result['error_code'], 'SOURCE_CONNECT_FAILED')
        self.assertEqual(result['slack'], 'DISABLED')  # no webhook in this environment

    def test_tls_failure_and_manual_runs_are_not_retried(self):
        sleeps = []

        def tls_fail(environ):
            raise g.SyncError('TARGET_TLS_FAILED')

        scheduled = g.execute('scheduled', {}, connect_src=lambda: _Closable(), connect_tgt=tls_fail, sleep=sleeps.append)
        manual = g.execute('run', {}, connect_src=lambda: (_ for _ in ()).throw(
            g.SyncError('SOURCE_CONNECT_FAILED', retryable=True)), sleep=sleeps.append)
        self.assertEqual((scheduled['attempts'], manual['attempts'], sleeps), (1, 1, []))
        self.assertNotIn('slack', manual)


class _Closable:
    def close(self):
        pass


if __name__ == '__main__':
    unittest.main()
