"""First-sale direct-order progress must remain the original worksheet metric."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace
import unittest

from openpyxl import Workbook

from modules.launch_rhythm import LaunchRhythmModule
import test_ui_template as ui_runtime


METRIC = "累计直接大定进度"
MISSING_ROW = object()


class LaunchDirectProgressTests(unittest.TestCase):
    def phase(self, values=MISSING_ROW, *, grain="day", number_format="General", phase_number=1):
        workbook = Workbook()
        self.addCleanup(workbook.close)
        sheet = workbook.active
        suffix = "by周" if grain == "week" else "by天"
        sheet.title = f"问界 F2N 2026款{suffix}第{phase_number}期"
        periods = ("26WK31", "26WK32", "26WK33") if grain == "week" else ("D1", "D2", "D3")
        sheet.append(["指标", *periods])
        sheet.append(["日期", *[f"2026-08-{phase_number * 3 + offset:02d}" for offset in range(3)]])
        sheet.append(["当日大定数量", 80, 120, 100])
        sheet.append(["当日净大定数量", 70, 100, 90])
        sheet.append(["当日小订转大定数量", 20, 20, 20])
        sheet.append(["当日直接大定数量", 60, 100, 80])
        sheet.append(["累计直接大定数量", 60, 160, 240])
        # A similarly named metric must not override the requested source row.
        sheet.append(["累计直接大定占比", .9, .9, .9])
        if values is not MISSING_ROW:
            sheet.append([METRIC, *values])
            for cell in sheet[sheet.max_row][1:]:
                cell.number_format = number_format
        return LaunchRhythmModule()._build_phase(
            SimpleNamespace(path=Path("首销期订单节奏.xlsx")), sheet,
            phase_number, None, True, grain=grain,
        )

    def card(self, phase):
        card = phase["page"]["kpis"][3]
        self.assertEqual(card["label"], METRIC)
        return card

    def test_day_and_week_cards_use_original_progress_instead_of_quantity_ratio(self):
        for grain in ("day", "week"):
            with self.subTest(grain=grain):
                phase = self.phase((.1, .33, .794), grain=grain)
                self.assertAlmostEqual(self.card(phase)["value"], 79.4)
                self.assertEqual(phase["direct_progress"], .794)
                self.assertNotEqual(self.card(phase)["value"], phase["direct"] / phase["orders"] * 100)
                self.assertEqual(phase["metrics"][METRIC], [.1, .33, .794])

    def test_blank_tail_keeps_last_observation_and_real_zero_is_not_missing(self):
        for grain in ("day", "week"):
            for values, expected in (((.1, .794, None), .794), ((.1, .794, ""), .794),
                                     ((.1, .794, 0), 0), ((0, None, None), 0)):
                with self.subTest(grain=grain, values=values):
                    phase = self.phase(values, grain=grain)
                    self.assertEqual(phase["direct_progress"], expected)
                    self.assertAlmostEqual(self.card(phase)["value"], expected * 100)

    def test_missing_and_erroneous_progress_stays_unknown_without_calculated_fallback(self):
        for grain in ("day", "week"):
            for values in (MISSING_ROW, (None, None, None), ("#DIV/0!", "#N/A", "待更新"),
                           ("—", "--", ""), (float("nan"), float("inf"), float("-inf"))):
                with self.subTest(grain=grain, values=values):
                    phase = self.phase(values, grain=grain)
                    self.assertIsNone(self.card(phase)["value"])
                    self.assertIsNone(phase["direct_progress"])
                    self.assertEqual(phase["direct"], 240)
                    self.assertEqual(phase["orders"], 300)
                    if values is not MISSING_ROW:
                        self.assertEqual(phase["metrics"][METRIC], [None, None, None])
            phase = self.phase((.1, .794, "#DIV/0!"), grain=grain)
            self.assertAlmostEqual(self.card(phase)["value"], 79.4)
            self.assertEqual(phase["metrics"][METRIC], [.1, .794, None])

    def test_original_percentage_encodings_have_the_same_progress(self):
        for grain in ("day", "week"):
            for value, number_format in (("79.4%", "General"), ("79.4％", "General"),
                                          (79.4, "General"), (.794, "General"), (.794, "0.0%")):
                with self.subTest(grain=grain, value=value, number_format=number_format):
                    phase = self.phase((None, value, None), grain=grain, number_format=number_format)
                    self.assertAlmostEqual(self.card(phase)["value"], 79.4)
                    self.assertEqual(phase["metrics"][METRIC], [None, .794, None])

    def test_matrix_preserves_original_progress_values_and_blank_cells(self):
        for grain in ("day", "week"):
            with self.subTest(grain=grain):
                phase = self.phase((0, .794, None), grain=grain)
                matrix = next(section for section in phase["page"]["sections"] if section["kind"] == "matrix")
                row = next(row for row in matrix["data"]["rows"] if row[0] == METRIC)
                self.assertEqual(row, [METRIC, "0.0%", "79.4%", None])
                self.assertEqual(phase["metrics"][METRIC], [0, .794, None])

    def test_all_phases_keep_separate_original_progress_without_combining_rates(self):
        for grain in ("day", "week"):
            for values in ((.2, .8), (.2, 0), (.2, None)):
                with self.subTest(grain=grain, values=values):
                    phases = [self.phase((None, value, None), grain=grain, phase_number=index)
                              for index, value in enumerate(values, start=1)]
                    page = LaunchRhythmModule._combined_page(phases)
                    self.assertEqual(page["kpis"][3]["label"], METRIC)
                    self.assertIsNone(page["kpis"][3]["value"])
                    self.assertEqual(page["kpis"][3]["note"], "各期原表进度见阶段概览")
                    summary = page["sections"][0]["data"]
                    self.assertEqual(summary["columns"][-1], METRIC)
                    self.assertEqual(summary["formats"][-1], "percent")
                    self.assertEqual([row[-1] for row in summary["rows"]], list(values))
                    composites = [section for section in page["sections"] if section["kind"] == "launch_composite"]
                    self.assertEqual([section["data"]["metrics"][METRIC] for section in composites],
                                     [[None, value, None] for value in values])

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_frontend_curve_and_labels_match_original_progress_without_summary(self):
        runtime = ui_runtime.DashboardTemplateTests.rhythm_runtime()
        for grain in ("day", "week"):
            for values in ((.1, .794, None), (.1, .794, 0), (None, None, None)):
                with self.subTest(grain=grain, values=values):
                    phase = self.phase(values, grain=grain)
                    chart = phase["page"]["sections"][0]["data"]
                    result = subprocess.run(
                        [shutil.which("node"), "-e", runtime + "process.stdout.write(renderLaunch(JSON.parse(process.argv[1])));",
                         json.dumps(chart, ensure_ascii=False)],
                        check=True, capture_output=True, text=True, encoding="utf-8",
                    )
                    html = result.stdout
                    self.assertNotIn("data-launch-rate-summary=", html)
                    self.assertNotIn("launch-rate-summaries", html)
                    self.assertNotIn("截至 ", html)
                    self.assertIn('data-launch-rate-legend="bigRate"', html)
                    expected = [value for value in values if value is not None]
                    points = [float(value) for value in re.findall(
                        r'data-launch-rate-point="bigRate"[^>]*data-value="([^"]+)"', html)]
                    self.assertEqual(points, expected)
                    labels = re.findall(r'data-launch-rate-label="bigRate"[^>]*>([^<]*)</text>', html)
                    self.assertEqual(labels, [f"{value * 100:.1f}%" for value in expected])
                    card_value = self.card(phase)["value"]
                    self.assertEqual(card_value, expected[-1] * 100 if expected else None)
                    self.assertNotIn("NaN", html)


if __name__ == "__main__":
    unittest.main()
