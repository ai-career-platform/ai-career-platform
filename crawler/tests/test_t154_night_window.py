"""T154 STEP21: night window and one-slot-per-period contract tests."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from uuid import UUID
from contextlib import nullcontext

from crawler.jobs.fixture_night_window import (
    KST,night_slot, NightSlotStore, NightSlotUnavailable,execute_night_fixture_once,
)
JOB=UUID("00000000-0000-4000-8000-000000000001")


def kst(day,h,m=0):
    return datetime(2026,11,day,h,m,tzinfo=KST)


class FakeCursor:
    def __init__(self,db):self.db=db
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,args):
        self.db.sql=sql;self.db.args=args
    def fetchone(self):
        k=self.db.args[:2]
        if k in self.db.used or self.db.args[2] in self.db.jobs:return None
        self.db.used.add(k);self.db.jobs.add(self.db.args[2])
        return (self.db.args[1],)


class FakeConnection:
    def __init__(self):self.used=set();self.jobs=set();self.sql=None;self.args=None
    def transaction(self):return nullcontext()
    def cursor(self):return FakeCursor(self)


class WindowTests(unittest.TestCase):
    def test_boundaries_and_midnight(self):
        self.assertIsNone(night_slot(kst(8,20,59)))
        self.assertEqual(night_slot(kst(8,21)).slot_index,0)
        self.assertEqual(night_slot(kst(8,21,29)).slot_index,0)
        self.assertEqual(night_slot(kst(8,21,30)).slot_index,1)
        self.assertEqual(night_slot(kst(8,23,59)).slot_index,5)
        self.assertEqual(night_slot(kst(9,0)).slot_index,6)
        self.assertEqual(night_slot(kst(9,7,59)).slot_index,21)
        self.assertIsNone(night_slot(kst(9,8)))
        self.assertIsNone(night_slot(kst(9,12)))
        self.assertEqual(night_slot(kst(9,0)).night_date,
                         night_slot(kst(8,21)).night_date)

    def test_slot_expiry(self):
        self.assertEqual(night_slot(kst(8,21)).expires_at,kst(8,21,30))
        self.assertEqual(night_slot(kst(8,23,30)).expires_at,kst(9,0))
        self.assertEqual(night_slot(kst(9,7,30)).expires_at,kst(9,8))

    def test_aware_datetime_required(self):
        with self.assertRaises(ValueError):
            night_slot(datetime(2026,11,8,21))

    def test_duplicate_slot_and_job_are_denied(self):
        db=FakeConnection();store=NightSlotStore(db)
        self.assertIsNotNone(store.reserve(job_id=JOB,now=kst(8,21)))
        self.assertIsNone(store.reserve(job_id=JOB,now=kst(8,21)))
        self.assertIsNone(store.reserve(job_id=JOB,now=kst(8,21,30)))
        self.assertIn("ON CONFLICT DO NOTHING",db.sql)

    def test_outside_window_does_not_use_database(self):
        db=FakeConnection()
        self.assertIsNone(NightSlotStore(db).reserve(job_id=JOB,now=kst(9,8)))
        self.assertIsNone(db.sql)

    def test_explicit_worker_bridge_and_connection_separation(self):
        slot_db=FakeConnection();a=FakeConnection();w=FakeConnection()
        with patch("crawler.jobs.fixture_night_window.execute_manual_fixture_attempt",
                   return_value="OK") as fn:
            result=execute_night_fixture_once(
                slot_connection=slot_db,attempt_connection=a,
                worker_connection=w,files=None,job_id=JOB,now=kst(8,21))
        self.assertEqual(result,"OK")
        self.assertIs(fn.call_args.kwargs["worker_connection"],w)
        with self.assertRaises(ValueError):
            execute_night_fixture_once(
                slot_connection=a,attempt_connection=a,worker_connection=w,
                files=None,job_id=JOB,now=kst(8,21))
        with self.assertRaises(NightSlotUnavailable):
            execute_night_fixture_once(
                slot_connection=slot_db,attempt_connection=a,worker_connection=w,
                files=None,job_id=JOB,now=kst(8,21))

    def test_no_automatic_activation(self):
        from pathlib import Path
        code=(Path(__file__).resolve().parents[1]/"jobs"/"fixture_night_window.py").read_text()
        for s in ("import requests","import subprocess","systemctl","Timer(","sleep("):
            self.assertNotIn(s,code)
        migration=(Path(__file__).resolve().parents[1]/"storage"/"migrations"/"0010_fixture_night_slots.sql").read_text()
        self.assertIn("BETWEEN 0 AND 21",migration)
        self.assertIn("current_database()",migration)


if __name__=="__main__":
    unittest.main()
