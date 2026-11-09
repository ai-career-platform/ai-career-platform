"""T154 STEP07 immutable fixture payload contract tests; no live DB."""
import unittest
from contextlib import nullcontext
from datetime import datetime,timezone
from unittest.mock import patch
from uuid import UUID

from crawler.jobs.fixture_payloads import (
    FixturePayloadConflict, FixturePayloadStore, persist_fixture_keyword_jobs,
)
from crawler.jobs.fixture_keyword_jobs import PlannedJob
from crawler.jobs.incremental_fixture_plan import PlannedBatch

JOB=UUID("00000000-0000-4000-8000-000000000001")
NOW=datetime(2026,11,8,12,tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self,db):
        self.db=db
        self.result=None
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,params):
        self.db.queries.append(sql)
        if "INSERT INTO crawler_training.fixture_job_payloads" in sql:
            ids,job_id,keyword_id=params
            if job_id not in self.db.jobs or self.db.jobs[job_id] != keyword_id:
                self.result=None
            elif job_id in self.db.payloads:
                self.result=None
            else:
                self.db.payloads[job_id]=(keyword_id,tuple(ids))
                self.result=(job_id,)
        elif "SELECT keyword_id,posting_ids" in sql:
            self.result=self.db.payloads.get(params[0])
        else:
            self.result=None
    def fetchone(self):return self.result


class FakeDB:
    def __init__(self):
        self.jobs={JOB:1}
        self.payloads={}
        self.queries=[]
        self.transaction_calls=0
    def cursor(self):return FakeCursor(self)
    def transaction(self):
        self.transaction_calls+=1
        return nullcontext()


class FixturePayloadTests(unittest.TestCase):
    def test_same_job_same_payload_idempotent(self):
        db=FakeDB()
        store=FixturePayloadStore(db)
        store.register(job_id=JOB,keyword_id=1,posting_ids=("1","2"))
        store.register(job_id=JOB,keyword_id=1,posting_ids=("1","2"))
        self.assertEqual(len(db.payloads),1)
        self.assertEqual(db.payloads[JOB],(1,("1","2")))

    def test_reuse_job_with_changed_payload_rejected(self):
        db=FakeDB()
        store=FixturePayloadStore(db)
        store.register(job_id=JOB,keyword_id=1,posting_ids=("1","2"))
        with self.assertRaises(FixturePayloadConflict):
            store.register(job_id=JOB,keyword_id=1,posting_ids=("3",))
        self.assertEqual(db.payloads[JOB],(1,("1","2")))

    def test_missing_job_fails_closed(self):
        with self.assertRaises(FixturePayloadConflict):
            FixturePayloadStore(FakeDB()).register(
                job_id=UUID("00000000-0000-4000-8000-000000000002"),
                keyword_id=1,posting_ids=("3",))

    def test_invalid_payloads(self):
        for ids in ([],["1","1"],["bad"],["1"]*11):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                FixturePayloadStore(FakeDB()).register(
                    job_id=JOB,keyword_id=1,posting_ids=ids)

    def test_orchestration_uses_outer_transaction(self):
        db=FakeDB()
        planned=PlannedJob(PlannedBatch(1,1,("1","2"),"fixture:t154:2026-11-08:1:1"),JOB)
        with patch("crawler.jobs.fixture_payloads.create_fixture_keyword_jobs",
                   return_value=(planned,)) as planner:
            result=persist_fixture_keyword_jobs(
                connection=db,keyword_id=1,observations=(),now=NOW)
        self.assertEqual(result,(planned,))
        self.assertEqual(db.transaction_calls,1)
        self.assertEqual(db.payloads[JOB],(1,("1","2")))
        planner.assert_called_once()

    def test_migration_is_manual_only(self):
        from pathlib import Path
        sql=(Path(__file__).resolve().parents[1]/"storage"/"migrations"/
             "0008_fixture_job_payloads.sql").read_text(encoding="utf-8")
        self.assertIn("current_database() <> 'ai_career_crawler_training'",sql)
        self.assertIn("PRIMARY KEY REFERENCES crawler_training.keyword_jobs(job_id)",sql)
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"),1)
        self.assertNotIn("ALTER TABLE",sql)


if __name__=="__main__":
    unittest.main()
