"""Harvest week, skip, and window-open rules — no more 168h / silent close."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from backend.windows.coverage import (
    complete_daily_buckets,
    coverage_need,
    min_days_for,
    window_available,
    window_day_range,
)


class HarvestWindowMathTests(unittest.TestCase):
    def test_30d_range_is_half_open_at_monday_cut(self):
        cut = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
        start, end = window_day_range(30, cut)
        self.assertEqual(start, "2026-08-29")
        self.assertEqual(end, "2026-09-28")

    def test_min_days_matches_coverage_rule(self):
        self.assertEqual(min_days_for(30, 0.7), 21)
        self.assertEqual(min_days_for(90, 0.7), 62)
        self.assertEqual(min_days_for(365, 0.7), 255)
        self.assertEqual(min_days_for(7, 0.7), 4)

    def test_do_not_open_without_enough_roster(self):
        self.assertFalse(window_available(daily_ready=0, written=0, roster_size=21, need=0.7))
        self.assertFalse(window_available(daily_ready=10, written=0, roster_size=21, need=0.7))

    def test_open_when_daily_or_already_written(self):
        self.assertTrue(window_available(daily_ready=21, written=0, roster_size=21, need=0.7))
        self.assertTrue(window_available(daily_ready=0, written=21, roster_size=21, need=0.7))
        self.assertTrue(window_available(daily_ready=15, written=18, roster_size=21, need=0.7))

    def test_timer_drift_does_not_look_like_same_week(self):
        """Last Monday 06:23 vs this Monday 06:02 is a new week — must fetch."""
        last = datetime(2026, 9, 21, 6, 23, tzinfo=timezone.utc)
        this = datetime(2026, 9, 28, 6, 2, tzinfo=timezone.utc)
        self.assertGreaterEqual((this - last).total_seconds(), 0)
        self.assertLess((this - last), timedelta(hours=168))
        start, end = window_day_range(7, this)
        self.assertEqual(start, "2026-09-21")
        self.assertEqual(end, "2026-09-28")
        # One leftover day from last week is not enough to skip.
        self.assertFalse(1 >= min_days_for(7, 0.7))

    def test_complete_daily_buckets_fills_zeros(self):
        since = datetime(2026, 9, 21, 6, 0, tzinfo=timezone.utc)
        until = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
        filled = complete_daily_buckets([("2026-09-22", 3)], since, until)
        days = [d for d, _ in filled]
        self.assertEqual(days[0], "2026-09-21")
        self.assertEqual(days[-1], "2026-09-27")
        self.assertEqual(len(filled), 7)
        self.assertEqual(dict(filled)["2026-09-22"], 3)
        self.assertEqual(dict(filled)["2026-09-21"], 0)

    def test_coverage_need_is_clamped(self):
        self.assertGreaterEqual(coverage_need(), 0.1)
        self.assertLessEqual(coverage_need(), 1.0)


if __name__ == "__main__":
    unittest.main()
