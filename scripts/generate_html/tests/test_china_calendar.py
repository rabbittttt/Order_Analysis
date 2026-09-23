from __future__ import annotations

import unittest

from core.china_calendar import classify_day, window_profile


class ChinaCalendarTests(unittest.TestCase):
    def test_adjusted_weekend_is_workday(self):
        day = classify_day("2026-01-04")
        self.assertEqual("workday", day["type"])
        self.assertTrue(day["adjusted"])
        self.assertEqual("调休工作日", day["label"])

    def test_weekend_inside_official_break_is_holiday(self):
        day = classify_day("2026-09-26")
        self.assertEqual("holiday", day["type"])
        self.assertEqual("中秋节", day["name"])

    def test_ordinary_weekend_stays_weekend(self):
        self.assertEqual("weekend", classify_day("2026-08-22")["type"])

    def test_window_profile_counts_adjusted_days(self):
        profile = window_profile("2025-09-28", 12)
        self.assertGreaterEqual(profile["holidays"], 8)
        self.assertGreaterEqual(profile["adjusted_workdays"], 1)
        self.assertIn("中秋国庆", profile["holiday_names"])


if __name__ == "__main__":
    unittest.main()
