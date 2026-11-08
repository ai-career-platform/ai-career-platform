"""Opt-in real runtime PostgreSQL + real child supervisor integration.

Caller prepares migrations 0002..0010 once on an isolated DB. Never targets
staging; DSN must resolve to loopback, training database, crawler_staging role.
"""
import json,os,sys,tempfile,time,unittest,uuid,signal,subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import urlsplit

from crawler.jobs.fixture_night_window import KST, NightSlotStore, NightSlotUnavailable, execute_night_fixture_once
from crawler.jobs.fixture_retry_budget import DurableFixtureAttemptStore
from crawler.jobs.fixture_night_executor import WORKER_LOCK, run_once
from crawler.jobs.keyword_management import KeywordStore
from crawler.jobs.fixture_payloads import FixturePayloadStore
from crawler.jobs.raw_artifact_store import RawArtifactStore,RawArtifactMetadata


def connect(**kw):
    import psycopg
    dsn=os.environ['CRAWLER_NIGHT_TEST_DSN'];p=urlsplit(dsn)
    assert p.hostname in ('127.0.0.1','localhost') and p.username=='crawler_staging' and p.path=='/ai_career_crawler_training'
    return psycopg.connect(dsn,autocommit=True,**kw)


def test_child(job,root,phase):
    import psycopg
    from crawler.jobs.fixture_night_executor import child_once
    class Paused(psycopg.Cursor):
        def execute(self,q,p=None,**kw):
            if 'INSERT INTO crawler_training.keyword_checkpoints' in str(q):
                # Actual atomic Worker already wrote postings, lineage and job state.
                state=self.connection.execute('SELECT status FROM crawler_training.keyword_jobs WHERE job_id=%s',(job,)).fetchone()[0]
                assert state=='COMPLETED'
                Path(root,'partial.json').write_text(json.dumps({'job_state_before_rollback':state}))
                self.connection.execute('SELECT pg_sleep(30)')
            return super().execute(q,p,**kw)
    if phase=='pause_ignore' and os.name!='nt':
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
    count=0
    def connector():
        nonlocal count
        count+=1
        return connect(cursor_factory=Paused if phase.startswith('pause') and count==3 else psycopg.Cursor)
    now=datetime.fromisoformat(os.environ['CRAWLER_NIGHT_TEST_NOW'])
    out=child_once(job,root,connector=connector,now=now)
    print(json.dumps({'event':'result',**out}),flush=True)


