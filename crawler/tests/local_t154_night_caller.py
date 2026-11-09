"""Opt-in isolated PostgreSQL caller/supply integration; no staging connection."""
import json,os,sys,tempfile,unittest,uuid
from datetime import datetime,timedelta
from pathlib import Path
from crawler.tests.local_t154_night_executor import connect
from crawler.jobs.fixture_night_caller import call_once,guarded_once,CALLER_LOCK
from crawler.jobs.fixture_night_window import KST
from crawler.jobs.fixture_night_executor import run_once
from crawler.jobs.fixture_retry_budget import DurableFixtureAttemptStore

@unittest.skipUnless(os.environ.get('CRAWLER_NIGHT_PG_TEST')=='1','isolated PG opt-in')
class CallerPG(unittest.TestCase):
 def setUp(self):
  self.c=connect();self.root=Path(tempfile.mkdtemp(prefix='t154-caller-',dir=os.environ.get('CRAWLER_NIGHT_TEST_ROOT')))
  while True:
   self.now=datetime(2050,1,1,21,tzinfo=KST)+timedelta(days=uuid.uuid4().int%100000)
   self.day=self.now.date()
   if not self.c.execute('SELECT 1 FROM crawler_training.fixture_night_slots WHERE night_date=%s',(self.day,)).fetchone() and not self.c.execute('SELECT 1 FROM crawler_training.search_keywords WHERE keyword=%s',('synthetic-night-'+str(self.day),)).fetchone():break
  self.input=self.root/'input.json';self.input.write_text(json.dumps({'mode':'synthetic_fixture_only','items':[{'title':'Synthetic Fixture Caller','company':'Synthetic Fixture Company'}]}))
 def tearDown(self):self.c.close()
 def execute(self,phase='success'):
  def executor(**kw):
   os.environ['CRAWLER_NIGHT_TEST_NOW']=kw['now'].isoformat()
   cmd=[sys.executable,'-m','crawler.tests.local_t154_night_executor','--child',str(kw['job_id']),str(kw['raw_root']),phase]
   return run_once(**kw,connector=connect,command=cmd,maximum=3,grace=.2,cleanup_budget=.7)
  return executor
 def invoke(self,phase='success',**kw):
  return call_once(night_date=self.day,input_file=self.input,raw_root=self.root/'raw',log_file=self.root/'caller.jsonl',connector=connect,clock=lambda:self.now,executor=self.execute(phase),**kw)
 def test_supply_success_duplicate_and_completed_idle(self):
  r=self.invoke();self.assertEqual(r['status'],'COMPLETED');job=r['job_id'];self.assertEqual(r['processed_postings'],1)
  dup=self.invoke();self.assertEqual((dup['status'],dup['reason']),('IDLE','SLOT_ALREADY_USED'))
  self.now+=timedelta(minutes=30);self.input.write_text('{"mode":"synthetic_fixture_only","items":[]}')
  idle=self.invoke();self.assertEqual((idle['status'],idle['reason']),('IDLE','NO_INPUT'))
  self.assertEqual(self.c.execute('SELECT attempt_count FROM crawler_training.fixture_job_attempts WHERE job_id=%s',(job,)).fetchone()[0],1)
 def test_empty_input_idle_no_keyword(self):
  self.input.write_text('{"mode":"synthetic_fixture_only","items":[]}');r=self.invoke();self.assertEqual(r['reason'],'NO_INPUT')
  self.assertFalse(self.c.execute('SELECT 1 FROM crawler_training.search_keywords WHERE keyword=%s',('synthetic-night-'+str(self.day),)).fetchone())
 def test_inprogress_blocks_fresh_supply_and_corrupt_raw_is_unresolved(self):
  failed=self.invoke('pause');self.assertEqual(failed['status'],'INTERRUPTED');job=failed['job_id']
  self.now+=timedelta(minutes=30);self.assertEqual(self.invoke()['reason'],'NIGHT_REQUIRES_REVIEW')
  self.assertTrue(DurableFixtureAttemptStore(self.c).record_failure(job_id=job,attempt=1,error_code='WORKER_TIMEOUT'))
  key=self.c.execute("SELECT storage_key FROM crawler_training.raw_artifacts WHERE job_id=%s AND kind='detail'",(job,)).fetchone()[0]
  (self.root/'raw'/key).write_bytes(b'corrupted synthetic test bytes')
  bad=self.invoke();self.assertEqual(bad['status'],'UNRESOLVED');self.assertTrue(bad['requires_manual_review'])
  self.assertEqual(self.c.execute('SELECT count(*) FROM crawler_training.fixture_night_slots WHERE night_date=%s',(self.day,)).fetchone()[0],1)
 def test_retry_same_job_then_max3_stop_no_new_slot(self):
  first=self.invoke('pause');job=first['job_id'];budget=DurableFixtureAttemptStore(self.c)
  self.assertTrue(budget.record_failure(job_id=job,attempt=1,error_code='WORKER_TIMEOUT'))
  self.now+=timedelta(minutes=30);second=self.invoke();self.assertEqual(second['job_id'],job);self.assertEqual(second['attempt_count'],2);self.assertEqual(second['status'],'COMPLETED')
 def test_three_limit_no_bypass_new_job(self):
  first=self.invoke('pause');job=first['job_id'];budget=DurableFixtureAttemptStore(self.c)
  budget.record_failure(job_id=job,attempt=1,error_code='WORKER_TIMEOUT')
  for n in [2,3]:
   self.assertEqual(budget.reserve(job).attempt,n);budget.record_failure(job_id=job,attempt=n,error_code='WORKER_TIMEOUT')
  self.now+=timedelta(minutes=30);self.assertEqual(self.invoke()['reason'],'NIGHT_REQUIRES_REVIEW');self.assertEqual(budget.read(job),(3,'STOPPED','WORKER_TIMEOUT'))
 def test_0800_no_database(self):
  self.now=(self.now+timedelta(days=1)).replace(hour=8)
  def denied():raise AssertionError('DB must not be opened')
  r=call_once(night_date=self.day,input_file=self.input,raw_root=self.root/'raw',log_file=self.root/'caller.jsonl',connector=denied,clock=lambda:self.now)
  self.assertEqual(r['status'],'IDLE')
 def test_whole_caller_happy_nested_worker(self):
  cmd=[sys.executable,'-m',__name__,'--call-child',str(self.day),str(self.root),self.now.isoformat()]
  r=guarded_once(night_date=self.day,input_file=self.input,raw_root=self.root/'raw',log_file=self.root/'caller.jsonl',connector=connect,now=self.now,command=cmd,maximum=10,cleanup_budget=1,grace=.2)
  self.assertEqual(r['status'],'COMPLETED');self.assertEqual(r['whole_caller_cleanup'],'PASS')
  self.assertEqual(DurableFixtureAttemptStore(self.c).read(r['job_id']),(1,'COMPLETED',None))
 def test_whole_caller_kills_real_preparation_and_cleans_db(self):
  name='guard-preparation-'+uuid.uuid4().hex
  cmd=[sys.executable,'-m',__name__,'--prep-child',name,str(self.root/'ready')]
  r=guarded_once(night_date=self.day,input_file=self.input,raw_root=self.root/'raw',log_file=self.root/'guard.jsonl',connector=connect,now=self.now,command=cmd,maximum=3,cleanup_budget=.8,grace=.2)
  self.assertTrue((self.root/'ready').exists());self.assertEqual(r['status'],'UNRESOLVED');self.assertEqual(r['whole_caller_cleanup'],'PASS')
  self.assertFalse(self.c.execute('SELECT 1 FROM crawler_training.search_keywords WHERE keyword=%s',(name,)).fetchone())
  self.assertTrue(self.c.execute('SELECT pg_try_advisory_lock(%s)',(154250099,)).fetchone()[0])

