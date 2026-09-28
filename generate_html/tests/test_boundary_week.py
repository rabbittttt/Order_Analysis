from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook

from core.excel import WorkbookItem, WorkbookStore, _week_period, _source_date_range, display_period, parse_metric_sheet
from core.forecast_summary import INDEX_SHEET, summary_scope
from modules.conversion import ConversionModule, STAGES
from modules.sales_forecast import _read_steady_history
from core.models import Subject


MODEL = "问界 M9 2026款"


class BoundaryWeekTests(unittest.TestCase):
    def store(self, books, keyword="锁单选配比例分析", ranges=None, infer_test_ranges=True):
        if ranges is None and infer_test_ranges:
            week = next((week for book in books for sheet in book.worksheets
                         for row in sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 3), values_only=True)
                         for value in row if (week := _week_period(str(value))) and week[3]), None)
            if week:
                cutoff = date(week[1].year, 12, 31) if week[3] == "跨年" else date(week[1].year, 6, 30)
                ranges = [(week[1], cutoff), *[(date(cutoff.year + 1, 1, 1) if cutoff.month == 12
                                               else date(cutoff.year, 7, 1), week[2])] * (len(books) - 1)]
        if "订单7级转化" not in keyword:
            for book, span in zip(books, ranges or []):
                sheet = book.create_sheet(MODEL + "by天")
                sheet.append(["指标", "统计类型", "分类", *span])
                sheet.append(["交车锁单", "数量", "数量", 1, 1])
        store = WorkbookStore(Path("."))
        store.items = [WorkbookItem(Path(f"{keyword}_{index}.xlsx"), book) for index, book in enumerate(books)]
        if "订单7级转化" in keyword:
            # Record-only fixtures receive the original coverage evidence just
            # as summary_scope restores it from the imported source directory.
            for item, span in zip(store.items, ranges or []):
                item._boundary_date_range = span
        self.addCleanup(store.close)
        return store

    def metric(self, period, quantity, share=None):
        book = Workbook()
        sheet = book.active
        sheet.title = MODEL + "by周"
        sheet.append(["指标", "统计类型", "分类", period])
        sheet.append(["交车锁单", "数量", "数量", quantity])
        if share is not None:
            sheet.append(["版本", "占比", "A", share])
            sheet.append([None, None, "B", 1 - share])
        return book

    def test_boundaries_use_calendar_not_hardcoded_years(self):
        for period, reason in [("26WK53", "跨年"), ("2026WK53", "跨年"), ("26WK27", "跨半年"),
                               ("25WK27", "跨半年"), ("24WK26", ""), ("23WK52", ""), ("26WK28", "")]:
            with self.subTest(period=period):
                self.assertEqual(_week_period(period)[3], reason)
        self.assertIsNone(_week_period("25WK53"))
        self.assertIsNone(_week_period("26-06"))
        self.assertEqual(display_period("2026WK53"), "26WK53")

    def test_boundary_quantities_sum_and_week_aliases_align(self):
        for period, alias, reason in [("26WK53", "2026WK53", "跨年"), ("26WK27", "26wk27", "跨半年")]:
            with self.subTest(period=period):
                books = [self.metric(period, 140), self.metric(alias, 90)]
                store = self.store(books)
                with self.assertLogs("core.excel", level="INFO") as logs:
                    _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
                parsed = parse_metric_sheet(sheet)
                self.assertEqual(list(parsed), [period])
                self.assertEqual(parsed[period]["metrics"]["交车锁单"], 230)
                self.assertIn("边界周累加", "\n".join(logs.output))
                self.assertIn(reason, "\n".join(logs.output))
                self.assertIn("→ 230", "\n".join(logs.output))
                self.assertEqual(books[0].active["D2"].value, 140)
                self.assertEqual(len(sheet._source_matches), 2)

    def test_sunday_cutoffs_and_regular_weeks_keep_conflict_priority(self):
        for period in ["24WK26", "23WK52", "26WK28"]:
            with self.subTest(period=period):
                store = self.store([self.metric(period, 140), self.metric(period, 90)])
                with self.assertLogs("core.excel", level="WARNING"):
                    _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
                self.assertEqual(parse_metric_sheet(sheet)[period]["metrics"]["交车锁单"], 140)
                self.assertEqual(sheet._boundary_week_merges, [])

    def test_identical_pieces_stay_deduplicated_after_sum(self):
        store = self.store([self.metric("26WK53", value) for value in [140, 90, 140, 230]])
        _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        self.assertEqual(parse_metric_sheet(sheet)["26WK53"]["metrics"]["交车锁单"], 230)
        same = self.store([self.metric("26WK53", 140), self.metric("26WK53", 140)])
        with patch("core.excel.LOGGER.info") as log:
            _, sheet = same.find_subject_sheet("锁单选配比例", MODEL, "week")
        log.assert_not_called()
        self.assertEqual(parse_metric_sheet(sheet)["26WK53"]["metrics"]["交车锁单"], 140)

    def test_boundary_zero_is_added_but_invalid_values_are_not(self):
        store = self.store([self.metric("26WK53", 0), self.metric("26WK53", 90)])
        _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        self.assertEqual(parse_metric_sheet(sheet)["26WK53"]["metrics"]["交车锁单"], 90)
        for invalid in [-1, "not a number", float("inf")]:
            with self.subTest(invalid=invalid):
                store = self.store([self.metric("26WK53", 140), self.metric("26WK53", invalid)])
                with patch("core.excel.LOGGER.warning"):
                    _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
                self.assertEqual(parse_metric_sheet(sheet)["26WK53"]["metrics"]["交车锁单"], 140)

    def test_shares_are_weighted_not_added(self):
        store = self.store([self.metric("26WK53", 140, .4), self.metric("26WK53", 90, .8)])
        with patch("core.excel.LOGGER.warning") as warning:
            _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        warning.assert_not_called()
        rows = parse_metric_sheet(sheet)["26WK53"]["structures"]["版本"]
        self.assertAlmostEqual(rows[0]["share"], (140 * .4 + 90 * .8) / 230)
        self.assertAlmostEqual(sum(row["share"] for row in rows), 1)

    def test_shares_recalculate_from_summed_category_counts(self):
        books = [self.metric("26WK53", 140, .4), self.metric("26WK53", 90, .8)]
        for book, counts in zip(books, [(56, 84), (72, 18)]):
            book.active.append(["版本", "数量", "A", counts[0]])
            book.active.append([None, None, "B", counts[1]])
        store = self.store(books)
        _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        rows = parse_metric_sheet(sheet)["26WK53"]["structures"]["版本"]
        self.assertEqual([row["count"] for row in rows], [128, 102])
        self.assertAlmostEqual(rows[0]["share"], 128 / 230)

    def test_conversion_adds_counts_not_average_days_and_derives_rates(self):
        books = []
        for quantities, days in [([100, 95, 90, 80, 75, 72, 70], 3.5), ([50, 45, 40, 35, 30, 25, 20], 5.5)]:
            book = Workbook()
            sheet = book.active
            sheet.title = MODEL + "by周"
            sheet.append(["名称", "周", *STAGES, "大定到交车锁单（天）", "交车锁单到交付（天）"])
            sheet.append([None, None, *["数量"] * len(STAGES), None, None])
            sheet.append(["总计", "26WK53", *quantities, days, 18])
            books.append(book)
        store = self.store(books, "订单7级转化")
        with patch("core.excel.LOGGER.warning"):
            dashboard = ConversionModule().build(store, Subject("m9", MODEL, "generation", "问界"))
        page = dashboard.views["week"]["pages"]["26WK53"]
        funnel = next(section["data"] for section in page["sections"] if section["kind"] == "funnel")
        self.assertEqual(funnel[0]["value"], 150)
        self.assertEqual(funnel[-1]["value"], 90)
        self.assertAlmostEqual(funnel[-1]["total_rate"], .6)
        self.assertEqual(store.find("订单7级转化").workbook.worksheets[0].cell(3, 10).value, 3.5)

    def test_chart_total_and_shares_follow_the_same_rule_without_repeat_logs(self):
        books = []
        for period, total, rate in [("26WK53", 140, .4), ("2026WK53", 90, .8), ("26WK53", 140, .4)]:
            book = Workbook()
            sheet = book.active
            sheet.title = "问界净大定by周图表"
            sheet.append([MODEL])
            sheet.append([None, "留存大定", period])
            sheet.append([None, "A", rate])
            sheet.append([None, "B", 1 - rate])
            sheet.append([None, "总计", total])
            books.append(book)
        store = self.store(books, "大定选配比例分析")
        with self.assertLogs("core.excel", level="INFO") as logs:
            data = store.find_chart_data("大定选配比例", MODEL, "week")[2]
            store.find_chart_data("大定选配比例", MODEL, "week")
        self.assertEqual(data["periods"], ["26WK53"])
        self.assertEqual(data["totals"], [230])
        self.assertAlmostEqual(data["series"][0]["values"][0], 128 / 230)
        self.assertEqual(sum("边界周累加" in line for line in logs.output), 1)

    def test_steady_forecast_receives_the_complete_merged_week(self):
        store = self.store([self.metric("26WK53", 140), self.metric("26WK53", 90)])
        with patch("modules.sales_forecast._read_model_mapping", return_value={}), patch(
            "modules.sales_forecast._read_model_master", return_value={}
        ):
            rows, _ = _read_steady_history(store, {"m9": {"generation": MODEL, "end_date": "2026-11-30"}}, date(2027, 1, 11))
        self.assertEqual(rows[0]["weeks"][0]["lock"], 230)
        self.assertEqual(rows[0]["weeks"][0]["start_date"], "2026-12-28")
        self.assertEqual(rows[0]["weeks"][0]["end_date"], "2027-01-03")

    def test_sku_count_blocks_add_without_summing_percentage_blocks(self):
        books = []
        for quantity in [140, 90]:
            book = Workbook()
            sheet = book.active
            sheet.title = MODEL + "_SKU"
            share = .4 if quantity == 140 else .8
            sheet.append(["累计锁单", None, None, None, "总计占比", None, None])
            sheet.append(["SKU", "26WK53", "总计", None, "SKU", "26WK53", "总计"])
            sheet.append(["版本A", quantity, quantity, None, "版本A", share, share])
            books.append(book)
        store = self.store(books, "SKU收敛度报告")
        with self.assertLogs("core.excel", level="INFO") as logs:
            sheet = store.find("SKU").workbook.worksheets[0]
        self.assertEqual(sheet.cell(3, 2).value, 230)
        self.assertEqual(sheet.cell(3, 3).value, 140)  # Annual totals are not additive.
        self.assertEqual(sheet.cell(3, 6).value, .4)  # No percentage summation.
        self.assertTrue(any("边界周累加" in line for line in logs.output))

    def test_file_already_crosses_boundary_is_not_added(self):
        books = [self.metric("26WK27", 1853), self.metric("26WK27", 3)]
        store = self.store(books, ranges=[(date(2026, 1, 1), date(2026, 7, 5)),
                                         (date(2026, 7, 1), date(2026, 7, 5))])
        with patch("core.excel.LOGGER.info") as info, patch("core.excel.LOGGER.warning"):
            _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        self.assertEqual(parse_metric_sheet(sheet)["26WK27"]["metrics"]["交车锁单"], 1853)
        self.assertEqual(sheet._boundary_week_merges, [])
        info.assert_not_called()

    def test_unknown_overlapping_gap_and_unrelated_ranges_do_not_add(self):
        cases = [None,
                 [(date(2026, 6, 29), date(2026, 6, 30)), (date(2026, 6, 30), date(2026, 7, 5))],
                 [(date(2026, 6, 29), date(2026, 6, 29)), (date(2026, 7, 1), date(2026, 7, 5))],
                 [(date(2021, 1, 1), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 7, 5))]]
        for ranges in cases:
            with self.subTest(ranges=ranges):
                store = self.store([self.metric("26WK27", 140), self.metric("26WK27", 90)],
                                   ranges=ranges, infer_test_ranges=False)
                with patch("core.excel.LOGGER.warning"):
                    _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
                self.assertEqual(parse_metric_sheet(sheet)["26WK27"]["metrics"]["交车锁单"], 140)
                self.assertEqual(sheet._boundary_week_merges, [])

    def test_one_physical_file_never_enters_addition(self):
        book = self.metric("26WK53", 140)
        store = self.store([book], ranges=[(date(2026, 1, 1), date(2027, 1, 3))])
        _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        self.assertEqual(parse_metric_sheet(sheet)["26WK53"]["metrics"]["交车锁单"], 140)

    def test_future_blank_columns_do_not_make_a_file_cross_the_cut(self):
        book = self.metric("26WK27", 140)
        store = self.store([book], ranges=[(date(2026, 6, 29), date(2026, 6, 30))])
        book.worksheets[1].cell(1, 6, date(2026, 7, 1))
        self.assertEqual(_source_date_range(store.items[0]), (date(2026, 6, 29), date(2026, 6, 30)))

    def test_sparse_old_model_uses_whole_file_dates_including_real_zero(self):
        books = [self.metric("26WK27", 1), self.metric("26WK27", 2)]
        for book, sold in zip(books, [date(2026, 6, 29), date(2026, 7, 3)]):
            daily = book.create_sheet(MODEL + "by天")
            daily.append(["指标", "统计类型", "分类", sold])
            daily.append(["交车锁单", "数量", "数量", 1])
        for book, days in zip(books, [(date(2026, 6, 29), date(2026, 6, 30)),
                                      (date(2026, 7, 1), date(2026, 7, 5))]):
            daily = book.create_sheet("鸿蒙智行by天")
            daily.append(["指标", "统计类型", "分类", *days])
            daily.append(["交车锁单", "数量", "数量", 0, 0])
        store = self.store(books, infer_test_ranges=False)
        self.assertEqual(_source_date_range(store.items[0]), (date(2026, 6, 29), date(2026, 6, 30)))
        self.assertEqual(_source_date_range(store.items[1]), (date(2026, 7, 1), date(2026, 7, 5)))
        _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        self.assertEqual(parse_metric_sheet(sheet)["26WK27"]["metrics"]["交车锁单"], 3)

    def test_sparse_model_cannot_hide_that_its_file_already_crosses_cut(self):
        books = [self.metric("26WK27", 1), self.metric("26WK27", 2)]
        store = self.store(books, ranges=[(date(2026, 6, 29), date(2026, 6, 30)),
                                         (date(2026, 7, 1), date(2026, 7, 5))])
        other = books[0].create_sheet("鸿蒙智行by天")
        other.append(["指标", "统计类型", "分类", date(2026, 7, 5)])
        other.append(["交车锁单", "数量", "数量", 5])
        with patch("core.excel.LOGGER.warning"), patch("core.excel.LOGGER.info") as info:
            _, sheet = store.find_subject_sheet("锁单选配比例", MODEL, "week")
        self.assertEqual(parse_metric_sheet(sheet)["26WK27"]["metrics"]["交车锁单"], 1)
        info.assert_not_called()

    def test_summary_preserves_original_file_ranges_even_without_importing_daily_sheets(self):
        book = Workbook()
        directory = book.active
        directory.title = INDEX_SHEET
        directory.append(["类别", "原始文件", "原始Sheet", "汇总Sheet", "文件数据开始日期", "文件数据结束日期"])
        for index, (quantity, start, end) in enumerate([(140, "2026-06-29", "2026-06-30"), (90, "2026-07-01", "2026-07-05")]):
            stored = book.create_sheet(f"source{index}")
            for row in self.metric("26WK27", quantity).active.iter_rows(values_only=True):
                stored.append(row)
            directory.append(["订单", f"锁单选配比例_{index}.xlsx", MODEL + "by周", stored.title, start, end])
        with summary_scope(Path("summary.xlsx"), workbook=book) as active:
            _, sheet = active["store"].find_subject_sheet("锁单选配比例", MODEL, "week")
            self.assertEqual(parse_metric_sheet(sheet)["26WK27"]["metrics"]["交车锁单"], 230)

    def test_compact_source_directory_keeps_physical_file_dates(self):
        from tools.refresh_sales_forecast_data import compact_source_sheets

        book = Workbook()
        directory = book.active
        directory.title = INDEX_SHEET
        directory.append(["类别", "原始文件", "原始Sheet", "汇总Sheet", "行数", "列数", "阅读用途",
                          "文件数据开始日期", "文件数据结束日期"])
        for name in ["源_平销_001", "源_平销_002"]:
            book.create_sheet(name)
            directory.append(["订单", "锁单选配比例.xlsx", name, name, 2, 4, "订单", "2026-07-01", "2026-07-05"])
        compact_source_sheets(book)
        row = next(book[INDEX_SHEET].iter_rows(min_row=2, values_only=True))
        self.assertEqual(row[2], 2)
        self.assertEqual(row[-2:], ("2026-07-01", "2026-07-05"))
        self.assertFalse(any(name.startswith("源_") for name in book.sheetnames))

    def test_summary_does_not_infer_narrower_ranges_from_imported_subset(self):
        for original_range in [(None, None), ("2026-01-01", "2026-07-05")]:
            with self.subTest(original_range=original_range):
                book = Workbook()
                directory = book.active
                directory.title = INDEX_SHEET
                directory.append(["类别", "原始文件", "原始Sheet", "汇总Sheet",
                                  "文件数据开始日期", "文件数据结束日期"])
                for index, (quantity, span, evidence) in enumerate([
                    (140, (date(2026, 6, 29), date(2026, 6, 30)), original_range),
                    (90, (date(2026, 7, 1), date(2026, 7, 5)), ("2026-07-01", "2026-07-05")),
                ]):
                    stored = book.create_sheet(f"source{index}")
                    for row in self.metric("26WK27", quantity).active.iter_rows(values_only=True):
                        stored.append(row)
                    daily = book.create_sheet(f"daily{index}")
                    daily.append(["指标", "统计类型", "分类", *span])
                    daily.append(["交车锁单", "数量", "数量", 1, 1])
                    for sheet, original in [(stored, MODEL + "by周"), (daily, MODEL + "by天")]:
                        directory.append(["订单", f"锁单选配比例_{index}.xlsx", original, sheet.title, *evidence])
                with summary_scope(Path("summary.xlsx"), workbook=book) as active, patch("core.excel.LOGGER.warning"):
                    _, sheet = active["store"].find_subject_sheet("锁单选配比例", MODEL, "week")
                    self.assertEqual(parse_metric_sheet(sheet)["26WK27"]["metrics"]["交车锁单"], 140)


if __name__ == "__main__":
    unittest.main()