@unittest.skipUnless(os.environ.get('CRAWLER_NIGHT_PG_TEST')=='1','explicit isolated PostgreSQL opt-in')
class NightExecutorPG(unittest.TestCase):
    def setUp(self):
        self.c=connect();self.ks=KeywordStore(self.c);self.k=self.ks.add_keyword('night-'+uuid.uuid4().hex)
        # Retain synthetic evidence; no cleanup/deletion or sequence reset.
        self.root=Path(tempfile.mkdtemp(prefix='t154-night-',dir=os.environ.get('CRAWLER_NIGHT_TEST_ROOT')))
        self.files=RawArtifactStore(self.root)
        # Reused isolated DB retains past evidence; never collide with its slots.
        while True:
            self.now=datetime(2050,1,1,21,tzinfo=KST)+timedelta(days=uuid.uuid4().int%100000)
            self.day=self.now.date()
            if not self.c.execute('SELECT 1 FROM crawler_training.fixture_night_slots WHERE night_date=%s LIMIT 1',(self.day,)).fetchone():
                break
    def tearDown(self):
        self.c.close()
        proof=os.environ.get('CRAWLER_NIGHT_PROOF_PATH')
        if proof:
            with Path(proof).open('a',encoding='utf-8') as out:
                log=self.root/'summary.jsonl'
                out.write(json.dumps({'test':self.id(),'summary':json.loads(log.read_text()) if log.exists() else None,'isolated_artifact_directory':str(self.root)})+'\n')
    def prepare(self):
        job=self.ks.create_job(self.k,'night:'+uuid.uuid4().hex);ids=[str(uuid.uuid4().int%1000000000000000) for _ in range(2)]
        FixturePayloadStore(self.c).register(job_id=job,keyword_id=self.k,posting_ids=ids)
        for i in ids:
            url='https://www.jobkorea.co.kr/Recruit/GI_Read/'+i
            body=('<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Synthetic night '+i,'hiringOrganization':{'name':'Synthetic Fixture Company'},'identifier':{'value':i},'url':url})+'</script>').encode()
            RawArtifactMetadata(self.c).insert(receipt=self.files.save(kind='detail',source_url=url,body=body),keyword_id=self.k,job_id=job)
        return job,ids
    def slots(self):return self.c.execute('SELECT slot_index FROM crawler_training.fixture_night_slots WHERE night_date=%s',(self.day,)).fetchall()
    def counts(self,job,ids):
        return (self.c.execute('SELECT status FROM crawler_training.keyword_jobs WHERE job_id=%s',(job,)).fetchone()[0],
            self.c.execute("SELECT count(*) FROM crawler_training.postings WHERE external_posting_id=ANY(%s)",(ids,)).fetchone()[0],
            self.c.execute('SELECT count(*) FROM crawler_training.raw_parse_results r JOIN crawler_training.raw_artifacts a USING(artifact_id) WHERE a.job_id=%s',(job,)).fetchone()[0],
            self.c.execute('SELECT count(*) FROM crawler_training.keyword_checkpoints WHERE keyword_id=%s',(self.k,)).fetchone()[0])
    def bridge(self,job,slot):
        with connect() as s,connect() as a,connect() as w:
            return execute_night_fixture_once(slot_connection=s,attempt_connection=a,worker_connection=w,files=self.files,job_id=job,now=self.now+timedelta(minutes=30*slot))
    def test_child_success_log_and_db_cleanup(self):
        job,ids=self.prepare();os.environ['CRAWLER_NIGHT_TEST_NOW']=self.now.isoformat()
        cmd=[sys.executable,'-m',__name__,'--child',str(job),str(self.root),'success']
        out=run_once(job_id=job,raw_root=self.root,log_file=self.root/'summary.jsonl',now=self.now,connector=connect,command=cmd,maximum=5,grace=.2)
        self.assertEqual(out['status'],'COMPLETED');self.assertEqual(out['db_cleanup'],'PASS');self.assertFalse(out['state_mismatch'])
        self.assertEqual(self.counts(job,ids),('COMPLETED',2,2,1));self.assertEqual(DurableFixtureAttemptStore(self.c).read(job),(1,'COMPLETED',None))
        self.assertEqual(json.loads((self.root/'summary.jsonl').read_text())['processed_postings'],2)
        with self.assertRaises(NightSlotUnavailable):self.bridge(job,1)
        self.assertEqual(len(self.slots()),1)
    def test_actual_child_deadline_rolls_back_and_unlocks(self):
        job,ids=self.prepare()
        self.now=(self.now+timedelta(days=1)).replace(hour=7,minute=59,second=55,microsecond=0)
        os.environ['CRAWLER_NIGHT_TEST_NOW']=self.now.isoformat()
        cmd=[sys.executable,'-m',__name__,'--child',str(job),str(self.root),'pause_ignore' if os.name!='nt' else 'pause']
        out=run_once(job_id=job,raw_root=self.root,log_file=self.root/'summary.jsonl',now=self.now,connector=connect,command=cmd,maximum=120,grace=.2,cleanup_budget=1)
        self.assertTrue((self.root/'partial.json').exists(),'Worker must reach actual completed transaction before kill')
        self.assertEqual(out['status'],'INTERRUPTED');self.assertEqual(out['db_cleanup'],'PASS');self.assertTrue(out['cleanup_before_deadline'])
        if os.name!='nt':self.assertEqual(out['termination_reason'],'KILL')
        self.assertEqual(self.counts(job,ids),('PENDING',0,0,0));self.assertEqual(DurableFixtureAttemptStore(self.c).read(job),(1,'IN_PROGRESS',None));self.assertTrue(out['requires_manual_review'])
        self.assertEqual(len(self.slots()),1)
        with connect() as c:
            self.assertTrue(c.execute('SELECT pg_try_advisory_lock(%s)',(WORKER_LOCK,)).fetchone()[0])
            c.execute('SELECT job_id FROM crawler_training.keyword_jobs WHERE job_id=%s FOR UPDATE NOWAIT',(job,))
        self.now=datetime.combine(self.day,datetime.min.time(),KST).replace(hour=21)
        before=len(self.slots())
        with self.assertRaises(NightSlotUnavailable):self.bridge(job,1)
        self.assertEqual(len(self.slots()),before)
    @unittest.skipIf(os.name=='nt','POSIX supervisor SIGTERM test')
    def test_supervisor_sigterm_cleans_actual_worker(self):
        job,ids=self.prepare();os.environ['CRAWLER_NIGHT_TEST_NOW']=self.now.isoformat()
        command=[sys.executable,'-m','crawler.tests.local_t154_night_executor','--supervisor',str(job),str(self.root)]
        parent=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            until=time.monotonic()+8
            while not (self.root/'partial.json').exists() and time.monotonic()<until:time.sleep(.05)
            self.assertTrue((self.root/'partial.json').exists())
            interrupted_at=time.monotonic()
            parent.send_signal(signal.SIGTERM);self.assertEqual(parent.wait(timeout=5),0)
            self.assertLess(time.monotonic()-interrupted_at,3)
        finally:
            if parent.poll() is None:parent.kill();parent.wait()
        out=json.loads((self.root/'summary.jsonl').read_text())
        self.assertEqual(out['error_code'],'SUPERVISOR_INTERRUPTED');self.assertEqual(out['db_cleanup'],'PASS')
        self.assertEqual(self.counts(job,ids),('PENDING',0,0,0))
        self.assertEqual(DurableFixtureAttemptStore(self.c).read(job),(1,'IN_PROGRESS',None))
        with connect() as c:self.assertTrue(c.execute('SELECT pg_try_advisory_lock(%s)',(WORKER_LOCK,)).fetchone()[0])

    def test_three_attempts_no_fourth_slot_consumed(self):
        job,ids=self.prepare()
        for i in range(3):
            with connect() as c:claim=NightSlotStore(c).reserve_execution(job_id=job,now=self.now+timedelta(minutes=30*i))
            self.assertEqual(claim[1].attempt,i+1)
            self.assertTrue(DurableFixtureAttemptStore(self.c).record_failure(job_id=job,attempt=i+1,error_code='WORKER_TIMEOUT'))
        self.assertEqual(DurableFixtureAttemptStore(self.c).read(job),(3,'STOPPED','WORKER_TIMEOUT'))
        with self.assertRaises(NightSlotUnavailable):self.bridge(job,3)
        self.assertEqual(len(self.slots()),3)
    def test_blocked_errors_no_next_slot(self):
        for i,code in enumerate(['ACCESS_FORBIDDEN','RATE_LIMITED']):
            job,_=self.prepare()
            with connect() as c:NightSlotStore(c).reserve_execution(job_id=job,now=self.now+timedelta(minutes=30*i))
            DurableFixtureAttemptStore(self.c).record_failure(job_id=job,attempt=1,error_code=code)
            with self.assertRaises(NightSlotUnavailable):self.bridge(job,i+2)
        self.assertEqual(len(self.slots()),2)
    def test_global_worker_session_lock_blocks_other_job_before_slot(self):
        job,_=self.prepare();os.environ['CRAWLER_NIGHT_TEST_NOW']=self.now.isoformat()
        with connect() as lock:
            self.assertTrue(lock.execute('SELECT pg_try_advisory_lock(%s)',(WORKER_LOCK,)).fetchone()[0])
            cmd=[sys.executable,'-m',__name__,'--child',str(job),str(self.root),'success']
            out=run_once(job_id=job,raw_root=self.root,log_file=self.root/'summary.jsonl',now=self.now,connector=connect,command=cmd,maximum=5,grace=.2)
            self.assertEqual(out['error_code'],'WORKER_BUSY');self.assertEqual(len(self.slots()),0)
    def test_concurrent_atomic_slot_attempt_and_commit(self):
        job,_=self.prepare()
        def reserve():
            import psycopg
            with connect() as c:
                try:return NightSlotStore(c).reserve_execution(job_id=job,now=self.now)
                except psycopg.errors.LockNotAvailable:return None
        with ThreadPoolExecutor(max_workers=5) as p:results=list(p.map(lambda _:reserve(),range(5)))
        self.assertEqual(sum(r is not None for r in results),1);self.assertEqual(len(self.slots()),1)
        with connect() as observer:self.assertEqual(DurableFixtureAttemptStore(observer).read(job),(1,'IN_PROGRESS',None))
    def test_22_slots_db_bound_and_0800(self):
        import psycopg
        for i in range(22):
            job,_=self.prepare()
            with connect() as c:self.assertIsNotNone(NightSlotStore(c).reserve_execution(job_id=job,now=self.now+timedelta(minutes=30*i)))
        self.assertEqual(len(self.slots()),22)
        with self.assertRaises(psycopg.errors.CheckViolation):self.c.execute('INSERT INTO crawler_training.fixture_night_slots(night_date,slot_index,job_id) VALUES(%s,22,%s)',(self.day,job))
        with self.assertRaises(NightSlotUnavailable):self.bridge(job,22)


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--child':test_child(*sys.argv[2:])
    elif len(sys.argv)>1 and sys.argv[1]=='--supervisor':
        job,root=sys.argv[2:]
        cmd=[sys.executable,'-m','crawler.tests.local_t154_night_executor','--child',job,root,'pause_ignore']
        run_once(job_id=job,raw_root=root,log_file=Path(root)/'summary.jsonl',
                 now=datetime.fromisoformat(os.environ['CRAWLER_NIGHT_TEST_NOW']),
                 connector=connect,command=cmd,maximum=120,grace=.2,cleanup_budget=1)
    else:unittest.main(verbosity=2)
