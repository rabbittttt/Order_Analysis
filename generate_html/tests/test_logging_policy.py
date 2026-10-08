from datetime import date
import logging
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from openpyxl import Workbook

from core.excel import WorkbookItem, WorkbookStore, _merge_matrix, _merge_partitioned
import main


class LoggingPolicyTests(TestCase):
    def matrix(self, periods, values, *, title='车型_SKU', filename='SKU分析.xlsx', span=None):
        book = Workbook()
        self.addCleanup(book.close)
        sheet = book.active
        sheet.title = title
        sheet.append(['累计占比', *([None] * len(periods))])
        sheet.append(['排名', *periods])
        for index, row in enumerate(values, 1):
            sheet.append([f'TOP{index}', *row])
        item = WorkbookItem(Path(filename), book)
        item._boundary_date_range = span
        return item, sheet

    def test_cross_file_aggregate_is_not_comparable_and_values_stay_unchanged(self):
        periods = ['总计', '近28天', '总计占比']
        matches = [self.matrix(periods, [[.4, .5, .6]], filename='SKU2026.xlsx'),
                   self.matrix(periods, [[.8, .9, 1]], filename='SKU2025.xlsx')]
        with self.assertLogs('core.excel', level='INFO') as logs:
            result = _merge_matrix(matches, 2, 1)
        self.assertTrue(all(r.levelno == logging.INFO for r in logs.records))
        self.assertIn('没有共同统计范围', logs.output[0])
        self.assertEqual({result.cell(2, c).value: result.cell(3, c).value for c in range(2, 5)},
                         dict(zip(periods, [.4, .5, .6])))

    def test_duplicate_aggregate_inside_same_file_still_warns(self):
        matches = [self.matrix(['总计'], [[.4]], title='车_SKU', filename='SKU.xlsx'),
                   self.matrix(['总计'], [[.8]], title='车 _SKU', filename='SKU.xlsx')]
        with self.assertLogs('core.excel', level='WARNING') as logs:
            _merge_matrix(matches, 2, 1)
        self.assertEqual(len(logs.records), 1)
        self.assertIn('同文件重复键冲突', logs.output[0])

    def test_proven_split_ratio_has_info_but_no_false_conflict(self):
        for period, left, right in [('26WK01', (date(2025, 12, 29), date(2025, 12, 31)), (date(2026, 1, 1), date(2026, 1, 4))),
                                    ('26WK27', (date(2026, 6, 29), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 7, 5)))]:
            with self.subTest(period=period):
                matches = [self.matrix([period], [[.4]], filename='SKU_A.xlsx', span=left),
                           self.matrix([period], [[.8]], filename='SKU_B.xlsx', span=right)]
                with self.assertLogs('core.excel', level='INFO') as logs:
                    result = _merge_matrix(matches, 2, 1)
                self.assertTrue(all(r.levelno == logging.INFO for r in logs.records))
                self.assertIn('不代表合并全周指标', logs.output[0])
                self.assertEqual(result.cell(3, 2).value, .4)

    def test_unknown_boundary_scope_lists_all_cells_without_claiming_value_conflict(self):
        matches = [self.matrix(['26WK01'], [[.4]]*80, filename='SKU_2021-2025.xlsx'),
                   self.matrix(['26WK01'], [[.8]]*80, filename='SKU_2026.xlsx')]
        with self.assertLogs('core.excel', level='WARNING') as logs:
            _merge_matrix(matches, 2, 1)
        self.assertEqual(len(logs.records), 1)
        self.assertIn('统计范围待核对', logs.output[0])
        self.assertIn('B3:B82', logs.output[0])
        self.assertIn('涉及80处差异', logs.output[0])
        self.assertNotIn('多文件数值冲突', logs.output[0])

    def test_full_overlapping_boundary_still_prints_every_real_difference(self):
        span = (date(2025, 12, 29), date(2026, 1, 4))
        matches = [self.matrix(['26WK01'], [[.4]]*8, filename='SKU_A.xlsx', span=span),
                   self.matrix(['26WK01'], [[.8]]*8, filename='SKU_B.xlsx', span=span)]
        with self.assertLogs('core.excel', level='WARNING') as logs:
            result = _merge_matrix(matches, 2, 1)
        self.assertEqual(len(logs.records), 8)
        self.assertIn('TOP8', logs.output[-1])
        self.assertEqual(result.cell(10, 2).value, .4)

    def test_float_tail_is_ignored_but_real_difference_and_zero_are_not(self):
        matches = [self.matrix(['26WK02'], [[.1 + .2], [.3], [0]], filename='SKU_A.xlsx'),
                   self.matrix(['26WK02'], [[.3], [.300001], [.2]], filename='SKU_B.xlsx')]
        with self.assertLogs('core.excel', level='WARNING') as logs:
            result = _merge_matrix(matches, 2, 1)
        self.assertEqual(len(logs.records), 2)
        self.assertTrue(all('TOP1' not in line for line in logs.output))
        self.assertEqual(result.cell(3, 2).value, .1 + .2)
        self.assertEqual(result.cell(5, 2).value, 0)

    def test_partitioned_conflict_reports_original_not_temporary_coordinate(self):
        matches = []
        for filename, column, value in [('SKU_A.xlsx', 5, .4), ('SKU_B.xlsx', 9, .8)]:
            book = Workbook(); self.addCleanup(book.close)
            sheet = book.active; sheet.title = '车型_SKU'
            sheet.cell(1, 1, '订单数量'); sheet.cell(2, 1, 'SKU'); sheet.cell(2, 2, '26WK02'); sheet.cell(3, 1, 'A'); sheet.cell(3, 2, 10)
            sheet.cell(1, column, '总计占比'); sheet.cell(2, column, '排名'); sheet.cell(2, column+1, '26WK02')
            sheet.cell(3, column, 'TOP1'); sheet.cell(3, column+1, value)
            matches.append((WorkbookItem(Path(filename), book), sheet))
        with self.assertLogs('core.excel', level='WARNING') as logs:
            _merge_partitioned(matches, horizontal=True)
        self.assertEqual(len(logs.records), 1)
        self.assertIn('单元格=F3: 0.4', logs.output[0])
        self.assertIn('单元格=J3: 0.8', logs.output[0])

    def test_chart_conflicts_include_every_period_and_original_cell(self):
        store = WorkbookStore(Path('.')); self.addCleanup(store.close)
        for i in range(2):
            book = Workbook(); sheet = book.active; sheet.title = '问界by天图表'
            sheet.append(['问界'])
            sheet.append([None, '留存大定', *[f'2026-01-{d:02d}' for d in range(1, 6)]])
            sheet.append([None, '版本A', *([.4 + i*.2]*5)])
            sheet.append([None, '总计', *([100 + i]*5)])
            store.items.append(WorkbookItem(Path(f'大定选配比例{i}.xlsx'), book))
        with self.assertLogs('core.excel', level='WARNING') as logs:
            result = store.find_chart_data('大定选配比例', '问界', 'day')[2]
        self.assertEqual(len(logs.records), 10)
        self.assertTrue(any('2026-01-05' in line and '单元格=G4' in line for line in logs.output))
        self.assertTrue(any('2026-01-05' in line and '单元格=G3' in line for line in logs.output))
        self.assertEqual(result['totals'], [100]*5)
        self.assertFalse(any(key.startswith('_log_') for key in result))

    def test_relay_preserves_severity_duplicates_and_one_traceback_issue(self):
        collector = main.DiagnosticCollector()
        before = list(main.BUILD_DIAGNOSTICS); counts = dict(main.DIAGNOSTIC_COUNTS)
        self.addCleanup(lambda: main.BUILD_DIAGNOSTICS.__setitem__(slice(None), before))
        self.addCleanup(lambda: main.DIAGNOSTIC_COUNTS.update(counts))
        main.BUILD_DIAGNOSTICS.clear(); main.DIAGNOSTIC_COUNTS.update(WARNING=0, ERROR=0)
        with self.assertLogs('order_analysis', level='DEBUG') as logs:
            main.LOGGER.addHandler(collector)
            try:
                level = logging.INFO
                for line in ['[WARNING] 缺D3', '[WARNING] 缺D3', '[ERROR] 刷新失败',
                             'Traceback (most recent call last):', '  File "source.py", line 1',
                             'ValueError: 输入格式错误', '[INFO] 收尾', '[DEBUG] 读取细节']:
                    level = main.relay_refresh_line(line, level)
            finally:
                main.LOGGER.removeHandler(collector)
        self.assertEqual([r.levelno for r in logs.records], [30,30,40,40,40,40,20,10])
        self.assertTrue(all('[WARNING]' not in r.getMessage() and '[ERROR]' not in r.getMessage() for r in logs.records))
        self.assertEqual(main.DIAGNOSTIC_COUNTS, {'WARNING': 2, 'ERROR': 1})
        self.assertEqual(len(main.BUILD_DIAGNOSTICS), 2)

    def test_refresh_relays_before_wait_and_propagates_failure(self):
        process = MagicMock()
        process.__enter__.return_value = process
        observed = []
        def output():
            yield '[WARNING] 第一个问题\n'
            self.assertTrue(observed)  # Already relayed while the child is still producing output.
            yield '[ERROR] 第二个问题\n'
        process.stdout = output(); process.wait.return_value = 1
        with patch('main.subprocess.Popen', return_value=process) as popen, patch('main.relay_refresh_line', side_effect=lambda line, level: observed.append(line) or logging.WARNING):
            with self.assertRaisesRegex(RuntimeError, '退出码 1'):
                main.refresh_sales_forecast_data({'refresh_sales_forecast_data_before_build': True})
        self.assertEqual(len(observed), 2)
        self.assertIn('-u', popen.call_args.args[0])
        self.assertEqual(popen.call_args.kwargs['stderr'], main.subprocess.STDOUT)
