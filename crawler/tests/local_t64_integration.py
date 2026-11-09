"""Opt-in isolated PostgreSQL tests; never use an active scheduler DB."""
import os
import sys
import subprocess
import time as clock
import unittest
from datetime import datetime,timedelta,timezone,time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from crawler.storage.staging import connect_configured_database
from crawler.jobs.scheduler import SchedulerStore
from crawler.jobs.dispatcher import dispatch
from crawler.jobs.scheduled_worker import execute


class DurableSchedulerTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('CRAWLER_T64_ISOLATED_TEST')!='1':
            self.skipTest('Isolated database opt-in required')
        self.connection=connect_configured_database()
        self.store=SchedulerStore(self.connection)
        self.original=self.store.schedule()
        self.assertIsNotNone(self.original)
        self.assertFalse(self.original['enabled'],'Refuse tests against an enabled scheduler')
        self.ids=[]
        self.now=datetime.now(timezone.utc)
        self.store.configure(enabled=True,local_time=time(3),mode='fixture',now=self.now)
        self.connection.execute("UPDATE crawler_training.schedules SET next_run_at=%s",(self.now-timedelta(seconds=1),))

    def tearDown(self):
        if not hasattr(self,'connection'):return
        for run_id in self.ids:
            self.connection.execute('DELETE FROM crawler_training.run_events WHERE run_id=%s',(run_id,))
            self.connection.execute('DELETE FROM crawler_training.runs WHERE run_id=%s',(run_id,))
        # Restore configuration, not arbitrary existing runs/postings.
        original=self.original
        self.connection.execute('''UPDATE crawler_training.schedules SET enabled=%s,local_time=%s,mode=%s,
            next_run_at=%s,last_run_at=%s,updated_at=%s WHERE schedule_id=%s''',
            (original['enabled'],original['local_time'],original['mode'],original['next_run_at'],original['last_run_at'],original['updated_at'],original['schedule_id']))
        self.connection.close()

    def claim(self,now=None):
        run_id=self.store.claim(now or self.now)
        if run_id:self.ids.append(run_id)
        return run_id

    def test_disabled_and_unapproved_make_no_process_or_http_calls(self):
        self.connection.execute('UPDATE crawler_training.schedules SET enabled=false')
        with patch('subprocess.Popen') as spawn,patch('crawler.jobs.import_jobkorea_html._get') as get:
            self.assertEqual(dispatch(self.store)['status'],'IDLE')
        spawn.assert_not_called();get.assert_not_called()
        self.connection.execute("UPDATE crawler_training.schedules SET enabled=true,mode='live',approval=NULL")
        self.assertIsNone(self.claim())

    def test_concurrent_claim_is_single_owner(self):
        def claim():
            with connect_configured_database() as connection:
                return SchedulerStore(connection).claim(self.now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:claim(),range(2)))
        self.ids.extend(r for r in results if r)
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertIsNone(self.claim())

    def test_real_fixture_worker_success_events_and_idempotence(self):
        for _ in range(2):
            result=dispatch(self.store)
            self.ids.append(result['run_id'])
            self.assertEqual(result['status'],'SUCCEEDED')
            row=self.store.read('run',result['run_id'])[0]
            self.assertEqual(row['fetched_count'],2)
            self.assertGreaterEqual(len(self.store.read('events',result['run_id'])),3)
            self.connection.execute('UPDATE crawler_training.schedules SET next_run_at=now()-interval \'1 second\'')
        self.assertEqual(row['inserted_count'],0)
        self.assertEqual(row['duplicate_count'],2)

    def test_worker_crash_records_failure_without_retry(self):
        result=dispatch(self.store,worker_command=[sys.executable,'-c','raise SystemExit(7)'])
        self.ids.append(result['run_id'])
        row=self.store.read('run',result['run_id'])[0]
        self.assertEqual(row['error_code'],'WORKER_CRASH')
        self.assertIsNone(row['retry_at'])

    def test_timeout_kills_worker_and_bounds_retry(self):
        result=dispatch(self.store,timeout=0.2,heartbeat_seconds=0.05,worker_command=[sys.executable,'-c','import time;time.sleep(30)'])
        self.ids.append(result['run_id'])
        row=self.store.read('run',result['run_id'])[0]
        self.assertEqual(row['error_code'],'WORKER_TIMEOUT')
        self.assertIsNotNone(row['retry_at'])
        self.assertIsNone(self.claim(self.now))
        second=self.claim(row['retry_at']+timedelta(seconds=1))
        self.assertIsNotNone(second)
        self.assertEqual(self.store.read('run',second)[0]['attempt'],2)

    def test_stale_heartbeat_requires_worker_lock_to_be_released(self):
        run_id=self.claim()
        self.connection.execute("UPDATE crawler_training.runs SET heartbeat_at=%s WHERE run_id=%s",(self.now-timedelta(minutes=6),run_id))
        with connect_configured_database() as other:
            worker=SchedulerStore(other);self.assertTrue(worker.lock(1))
            self.assertEqual(self.store.recover(self.now),0)
            worker.unlock(1)
        self.assertEqual(self.store.recover(self.now),1)
        row=self.store.read('run',run_id)[0]
        self.assertEqual(row['error_code'],'HEARTBEAT_TIMEOUT')

    def test_dispatcher_lock_excludes_second_process(self):
        self.assertTrue(self.store.lock(0))
        try:
            with connect_configured_database() as connection:
                self.assertEqual(dispatch(SchedulerStore(connection))['status'],'LOCKED')
        finally:self.store.unlock(0)

    def test_duplicate_worker_cannot_fail_the_real_owner(self):
        run_id=self.claim()
        with connect_configured_database() as connection:
            owner=SchedulerStore(connection);self.assertTrue(owner.lock(1))
            try:
                self.assertEqual(execute(run_id),1)
                self.assertEqual(self.store.read('run',run_id)[0]['status'],'RUNNING')
            finally:owner.unlock(1)

    def test_killed_real_worker_releases_source_and_recovers(self):
        run_id=self.claim()
        script="import sys,time;from crawler.jobs import scheduled_worker as w;w.run=lambda **kw:time.sleep(30);sys.exit(w.execute(sys.argv[1]))"
        process=subprocess.Popen([sys.executable,'-c',script,run_id],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=clock.monotonic()+5
            while True:
                acquired=self.store.lock(1)
                if not acquired:break
                self.store.unlock(1)
                if clock.monotonic()>deadline:self.fail('Worker did not acquire source lock')
                clock.sleep(0.05)
            process.kill();process.wait(timeout=5)
            self.connection.execute('UPDATE crawler_training.runs SET heartbeat_at=%s WHERE run_id=%s',(self.now-timedelta(minutes=6),run_id))
            # PostgreSQL notices the terminated client's TCP close asynchronously.
            deadline=clock.monotonic()+5
            recovered=self.store.recover(self.now)
            while not recovered and clock.monotonic()<deadline:
                clock.sleep(0.05);recovered=self.store.recover(self.now)
            self.assertEqual(recovered,1)
            self.assertEqual(self.store.read('run',run_id)[0]['error_code'],'HEARTBEAT_TIMEOUT')
        finally:
            if process.poll() is None:process.kill();process.wait(timeout=5)
