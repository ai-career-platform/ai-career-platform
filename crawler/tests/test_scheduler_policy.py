import unittest
from datetime import datetime,time,timezone
from crawler.jobs.scheduler import next_daily, eligible, retry_at
from crawler.jobs.scheduled_worker import failure_code
from unittest.mock import patch
import io
from contextlib import redirect_stdout


class SchedulerPolicyTests(unittest.TestCase):
    def test_db_failure_is_nonzero_and_sanitized(self):
        from crawler.jobs.dispatcher import main
        output=io.StringIO()
        with patch('sys.argv',['dispatcher','dispatch']),patch('crawler.jobs.dispatcher.connect_configured_database',side_effect=RuntimeError('private-password')):
            with redirect_stdout(output):self.assertEqual(main(),2)
        self.assertNotIn('private-password',output.getvalue())
        self.assertIn('DISPATCHER_UNAVAILABLE',output.getvalue())

    def test_kst_next_daily_boundary(self):
        now=datetime(2026,11,8,17,59,tzinfo=timezone.utc)
        self.assertEqual(next_daily(now,time(3)),datetime(2026,11,8,18,tzinfo=timezone.utc))
        self.assertEqual(next_daily(datetime(2026,11,8,18,tzinfo=timezone.utc),time(3)),datetime(2026,11,9,18,tzinfo=timezone.utc))

    def test_disabled_and_unapproved_live_are_blocked(self):
        now=datetime.now(timezone.utc)
        self.assertFalse(eligible({'enabled':False,'mode':'fixture'},now)[0])
        self.assertFalse(eligible({'enabled':True,'mode':'live','approval':None,'target_urls':[]},now)[0])
        self.assertTrue(eligible({'enabled':True,'mode':'fixture'},now)[0])

    def test_retries_are_bounded_and_stop_on_blocks(self):
        now=datetime.now(timezone.utc)
        self.assertIsNotNone(retry_at('WORKER_TIMEOUT',1,now))
        self.assertGreater(retry_at('TEMPORARY_IO',2,now),retry_at('TEMPORARY_IO',1,now))
        for code in ('ACCESS_FORBIDDEN','RATE_LIMITED','INVALID_CONTRACT','UNAPPROVED_SOURCE'):
            self.assertIsNone(retry_at(code,1,now))
        self.assertIsNone(retry_at('WORKER_TIMEOUT',3,now))

    def test_http_failures_map_to_safe_retry_or_stop_codes(self):
        for code,expected in ((403,'ACCESS_FORBIDDEN'),(429,'RATE_LIMITED'),(500,'TEMPORARY_IO')):
            self.assertEqual(failure_code({'stopped':{'http_status':code}}),expected)
        self.assertEqual(failure_code({'errors':[{'reason':'TIMEOUT'}]}),'WORKER_TIMEOUT')
        self.assertEqual(failure_code({'errors':[{'reason':'NETWORK_ERROR'}]}),'TEMPORARY_IO')
        self.assertEqual(failure_code({'errors':[{'reason':'HtmlPostingError'}]}),'INVALID_CONTRACT')

    def test_existing_t61_gate_checks_expiry_and_exact_scope(self):
        now=datetime(2026,11,8,tzinfo=timezone.utc)
        url='https://www.jobkorea.co.kr/Recruit/GI_Read/123'
        # Fabricated policy for an offline unit test, never persisted or used live.
        approval={'source_code':'jobkorea','approval_status':'APPROVED','enabled':True,
            'approved_by':'test-only','evidence_ref':'test-only','valid_from_utc':'2026-11-07T00:00:00Z',
            'review_due_utc':'2026-11-09T00:00:00Z','collection_method':'WEB','allowed_urls':[url],
            'allowed_purposes':['scheduled_collection'],'max_requests':2,'retention_days':0,'stop_on_block':True}
        s={'enabled':True,'mode':'live','target_urls':[url],'approval':approval}
        with patch.dict('os.environ',{'CRAWLER_LIVE_SCHEDULE_APPROVED':'1'}):
            self.assertTrue(eligible(s,now)[0])
            self.assertFalse(eligible(s,datetime(2026,11,10,tzinfo=timezone.utc))[0])
            self.assertFalse(eligible({**s,'target_urls':[url+'4']},now)[0])
