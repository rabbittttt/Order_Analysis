"""Unknown conversion facts must survive Python -> JSON -> chart rendering."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest

from openpyxl import Workbook

from core.excel import WorkbookItem, WorkbookStore
from core.models import Subject
from modules.conversion import ConversionModule, STAGES, _observed_number


ROOT = Path(__file__).resolve().parents[1]


class ConversionMissingFactsTests(unittest.TestCase):
    def build_page(self, quantities, durations=(None, "#DIV/0!")):
        book = Workbook()
        self.addCleanup(book.close)
        sheet = book.active
        sheet.title = "测试车by周"
        sheet.append(["周", *STAGES, "大定到交车锁单（天）", "交车锁单到交付（天）"])
        sheet.append([None, *["数量"] * 7, None, None])
        sheet.append(["26WK40", *quantities, *durations])
        store = WorkbookStore(Path("."))
        store.items = [WorkbookItem(Path("鸿蒙智行订单7级转化报表.xlsx"), book)]
        return ConversionModule().build(store, Subject("car", "测试车", "generation")).views["week"]["pages"]["26WK40"]

    def test_blank_middle_stage_does_not_fabricate_loss(self):
        page = self.build_page([100, 90, None, 80, 75, 70, 60])
        stages = page["sections"][0]["data"]
        self.assertIsNone(stages[2]["value"])
        self.assertIsNone(stages[2]["total_rate"])
        self.assertIsNone(stages[2]["loss"])
        self.assertIsNone(stages[3]["loss"])
        self.assertIsNone(stages[3]["stage_rate"])
        self.assertEqual(stages[3]["total_rate"], .8)
        self.assertEqual(page["kpis"][0]["value"], 60)
        self.assertIsNone(page["kpis"][3]["value"])
        self.assertEqual([r["count"] for r in page["sections"][2]["data"]["rows"]], [10, 5, 5, 10])

    def test_missing_delivery_is_not_zero_conversion(self):
        page = self.build_page([100, 90, 85, 80, 75, 70, None])
        self.assertIsNone(page["kpis"][0]["value"])
        self.assertIsNone(page["kpis"][2]["value"])
        self.assertIsNone(page["kpis"][3]["value"])

    def test_missing_base_does_not_invent_zero_percentages(self):
        page = self.build_page([None, 90, 85, 80, 75, 70, 60])
        self.assertTrue(all(s["total_rate"] is None for s in page["sections"][0]["data"]))
        self.assertEqual(page["sections"][0]["data"][-1]["stage_rate"], 60 / 70)
        self.assertEqual(page["sections"][2]["data"]["rows"], [])

    def test_real_zero_is_preserved_and_zero_denominator_is_undefined(self):
        page = self.build_page([100, 90, 0, 0, 0, 0, 0], (0, 0))
        stages = page["sections"][0]["data"]
        self.assertEqual(stages[2]["value"], 0)
        self.assertEqual(stages[2]["total_rate"], 0)
        self.assertEqual(stages[2]["stage_rate"], 0)
        self.assertEqual(stages[2]["loss"], 90)
        self.assertIsNone(stages[3]["stage_rate"])
        self.assertEqual(page["kpis"][0]["value"], 0)
        self.assertEqual(page["kpis"][3]["value"], 90)
        self.assertEqual(page["sections"][1]["data"][0]["order_to_lock_days"], 0)
        empty = self.build_page([0] * 7)
        self.assertIsNone(empty["kpis"][0]["value"])
        self.assertEqual(empty["kpis"][3]["value"], 0)

    def test_blank_or_error_durations_remain_unknown(self):
        page = self.build_page([100, 90, 85, 80, 75, 70, 60])
        cohort = page["sections"][1]["data"][0]
        self.assertIsNone(cohort["order_to_lock_days"])
        self.assertIsNone(cohort["lock_to_delivery_days"])

    def test_invalid_numbers_do_not_become_observations(self):
        for value in (None, "", "  ", "#DIV/0!", "—", True, False, -1, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(_observed_number(value))
        for value, expected in ((0, 0), ("0", 0), (3.5, 3.5), ("1,234", 1234)):
            self.assertEqual(_observed_number(value), expected)

    def test_complete_inputs_retain_existing_calculations(self):
        page = self.build_page([100, 90, 85, 80, 75, 70, 60], (3.5, 18))
        self.assertEqual([k["value"] for k in page["kpis"]], [60, 100, 60, 10])
        self.assertEqual([s["loss"] for s in page["sections"][0]["data"]], [0, 10, 5, 5, 5, 5, 10])
        self.assertEqual(page["sections"][1]["data"][0]["lock_to_delivery_days"], 18)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_renderer_keeps_unknown_distinct_from_real_zero(self):
        source = (ROOT / "templates/dashboard.js").read_text(encoding="utf-8")
        helpers = source[source.index("  const displayText ="):source.index("  const LABEL_SCALE_HEADROOM")]
        renderer = source[source.index("  function renderFunnel("):source.index("  function renderRankCards(")]
        page = self.build_page([100, 90, None, 80, 75, 70, 0], (None, 0))
        script = """
const input=JSON.parse(process.argv[1]);
""" + helpers + renderer + """
console.log(JSON.stringify({funnel:renderFunnel(input[0].data),matrix:renderCohortMatrix(input[1].data)}));
"""
        result = subprocess.run(["node", "-e", script, json.dumps(page["sections"])],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True)
        html = json.loads(result.stdout)
        self.assertIn('title="数据缺失或分母为0">—', html["funnel"])
        self.assertIn('<b>0</b><b>0.0%</b>', html["funnel"])
        self.assertIn('<td title="数据缺失或分母为0">—</td>', html["matrix"])
        self.assertIn('<td>—</td><td>0天</td>', html["matrix"])
        self.assertNotIn("NaN", html["funnel"] + html["matrix"])
        self.assertNotIn("—天", html["matrix"])


if __name__ == "__main__":
    unittest.main()
