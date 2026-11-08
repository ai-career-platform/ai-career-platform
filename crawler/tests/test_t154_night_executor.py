"""Real child-process deadlines; no DB, network, timer or sleeps until night."""
import json,os,signal,sys,tempfile,time,unittest
from datetime import datetime
from pathlib import Path
from crawler.jobs.fixture_night_executor import execution_budget, supervise
from crawler.jobs.fixture_night_window import KST

class SupervisorTests(unittest.TestCase):
 def test_boundaries_and_remaining_budget(self):
  for hour,minute in [(20,59),(8,0)]:
   self.assertIsNone(execution_budget(datetime(2026,11,8,hour,minute,tzinfo=KST)))
  self.assertEqual(execution_budget(datetime(2026,11,8,21,tzinfo=KST)),120)
  self.assertEqual(execution_budget(datetime(2026,11,9,7,59,tzinfo=KST)),60)
  self.assertIsNone(execution_budget(datetime(2026,11,9,7,59,59,tzinfo=KST)))
 def test_real_child_success(self):
  r=supervise([sys.executable,'-c','print("safe")'],deadline=time.monotonic()+3,grace=.1)
  self.assertEqual(r.returncode,0);self.assertFalse(r.terminated)
 def test_real_child_deadline_termination(self):
  r=supervise([sys.executable,'-c','import time;time.sleep(30)'],deadline=time.monotonic()+.6,grace=.1)
  self.assertTrue(r.terminated);self.assertIsNotNone(r.returncode);self.assertLess(r.elapsed,3)
 @unittest.skipIf(os.name=='nt','POSIX SIGTERM handler; Windows terminate cannot be ignored')
 def test_ignoring_sigterm_is_killed(self):
  code='import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print("ready",flush=True);time.sleep(30)'
  r=supervise([sys.executable,'-c',code],deadline=time.monotonic()+.8,grace=.15)
  self.assertIn('ready',r.stdout);self.assertTrue(r.killed);self.assertEqual(r.returncode,-signal.SIGKILL)
 def test_no_spawn_after_deadline(self):
  r=supervise(['unavailable-command'],deadline=time.monotonic()-1,grace=.1)
  self.assertFalse(r.started)
