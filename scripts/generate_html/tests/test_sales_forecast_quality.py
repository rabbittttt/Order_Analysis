from __future__ import annotations

import unittest

from tools.refresh_sales_forecast_data import cumulative, curve_for, day_structure_quality, mapping_record_for, summary_quality


class SalesForecastQualityTests(unittest.TestCase):
    def test_cumulative_keeps_future_dates_blank(self):
        self.assertEqual(cumulative([100, 50, None, None], 1000), [.1, .15, None, None])

    def test_cumulative_keeps_explicit_zero_observed(self):
        self.assertEqual(cumulative([100, 0, 50], 1000), [.1, .1, .15])

    def test_cumulative_does_not_claim_complete_total_after_gap(self):
        self.assertEqual(cumulative([100, None, 50], 1000), [.1, None, None])
        self.assertEqual(cumulative([None, 100], 1000), [None, None])

    def test_refresh_queries_accept_propagation_generation_and_alias_names(self):
        record = {"历史传播名": "尊界 G9", "订单分析代际名": "尊界 G9 2027款"}
        mapping = {"尊界g9": record}
        aliases = {
            "尊界g9": {"尊界g9", "尊界g92027", "g9旗舰"},
            "尊界g92027": {"尊界g9", "尊界g92027", "g9旗舰"},
        }
        self.assertIs(mapping_record_for("尊界 G9 2027款", mapping, aliases), record)
        self.assertIs(mapping_record_for("G9旗舰", mapping, aliases), record)
        self.assertEqual(curve_for("尊界 G9 2027款", {"尊界 G9": [1, 2]}, mapping, aliases, "测试"), [1, 2])

    def test_day_structure_rejects_impossible_components(self):
        valid, issue = day_structure_quality(80, 20, 100, "D1")
        self.assertTrue(valid)
        self.assertEqual(issue, "")
        valid, issue = day_structure_quality(120, 10, 100, "D1")
        self.assertFalse(valid)
        self.assertIn("高于总大定", issue)

    def test_summary_quality_separates_completeness_and_consistency(self):
        completeness, consistency, issues = summary_quality(
            1000, 300, .30, 400, 100, .25, 50, .05,
            350, .875, 280, .70,
        )
        self.assertEqual(completeness, 1)
        self.assertEqual(consistency, 1)
        self.assertEqual(issues, [])

        completeness, consistency, issues = summary_quality(
            1000, 450, .45, 400, 100, .25, 50, .05,
            350, .875, 280, .70,
        )
        self.assertEqual(completeness, 1)
        self.assertLess(consistency, 1)
        self.assertTrue(any("总小转大+总直接大定" in issue for issue in issues))

    def test_summary_quality_can_treat_an_explicit_zero_as_present(self):
        completeness, _, _ = summary_quality(
            1000, 300, .30, 500, 200, .40, 0, 0,
            450, .90, 400, .80,
            (True,) * 12,
        )
        self.assertEqual(completeness, 1)


if __name__ == "__main__":
    unittest.main()
