import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from crawler.jobs.incremental_checkpoint import Candidate
from crawler.jobs.fixture_keyword_jobs import create_fixture_keyword_jobs

NIGHT = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
DAY = datetime(2026, 11, 8, 3, 0, tzinfo=timezone.utc)


class FakeConnection:
    def __init__(self):
        self.transaction_calls = 0

    def transaction(self):
        self.transaction_calls += 1
        return nullcontext()


class FixtureJobsTests(unittest.TestCase):
    def test_night_creates_bounded_jobs_then_reuses(self):
        connection = FakeConnection()
        jobs = {}
        created = []
        class FakeCheckpoints:
            def __init__(self, conn):
                self.assert_conn = conn
            def read(self, keyword_id):
                return (NIGHT-timedelta(days=2), "prior")
        class FakeKeywords:
            def __init__(self, conn):
                pass
            def create_job(self, keyword_id, key):
                created.append(key)
                return jobs.setdefault(key, f"job-{len(jobs)+1}")
        observations = [
            Candidate("10", NIGHT-timedelta(days=1)),
            Candidate("20", NIGHT),
            Candidate("20", NIGHT),
            Candidate("30", NIGHT-timedelta(days=10)),
        ]
        with patch("crawler.jobs.fixture_keyword_jobs.KeywordCheckpointStore",FakeCheckpoints), patch(
            "crawler.jobs.fixture_keyword_jobs.KeywordStore",FakeKeywords
        ):
            first = create_fixture_keyword_jobs(connection=connection,keyword_id=1,
                observations=observations,now=NIGHT,batch_size=1)
            second = create_fixture_keyword_jobs(connection=connection,keyword_id=1,
                observations=observations,now=NIGHT,batch_size=1)
        self.assertEqual(len(first),2)
        self.assertEqual([x.job_id for x in first],[x.job_id for x in second])
        self.assertEqual([x.batch.posting_ids for x in first],[("20",),("10",)])
        self.assertEqual(len(jobs),2)
        self.assertEqual(connection.transaction_calls,2)

    def test_outside_window_never_reads_or_writes_db(self):
        self.assertEqual(create_fixture_keyword_jobs(connection=None,keyword_id=1,
            observations=[Candidate("1",DAY)],now=DAY),())

    def test_invalid_observation_fails_before_db_access(self):
        with self.assertRaises(ValueError):
            create_fixture_keyword_jobs(connection=None,keyword_id=1,
                observations=[Candidate("bad",NIGHT)],now=NIGHT)

    def test_checkpoint_filters_out_old_observations(self):
        connection=FakeConnection()
        class Checkpoints:
            def __init__(self,conn):pass
            def read(self,keyword_id):return (NIGHT,"previous")
        with patch("crawler.jobs.fixture_keyword_jobs.KeywordCheckpointStore",Checkpoints):
            result=create_fixture_keyword_jobs(connection=connection,keyword_id=1,
                observations=[Candidate("1",NIGHT-timedelta(days=6))],now=NIGHT)
        self.assertEqual(result,())
        self.assertEqual(connection.transaction_calls,0)

    def test_invalid_inputs(self):
        for params in ({"keyword_id":0},{"now":datetime(2026,11,8,21)},
                       {"batch_size":0},{"lookback_days":2}):
            values=dict(connection=None,keyword_id=1,observations=[],now=NIGHT)
            values.update(params)
            with self.subTest(params=params),self.assertRaises(ValueError):
                create_fixture_keyword_jobs(**values)


if __name__=="__main__":
    unittest.main()
