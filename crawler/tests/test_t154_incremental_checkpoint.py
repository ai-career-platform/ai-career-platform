import unittest
from datetime import datetime,timezone,timedelta
from uuid import UUID
from crawler.jobs.incremental_checkpoint import (
    Candidate, select_incremental_candidates, retry_fixture_decision,
    KeywordCheckpointStore,
)
from crawler.jobs.offline_recovery import RecoveryDecision

NOW=datetime(2026,11,8,12,0,tzinfo=timezone.utc)


class CheckpointTests(unittest.TestCase):
    def test_overlap_and_newest_first(self):
        items=[Candidate("1",NOW-timedelta(days=10)),
               Candidate("2",NOW-timedelta(days=2)),
               Candidate("3",NOW+timedelta(hours=1)),
               Candidate("2",NOW-timedelta(days=1))]
        self.assertEqual(select_incremental_candidates(items=items,checkpoint=NOW),
                         ("3","2"))
        self.assertEqual(select_incremental_candidates(items=items,checkpoint=NOW,lookback_days=7),
                         ("3","2"))

    def test_retry_is_decision_only(self):
        self.assertEqual(retry_fixture_decision(status="FAILED",error_code="TEMPORARY_IO",attempt=1),
                         RecoveryDecision.RETRY_ELIGIBLE)
        self.assertEqual(retry_fixture_decision(status="FAILED",error_code="RATE_LIMITED",attempt=1),
                         RecoveryDecision.STOP_NONRETRYABLE)
        self.assertEqual(retry_fixture_decision(status="FAILED",error_code="ACCESS_FORBIDDEN",attempt=1),
                         RecoveryDecision.STOP_NONRETRYABLE)
        self.assertEqual(retry_fixture_decision(status="FAILED",error_code="WORKER_TIMEOUT",attempt=3),
                         RecoveryDecision.STOP_LIMIT)
        self.assertEqual(retry_fixture_decision(status="PENDING",error_code=None,attempt=1),
                         RecoveryDecision.WAIT)

    def test_input_validation(self):
        for kw in (0,-1,"1",True):
            with self.subTest(kw=kw),self.assertRaises(ValueError):
                KeywordCheckpointStore(None).read(kw)
        for value in (None,datetime(2026,11,8),3):
            with self.subTest(value=value),self.assertRaises(ValueError):
                select_incremental_candidates(items=[Candidate("1",value)],checkpoint=NOW)

    def test_checkpoint_requires_completed_job_sql_contract(self):
        class Cursor:
            def __init__(self,return_row):
                self.return_row=return_row
                self.sql=""
                self.params=()
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def execute(self,sql,params):self.sql=sql;self.params=params
            def fetchone(self):return self.return_row
        class Connection:
            def __init__(self,row):
                from contextlib import nullcontext
                self.c=Cursor(row)
                self.transaction=lambda:nullcontext()
            def cursor(self):return self.c
        conn=Connection((1,))
        store=KeywordCheckpointStore(conn)
        self.assertTrue(store.mark_completed(keyword_id=1,
                          job_id=UUID("00000000-0000-4000-8000-000000000001"),
                          completed_at=NOW))
        self.assertIn("j.status='COMPLETED'",conn.c.sql)
        self.assertIn("last_success_at",conn.c.sql)
        self.assertIn("ON CONFLICT",conn.c.sql)
        self.assertIn("WHERE crawler_training.keyword_checkpoints.last_success_at",conn.c.sql)
        conn2=Connection(None)
        self.assertFalse(KeywordCheckpointStore(conn2).mark_completed(
            keyword_id=1,job_id=UUID("00000000-0000-4000-8000-000000000001"),
            completed_at=NOW))

    def test_migration_manual_and_isolated(self):
        from pathlib import Path
        sql=(Path(__file__).resolve().parents[1]/"storage"/"migrations"/"0007_keyword_checkpoints.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'",sql)
        self.assertIn("last_completed_job_id uuid",sql)
        self.assertNotIn("ALTER TABLE",sql)


if __name__=="__main__":unittest.main()
