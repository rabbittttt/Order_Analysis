from datetime import date, datetime, timedelta
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook

from core.excel import WorkbookItem, WorkbookStore, _merge_records
from core.forecast_summary import MASTER_SHEET, DAILY_SHEET
from core.validation import forecast_diagnostics, flush_forecast_diagnostics
from modules.sales_forecast import _complete_steady_weeks, _stage_window, _read_steady_history
from tools.refresh_sales_forecast_data import audit_final_forecast, curve_for


MODEL = '问界 M9 2026款'


class ForecastDiagnosticsTests(TestCase):
    def test_batch_bounds_examples_deduplicates_and_preserves_errors(self):
        logger = logging.getLogger('modules.sales_forecast')
        with self.assertLogs(level='DEBUG') as logs:
            with forecast_diagnostics():
                for _ in range(2):
                    for i in range(9):
                        logger.warning('[销量预测条件不足] 预测对象=车%s | 原因=首销日期缺失', i)
                logger.error('读取失败，不允许降级')
                flush_forecast_diagnostics()
        warnings = [r for r in logs.records if r.levelno == logging.WARNING]
        self.assertEqual(len(warnings), 1)
        self.assertIn('共9项', warnings[0].getMessage())
        self.assertNotIn('车8', warnings[0].getMessage())
        self.assertEqual(sum(r.levelno == logging.DEBUG for r in logs.records), 9)
        self.assertEqual(sum(r.levelno == logging.ERROR for r in logs.records), 1)

    def test_nested_batch_and_failure_restore_filters(self):
        logger = logging.getLogger('sales_forecast_refresh')
        filters = list(logger.filters)
        with self.assertLogs(level='WARNING') as logs:
            with self.assertRaises(ValueError):
                with forecast_diagnostics():
                    with forecast_diagnostics():
                        logger.warning('必须保留的告警')
                    raise ValueError('test')
        self.assertEqual(logger.filters, filters)
        self.assertEqual(len(logs.records), 1)

    def test_unmatched_preliminary_curve_is_debug_not_final_failure(self):
        with self.assertLogs('sales_forecast_refresh', level='DEBUG') as logs:
            self.assertEqual(curve_for('未来车', {}, {}, {}, '退订'), [])
        self.assertEqual([r.levelno for r in logs.records], [logging.DEBUG])

    def cancellation_sheet(self, book, title, value):
        sheet = book.create_sheet(title)
        sheet.append(['退订分析'])
        sheet.append(['取消日期', '当日小订退'])
        sheet.append([datetime(2026, 7, 27), value])
        return sheet

    def test_same_file_conflict_locates_both_original_sheets_and_cells(self):
        book = Workbook()
        first = self.cancellation_sheet(book, 'V800  2026款_日度退订', 35)
        second = self.cancellation_sheet(book, 'V800 2026款_日度退订', 2)
        item = WorkbookItem(Path('鸿蒙智行小订退订分析.xlsx'), book)
        with self.assertLogs('core.excel', level='DEBUG') as logs:
            merged = _merge_records([(item, first), (item, second)], ({'取消日期'},))
        self.assertEqual(merged.cell(3, 2).value, 35)
        self.assertEqual(merged._merge_conflict_kinds['同文件重复键'], 1)
        detail = '\n'.join(logs.output)
        self.assertIn('Sheet=V800  2026款_日度退订', detail)
        self.assertIn('Sheet=V800 2026款_日度退订', detail)
        self.assertIn('单元格=B3: 35', detail)
        self.assertIn('单元格=B3: 2', detail)
        book.close()

    def test_same_sheet_duplicate_dates_are_located_not_added(self):
        book = Workbook()
        first = self.cancellation_sheet(book, 'V800_日度退订', 35)
        first.append([datetime(2026, 7, 27), 2])
        other = Workbook(); second = self.cancellation_sheet(other, first.title, 35)
        with self.assertLogs('core.excel', level='DEBUG') as logs:
            merged = _merge_records([(WorkbookItem(Path('小订退订分析.xlsx'), book), first),
                                     (WorkbookItem(Path('小订退订分析_历史.xlsx'), other), second)], ({'取消日期'},))
        self.assertEqual(merged.cell(3, 2).value, 35)
        self.assertIn('单元格=B4: 2', '\n'.join(logs.output))
        book.close(); other.close()

    def test_cross_file_conflict_keeps_priority_and_reports_locations(self):
        books = [Workbook(), Workbook()]
        for book, count in zip(books, (35, 2)):
            book.remove(book.active)
            self.cancellation_sheet(book, 'V800_日度退订', count)
        store = WorkbookStore(Path('.'))
        store.items = [WorkbookItem(Path(f'小订退订分析{i}.xlsx'), b) for i, b in enumerate(books)]
        with self.assertLogs('core.excel', level='WARNING') as logs:
            item = store.find('小订退订分析')
        self.assertEqual(item.workbook.worksheets[0].cell(3, 2).value, 35)
        self.assertIn('跨文件冲突1项', logs.output[0])
        self.assertIn('Sheet=V800_日度退订 / 单元格=B3', logs.output[0])
        store.close()

    def test_stage_end_is_shared_and_input_record_is_not_modified(self):
        window = {'generation': MODEL, 'launch_date': '2026-06-01', 'days': 30}
        parsed = _stage_window({'m9': window}, MODEL)
        self.assertEqual(parsed['end_date'], '2026-06-30')
        self.assertNotIn('end_date', window)
        invalid = {**window, 'end_date': '2026-05-30'}
        self.assertEqual(_stage_window({'m9': invalid}, MODEL)['end_date'], '2026-05-30')

    def test_steady_reader_uses_derived_launch_end(self):
        book = Workbook(); sheet = book.active; sheet.title = MODEL+'by周'
        sheet.append(['指标', '统计类型', '分类', '26WK28'])
        sheet.append(['交车锁单', '数量', '数量', 700])
        item = WorkbookItem(Path('锁单选配比例.xlsx'), book)
        with patch('modules.sales_forecast._read_model_mapping', return_value={}), patch('modules.sales_forecast._read_model_master', return_value={}):
            rows, _ = _read_steady_history(SimpleNamespace(find=lambda _: item),
                {'m9': {'generation': MODEL, 'launch_date': '2026-06-01', 'days': 30}}, date(2026, 7, 20))
        self.assertEqual(rows[0]['steady_start_date'], '2026-07-01')
        self.assertEqual(rows[0]['weeks'][0]['lock'], 700)
        book.close()

    def test_zero_week_requires_full_coverage_and_blank_week_stays_unknown(self):
        start = date(2026, 7, 6); today = date(2026, 7, 28)
        weeks = [{'period': '26WK28', 'start_date': '2026-07-06', 'end_date': '2026-07-12', 'lock': 7}]
        coverage = [(start, date(2026, 7, 26))]
        result = _complete_steady_weeks(list(weeks), {'26WK28': 7, '26WK30': None}, [], coverage, start, today)
        self.assertEqual([(r['period'], r['lock']) for r in result], [('26WK28', 7), ('26WK29', 0)])
        short = _complete_steady_weeks(list(weeks), {'26WK28': 7}, [], [(start, date(2026, 7, 18))], start, today)
        self.assertEqual(len(short), 1)
        unknown_day = [{'date': '2026-07-13', 'lock': None, 'complete': True}]
        blocked = _complete_steady_weeks(list(weeks), {'26WK28': 7}, unknown_day, coverage, start, date(2026, 7, 21))
        self.assertEqual(len(blocked), 1)

    def final_book(self, small_end, launch_start, launch_end, total=None, has_small=True):
        book = Workbook(); book.remove(book.active)
        master = book.create_sheet(MASTER_SHEET)
        master.append(['代际名', '二级代际名', '有小订', '小订开始', '小订结束', '首销开始', '首销结束', '首销天数', '总小订', '首销期留存大定', '首销期锁单'])
        master.append([MODEL, None, has_small, date(2026, 9, 1) if has_small else None, small_end, launch_start, launch_end, 2, total, 0, 0])
        daily = book.create_sheet(DAILY_SHEET)
        daily.append(['代际名', '二级代际名', '日期', '小订数量', '大定', '小转大', '直接大定'])
        return book, daily

    def test_future_terminal_fields_are_not_required_and_complete_actuals_resolve_gaps(self):
        book, daily = self.final_book(date(2026, 9, 4), date(2026, 9, 5), date(2026, 9, 6))
        book[MASTER_SHEET]['J2'] = None
        book[MASTER_SHEET]['K2'] = None
        for day in (1, 2): daily.append([MODEL, None, date(2026, 9, day), 5, None, None, None])
        self.assertEqual(audit_final_forecast(book, date(2026, 9, 3)), [])
        book.close()

    def test_final_missing_small_days_and_total_disagreement_remain_visible(self):
        book, daily = self.final_book(date(2026, 9, 2), date(2026, 9, 5), date(2026, 9, 6), total=20)
        daily.append([MODEL, None, date(2026, 9, 1), 5])
        with self.assertLogs('sales_forecast_refresh', level='WARNING'):
            issues = audit_final_forecast(book, date(2026, 9, 3))
        self.assertIn('D2', '\n'.join(issues))
        daily.append([MODEL, None, date(2026, 9, 2), 5])
        with self.assertLogs('sales_forecast_refresh', level='WARNING'):
            issues = audit_final_forecast(book, date(2026, 9, 3))
        self.assertIn('多来源逐日合计=10', '\n'.join(issues))
        self.assertNotIn('数量缺失', '\n'.join(issues))
        book.close()

    def test_no_small_vehicle_and_true_zero_terminal_are_valid(self):
        book, daily = self.final_book(None, date(2026, 9, 1), date(2026, 9, 2), has_small=False)
        for day in (1, 2): daily.append([MODEL, None, date(2026, 9, day), None, 0, None, 0])
        self.assertEqual(audit_final_forecast(book, date(2026, 9, 3)), [])
        book.close()

    def test_ended_terminal_gap_limits_only_corresponding_reference(self):
        book, daily = self.final_book(None, date(2026, 9, 1), date(2026, 9, 2), has_small=False)
        book[MASTER_SHEET]['J2'] = None
        book[MASTER_SHEET]['K2'] = None
        for day in (1, 2): daily.append([MODEL, None, date(2026, 9, day), None, 0, None, 0])
        with self.assertLogs('sales_forecast_refresh', level='WARNING'):
            issues = audit_final_forecast(book, date(2026, 9, 3))
        self.assertEqual(len(issues), 1)
        self.assertIn('不停止其他有效预测', issues[0])
        self.assertIn('首销期留存大定、首销期锁单', issues[0])
        book.close()
