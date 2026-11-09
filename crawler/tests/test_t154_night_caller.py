import json,tempfile,unittest,os,subprocess,sys,time
from pathlib import Path
from datetime import date,datetime
from crawler.jobs.fixture_night_caller import load_input,allowed_slot,synthetic_ids
from crawler.jobs.fixture_night_window import KST
class CallerContracts(unittest.TestCase):
 def test_absolute_night_and_0800(self):
  d=date(2026,11,8)
  self.assertEqual(allowed_slot(d,datetime(2026,11,9,1,tzinfo=KST)).slot_index,8)
  self.assertIsNone(allowed_slot(d,datetime(2026,11,9,8,tzinfo=KST)))
  self.assertIsNone(allowed_slot(d,datetime(2026,11,9,21,tzinfo=KST)))
 def test_input_absent_empty_and_live_denied(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'input.json';self.assertEqual(load_input(p),[])
   p.write_text(json.dumps({'mode':'synthetic_fixture_only','items':[]}));self.assertEqual(load_input(p),[])
   p.write_text(json.dumps({'mode':'live_jobkorea','items':[]}))
   with self.assertRaises(ValueError):load_input(p)
 def test_ids_repeat_and_slots_separate(self):
  self.assertEqual(synthetic_ids('2026-11-08',8,2),synthetic_ids('2026-11-08',8,2))
  self.assertTrue(set(synthetic_ids('2026-11-08',8,2)).isdisjoint(synthetic_ids('2026-11-08',9,2)))
 def test_timer_is_finite_disabled_default(self):
  r=Path(__file__).resolve().parents[2]/'poc/staging/crawler';t=(r/'ai-career-t154-night-20261108.timer').read_text()
  self.assertIn('Persistent=false',t);self.assertIn('RemainAfterElapse=false',t)
  self.assertIn('2026-11-08',t);self.assertIn('2026-11-09',t);self.assertNotIn('OnBootSec',t)

 @unittest.skipIf(os.name=='nt','POSIX wrapper')
 def test_archive_lookup_failure_halts_next_call(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);bin=root/'bin';bin.mkdir();docker=bin/'docker'
   docker.write_text('#!/bin/sh\ncase "$*" in *" exec "*) echo \'{"status":"COMPLETED"}\';; *) exit 1;; esac\n');docker.chmod(0o700)
   original=Path(__file__).resolve().parents[2]/'poc/staging/crawler/t154-night-once-20261108.sh'
   script=root/'run.sh';script.write_text(original.read_text().replace('/home/kant/ai-career-staging-poc',tmp))
   env={**os.environ,'PATH':str(bin)+':'+os.environ['PATH']}
   first=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
   self.assertNotEqual(first.returncode,0);self.assertTrue((root/'outputs/t154-night-20261108/HALT').exists())
   second=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
   self.assertEqual(second.returncode,0);self.assertIn('HALT_REQUIRES_REVIEW',second.stdout)
 @unittest.skipIf(os.name=='nt','POSIX process groups')
 def test_launcher_exit_reaps_term_ignoring_descendant(self):
  from crawler.jobs.fixture_night_executor import supervise
  code="import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print(p.pid,flush=True)"
  r=supervise([sys.executable,'-c',code],deadline=time.monotonic()+3,grace=.2,process_group=True)
  pid=int(r.stdout.strip());until=time.monotonic()+2
  def alive():
   try:return Path('/proc/'+str(pid)+'/stat').read_text().split()[2]!='Z'
   except FileNotFoundError:return False
  while alive() and time.monotonic()<until:time.sleep(.02)
  self.assertFalse(alive())
