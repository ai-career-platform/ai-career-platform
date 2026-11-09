"""T64 STEP 05: offline KST schedule eligibility tests, zero dispatch."""
import unittest
from datetime import datetime, time, timedelta, timezone

from crawler.jobs.offline_schedule import (
    KST, OfflineSchedule, ScheduleDecision, evaluate_daily,
)


class TestOfflineSchedule(unittest.TestCase):
    def setUp(self):
        self.schedule = OfflineSchedule(enabled=True)
        self.slot = datetime(2026, 11, 7, 3, 0, tzinfo=KST)

    def at(self, minutes):
        return self.slot + timedelta(minutes=minutes)

    def decision(self, minutes, **kwargs):
        return evaluate_daily(self.schedule, now=self.at(minutes), **kwargs).decision

    def test_default_disabled(self):
        self.assertEqual(
            evaluate_daily(OfflineSchedule(), now=self.at(0)).decision,
            ScheduleDecision.DISABLED,
        )

    def test_disabled_even_when_due(self):
        schedule = OfflineSchedule(enabled=False)
        self.assertEqual(
            evaluate_daily(schedule, now=self.at(5)).decision,
            ScheduleDecision.DISABLED,
        )

    def test_not_due_before_slot(self):
        self.assertEqual(self.decision(-1), ScheduleDecision.NOT_DUE)

    def test_due_at_slot(self):
        self.assertEqual(self.decision(0), ScheduleDecision.DUE)

    def test_due_within_grace_window(self):
        self.assertEqual(self.decision(10), ScheduleDecision.DUE)

    def test_due_at_inclusive_window_boundary(self):
        self.assertEqual(self.decision(30), ScheduleDecision.DUE)

    def test_expired_after_window(self):
        self.assertEqual(self.decision(31), ScheduleDecision.WINDOW_EXPIRED)

    def test_before_next_day_slot_does_not_replay_yesterday(self):
        self.assertEqual(self.decision(23 * 60 + 40), ScheduleDecision.NOT_DUE)

    def test_same_slot_already_dispatched(self):
        self.assertEqual(
            self.decision(5, last_dispatched_for=self.slot),
            ScheduleDecision.ALREADY_DISPATCHED,
        )

    def test_prior_slot_does_not_block_new_day(self):
        previous = self.slot - timedelta(days=1)
        self.assertEqual(
            self.decision(5, last_dispatched_for=previous),
            ScheduleDecision.DUE,
        )

    def test_future_last_dispatched_rejected(self):
        with self.assertRaises(ValueError):
            self.decision(5, last_dispatched_for=self.slot + timedelta(days=1))

    def test_naive_now_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_daily(self.schedule, now=datetime(2026, 11, 7, 3))

    def test_naive_previous_rejected(self):
        with self.assertRaises(ValueError):
            self.decision(5, last_dispatched_for=datetime(2026, 11, 7, 3))

    def test_utc_conversion_in_snapshot(self):
        output = evaluate_daily(self.schedule, now=self.slot).snapshot()
        self.assertEqual(output["scheduled_at_utc"], "2026-11-06T18:00:00Z")
        self.assertEqual(output["local_day"], "2026-11-07")
        self.assertEqual(output["decision"], "DUE")

    def test_custom_local_time_is_not_activated(self):
        config = OfflineSchedule(enabled=True, local_time=time(4, 15))
        report = evaluate_daily(config, now=datetime(2026, 11, 7, 4, 15, tzinfo=KST))
        self.assertEqual(report.decision, ScheduleDecision.DUE)
        self.assertEqual(report.snapshot()["scheduled_at_utc"], "2026-11-06T19:15:00Z")

    def test_invalid_config_rejected(self):
        for config in (
            {"enabled": "yes"},
            {"source_id": "other"},
            {"local_time": time(3, tzinfo=timezone.utc)},
            {"catchup_window": timedelta(0)},
            {"catchup_window": timedelta(hours=3)},
        ):
            with self.subTest(config=config), self.assertRaises(ValueError):
                OfflineSchedule(**config)

    def test_invalid_schedule_input_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_daily(None, now=self.slot)

    def test_utc_now_works_equally(self):
        first = evaluate_daily(self.schedule, now=self.at(2))
        second = evaluate_daily(self.schedule, now=self.at(2).astimezone(timezone.utc))
        self.assertEqual(first, second)

    def test_never_mutates_state(self):
        first = evaluate_daily(self.schedule, now=self.at(2))
        second = evaluate_daily(self.schedule, now=self.at(2))
        self.assertEqual(first.decision, ScheduleDecision.DUE)
        self.assertEqual(second, first)

    def test_custom_window(self):
        config = OfflineSchedule(enabled=True, catchup_window=timedelta(minutes=5))
        self.assertEqual(evaluate_daily(config, now=self.at(6)).decision, ScheduleDecision.WINDOW_EXPIRED)


if __name__ == "__main__":
    unittest.main()
