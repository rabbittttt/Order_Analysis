import importlib.util
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launch = load("launch_patterns")
rules = load("report_rules")


def panel_rows(model="车型A", metric="留存大定", start=date(2025, 8, 1),
               values=None, source="首销日表"):
    values = list(values or [])
    return [
        {
            "model": model, "metric": metric, "stage": "首销",
            "cycle": start.isoformat(), "source": source,
            "brand": "品牌", "segment": "SUV", "energy": "增程",
            "date": start + timedelta(days=index), "life": index + 1,
            "value": value,
        }
        for index, value in enumerate(values)
    ]


class LaunchPatternTests(unittest.TestCase):
    def test_second_and_third_launch_weeks_are_separate_for_net_and_lock(self):
        rows = []
        for metric, values in (
            ("留存大定", [1] * 7 + [2] * 7 + [3] * 7),
            ("交车锁单", [2] * 7 + [3] * 7 + [6] * 7),
        ):
            rows.extend(panel_rows(metric=metric, values=values))

        output = launch.build_launch_pacing(rows)
        self.assertEqual(len(output), 4)
        net = [row for row in output if row["metric"] == "留存大定"]
        lock = [row for row in output if row["metric"] == "交车锁单"]
        self.assertEqual([row["pattern"] for row in net],
                         ["首销第2周/第1周", "首销第3周/第2周"])
        self.assertEqual([row["ratio"] for row in net], [2.0, 1.5])
        self.assertEqual([row["ratio"] for row in lock], [1.5, 2.0])
        second = next(row for row in net if row["pattern"] == "首销第2周/第1周")
        self.assertEqual((second["current_observed"], second["previous_observed"]), (7, 7))
        self.assertEqual((second["start"], second["end"]), (date(2025, 8, 8), date(2025, 8, 14)))

    def test_missing_negative_and_zero_denominator_are_explicit(self):
        rows = panel_rows(values=[5] * 7 + [0, 0, 0, 0, 0, 0])
        output = launch.build_launch_pacing(rows)
        second = next(row for row in output if row["pattern"] == "首销第2周/第1周")
        self.assertIsNone(second["ratio"])
        self.assertEqual(second["status"], "本期缺失或不完整")
        self.assertEqual((second["current_observed"], second["previous_observed"]), (6, 7))

        rows = panel_rows(model="车型B", values=[0] * 14)
        output = launch.build_launch_pacing(rows)
        second = next(row for row in output if row["pattern"] == "首销第2周/第1周")
        self.assertIsNone(second["ratio"])
        self.assertEqual(second["status"], "前期为零")

        rows = panel_rows(model="车型C", values=[4] * 7 + [-1] + [4] * 6)
        output = launch.build_launch_pacing(rows)
        second = next(row for row in output if row["pattern"] == "首销第2周/第1周")
        self.assertIsNone(second["ratio"])
        self.assertEqual(second["status"], "本期含负值")

        rows = panel_rows(model="车型D", values=[4] * 7 + [0] * 7)
        second = next(row for row in launch.build_launch_pacing(rows)
                      if row["pattern"] == "首销第2周/第1周")
        self.assertEqual(second["ratio"], 0.0)
        self.assertEqual(second["status"], "有效")

    def test_invalid_lifecycle_source_switch_and_duplicate_never_overwrite(self):
        rows = panel_rows(values=[1] * 14)
        rows[7]["life"] = 99
        output = launch.build_launch_pacing(rows)
        second = next(row for row in output if row["pattern"] == "首销第2周/第1周")
        self.assertIsNone(second["ratio"])
        self.assertEqual(second["status"], "本期缺失或不完整")
        self.assertEqual(second["current_observed"], 6)

        switched = panel_rows(values=[1] * 14)
        switched[7]["source"] = "另一来源"
        output = launch.build_launch_pacing(switched)
        self.assertEqual(len(output), 2)
        self.assertTrue(all(row["ratio"] is None for row in output))
        self.assertTrue(all(row["status"] == "本期缺失或不完整" for row in output))
        self.assertEqual(sorted((row["current_observed"], row["previous_observed"])
                                for row in output), [(1, 0), (6, 7)])
        no_previous = next(row for row in output if row["previous_observed"] == 0)
        self.assertIsNone(no_previous["previous"])

        with self.assertRaisesRegex(ValueError, "同一日重复"):
            launch.build_launch_pacing(rows + [dict(rows[0])])

    def test_only_touched_second_or_third_week_is_emitted(self):
        rows = panel_rows(values=[1] * 7)
        self.assertEqual(launch.build_launch_pacing(rows), [])
        rows = panel_rows(values=[1] * 7 + [2])
        output = launch.build_launch_pacing(rows)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0]["pattern"], "首销第2周/第1周")
        self.assertEqual(output[0]["current_observed"], 1)
        self.assertIsNone(output[0]["ratio"])

    def test_rule_summary_uses_model_equal_launch_pacing_and_marks_no_holdout(self):
        rows = []
        rows.extend(panel_rows(model="车型A", values=[1] * 7 + [2] * 7))
        rows.extend(panel_rows(model="车型B", values=[1] * 7 + [4] * 7))
        launch_rows = launch.build_launch_pacing(rows)
        results = {"launch_pacing": launch_rows}
        model_map = {"车型A": {"category": "A"}, "车型B": {"category": "B"}}
        output = rules.build_rule_summary(results, model_map, ["A", "B"])
        all_models = next(row for row in output
                          if row["category"] == "全部车型"
                          and row["pattern"] == "首销第2周/第1周")
        self.assertEqual(all_models["typical"], 3.0)
        self.assertEqual(all_models["models"], 2)
        self.assertEqual(all_models["samples"], 2)
        self.assertEqual(all_models["detail_sheet"], "生命周期明细")
        self.assertEqual(all_models["validation_note"], "首销批次描述，未做跨批次留出验证")
        self.assertIn("未做跨批次留出验证", all_models["conclusion"])


if __name__ == "__main__":
    unittest.main()
