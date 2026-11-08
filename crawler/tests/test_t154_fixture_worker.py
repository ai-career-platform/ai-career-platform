"""Offline T154 STEP09 orchestration tests, with explicit fake services."""
import unittest
from contextlib import nullcontext
from datetime import datetime,timezone
from unittest.mock import patch
from uuid import UUID
from crawler.jobs.fixture_worker import process_fixture_job

JOB=UUID("00000000-0000-4000-8000-000000000001")
NOW=datetime(2026,11,8,12,tzinfo=timezone.utc)


class FakeCursor:
    def __init__(self,db):
        self.db=db
        self.query=""
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,params):self.query=sql
    def fetchone(self):
        if "keyword_id,status" in self.query:return (1,self.db.status)
        if "SELECT ended_at" in self.query:return (NOW,)
        return None
    def fetchall(self):
        return [(JOB,"https://www.jobkorea.co.kr/Recruit/GI_Read/123")]


class FakeDB:
    def __init__(self,status="PENDING"):
        self.status=status
        self.transactions=0
    def transaction(self):
        self.transactions+=1
        return nullcontext()
    def cursor(self):return FakeCursor(self)


class FakePayload:
    keyword_id=1
    posting_ids=("123",)


class FakePayloadStore:
    def __init__(self,connection):pass
    def read(self,job_id):return FakePayload()


class FakeKeywordStore:
    def __init__(self,connection):self.connection=connection
    def transition(self,job_id,from_status,to_status):
        if self.connection.status!=from_status:return False
        self.connection.status=to_status
        return True


class FakeParse:
    status="VALID"


class FakeLedger:
    def __init__(self,connection,files):pass
    def process(self,artifact_id):return FakeParse()


class FakeCheckpoints:
    def __init__(self,connection):pass
    def mark_completed(self,**kwargs):return True


class WorkerTests(unittest.TestCase):
    def call(self,db):
        with patch("crawler.jobs.fixture_worker.FixturePayloadStore",FakePayloadStore), patch(
            "crawler.jobs.fixture_worker.KeywordStore",FakeKeywordStore), patch(
            "crawler.jobs.fixture_worker.RawParseLedger",FakeLedger), patch(
            "crawler.jobs.fixture_worker.KeywordCheckpointStore",FakeCheckpoints):
            return process_fixture_job(connection=db,files=None,job_id=JOB)

    def test_all_transitions_and_checkpoint(self):
        db=FakeDB()
        result=self.call(db)
        self.assertEqual((result.status,result.detail_count,result.valid_count,result.checkpoint_advanced),
                         ("COMPLETED",1,1,True))
        self.assertEqual(db.status,"COMPLETED")

    def test_completed_job_short_circuits(self):
        db=FakeDB(status="COMPLETED")
        outcome=process_fixture_job(connection=db,files=None,job_id=JOB)
        self.assertEqual(outcome.detail_count,0)
        self.assertFalse(outcome.checkpoint_advanced)

    def test_nonpending_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"not PENDING"):
            process_fixture_job(connection=FakeDB("RUNNING"),files=None,job_id=JOB)

    def test_invalid_payload_does_not_transition(self):
        class IncompleteCursor(FakeCursor):
            def fetchall(self):return []
        class IncompleteDB(FakeDB):
            def cursor(self):return IncompleteCursor(self)
        db=IncompleteDB()
        with patch("crawler.jobs.fixture_worker.FixturePayloadStore",FakePayloadStore):
            with self.assertRaisesRegex(ValueError,"Incomplete fixture Raw"):
                process_fixture_job(connection=db,files=None,job_id=JOB)
        self.assertEqual(db.status,"PENDING")

    def test_no_http_or_dispatch_import(self):
        from pathlib import Path
        text=(Path(__file__).resolve().parents[1]/"jobs"/"fixture_worker.py").read_text()
        self.assertNotIn("subprocess",text)
        self.assertNotIn("fetch_pages(",text)
        self.assertNotIn("SchedulerStore",text)


if __name__=="__main__":unittest.main()
