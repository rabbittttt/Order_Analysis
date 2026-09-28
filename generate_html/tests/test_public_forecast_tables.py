from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from tempfile import TemporaryDirectory

from openpyxl import Workbook

from core.excel import WorkbookItem
from core.forecast_summary import (
    GUIDE_SHEET, MASTER_SHEET, DAILY_SHEET, SMALL_HOURLY_SHEET, LAUNCH_HOURLY_SHEET,
    WEEKLY_SHEET, public_forecast_tables, read_public_forecast, visible_target_names,
)
from tools.refresh_sales_forecast_data import forecast_weekly_orders, write_rows


class PublicForecastTablesTests(TestCase):
    def make_public(self, target_start='2026-01-03'):
        book = Workbook()
        book.active.title = MASTER_SHEET
        book.active.append(['历史传播名', '订单分析代际名', '产品档位'])
        book.active.append(['历史车', '测试车', '中型SUV'])
        base = book.create_sheet('预测基准总表')
        base.append(['传播名', '代际名', '总大定', '发布日', '首销截止'])
        base.append(['历史车', '测试车', 20, datetime(2026, 1, 3), datetime(2026, 1, 9)])
        profile = {'model': '测试车', 'total_small': 100, 'stage_profiles': {},
                   'small_daily_days': [{'date': '2026-01-01', 'orders': 0}, {'date': '2026-01-02', 'orders': 10}],
                   'small_hourly_days': [{'date': '2026-01-02', 'orders': 10, 'hours': [{'hour': 15, 'orders': 4}, {'hour': 16, 'orders': 6}]}]}
        for stage, gross, owner in [('before', 20, 'history'), ('active', 30, 'launch'), ('ended', 20, 'history')]:
            profile['stage_profiles'][stage] = {'total_small': 100, 'total_small_source': 'history', 'selected_source': owner,
                'days': [{'date': '2026-01-03', 'day': 'D1', 'gross': gross, 'small_to_big': 10, 'direct': gross - 10,
                          '_field_sources': {'gross': owner, 'small_to_big': owner, 'direct': owner}}]}
        data = {'targets': [{'name': '测试车', 'history_model': '历史车', 'launch_date': target_start, 'end_date': '2026-01-09',
                            'small_start_date': '2026-01-01', 'small_end_date': '2026-01-02', 'days': 7}],
                'actuals': [profile], 'history': [], 'steady_history': [],
                'small_order_history': [{'model': '历史车', 'generation': '测试车', 'event_id': 'event1',
                    'small_start_date': '2026-01-01', 'small_end_date': '2026-01-02', 'days': 2, 'total': 100,
                    'daily_actual': True, 'dates': ['2026-01-01', '2026-01-02'], 'daily_orders': [0, 10],
                    'small_progress': [0, .1], 'standard_progress': [0, .1, .8, 1], 'small_hourly_curve': []}]}
        def emit(name, headers, rows, percent_headers=None):
            if name in book.sheetnames:
                del book[name]
            write_rows(book, name, headers, rows, 'PublicTest', percent_headers)
        public_forecast_tables(book, data, emit, as_of_date=date(2026, 1, 4))
        return book

    def test_no_cache_merged_tables_and_typed_values(self):
        book = self.make_public()
        self.assertEqual(book.sheetnames[:6], [GUIDE_SHEET, MASTER_SHEET, DAILY_SHEET, SMALL_HOURLY_SHEET, LAUNCH_HOURLY_SHEET, WEEKLY_SHEET])
        self.assertNotIn('预测基准总表', book.sheetnames)
        self.assertTrue(all(s.sheet_state == 'visible' for s in book))
        self.assertEqual(visible_target_names(book), ['测试车'])
        headers = [c.value for c in book[DAILY_SHEET][1]]
        self.assertNotIn('累计退订', headers)
        self.assertNotIn('累计退订率', headers)
        self.assertIsInstance(book[DAILY_SHEET].cell(2, headers.index('日期') + 1).value, datetime)
        book.close()

    def test_public_cells_are_authoritative_and_partial_history_is_not_padded(self):
        book = self.make_public()
        profiles, windows, small, _ = read_public_forecast(book, [])
        self.assertEqual(small[0]['daily_orders'], [0, 10])
        self.assertEqual(small[0]['standard_progress'], [0, .1, .8, 1])
        self.assertEqual(small[0]['small_hourly_curve'], [])
        self.assertEqual(profiles[0]['stage_profiles']['active']['days'][0]['gross'], 30)
        self.assertEqual(profiles[0]['stage_profiles']['ended']['days'][0]['gross'], 20)
        self.assertEqual(profiles[0]['small_hourly_days'][0]['hours'][0]['hour'], 15)
        sheet = book[DAILY_SHEET]
        headers = [c.value for c in sheet[1]]
        for row in sheet.iter_rows(min_row=2):
            if row[headers.index('适用取数阶段')].value == '首销中':
                row[headers.index('大定')].value = 99
        updated = read_public_forecast(book, [])[0]
        self.assertEqual(updated[0]['stage_profiles']['active']['days'][0]['gross'], 99)
        self.assertEqual(updated[0]['stage_profiles']['ended']['days'][0]['gross'], 20)
        book.close()

    def test_current_window_does_not_overwrite_historical_reference_dates(self):
        book = self.make_public(target_start='2026-01-05')
        rows = list(book[MASTER_SHEET].values)
        record = dict(zip(rows[0], rows[1]))
        self.assertEqual(record['首销开始'], datetime(2026, 1, 3))
        self.assertEqual(record['当前首销开始'], datetime(2026, 1, 5))
        windows = read_public_forecast(book, [])[1]
        self.assertEqual(next(iter(windows.values()))['launch_date'], '2026-01-05')
        book.close()

    def test_dashboard_reads_public_workbook_without_original_files(self):
        from modules.sales_forecast import SalesForecastModule
        from core.models import Subject
        book = self.make_public()
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'summary.xlsx'
            book.save(path)
            module = SalesForecastModule()
            module.summary_path = path
            module.as_of_date = date(2026, 1, 4)
            with patch('modules.sales_forecast._read_actual_profiles', side_effect=AssertionError('raw orders must not be loaded')), \
                 patch('modules.sales_forecast._read_small_order_history', side_effect=AssertionError('raw history must not be loaded')), \
                 patch('modules.sales_forecast._read_steady_history', side_effect=AssertionError('raw steady must not be loaded')):
                dashboard = module.build(None, Subject('summary', '鸿蒙智行', 'group'))
            data = dashboard.views['week']['pages']['预测方案']['workspace']['data']
            self.assertEqual(data['actuals'][0]['days'][0]['gross'], 30)
            self.assertEqual(data['small_order_history'][0]['daily_orders'], [0, 10])
        book.close()

    def weekly_fixture(self, *, complete_days=True, cutoff='2026-01-01'):
        model = '问界 M7 2026款'
        book = Workbook()
        week = book.active
        week.title = model + 'by周'
        week.append(['指标', '统计类型', '分类', '26WK01'])
        week.append(['大定', '数量', '数量', 100])
        week.append(['净大定', '数量', '数量', 70])
        week.append(['交车锁单', '数量', '数量', 50])
        if complete_days:
            day = book.create_sheet(model + 'by天')
            dates = [date.fromisocalendar(2026, 1, n) for n in range(1, 8)]
            day.append(['指标', '统计类型', '分类', *dates])
            day.append(['大定', '数量', '数量', 1, 2, 3, 4, 5, 6, 7])
            day.append(['留存大定', '数量', '数量', 1, 1, 2, 2, 3, 3, 4])
            day.append(['交车锁单', '数量', '数量', 0, 1, 1, 1, 2, 2, 2])
        item = WorkbookItem(Path('大定选配比例分析.xlsx'), book)
        store = SimpleNamespace(find=lambda key: item if key == '大定选配比例' else None)
        data = {'targets': [{'name': model, 'launch_date': '2025-12-20', 'end_date': cutoff}], 'actuals': []}
        dashboard = SimpleNamespace(views={'week': {'pages': {'预测方案': {'workspace': {'data': data}}}}})
        with patch('modules.sales_forecast._read_model_mapping', return_value={}):
            rows = forecast_weekly_orders(store, dashboard, date(2026, 1, 10))
        book.close()
        return rows

    def test_cross_year_week_is_split_at_stage_date_for_all_three_metrics(self):
        rows = self.weekly_fixture()
        self.assertEqual([(r[2], *r[5:8]) for r in rows], [('首销', 10, 6, 3), ('平销', 18, 10, 6)])
        self.assertEqual(sum(r[5] for r in rows), 28)  # Never repeat the original whole-week 100.

    def test_cannot_split_whole_week_without_daily_evidence(self):
        with self.assertLogs('sales_forecast_refresh', level='WARNING') as logs:
            rows = self.weekly_fixture(complete_days=False)
        self.assertEqual(len(logs.output), 1)
        self.assertTrue(all(r[5:8] == [None, None, None] for r in rows))

    def test_whole_steady_week_prefers_source_week_over_daily_sum(self):
        rows = self.weekly_fixture(cutoff='2025-12-28')
        self.assertEqual(rows[0][5:8], [100, 70, 50])
