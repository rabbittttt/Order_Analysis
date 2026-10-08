from datetime import date
from unittest import TestCase

from core.forecast_summary import SMALL_CURVE_SHEET, SMALL_DAILY_SHEET, D12_SHEET, table_records, read_public_forecast
from modules.sales_forecast import _history_item, _attach_small_hourly_curves
from tools.refresh_sales_forecast_data import normalize_public_names, write_rows, SUMMARY_HEADER_ALIASES
from tests import test_public_forecast_tables
from tests import test_forecast_math
from modules.overview import _rise_rankings_with_empty


class SummaryLifecycleTests(TestCase):
    def test_rise_rankings_distinguish_empty_from_no_comparable_base(self):
        series = {'测试车': {metric: {'上期': {'metrics': {metric:100}}, '本期': {'metrics': {metric:50}}}
                        for metric in ('留存大定', '交车锁单')}}
        self.assertEqual(_rise_rankings_with_empty(series, '本期', '上期')['交车锁单']['empty_reason'], '本期暂无环比上涨车型')
        self.assertIn('暂无可比数据', _rise_rankings_with_empty(series, '本期', None)['交车锁单']['empty_reason'])

    def test_ongoing_small_without_historical_curve_keeps_complete_days(self):
        def customize(data):
            data['small_order_history'] = []
            data['targets'][0].update(small_end_date='2026-01-07')
            data['actuals'][0]['small_daily_days'] += [{'date': '2026-01-04', 'orders': 999}]
        book = test_public_forecast_tables.PublicForecastTablesTests().make_public(customize=customize)
        daily = table_records(book, SMALL_DAILY_SHEET)[0]
        curve = table_records(book, SMALL_CURVE_SHEET)[0]
        self.assertEqual(daily['小订阶段'], '进行中')
        self.assertEqual((daily['D1'], daily['D2'], daily['D4']), (0, 10, None))
        self.assertTrue(all(v is None for k, v in curve.items() if k.startswith('D')))
        profiles, _, small, _ = read_public_forecast(book, [], today=date(2026, 1, 4))
        self.assertFalse(small[0]['total_complete'])
        self.assertEqual(small[0]['days'], 7)
        book.close()

    def test_unfinished_launch_keeps_d1_but_not_today_or_terminal_progress(self):
        def customize(data):
            data['reference_daily'] = {'小转大当日数量': {'历史车': [10, 8]}, '直接大定当日数量': {'历史车': [20, 9]}}
        book = test_public_forecast_tables.PublicForecastTablesTests().make_public(customize=customize)
        row = table_records(book, D12_SHEET)[0]
        self.assertEqual(row['D1小转大'], 10)
        self.assertIsNone(row['D2小转大'])
        self.assertIsNone(row['D1小转大/总小转大'])
        book.close()

    def test_rename_preserves_numeric_progress_percent_format(self):
        book = test_public_forecast_tables.PublicForecastTablesTests().make_public()
        def emit(name, headers, rows, percent_headers=None):
            del book[name]
            write_rows(book, name, headers, rows, 'Regression', percent_headers)
        normalize_public_names(book, {}, emit)
        sheet = book[SMALL_CURVE_SHEET]
        col = next(c.column for c in sheet[1] if c.value == 'D2')
        self.assertEqual(sheet.cell(2, col).value, .1)
        self.assertEqual(sheet.cell(2, col).number_format, '0.0%')
        self.assertNotIn('%', book[SMALL_DAILY_SHEET].cell(2, col).number_format)
        book.close()

    def test_new_lock_rate_headers_are_distinct_and_new_end_date_is_read(self):
        self.assertEqual(SUMMARY_HEADER_ALIASES['大定到锁单率'], {'大定到锁单率'})
        item = _history_item({'传播名': '测试车', '首销结束日期': '2026-01-09',
                              '留存大定到锁单率': .9, '大定到锁单率': .6}, True)
        self.assertEqual(item['end_date'], '2026-01-09')
        self.assertEqual(item['lock_rate'], .6)

    def test_maintained_lock_rates_are_preserved_only_after_launch_end(self):
        for today, expected in ((date(2026, 1, 4), None), (date(2026, 1, 10), .6)):
            book = test_public_forecast_tables.PublicForecastTablesTests().make_public(as_of=today,
                master_periods={'留存大定到锁单率': .9, '大定到锁单率': .6})
            row = table_records(book, '车型基本信息')[0]
            self.assertEqual(row['大定到锁单率'], expected)
            self.assertEqual(row['留存大定到锁单率'], .9 if expected is not None else None)
            book.close()


class ReleaseWeekTests(TestCase):
    run_node = test_forecast_math.ForecastMathTests.run_node

    def test_ongoing_small_can_supply_complete_d1_but_not_terminal_progress(self):
        item = "{total_complete:false,total:100,daily_orders:[20,10],small_start_hour:20,small_hourly_curve:[...Array(20).fill(null),.2,.5,.8,1]}"
        self.assertTrue(self.run_node(f"m.smallReferenceAvailable({item},'hourly')"))
        self.assertTrue(self.run_node(f"m.smallReferenceAvailable({item},'slope')"))
        self.assertFalse(self.run_node(f"m.smallReferenceAvailable({item},'progress')"))
        self.assertFalse(self.run_node(f"m.smallReferenceAvailable({item},'daily')"))
    def test_release_weeks_require_seven_complete_days(self):
        expression = "m.releaseWeeks({launchDate:'2026-01-01',today:'2026-01-15',rows:Array.from({length:14},(_,i)=>({date:'2026-01-'+String(i+1).padStart(2,'0'),lock:i===3?null:0}))})"
        result = self.run_node(expression)
        self.assertEqual([r['week'] for r in result], [2])
        self.assertEqual(result[0]['level'], 0)
        result = self.run_node(expression.replace("'2026-01-15'", "'2026-01-14'"))
        self.assertEqual(result, [])

    def test_release_alignment_never_compares_different_ages(self):
        result = self.run_node("m.alignedReleaseCurves([{week:8,level:3},{week:9,level:2}], [{week:1,level:99},{week:8,level:6},{week:9,level:4},{week:52,level:1}])")
        self.assertEqual(result, {'weeks':[8,9], 'current':[3,2], 'reference':[6,4]})
