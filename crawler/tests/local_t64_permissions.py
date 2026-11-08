"""CI-only staging runtime role permissions; mocked DNS, real PostgreSQL."""
import os
import unittest
from datetime import datetime,timedelta,timezone,time
from unittest.mock import patch
from crawler.storage.staging import connect_configured_database
from crawler.jobs.scheduler import SchedulerStore


class RuntimePermissions(unittest.TestCase):
    def test_claim_heartbeat_finish_events_as_nonowner(self):
        if os.environ.get('CRAWLER_STAGING_PG_TEST')!='1':
            self.skipTest('Explicit isolated staging role opt-in required')
        values={'CRAWLER_DB_MODE':'staging','CRAWLER_STAGING_DATABASE_URL':'postgresql://crawler_staging@db:5432/ai_career_crawler_training'}
        with patch.dict('os.environ',values),patch('socket.gethostbyname',return_value='127.0.0.1'):
            with connect_configured_database() as connection:
                store=SchedulerStore(connection)
                original=store.schedule()
                self.assertFalse(original['enabled'])
                now=datetime.now(timezone.utc)
                try:
                    # This rollback isolates the role test from all other runs.
                    with connection.transaction():
                        store.configure(enabled=True,local_time=time(3),now=now)
                        connection.execute('UPDATE crawler_training.schedules SET next_run_at=%s',(now-timedelta(seconds=1),))
                        run_id=store.claim(now)
                        self.assertIsNotNone(run_id)
                        store.heartbeat(run_id)
                        self.assertTrue(store.finish(run_id,'SUCCEEDED',metrics={'fetched':0,'inserted':0,'updated':0,'unchanged':0,'invalid':0},now=now+timedelta(seconds=1)))
                        self.assertEqual(store.read('run',run_id)[0]['status'],'SUCCEEDED')
                        self.assertGreaterEqual(len(store.read('events',run_id)),2)
                        raise _Rollback()
                except _Rollback:pass
                self.assertFalse(store.schedule()['enabled'])


class _Rollback(Exception):pass
