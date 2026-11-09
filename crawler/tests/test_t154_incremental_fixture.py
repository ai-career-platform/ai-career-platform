import unittest
from datetime import datetime,timezone
from crawler.jobs.incremental_fixture_plan import in_fixture_window,plan_fixture_batches


def utc(hour,minute=0):
    return datetime(2026,11,8,hour,minute,tzinfo=timezone.utc)

class IncrementalFixtureTests(unittest.TestCase):
    def test_window_midnight_and_boundaries(self):
        self.assertTrue(in_fixture_window(utc(12)))  # 21:00 KST
        self.assertTrue(in_fixture_window(utc(22)))  # 07:00 next day
        self.assertFalse(in_fixture_window(utc(23))) # 08:00 next day
        self.assertFalse(in_fixture_window(utc(11,59)))
        self.assertTrue(in_fixture_window(utc(21)))  # 06:00 KST

    def test_same_night_across_midnight_same_key(self):
        before=plan_fixture_batches(keyword_id=1,posting_ids=["101"],now=utc(13))
        after=plan_fixture_batches(keyword_id=1,posting_ids=["101"],now=utc(22))
        self.assertEqual(before[0].idempotency_key,after[0].idempotency_key)

    def test_batches_deduplicate_and_are_bounded(self):
        x=plan_fixture_batches(keyword_id=2,posting_ids=["1","2","1","3","4","5"],now=utc(14),batch_size=2)
        self.assertEqual([p.posting_ids for p in x],[("1","2"),("3","4"),("5",)])
        self.assertEqual(len({p.idempotency_key for p in x}),3)

    def test_daytime_returns_no_jobs(self):
        self.assertEqual(plan_fixture_batches(keyword_id=1,posting_ids=["1"],now=utc(3)),())

    def test_invalid_inputs_fail_closed(self):
        for kwargs in ({"keyword_id":0},{"posting_ids":["1","bad"]},
                       {"batch_size":11},{"lookback_days":8},
                       {"now":datetime(2026,11,8,20)}):
            values=dict(keyword_id=1,posting_ids=["1"],now=utc(14))
            values.update(kwargs)
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                plan_fixture_batches(**values)

if __name__=="__main__":
    unittest.main()
