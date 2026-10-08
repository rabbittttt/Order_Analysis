from datetime import date, datetime
from pathlib import Path
import unittest

from openpyxl import Workbook
from openpyxl.utils.datetime import to_excel

from core.excel import WorkbookItem, WorkbookStore, parse_metric_sheet
from core.models import Subject
from modules.overview import OverviewModule


class DailyPeriodIdentityTests(unittest.TestCase):
    def book(self, name, kind, periods, values, chart=False):
        book = Workbook()
        sheet = book.active
        sheet.title = name + "by天"
        sheet.append(["指标", "统计类型", "分类", *periods])
        labels = ("大定", "留存大定") if kind == "大定" else ("交车锁单", "已交付")
        for label, row in zip(labels, values):
            sheet.append([label, "数量", "数量", *row])
        if chart:
            sheet = book.create_sheet(name + "by天图表")
            sheet.append([name])
            sheet.append([None, labels[1] if kind == "大定" else labels[0], "2026/10/07"])
            sheet.append([None, "增程", 1])
            sheet.append([None, "总计", 1800 if kind == "大定" else 1702])
        return book

    def store(self, entries):
        store = WorkbookStore(Path("."))
        store.items = [WorkbookItem(Path(f"鸿蒙智行{kind}选配比例分析_{i}.xlsx"), book)
                       for i, (kind, book) in enumerate(entries)]
        self.addCleanup(store.close)
        return store

    def test_group_brand_and_generation_kpis_have_one_real_day(self):
        for name, kind in (("鸿蒙智行", "group"), ("问界", "brand"), ("问界 M9 2026款", "generation")):
            for duplicate in (False, True):
                with self.subTest(name=name, duplicate=duplicate):
                    entries = []
                    for metric, values in (("大定", [[2000], [1800]]), ("锁单", [[1702], [753]])):
                        for day in (["26/10/7", datetime(2026, 10, 7)] if duplicate else ["26/10/7"]):
                            entries.append((metric, self.book(name, metric, [day], values, chart=True)))
                    with self.assertNoLogs("core.excel", level="WARNING"):
                        view = OverviewModule().build(self.store(entries), Subject(name, name, kind)).views["day"]
                    self.assertEqual(view["periods"], ["2026-10-07"])
                    self.assertEqual(view["default_period"], "2026-10-07")
                    self.assertEqual([k["value"] for k in view["pages"]["2026-10-07"]["kpis"]],
                                     [2000, 1800, 1702, 753])

    def test_supported_date_encodings_share_one_key_without_changing_sources(self):
        encodings = ["26/10/7", "2026/10/07", "2026-10-07", "2026.10.7", "2026年10月7日",
                     date(2026, 10, 7), datetime(2026, 10, 7), to_excel(datetime(2026, 10, 7))]
        entries = [("锁单", self.book("问界", "锁单", [day], [[1702], [753]])) for day in encodings]
        store = self.store(entries)
        parsed = parse_metric_sheet(store.find_subject_sheet("锁单选配比例", "问界", "day")[1])
        self.assertEqual(list(parsed), ["2026-10-07"])
        self.assertEqual(parsed["2026-10-07"]["metrics"]["交车锁单"], 1702)
        for (_, book), original in zip(entries, encodings):
            self.assertEqual(book.active["D1"].value, original)

    def test_real_omission_zero_blank_fallback_and_unupdated_day(self):
        first = self.book("问界", "锁单", ["26/10/5", "26/10/7"], [[0, None], [0, 753]])
        second = self.book("问界", "锁单", [date(2026, 10, d) for d in (5, 6, 7, 8)],
                           [[99, 22, 1702, 88], [0, 22, 753, 88]])
        store = self.store([("锁单", first), ("锁单", second)])
        with self.assertLogs("core.excel", level="WARNING"):
            merged = store.find_subject_sheet("锁单选配比例", "问界", "day")[1]
        parsed = parse_metric_sheet(merged)
        self.assertEqual([row["metrics"]["交车锁单"] for row in parsed.values()], [0, 0, 1702, 88])
        self.assertIsNone(first.active["E2"].value)

    def test_chart_dates_are_normalized_before_cross_file_merge(self):
        entries = []
        for day in ("26/10/7", datetime(2026, 10, 7)):
            book = self.book("问界", "锁单", [day], [[1702], [753]], chart=True)
            book.worksheets[1]["C2"] = day
            entries.append(("锁单", book))
        data = self.store(entries).find_chart_data("锁单选配比例", "问界", "day")[2]
        self.assertEqual(data["periods"], ["2026-10-07"])
        self.assertEqual(data["totals"], [1702])

    def test_week_and_month_labels_are_unchanged(self):
        for suffix, period in (("周", "26WK41"), ("月", "26-10")):
            book = self.book("问界", "锁单", [period], [[1702], [753]])
            book.active.title = "问界by" + suffix
            self.assertEqual(list(parse_metric_sheet(book.active)), [period])

    def test_single_source_chart_override_matches_different_date_format(self):
        entries = [(kind, self.book("鸿蒙智行", kind, ["26/10/7"], [[10], [5]], chart=True))
                   for kind in ("大定", "锁单")]
        view = OverviewModule().build(self.store(entries), Subject("g", "鸿蒙智行", "group")).views["day"]
        self.assertEqual([k["value"] for k in view["pages"]["2026-10-07"]["kpis"]],
                         [10, 1800, 1702, 5])


if __name__ == "__main__":
    unittest.main()
