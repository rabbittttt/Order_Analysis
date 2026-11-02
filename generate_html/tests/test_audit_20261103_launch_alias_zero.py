"""A maintained zero must win over legacy launch-metric aliases."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from openpyxl import Workbook
from modules.launch_rhythm import LaunchRhythmModule

MISSING_ROW = object()


class LaunchAliasZeroTests(TestCase):
    def phase(self, overrides, grain="day"):
        book = Workbook()
        self.addCleanup(book.close)
        sheet = book.active
        sheet.title = "问界 M9 2026款by" + ("周" if grain == "week" else "天")
        sheet.append(["指标", "D1", "D2", "D3"])
        sheet.append(["日期", "2026-08-01", "2026-08-02", "2026-08-03"])
        metrics = {
            "当日大定数量": [80, 120, 100], "当日净大定数量": [70, 100, 90],
            "累计小订转大定数量": [20, 40, 60], "累计小订转化率": [.1, .2, .3],
            "累计直接大定数量": [60, 160, 240], "累计交车锁单数量": [30, 80, 150],
        }
        metrics.update(overrides)
        for name, values in metrics.items():
            if values is not MISSING_ROW:
                sheet.append([name, *values])
        return LaunchRhythmModule()._build_phase(SimpleNamespace(path=Path("首销期订单节奏.xlsx")),
                                                sheet, 1, None, True, grain=grain)

    def test_primary_zero_rate_and_quantity_win_over_positive_aliases(self):
        for grain in ("day", "week"):
            with self.subTest(grain=grain):
                phase = self.phase({
                    "累计小订转化率": [0, 0, 0], "累计小转大率": [.2, .3, .4],
                    "累计小订转大定数量": [0, 0, 0], "累计小订转大数量": [10, 20, 40],
                }, grain)
                self.assertEqual(phase["small"], 0)
                self.assertEqual(phase["small_rate"], 0)
                self.assertEqual(phase["page"]["kpis"][2]["value"], 0)
                self.assertEqual(phase["metrics"]["累计小订转化率"], [0, 0, 0])
                self.assertEqual(phase["metrics"]["累计小转大率"], [.2, .3, .4])

    def test_last_known_primary_zero_survives_trailing_unknowns(self):
        phase = self.phase({"累计小订转化率": [.1, 0, None], "累计小转大率": [.2, .3, .4]})
        self.assertEqual(phase["small_rate"], 0)
        self.assertEqual(phase["page"]["kpis"][2]["value"], 0)

    def test_missing_or_empty_primary_still_uses_legacy_alias(self):
        for primary in (MISSING_ROW, [None, None, None]):
            with self.subTest(primary=primary):
                phase = self.phase({
                    "累计小订转化率": primary, "累计小转大率": [.2, .3, .4],
                    "累计小订转大定数量": primary, "累计小订转大数量": [10, 20, 40],
                })
                self.assertEqual(phase["small_rate"], .4)
                self.assertEqual(phase["small"], 40)

    def test_zero_legacy_alias_is_valid_when_primary_absent(self):
        phase = self.phase({
            "累计小订转化率": MISSING_ROW, "累计小转大率": [0, 0, 0],
            "累计小订转大定数量": MISSING_ROW, "累计小订转大数量": [0, 0, 0],
        })
        self.assertEqual(phase["small_rate"], 0)
        self.assertEqual(phase["small"], 0)

    def test_positive_primary_keeps_its_priority(self):
        phase = self.phase({"累计小转大率": [.7, .8, .9], "累计小订转大数量": [200, 400, 600]})
        self.assertEqual(phase["small_rate"], .3)
        self.assertEqual(phase["small"], 60)
        self.assertEqual(phase["page"]["kpis"][2]["value"], 30)

    def test_percent_encoded_zero_is_not_missing(self):
        phase = self.phase({"累计小订转化率": ["0%", "0%", "0%"], "累计小转大率": [.2, .3, .4]})
        self.assertEqual(phase["page"]["kpis"][2]["value"], 0)
