"""Combined generations remain selectable without inflating brand statistics."""
from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook

from core.discovery import discover_subjects, is_valid_subject_name
from core.excel import (
    WorkbookItem, WorkbookStore, is_aggregate_generation, sheet_subject,
    subject_parent, subject_type,
)
from core.models import Subject
from modules.option_fee import OptionFeeModule
from modules.overview import OverviewModule, _group_model_series, _lock_share_rows


COMBINED = (
    "问界 M9&M9U 2026款",
    "尊界 V680&V800 2026款",
    "尚界 Z7&Z7T 2026款",
    "享界 S9&S9T 2026款",
)
FIRST = "问界 M9 2026款"
SECOND = "问界 M9 Ultimate 2026款"
LEGACY = "问界 F2N 2026款汇总"
PERIODS = ("26WK44", "26WK45")


class AmpersandAggregateTests(TestCase):
    def store(self, entries):
        result = WorkbookStore(Path("."))
        result.items = [WorkbookItem(Path(name), book) for name, book in entries]
        self.addCleanup(result.close)
        return result

    def metrics(self, records, lock=False):
        book = Workbook()
        book.remove(book.active)
        for name, quantity in records:
            sheet = book.create_sheet(name + "by周")
            sheet.append(["指标", "统计类型", "分类", *PERIODS])
            primary, secondary = ("交车锁单", "已交付") if lock else ("大定", "留存大定")
            sheet.append([primary, "数量", "数量", quantity, quantity])
            sheet.append([secondary, "数量", "数量", quantity, quantity])
            sheet.append(["版本", "数量", "标准版", quantity, quantity])
        return book

    def test_combination_marker_and_legacy_suffixes_preserve_classification(self):
        for name in (*COMBINED, "尊界 V680&V800", "问界 M9 & M9U 2026款",
                     "问界 F2N 2026款汇总", "问界 M9 2026款总计"):
            with self.subTest(name=name):
                self.assertTrue(is_aggregate_generation(name))
                self.assertTrue(is_valid_subject_name(name))
                self.assertEqual(subject_type(name), "generation")
        for name in (FIRST, SECOND, "尊界 S800典藏大观", "鸿蒙智行", "问界"):
            with self.subTest(name=name):
                self.assertFalse(is_aggregate_generation(name))

    def test_new_names_remain_discoverable_and_map_to_their_own_sheets(self):
        suffixes = (
            "by天", "by周", "by月", "by天第1期", "by天图表", "_SKU",
            "_日度退订", "_选配退订", "_选配渗透率", "_选配渗透率排名",
            "_付费选配占比", "_区域分析",
        )
        book = self.metrics([(name, index + 10) for index, name in enumerate(COMBINED)])
        store = self.store([("鸿蒙智行大定选配比例分析.xlsx", book)])
        with patch("core.discovery.generation_records", return_value=[]):
            subjects = discover_subjects(store)
        by_name = {item.name: item for item in subjects}
        for name in COMBINED:
            with self.subTest(name=name):
                self.assertIn(name, by_name)
                self.assertEqual(by_name[name].type, "generation")
                self.assertEqual(by_name[name].parent, name.split(" ", 1)[0])
                self.assertEqual(subject_parent(name, "generation"), by_name[name].parent)
                for suffix in suffixes:
                    self.assertEqual(sheet_subject(name + suffix), name)
                found = store.find_subject_sheet("大定选配比例", name, "week")
                self.assertIsNotNone(found)
                self.assertEqual(found[1].title, name + "by周")
        self.assertEqual(sheet_subject("尊界 V680&V800_区域分析"), "尊界 V680&V800")
        self.assertEqual(sheet_subject("尊界 V680 & V800_区域分析"), "尊界 V680 & V800")

    def test_brand_lock_share_excludes_combined_and_legacy_aggregate_counts(self):
        records = [("问界", 700), (FIRST, 20), (SECOND, 30), (COMBINED[0], 50), (LEGACY, 9999)]
        store = self.store([
            ("鸿蒙智行大定选配比例分析.xlsx", self.metrics(records)),
            ("鸿蒙智行锁单选配比例分析.xlsx", self.metrics(records, lock=True)),
        ])
        brand = Subject("brand", "问界", "brand", "鸿蒙智行")
        title, rows = _lock_share_rows(store, brand, "week", PERIODS[-1])
        self.assertEqual(title, "各代际交车锁单占比")
        by_name = {row["label"]: row for row in rows}
        self.assertEqual(set(by_name), {FIRST, SECOND})
        self.assertEqual(sum(row["count"] for row in rows), 50)
        self.assertAlmostEqual(by_name[FIRST]["share"], .4)
        self.assertAlmostEqual(by_name[SECOND]["share"], .6)
        # Brand KPIs still use the brand's own physical source; its child chart
        # is the part which must exclude combined generations from the count.
        board = OverviewModule().build(store, brand)
        self.assertIsNotNone(board)
        page = board.views["week"]["pages"][PERIODS[-1]]
        self.assertEqual({item["value"] for item in page["kpis"]}, {700})
        share = next(part for part in page["sections"] if part["title"] == title)
        self.assertEqual({row["label"] for row in share["data"]["rows"]}, {FIRST, SECOND})

    def test_group_model_rankings_keep_individuals_and_exclude_combinations(self):
        records = [(FIRST, 20), (SECOND, 30), (COMBINED[0], 50), (LEGACY, 9999)]
        store = self.store([
            ("鸿蒙智行大定选配比例分析.xlsx", self.metrics(records)),
            ("鸿蒙智行锁单选配比例分析.xlsx", self.metrics(records, lock=True)),
        ])
        series = _group_model_series(store, "week")
        self.assertEqual(set(series), {FIRST, SECOND})
        self.assertEqual(series[FIRST]["交车锁单"][PERIODS[-1]]["metrics"]["交车锁单"], 20)
        # Exclusion from brand/group aggregation must not disable the combined
        # generation's own board when the user selects it explicitly.
        combined = Subject("combined", COMBINED[0], "generation", "问界")
        board = OverviewModule().build(store, combined)
        self.assertIsNotNone(board)
        self.assertEqual(board.views["week"]["pages"][PERIODS[-1]]["kpis"][0]["value"], 50)

    def fee_sheet(self, book, name, free, paid, amount):
        sheet = book.create_sheet(name + "_选配渗透率")
        sheet.cell(3, 3, "26-11")
        for column, band in enumerate(("免费", "0-5000", "总计"), 3):
            sheet.cell(4, column, band)
        sheet.cell(5, 2, "订单数量")
        for column, quantity in enumerate((free, paid, free + paid), 3):
            sheet.cell(5, column, quantity)
        sheet.cell(6, 1, "标准版")
        sheet.cell(6, 2, "选配金额")
        sheet.cell(6, 5, amount)

    def test_brand_fee_totals_do_not_count_combined_generation_twice(self):
        book = Workbook()
        rank = book.active
        rank.title = "问界_选配渗透率排名"
        rank.cell(2, 8, "总计")
        generations = (FIRST, SECOND, COMBINED[0], LEGACY)
        for row, name in enumerate(generations, 3):
            rank.cell(row, 1, name)
            rank.cell(row, 2, 1)
            rank.cell(row, 8, "电动遮阳帘 80%\n(3000)")
        self.fee_sheet(book, FIRST, 20, 80, 6000)
        self.fee_sheet(book, SECOND, 40, 60, 10000)
        self.fee_sheet(book, COMBINED[0], 0, 9999, 900000)
        self.fee_sheet(book, LEGACY, 0, 8888, 800000)
        store = self.store([("鸿蒙智行选配金统计.xlsx", book)])
        with patch("modules.option_fee.LOGGER.warning"):
            board = OptionFeeModule().build(store, Subject("brand", "问界", "brand", "鸿蒙智行"))
        self.assertIsNotNone(board)
        page = board.views["month"]["pages"]["汇总"]
        values = {item["label"]: item["value"] for item in page["kpis"]}
        self.assertEqual(values["平均选配金额"], 8000)
        self.assertEqual(values["付费选配占比"], 70)
        bands = next(part["data"] for part in page["sections"] if part["kind"] == "fee_band_structure")
        self.assertEqual(bands["bands"], ["免费", "0-5000"])
        self.assertEqual({row["label"]: row["values"] for row in bands["rows"]},
                         {FIRST: [20, 80], SECOND: [40, 60]})
        used = {source.sheet for source in board.sources}
        self.assertNotIn(COMBINED[0] + "_选配渗透率", used)
        self.assertNotIn(LEGACY + "_选配渗透率", used)