if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='--call-child':
  day,folder,instant=sys.argv[2:];now=datetime.fromisoformat(instant);folder=Path(folder)
  def marked():
   c=connect();c.execute("SELECT set_config('application_name',%s,false)",('t154-caller:'+os.environ['T154_GUARD_TOKEN'],));return c
  def execute(**kw):
   os.environ['CRAWLER_NIGHT_TEST_NOW']=now.isoformat()
   cmd=[sys.executable,'-m','crawler.tests.local_t154_night_executor','--child',str(kw['job_id']),str(kw['raw_root']),'success']
   return run_once(**kw,connector=marked,command=cmd,maximum=5,cleanup_budget=1,grace=.2)
  r=call_once(night_date=now.date(),input_file=folder/'input.json',raw_root=folder/'raw',log_file=folder/'caller.jsonl',connector=marked,clock=lambda:now,executor=execute)
  print(json.dumps(r),flush=True)
 elif len(sys.argv)>1 and sys.argv[1]=='--prep-child':
  from crawler.jobs.keyword_management import KeywordStore
  with connect() as c:
   c.execute("SELECT set_config('application_name',%s,false)",('t154-caller:'+os.environ['T154_GUARD_TOKEN'],))
   with c.transaction():
    KeywordStore(c).add_keyword(sys.argv[2]);c.execute('SELECT pg_advisory_xact_lock(%s)',(154250099,));Path(sys.argv[3]).write_text('actual uncommitted preparation');c.execute('SELECT pg_sleep(30)')
 else:unittest.main(verbosity=2)
