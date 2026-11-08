"""T154 STEP14: offline durable retry budget contract tests."""
import unittest
from contextlib import nullcontext
from uuid import UUID
from pathlib import Path
from crawler.jobs.fixture_retry_budget import DurableFixtureAttemptStore

JOB=UUID("00000000-0000-4000-8000-000000000001")


class FakeCursor:
    def __init__(self,db):self.db=db;self.sql="";self.params=()
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,params):self.sql=sql;self.params=params;self.db.statements.append(sql)
    def fetchone(self):
        if "INSERT INTO crawler_training.fixture_job_attempts" in self.sql:
            if not self.db.pending or not self.db.payload: return None
            if self.db.state is None:
                self.db.count=1;self.db.state="IN_PROGRESS";return (1,)
            if self.db.state=="RETRYABLE" and self.db.count<3:
                self.db.count+=1;self.db.state="IN_PROGRESS";return (self.db.count,)
            return None
        if "UPDATE crawler_training.fixture_job_attempts" in self.sql:
            if self.db.count!=self.params[-1] or self.db.state!="IN_PROGRESS":
                return None
            success="SET state='COMPLETED'" in self.sql
            state="COMPLETED" if success else self.params[0]
            if success:
                if not self.db.completed:return None
            elif not self.db.pending:return None
            self.db.state=state
            return (JOB,)
        return (self.db.count,self.db.state,None) if self.db.state else None


class FakeDB:
    def __init__(self):
        self.pending=True;self.completed=False;self.payload=True
        self.count=0;self.state=None;self.statements=[];self.tx=0
    def transaction(self):self.tx+=1;return nullcontext()
    def cursor(self):return FakeCursor(self)


class RetryBudgetTests(unittest.TestCase):
    def test_budget_three_then_hard_stop(self):
        db=FakeDB();s=DurableFixtureAttemptStore(db)
        for attempt in (1,2,3):
            claim=s.reserve(JOB)
            self.assertEqual(claim.attempt,attempt)
            self.assertIsNone(s.reserve(JOB))  # concurrent or duplicate
            self.assertTrue(s.record_failure(job_id=JOB,attempt=attempt,
                                             error_code="TEMPORARY_IO"))
        self.assertEqual(db.state,"STOPPED")
        self.assertIsNone(s.reserve(JOB))
        self.assertEqual(db.count,3)

    def test_blocked_codes_no_retry(self):
        for error in ("RATE_LIMITED","ACCESS_FORBIDDEN","INVALID_CONTRACT",
                      "UNAPPROVED_SOURCE"):
            with self.subTest(error=error):
                db=FakeDB();s=DurableFixtureAttemptStore(db)
                s.reserve(JOB)
                self.assertTrue(s.record_failure(job_id=JOB,attempt=1,error_code=error))
                self.assertEqual(db.state,"STOPPED")
                self.assertIsNone(s.reserve(JOB))

    def test_success_requires_completed_job(self):
        db=FakeDB();s=DurableFixtureAttemptStore(db)
        s.reserve(JOB)
        self.assertFalse(s.record_success(job_id=JOB,attempt=1))
        db.pending=False;db.completed=True
        self.assertTrue(s.record_success(job_id=JOB,attempt=1))
        self.assertIsNone(s.reserve(JOB))
        self.assertEqual(db.state,"COMPLETED")

    def test_failed_worker_must_have_rolled_back(self):
        db=FakeDB();s=DurableFixtureAttemptStore(db)
        s.reserve(JOB);db.pending=False
        self.assertFalse(s.record_failure(job_id=JOB,attempt=1,error_code="TEMPORARY_IO"))

    def test_missing_payload_no_reservation(self):
        db=FakeDB();db.payload=False
        self.assertIsNone(DurableFixtureAttemptStore(db).reserve(JOB))
        self.assertEqual(db.tx,1)

    def test_contract_separate_transaction_and_migration(self):
        sql=(Path(__file__).resolve().parents[1]/"storage"/"migrations"/
             "0009_fixture_job_attempts.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'",sql)
        self.assertIn("state IN ('IN_PROGRESS','RETRYABLE','STOPPED','COMPLETED')",sql)
        self.assertNotIn("ALTER TABLE",sql)
        py=(Path(__file__).resolve().parents[1]/"jobs"/"fixture_retry_budget.py").read_text()
        self.assertIn("attempt_count<3",py)
        self.assertIn("j.status='PENDING'",py)
        self.assertIn("j.status='COMPLETED'",py)
        self.assertNotIn("subprocess.Popen",py)


if __name__=="__main__":unittest.main()
