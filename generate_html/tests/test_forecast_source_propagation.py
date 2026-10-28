"""Public sources follow the selected facts, including zero and adjacent differences."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook

from core.excel import WorkbookItem, WorkbookStore
from core.forecast_summary import DAILY_SHEET, LAUNCH_HOURLY_SHEET, table_records
from tests import test_forecast_reference_backfill as fixtures
from tools.refresh_sales_forecast_data import forecast_weekly_orders


class ForecastSourcePropagationTests(TestCase):
    def build(self, **kwargs):
        fixture = fixtures.ForecastReferenceBackfillTests()
        self.addCleanup(fixture.doCleanups)
        return fixture.build(**kwargs)

    def daily(self, book, day):
        return next(row for row in table_records(book, DAILY_SHEET)
                    if row['日期'].date().isoformat() == day)

    def test_selected_zero_and_each_daily_field_keep_their_actual_file(self):
        book = self.build(daily=[dict(date='2026-01-03', gross=0, net=0, lock=0,
                                     _field_origins={'gross': 'A.xlsx｜订单by天',
                                                     'net': 'B.xlsx｜订单by天',
                                                     'lock': 'C.xlsx｜订单by天'})])
        row = self.daily(book, '2026-01-03')
        self.assertEqual((row['大定'], row['留存大定'], row['交车锁单']), (0, 0, 0))
        for expected in ('大定=A.xlsx｜订单by天', '留存大定=B.xlsx｜订单by天',
                         '交车锁单=C.xlsx｜订单by天'):
            self.assertIn(expected, row['字段来源'])

    def test_adjacent_cumulative_difference_reports_both_endpoint_files(self):
        book = self.build(cumulative=[
            dict(date='2026-01-03', gross=10, _field_origins={'gross': 'A.xlsx｜累计'}),
            dict(date='2026-01-04', gross=25, _field_origins={'gross': 'B.xlsx｜累计'}),
        ])
        row = self.daily(book, '2026-01-04')
        self.assertEqual(row['大定'], 15)
        self.assertIn('A.xlsx｜累计', row['字段来源'])
        self.assertIn('B.xlsx｜累计', row['字段来源'])
        self.assertIn('相邻日累计差分', row['字段来源'])

    def test_nonadjacent_cumulative_does_not_fill_daily_gap(self):
        book = self.build(cumulative=[
            dict(date='2026-01-03', gross=10, _field_origins={'gross': 'A.xlsx｜累计'}),
            dict(date='2026-01-05', gross=40, _field_origins={'gross': 'B.xlsx｜累计'}),
        ])
        daily = {row['日期'].date().isoformat(): row for row in table_records(book, DAILY_SHEET)}
        self.assertIsNone(daily.get('2026-01-04', {}).get('大定'))
        self.assertIsNone(daily.get('2026-01-05', {}).get('大定'))
        curve = table_records(book, '大定累计完成度')[0]
        self.assertEqual((curve['D1'], curve['D2'], curve['D3']), (.25, None, 1))

    def test_cancel_difference_uses_actual_origins_of_both_days(self):
        book = self.build(cancel=[
            dict(date='2026-01-02', cancel=5, _field_origins={'cancel': 'A.xlsx｜日度退订'}),
            dict(date='2026-01-03', cancel=7, _field_origins={'cancel': 'B.xlsx｜日度退订'}),
        ])
        row = self.daily(book, '2026-01-03')
        self.assertEqual(row['退订数量'], 2)
        self.assertIn('A.xlsx｜日度退订', row['字段来源'])
        self.assertIn('B.xlsx｜日度退订', row['字段来源'])

    def test_hourly_export_lists_only_files_contributing_selected_fields(self):
        book = self.build(raw_fields={'hourly_days': [dict(date='2026-01-03', hours=[
            dict(hour=0, gross=0, small_to_big=0, direct=0,
                 _field_origins={'gross': 'A.xlsx｜by时', 'small_to_big': 'B.xlsx｜by时',
                                 'direct': 'B.xlsx｜by时'}),
        ])]})
        row = table_records(book, LAUNCH_HOURLY_SHEET)[0]
        self.assertEqual(row['小时大定'], 0)
        self.assertEqual(row['来源文件'], 'A.xlsx、B.xlsx')

    def test_mix_day_and_week_zero_and_fallback_keep_actual_file(self):
        store = WorkbookStore(Path('.'))
        for filename, values in (('大定选配比例_A.xlsx', [0, None]),
                                 ('大定选配比例_B.xlsx', [99, 5])):
            book = Workbook()
            self.addCleanup(book.close)
            for name, periods in (('测试车by天', [date(2026, 1, 3), date(2026, 1, 4)]),
                                  ('测试车by周', ['26WK01', '26WK02'])):
                sheet = book.create_sheet(name)
                sheet.append(['指标', '统计类型', '分类', *periods])
                sheet.append(['大定', '数量', '数量', *values])
            store.items.append(WorkbookItem(Path(filename), book))
        data = {'targets': [{'name': '测试车'}]}
        dashboard = SimpleNamespace(views={'week': {'pages': {'预测方案': {'workspace': {'data': data}}}}})
        with patch('modules.sales_forecast._read_model_mapping', return_value={}):
            forecast_weekly_orders(store, dashboard, date(2026, 1, 5), collect_only=True)
        for table, first, second in (('mix_daily', '2026-01-03', '2026-01-04'),
                                     ('mix_weekly', '26WK01', '26WK02')):
            self.assertEqual(data[table][('测试车', first, 'gross')][0], 0)
            self.assertIn('_A.xlsx', data[table][('测试车', first, 'gross')][1])
            self.assertEqual(data[table][('测试车', second, 'gross')][0], 5)
            self.assertIn('_B.xlsx', data[table][('测试车', second, 'gross')][1])
