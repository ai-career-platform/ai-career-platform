"""T154 STEP16 fixture-only coordinator; deterministic fake service tests."""
import unittest
from unittest.mock import patch
from uuid import UUID

from crawler.jobs.fixture_manual_retry import (
    AttemptUnavailable, AttemptFinalizationRequired, execute_manual_fixture_attempt,
)
from crawler.jobs.fixture_retry_budget import AttemptReservation
from crawler.jobs.fixture_worker import FixtureExecution

JOB=UUID("00000000-0000-4000-8000-000000000001")


class FakeBudget:
    reservation=AttemptReservation(JOB,1)
    finalized=True
    fail_error=None
    fail_record=False
    def __init__(self,conn):self.conn=conn
    def reserve(self,job_id):
        self.conn.events.append("reserve")
        return self.reservation
    def read(self,job_id):return (self.reservation.attempt,"IN_PROGRESS",None)
    def record_failure(self,**kwargs):
        self.conn.events.append(("failure",kwargs["error_code"]))
        if self.fail_record:raise RuntimeError("ledger error")
        return True
    def record_success(self,**kwargs):
        self.conn.events.append("success")
        return self.finalized


class FakeConnection:
    def __init__(self):self.events=[]


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        FakeBudget.reservation=AttemptReservation(JOB,1)
        FakeBudget.finalized=True
        FakeBudget.fail_record=False
        self.a=FakeConnection()
        self.w=FakeConnection()

    def execute(self,processor,**kwargs):
        with patch("crawler.jobs.fixture_manual_retry.DurableFixtureAttemptStore",FakeBudget), patch(
            "crawler.jobs.fixture_manual_retry.process_fixture_job",processor
        ):
            return execute_manual_fixture_attempt(
                attempt_connection=self.a,worker_connection=self.w,
                files=None,job_id=JOB,**kwargs)

    def test_success_reserves_before_worker_and_finalizes_after(self):
        sequence=[]
        def worker(**kwargs):
            self.assertEqual(self.a.events,["reserve"])
            self.assertIs(kwargs["connection"],self.w)
            sequence.append("worker")
            return FixtureExecution(JOB,"COMPLETED",2,2,True)
        r=self.execute(worker)
        self.assertEqual(sequence,["worker"])
        self.assertEqual(self.a.events,["reserve","success"])
        self.assertEqual((r.attempt,r.detail_count,r.status),(1,2,"COMPLETED"))

    def test_duplicate_or_exhausted_attempt_does_not_call_worker(self):
        FakeBudget.reservation=None
        called=[]
        with self.assertRaises(AttemptUnavailable):
            self.execute(lambda **kwargs:called.append(1))
        self.assertEqual(called,[])
        self.assertEqual(self.a.events,["reserve"])

    def test_known_failure_is_logged_after_worker_exception(self):
        def worker(**kwargs):
            self.assertEqual(self.a.events,["reserve"])
            raise ValueError("invalid fixture")
        with self.assertRaisesRegex(ValueError,"invalid fixture"):
            self.execute(worker,failure_error_code="INVALID_CONTRACT")
        self.assertEqual(self.a.events,["reserve",("failure","INVALID_CONTRACT")])

    def test_unknown_failure_remains_in_progress(self):
        def worker(**kwargs):raise OSError("unclassified")
        with self.assertRaises(OSError):
            self.execute(worker)
        self.assertEqual(self.a.events,["reserve"])

    def test_failure_recording_error_does_not_hide_original(self):
        FakeBudget.fail_record=True
        def worker(**kwargs):raise OSError("original")
        with self.assertRaisesRegex(OSError,"original"):
            self.execute(worker,failure_error_code="TEMPORARY_IO")
        self.assertEqual(self.a.events,["reserve",("failure","TEMPORARY_IO")])

    def test_success_finalization_failure_is_explicit(self):
        FakeBudget.finalized=False
        with self.assertRaises(AttemptFinalizationRequired):
            self.execute(lambda **kwargs:FixtureExecution(JOB,"COMPLETED",1,1,True))
        self.assertEqual(self.a.events,["reserve","success"])

    def test_same_connection_forbidden_before_db(self):
        with self.assertRaises(ValueError):
            execute_manual_fixture_attempt(attempt_connection=self.a,
                worker_connection=self.a,files=None,job_id=JOB)
        self.assertEqual(self.a.events,[])

    def test_unknown_code_forbidden_before_db(self):
        with self.assertRaises(ValueError):
            execute_manual_fixture_attempt(attempt_connection=self.a,
                worker_connection=self.w,files=None,job_id=JOB,
                failure_error_code="NOT_A_KNOWN_CODE")
        self.assertEqual(self.a.events,[])

    def test_no_implicit_run_or_network(self):
        from pathlib import Path
        p=(Path(__file__).resolve().parents[1]/"jobs"/"fixture_manual_retry.py")
        source=p.read_text()
        for forbidden in ("import requests","import subprocess",
                          "SchedulerStore(","Dispatcher("):
            self.assertNotIn(forbidden,source)


if __name__=="__main__":unittest.main()
