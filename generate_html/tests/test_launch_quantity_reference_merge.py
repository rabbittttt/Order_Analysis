"""Day-wise source selection owns both visible quantities and derived ratios."""
from datetime import date, datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from core.forecast_summary import DAILY_SHEET, MASTER_SHEET, D12_SHEET, LAUNCH_CANCEL_DAILY_SHEET, table_records, summary_scope
from modules.sales_forecast import _read_history
from tools.refresh_sales_forecast_data import reorder_summary_sheets, audit_source_retention
from tests import test_forecast_reference_backfill as fixtures
from tests import test_forecast_source_backfill_e2e as source_fixtures


class LaunchQuantityReferenceMergeTests(TestCase):
    model = '享界 G9 2027款'

    def build(self, **kwargs):
        return fixtures.ForecastReferenceBackfillTests.build(self, **kwargs)

    def values(self, book, sheet):
        row = table_records(book, sheet)[0]
        return [row.get(f'D{i}') for i in (1, 2, 3)]

    def cancel_export_issues(self, book):
        return [message for message in audit_source_retention(book, []) if f'Sheet={LAUNCH_CANCEL_DAILY_SHEET}' in message]

    def test_sources_merge_each_day_before_all_ratios_and_d12(self):
        book = self.build(
            daily=[{'date': f'2026-01-0{i}', 'gross': g, 'small_to_big': s, 'direct': d}
                   for i, g, s, d in ((3, 50, 20, 30), (4, 20, 8, 12), (5, 30, 12, 18))],
            history={'小转大当日数量': {'测试车': [4, None, 0]},
                     '直接大定当日数量': {'测试车': [6, None, 0]},
                     '总大定当日数量': {'测试车': [10, None, 0]},
                     LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [2, None, 0]}},
            cancel=[{'date': '2026-01-02', 'cancel': 3},
                    {'date': '2026-01-03', 'cancel': 8, 'daily_cancel': 5},
                    {'date': '2026-01-04', 'cancel': 12, 'daily_cancel': 4},
                    {'date': '2026-01-05', 'cancel': 14, 'daily_cancel': 2}])
        self.assertEqual(self.values(book, '大定当日数量'), [10, 20, 0])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [5, 4, 0])
        for sheet, expected in (
            ('小转大累计完成度', [1/3, 1, 1]), ('直接大定累计完成度', [1/3, 1, 1]),
            ('大定累计完成度', [1/3, 1, 1]), ('累计小订转化率', [.2, .6, .6]),
            ('累计退订率', [.25, .45, .45]), ('累计直接大定占比', [.6, .6, .6])):
            with self.subTest(sheet=sheet):
                for actual, value in zip(self.values(book, sheet), expected):
                    self.assertAlmostEqual(actual, value)
        self.assertEqual(self.values(book, '每日直接大定占比'), [.6, .6, None])
        master = table_records(book, MASTER_SHEET)[0]
        self.assertEqual((master['总大定'], master['总退订']), (30, 9))
        metrics = table_records(book, D12_SHEET)[0]
        self.assertEqual((metrics['D1退订'], metrics['D2退订'], metrics['D1+D2退订']), (2, 4, 6))
        self.assertEqual((metrics['D1退订率'], metrics['D2退订率']), (.1, .2))
        rows = {row['日期'].date(): row for row in table_records(book, DAILY_SHEET)}
        self.assertIn('小订及首销数据整理.xlsx', rows[date(2026, 1, 3)]['字段来源'])
        self.assertIn('小订退订分析.xlsx', rows[date(2026, 1, 4)]['字段来源'])

    def test_blank_middle_day_keeps_known_prefix_and_later_actual_anchor(self):
        book = self.build(history={LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [2, None, 3]}},
                          cancel=[{'date': '2026-01-03', 'cancel': 2},
                                  {'date': '2026-01-05', 'cancel': 7, 'daily_cancel': 2}])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [2, None, 3])
        self.assertEqual(self.values(book, '累计退订率'), [.1, None, .35])
        self.assertEqual(table_records(book, MASTER_SHEET)[0]['总退订'], 7)

    def test_g9_cumulative_baseline_continues_with_history_after_source_d1(self):
        book = self.build(small_total=24088,
            history={LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [974, 10, 0]}},
            cancel=[{'date': '2026-01-02', 'cancel': 2646, 'daily_cancel': 347},
                    {'date': '2026-01-03', 'cancel': 3620, 'daily_cancel': 974}])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [3620, 10, 0])
        self.assertEqual(self.values(book, '累计退订率'), [3620/24088, 3630/24088, 3630/24088])
        self.assertEqual(table_records(book, MASTER_SHEET)[0]['总退订'], 3630)
        first = next(r for r in table_records(book, DAILY_SHEET) if r['日期'].date() == date(2026, 1, 3))
        self.assertEqual(first['退订数量'], 974)
        self.assertEqual(table_records(book, D12_SHEET)[0]['D1退订'], 974)
        counts = self.values(book, LAUNCH_CANCEL_DAILY_SHEET)
        for i, rate in enumerate(self.values(book, '累计退订率'), 1):
            self.assertAlmostEqual(sum(counts[:i])/24088, rate)
        self.assertEqual(self.cancel_export_issues(book), [])

    def test_first_source_cumulative_and_daily_establish_prelaunch_baseline(self):
        book = self.build(small_total=100,
            history={LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [2, 3, 0]}},
            cancel=[{'date': '2026-01-03', 'cancel': 25, 'daily_cancel': 5}])
        self.assertEqual(self.values(book, '累计退订率'), [.22, .25, .25])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [22, 3, 0])

    def test_cumulative_d1_seed_does_not_replace_true_daily_d1_in_facts_or_scoring(self):
        book = self.build(small_total=100, history={LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [32, None, None]}},
                          cancel=[{'date': '2026-01-03', 'cancel': 38}])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [38, None, None])
        self.assertEqual(self.values(book, '累计退订率'), [.38, None, None])
        self.assertEqual(table_records(book, D12_SHEET)[0]['D1退订'], 32)

    def test_zero_d1_daily_with_prelaunch_baseline_keeps_both_meanings(self):
        book = self.build(history={LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [0, 2, 0]}},
            cancel=[{'date': '2026-01-02', 'cancel': 8},
                    {'date': '2026-01-03', 'cancel': 8, 'daily_cancel': 0}])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [8, 2, 0])
        self.assertEqual(table_records(book, D12_SHEET)[0]['D1退订'], 0)
        self.assertEqual(self.cancel_export_issues(book), [])

    def test_d1_seed_does_not_depend_on_total_small_or_take_latest_cumulative(self):
        book = self.build(small_total=None, raw_fields={'small_daily_days': [], 'small_daily_sources': {}},
            cancel=[{'date': '2026-01-03', 'cancel': 8, 'daily_cancel': 2},
                    {'date': '2026-01-04', 'cancel': 11, 'daily_cancel': 3}])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [8, 3, None])
        self.assertEqual(self.values(book, '累计退订率'), [None, None, None])
        self.assertEqual(self.cancel_export_issues(book), [])
        later = self.build(cancel=[{'date': '2026-01-05', 'cancel': 12, 'daily_cancel': 2}])
        self.assertEqual(self.values(later, LAUNCH_CANCEL_DAILY_SHEET), [None, None, 2])

    def test_retention_audit_detects_missing_or_daily_instead_of_cumulative_d1(self):
        book = self.build(cancel=[{'date': '2026-01-03', 'cancel': 8, 'daily_cancel': 2}])
        self.assertEqual(self.cancel_export_issues(book), [])
        for wrong in (None, 2):
            with self.subTest(value=wrong):
                book[LAUNCH_CANCEL_DAILY_SHEET]['B2'] = wrong
                self.assertTrue(any(LAUNCH_CANCEL_DAILY_SHEET in message and 'D1' in message
                                    for message in audit_source_retention(book, [])))

    def test_new_sheet_names_order_and_number_formats(self):
        book = self.build(history={'总大定当日数量': {'测试车': [1, 0, None]},
                                  LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [0, 2, None]}})
        reorder_summary_sheets(book)
        index = book.sheetnames.index('直接大定当日数量')
        self.assertEqual(book.sheetnames[index:index+3], ['直接大定当日数量', '大定当日数量', LAUNCH_CANCEL_DAILY_SHEET])
        self.assertIn('大定累计完成度', book.sheetnames)
        self.assertNotIn('累计大定完成度', book.sheetnames)
        self.assertNotIn('总大定当日数量', book.sheetnames)
        self.assertEqual(book.sheetnames[-1], '首销期累计退订率')
        self.assertEqual(book[LAUNCH_CANCEL_DAILY_SHEET]['C2'].value, 2)
        self.assertNotIn('%', book[LAUNCH_CANCEL_DAILY_SHEET]['C2'].number_format)
        self.assertIn('%', book['首销期累计退订率']['B2'].number_format)
        self.assertTrue(all(sheet.sheet_state == 'visible' for sheet in book))

    def test_legacy_cancel_quantity_name_is_read_but_not_exported(self):
        legacy = self.build(history={'退订当日数量': {'测试车': [2, 0, 3]}})
        current = self.build(history={LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [2, 0, 3]}})
        self.assertEqual(self.values(legacy, LAUNCH_CANCEL_DAILY_SHEET), [2, 0, 3])
        self.assertEqual(self.values(legacy, LAUNCH_CANCEL_DAILY_SHEET),
                         self.values(current, LAUNCH_CANCEL_DAILY_SHEET))
        self.assertNotIn('退订当日数量', legacy.sheetnames)
        before = table_records(current, LAUNCH_CANCEL_DAILY_SHEET)
        current[LAUNCH_CANCEL_DAILY_SHEET].title = '退订当日数量'
        self.assertEqual(table_records(current, LAUNCH_CANCEL_DAILY_SHEET), before)

    def test_web_reads_canonical_and_legacy_sheet_names_without_losing_values(self):
        book = self.build(daily=[{'date': f'2026-01-0{i}', 'gross': 10} for i in (3, 4, 5)])
        with patch('modules.sales_forecast._read_model_mapping', return_value={}), \
             patch('modules.sales_forecast._read_model_master', return_value={}):
            with summary_scope(Path('read-only-memory.xlsx'), workbook=book):
                current = _read_history()[1]
            book['大定当日数量'].title = '总大定当日数量'
            book['大定累计完成度'].title = '累计大定完成度'
            with summary_scope(Path('read-only-memory.xlsx'), workbook=book):
                legacy = _read_history()[1]
        self.assertEqual(current[0]['daily_orders'], [10, 10, 10])
        self.assertEqual(current[0]['gross_progress'], [1/3, 2/3, 1])
        self.assertEqual(current, legacy)

    def test_real_source_workbooks_history_cancellation_survives_final_refresh(self):
        book = source_fixtures.SourceBackfillEndToEndTests.build(
            self, source_quantities={'退订进度': [7, None, 0]})
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [7, 2, 0])
        self.assertEqual(self.values(book, '累计退订率'), [.07, .09, .09])
        self.assertEqual(self.values(book, '大定当日数量'), [50, 50, 30])
        for actual, expected in zip(self.values(book, '大定累计完成度'), [50/130, 100/130, 1]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(table_records(book, MASTER_SHEET)[0]['总退订'], 9)

    def test_missing_history_uses_real_source_zero_and_invalid_history_falls_back(self):
        book = self.build(history={LAUNCH_CANCEL_DAILY_SHEET: {'测试车': [None, -1, float('nan')]}},
            cancel=[{'date': '2026-01-03', 'cancel': 5, 'daily_cancel': 5},
                    {'date': '2026-01-04', 'cancel': 5, 'daily_cancel': 0},
                    {'date': '2026-01-05', 'cancel': 7, 'daily_cancel': 2}])
        self.assertEqual(self.values(book, LAUNCH_CANCEL_DAILY_SHEET), [5, 0, 2])
        self.assertEqual(self.values(book, '累计退订率'), [.25, .25, .35])

    def test_retention_audit_catches_missing_new_daily_outputs(self):
        book = source_fixtures.SourceBackfillEndToEndTests.build(self)
        self.assertEqual(audit_source_retention(book, []), [])
        for title in ('大定当日数量', LAUNCH_CANCEL_DAILY_SHEET):
            with self.subTest(sheet=title):
                sheet = book[title]
                headers = [cell.value for cell in sheet[1]]
                cell = sheet.cell(2, headers.index('D2')+1)
                original = cell.value
                cell.value = None
                self.assertTrue(any(title in message and 'D2' in message for message in audit_source_retention(book, [])))
                cell.value = original

