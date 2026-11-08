"""CI-only disposable container proof: losing docker-exec client is not a kill guard."""
import json,os,subprocess,time,unittest,uuid,tempfile
from pathlib import Path
from crawler.tests.local_t154_night_executor import connect

@unittest.skipUnless(os.environ.get('CRAWLER_NIGHT_CONTAINER_TEST')=='1','explicit disposable CI container opt-in')
class HostInvocation(unittest.TestCase):
 def test_killed_host_exec_still_has_bounded_preparation(self):
  name='t154-caller-proof-'+uuid.uuid4().hex[:10];keyword='host-prep-'+uuid.uuid4().hex
  dsn=os.environ['CRAWLER_NIGHT_TEST_DSN'];token=uuid.uuid4().hex[:16]
  subprocess.run(['docker','run','-d','--rm','--network','host','--name',name,'--entrypoint','python','-e','CRAWLER_LOCAL_DATABASE_URL='+dsn,'crawler-staging-test','-c','import time;time.sleep(60)'],capture_output=True,check=True)
  child="""import os,pathlib
from crawler.storage.staging import connect_configured_database
from crawler.jobs.keyword_management import KeywordStore
with connect_configured_database() as c:
 c.autocommit=True
 c.execute("SELECT set_config('application_name',%s,false)",('t154-caller:'+os.environ['T154_GUARD_TOKEN'],))
 with c.transaction():
  KeywordStore(c).add_keyword(KEYWORD)
  pathlib.Path('/tmp/ready').write_text('uncommitted preparation')
  c.execute('SELECT pg_sleep(30)')
""".replace('KEYWORD',repr(keyword))
  outer="""import sys
from datetime import datetime
from pathlib import Path
from crawler.jobs.fixture_night_window import KST
from crawler.jobs.fixture_night_caller import guarded_once
r=guarded_once(night_date=datetime(2050,1,1).date(),input_file='/tmp/no-input',raw_root='/tmp/raw',log_file='/tmp/caller.jsonl',now=datetime(2050,1,1,21,tzinfo=KST),command=[sys.executable,'-c',CHILD],maximum=4,cleanup_budget=1,grace=.2,invocation_id=TOKEN)
""".replace('CHILD',repr(child)).replace('TOKEN',repr(token))
  host=None
  try:
   host=subprocess.Popen(['docker','exec',name,'python','-c',outer],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   ready=False
   for _ in range(60):
    if subprocess.run(['docker','exec',name,'test','-f','/tmp/ready'],capture_output=True).returncode==0:ready=True;break
    time.sleep(.05)
   self.assertTrue(ready)
   host.terminate();host.wait(timeout=5)
   # Host finalizer uses the same known cancel/done identity before archival.
   subprocess.run(['docker','exec',name,'touch','/tmp/invocations/'+token+'.cancel'],capture_output=True,check=True)
   result=None
   for _ in range(100):
    p=subprocess.run(['docker','exec',name,'cat','/tmp/guard.jsonl'],capture_output=True,text=True)
    if p.returncode==0 and p.stdout.strip():result=json.loads(p.stdout.strip().splitlines()[-1]);break
    time.sleep(.05)
   self.assertIsNotNone(result);self.assertEqual(result['status'],'UNRESOLVED');self.assertEqual(result['whole_caller_cleanup'],'PASS')
   subprocess.run(['docker','exec',name,'test','-f','/tmp/invocations/'+token+'.done.json'],capture_output=True,check=True)
   with tempfile.TemporaryDirectory() as directory:
    destination=Path(directory)/'final.jsonl'
    subprocess.run(['docker','cp',name+':/tmp/guard.jsonl',str(destination)],capture_output=True,check=True)
    self.assertEqual(json.loads(destination.read_text().splitlines()[-1])['whole_caller_cleanup'],'PASS')
   with connect() as c:
    self.assertFalse(c.execute('SELECT 1 FROM crawler_training.search_keywords WHERE keyword=%s',(keyword,)).fetchone())
    self.assertEqual(c.execute("SELECT count(*) FROM pg_stat_activity WHERE usename=current_user AND application_name=%s",('t154-caller:'+result['guard_token'],)).fetchone()[0],0)
  finally:
   if host and host.poll() is None:host.kill();host.wait()
   subprocess.run(['docker','stop','--time','2',name],capture_output=True)

if __name__=='__main__':unittest.main(verbosity=2)
