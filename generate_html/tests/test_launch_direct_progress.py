"""First-sale direct-order shares follow matching raw quantity denominators."""
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


METRIC = "累计直接大定占比"
DAILY_METRIC = "每日直接大定占比"
PROGRESS = "累计直接大定进度"
MISSING_ROW = object()


class LaunchDirectProgressTests(unittest.TestCase):
    def phase(self, *, grain="day", phase_number=1, overrides=None, formats=None):
        workbook = Workbook()
        self.addCleanup(workbook.close)
        sheet = workbook.active
        suffix = "by周" if grain == "week" else "by天"
        sheet.title = f"问界 F2N 2026款{suffix}第{phase_number}期"
        periods = ("26WK31", "26WK32", "26WK33") if grain == "week" else ("D1", "D2", "D3")
        sheet.append(["指标", *periods])
        sheet.append(["日期", *[f"2026-08-{phase_number * 3 + offset:02d}" for offset in range(3)]])
        metrics = {
            "当日大定数量": [80, 120, 100],
            "当日净大定数量": [70, 100, 90],
            "当日小订转大定数量": [20, 20, 20],
            "当日直接大定数量": [60, 100, 80],
            "累计小订转大定数量": [20, 40, 60],
            "累计直接大定数量": [60, 160, 240],
            "累计交车锁单数量": [30, 80, 150],
            "累计小订转化率": [.1, .2, .3],
            DAILY_METRIC: [.99, .99, .99],
            METRIC: [.9, .9, .9],
            PROGRESS: [.1, .5, 1],
        }
        metrics.update(overrides or {})
        for name, values in metrics.items():
            if values is MISSING_ROW:
                continue
            sheet.append([name, *values])
            for cell in sheet[sheet.max_row][1:]:
                cell.number_format = (formats or {}).get(name, "General")
        return LaunchRhythmModule()._build_phase(
            SimpleNamespace(path=Path("首销期订单节奏.xlsx")), sheet,
            phase_number, None, True, grain=grain,
        )

    def card(self, phase):
        card = phase["page"]["kpis"][3]
        self.assertEqual(card["label"], METRIC)
        return card

    def test_day_and_week_use_quantity_shares_not_old_progress_or_maintained_share(self):
        for grain in ("day", "week"):
            with self.subTest(grain=grain):
                phase = self.phase(grain=grain)
                self.assertEqual(phase["metrics"][DAILY_METRIC], [.75, 100 / 120, .8])
                self.assertEqual(phase["metrics"][METRIC], [.75, .8, .8])
                self.assertEqual(self.card(phase)["value"], 80)
                self.assertEqual(phase["direct_share"], .8)
                self.assertEqual(phase["metrics"][PROGRESS], [.1, .5, 1])
                self.assertEqual([c["value"] for c in phase["page"]["kpis"][:3]], [300, 150, 30])

    def test_explicit_cumulative_gross_is_the_primary_denominator(self):
        for name in ("累计大定数量", "累计总大定数量"):
            with self.subTest(name=name):
                phase = self.phase(overrides={name: [100, 400, 600]})
                self.assertEqual(phase["metrics"][METRIC], [.6, .4, .4])
                self.assertEqual(self.card(phase)["value"], 40)

    def test_explicit_zero_gross_does_not_fall_back_to_components(self):
        phase = self.phase(overrides={
            "累计总大定数量": [0, 0, 0],
            "累计大定数量": [100, 400, 600],
        })
        self.assertEqual(phase["metrics"][METRIC], [None, None, None])
        self.assertIsNone(self.card(phase)["value"])

    def test_cumulative_fallback_uses_same_column_components(self):
        phase = self.phase(overrides={
            "累计大定数量": [100, None, ""],
            "累计小订转大定数量": [40, 40, 60],
        })
        self.assertEqual(phase["metrics"][METRIC], [.6, .8, .8])
        phase = self.phase(overrides={
            "累计小订转大定数量": MISSING_ROW,
            "累计小订转大数量": [20, 40, 60],
        })
        self.assertEqual(phase["metrics"][METRIC], [.75, .8, .8])

    def test_missing_counts_never_use_maintained_share_or_partial_daily_sum(self):
        for overrides in (
            {"累计小订转大定数量": MISSING_ROW},
            {"累计直接大定数量": MISSING_ROW},
            {"累计小订转大定数量": [None, None, None]},
        ):
            with self.subTest(overrides=overrides):
                phase = self.phase(overrides=overrides)
                self.assertEqual(phase["metrics"][METRIC], [None, None, None])
                self.assertIsNone(self.card(phase)["value"])
                self.assertEqual(phase["orders"], 300)
        phase = self.phase(overrides={"当日大定数量": [80, None, 100]})
        self.assertEqual(phase["metrics"][DAILY_METRIC], [.75, None, .8])

    def test_zero_numerator_positive_denominator_and_zero_denominator(self):
        phase = self.phase(overrides={
            "当日直接大定数量": [0, 0, 0],
            "当日大定数量": [10, 0, 20],
            "累计直接大定数量": [0, 0, 0],
            "累计大定数量": [10, 0, 20],
        })
        self.assertEqual(phase["metrics"][DAILY_METRIC], [0, None, 0])
        self.assertEqual(phase["metrics"][METRIC], [0, None, 0])
        self.assertEqual(self.card(phase)["value"], 0)

    def test_boolean_negative_nonfinite_and_error_quantities_are_unknown(self):
        for invalid in (True, False, -1, float("nan"), float("inf"), "#DIV/0!", "—", ""):
            with self.subTest(invalid=invalid):
                phase = self.phase(overrides={
                    "当日直接大定数量": [invalid] * 3,
                    "累计直接大定数量": [invalid] * 3,
                })
                self.assertEqual(phase["metrics"][DAILY_METRIC], [None] * 3)
                self.assertEqual(phase["metrics"][METRIC], [None] * 3)
                self.assertIsNone(self.card(phase)["value"])
        phase = self.phase(overrides={"当日大定数量": [True, False, -1]})
        self.assertEqual(phase["metrics"][DAILY_METRIC], [None] * 3)

    def test_card_uses_the_last_valid_same_column_pair(self):
        for tail in (None, "", 0, "#DIV/0!"):
            with self.subTest(tail=tail):
                phase = self.phase(overrides={
                    "累计大定数量": [100, 400, tail],
                    "累计小订转大定数量": MISSING_ROW,
                })
                self.assertEqual(phase["metrics"][METRIC], [.6, .4, None])
                self.assertEqual(self.card(phase)["value"], 40)
                self.assertEqual(phase["direct_share_numerator"], 160)
                self.assertEqual(phase["direct_share_denominator"], 400)
        phase = self.phase(overrides={
            "累计直接大定数量": [60, None, None],
            "累计大定数量": [None, 400, None],
            "累计小订转大定数量": MISSING_ROW,
        })
        self.assertEqual(phase["metrics"][METRIC], [None] * 3)
        self.assertIsNone(self.card(phase)["value"])

    def test_original_progress_and_other_percentage_rows_keep_their_formats(self):
        for value, number_format in (("79.4%", "General"), ("79.4％", "General"),
                                      (79.4, "General"), (.794, "General"), (.794, "0.0%")):
            with self.subTest(value=value, number_format=number_format):
                phase = self.phase(
                    overrides={PROGRESS: [0, value, None], "外部参考占比": [0, value, None]},
                    formats={PROGRESS: number_format, "外部参考占比": number_format})
                self.assertEqual(phase["metrics"][PROGRESS], [0, .794, None])
                self.assertEqual(phase["metrics"]["外部参考占比"], [0, .794, None])
                self.assertEqual(self.card(phase)["value"], 80)
                matrix = next(s for s in phase["page"]["sections"] if s["kind"] == "matrix")
                row = next(r for r in matrix["data"]["rows"] if r[0] == "外部参考占比")
                self.assertEqual(row, ["外部参考占比", "0.0%", "79.4%", None])

    def test_matrix_shares_are_percentages_and_week_label_is_period_specific(self):
        for grain in ("day", "week"):
            with self.subTest(grain=grain):
                phase = self.phase(grain=grain)
                matrix = next(s for s in phase["page"]["sections"] if s["kind"] == "matrix")
                rows = {r[0]: r for r in matrix["data"]["rows"]}
                label = "当周直接大定占比" if grain == "week" else DAILY_METRIC
                self.assertEqual(rows[label], [label, "75.0%", "83.3%", "80.0%"])
                self.assertEqual(rows[METRIC], [METRIC, "75.0%", "80.0%", "80.0%"])
                self.assertEqual(rows[PROGRESS], [PROGRESS, "10.0%", "50.0%", "100.0%"])

    def test_multiphase_share_uses_quantity_weighting_and_keeps_phase_rows(self):
        for grain in ("day", "week"):
            with self.subTest(grain=grain):
                phases = [
                    self.phase(grain=grain, phase_number=1, overrides={
                        "累计直接大定数量": [None, None, 20], "累计大定数量": [None, None, 100]}),
                    self.phase(grain=grain, phase_number=2, overrides={
                        "累计直接大定数量": [None, None, 270], "累计大定数量": [None, None, 300]}),
                ]
                page = LaunchRhythmModule._combined_page(phases)
                self.assertEqual(page["kpis"][3]["label"], METRIC)
                self.assertAlmostEqual(page["kpis"][3]["value"], 72.5)
                self.assertNotAlmostEqual(page["kpis"][3]["value"], 55)
                summary = page["sections"][0]["data"]
                self.assertEqual(summary["columns"][-1], METRIC)
                self.assertEqual(summary["formats"][-1], "percent")
                self.assertEqual([r[-1] for r in summary["rows"]], [.2, .9])
                self.assertEqual(len([s for s in page["sections"] if s["kind"] == "launch_composite"]), 2)

    def test_multiphase_missing_pair_is_unknown_and_zero_share_is_included(self):
        first = self.phase(overrides={
            "累计直接大定数量": [None, None, 20], "累计大定数量": [None, None, 100]})
        for direct, gross, expected in ((0, 100, 10), (None, 100, None), (0, 0, 20), (20, 0, None)):
            with self.subTest(direct=direct, gross=gross):
                second = self.phase(phase_number=2, overrides={
                    "累计直接大定数量": [None, None, direct],
                    "累计大定数量": [None, None, gross],
                    "累计小订转大定数量": MISSING_ROW})
                page = LaunchRhythmModule._combined_page([first, second])
                self.assertEqual(page["kpis"][3]["value"], expected)


    def test_missing_or_invalid_legacy_progress_does_not_erase_quantity_shares(self):
        for progress in (MISSING_ROW, [None, None, None],
                         ["#DIV/0!", "—", ""], [float("nan"), float("inf"), None]):
            with self.subTest(progress=progress):
                phase = self.phase(overrides={PROGRESS: progress})
                self.assertEqual(phase["metrics"][METRIC], [.75, .8, .8])
                self.assertEqual(self.card(phase)["value"], 80)
                self.assertEqual(phase["metrics"]["当日大定数量"], [80, 120, 100])
                self.assertEqual(phase["metrics"]["当日直接大定数量"], [60, 100, 80])
                self.assertEqual(phase["metrics"]["累计直接大定数量"], [60, 160, 240])

    def test_multiphase_known_zero_pairs_are_quantities_with_unknown_individual_rates(self):
        phases = [self.phase(phase_number=index, overrides={
            "累计直接大定数量": [0, 0, 0],
            "累计总大定数量": [0, 0, 0],
        }) for index in (1, 2)]
        for phase in phases:
            self.assertIsNone(self.card(phase)["value"])
            self.assertIsNone(phase["direct_share"])
            self.assertEqual((phase["direct_share_numerator"], phase["direct_share_denominator"]), (0, 0))
        all_zero = LaunchRhythmModule._combined_page(phases)
        self.assertIsNone(all_zero["kpis"][3]["value"])
        nonzero = self.phase(phase_number=3, overrides={
            "累计直接大定数量": [None, None, 20],
            "累计总大定数量": [None, None, 100],
        })
        combined = LaunchRhythmModule._combined_page([nonzero, phases[0]])
        self.assertEqual(combined["kpis"][3]["value"], 20)
        self.assertEqual([row[-1] for row in combined["sections"][0]["data"]["rows"]], [.2, None])

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_frontend_all_share_points_have_labels_and_no_upper_summary(self):
        runtime = ui_runtime.DashboardTemplateTests.rhythm_runtime()
        for grain in ("day", "week"):
            for totals in ([100, 400, 600], [100, None, 0], [0, 0, 0]):
                with self.subTest(grain=grain, totals=totals):
                    phase = self.phase(grain=grain, overrides={
                        "累计大定数量": totals, "累计小订转大定数量": MISSING_ROW})
                    chart = phase["page"]["sections"][0]["data"]
                    result = subprocess.run(
                        [shutil.which("node"), "-e", runtime + "process.stdout.write(renderLaunch(JSON.parse(process.argv[1])));",
                         json.dumps(chart, ensure_ascii=False)], check=True,
                        capture_output=True, text=True, encoding="utf-8")
                    html = result.stdout
                    self.assertNotIn("data-launch-rate-summary=", html)
                    self.assertNotIn("launch-rate-summaries", html)
                    self.assertNotIn("截至 ", html)
                    self.assertIn('data-launch-rate-legend="bigRate"', html)
                    self.assertIn(METRIC, html)
                    expected = [v for v in phase["metrics"][METRIC] if v is not None]
                    points = [float(v) for v in re.findall(
                        r'data-launch-rate-point="bigRate"[^>]*data-value="([^"]+)"', html)]
                    self.assertEqual(points, expected)
                    labels = re.findall(r'data-launch-rate-label="bigRate"[^>]*>([^<]*)</text>', html)
                    self.assertEqual(labels, [f"{v * 100:.1f}%" for v in expected])
                    self.assertEqual(self.card(phase)["value"], expected[-1] * 100 if expected else None)
                    self.assertNotIn("NaN", html)


if __name__ == "__main__":
    unittest.main()
