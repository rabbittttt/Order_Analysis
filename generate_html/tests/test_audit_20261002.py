"""Confirmed audit regressions; do not replace absent observations with sales."""
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from core.components import add_kpi_comparisons
from modules.sales_forecast import _attach_actual_shapes, _attach_small_hourly_curves, _history_item


class OctoberAuditTests(TestCase):
    def attach(self, stage, hours, total=100, today=date(2026, 9, 2)):
        small = stage == 'small'
        field = 'orders' if small else 'gross'
        item = {'model': 'test', 'small_start_date' if small else 'launch_date': '2026-09-01',
                'daily_orders': [total]}
        bucket = {'date': '2026-09-01', 'hours': [{'hour': h, field: v} for h, v in hours]}
        profile = {'model': 'test', 'small_hourly_days' if small else 'hourly_days': [bucket]}
        with patch('modules.sales_forecast._read_model_mapping', return_value={}):
            if small:
                _attach_small_hourly_curves([item], [profile], today=today)
            else:
                _attach_actual_shapes([item], [profile], today=today)
        return item['small_hourly_curve' if small else 'hourly_curve']

    def test_partial_d1_hourly_is_not_normalized_to_a_complete_reference(self):
        for stage in ('small', 'launch'):
            with self.subTest(stage=stage):
                self.assertEqual(self.attach(stage, [(18, 30)]), [])

    def test_missing_invalid_hourly_cells_do_not_become_zero(self):
        for stage in ('small', 'launch'):
            for hours in ([(18, 100), (19, None)], [(18, 110), (19, -10)],
                          [(18, 100), (24, 0)], [(18, 100), (19, float('nan'))]):
                with self.subTest(stage=stage, hours=hours):
                    self.assertEqual(self.attach(stage, hours), [])

    def test_unfinished_d1_cannot_be_historical_reference(self):
        for stage in ('small', 'launch'):
            with self.subTest(stage=stage):
                self.assertEqual(self.attach(stage, [(18, 100)], today=date(2026, 9, 1)), [])

    def test_known_zero_d1_cannot_validate_positive_hourly_reference(self):
        for stage in ('small', 'launch'):
            with self.subTest(stage=stage):
                self.assertEqual(self.attach(stage, [(18, 30)], total=0), [])

    def test_resolved_daily_actual_takes_precedence_over_old_reference_total(self):
        launch = {'model': 'test', 'launch_date': '2026-09-01', 'daily_orders': [100]}
        small = {'model': 'test', 'small_start_date': '2026-09-01', 'daily_orders': [100], 'daily_actual': False}
        profile = {'model': 'test', 'days': [{'date': '2026-09-01', 'gross': 30}],
            'small_daily_days': [{'date': '2026-09-01', 'orders': 30}],
            'hourly_days': [{'date': '2026-09-01', 'hours': [{'hour': 18, 'gross': 30}]}],
            'small_hourly_days': [{'date': '2026-09-01', 'hours': [{'hour': 18, 'orders': 30}]}]}
        with patch('modules.sales_forecast._read_model_mapping', return_value={}):
            _attach_actual_shapes([launch], [profile], today=date(2026, 9, 2))
            _attach_small_hourly_curves([small], [profile], today=date(2026, 9, 2))
        self.assertEqual(launch['hourly_curve'][18], 1)
        self.assertEqual(small['small_hourly_curve'][18], 1)

    def test_finished_d1_with_omitted_zero_hours_keeps_real_clock(self):
        for stage in ('small', 'launch'):
            with self.subTest(stage=stage):
                curve = self.attach(stage, [(20, 60), (18, 40)])
                self.assertEqual(curve[18:21], [.4, .4, 1])
                self.assertEqual(curve[21:], [1, 1, 1])

    def test_current_visible_summary_quantity_headers_are_recognized(self):
        item = _history_item({'传播名': 'test', '总小转大': 80, '总退订': 10}, True)
        self.assertEqual(item['small_to_big'], 80)
        self.assertEqual(item['cancel'], 10)

    def test_explicit_zero_never_falls_back_to_legacy_quantity(self):
        item = _history_item({'传播名': 'test', '总大定': 0, '大定量': 100,
            '总小转大': 0, '小订转大': 80, '总退订': 0, '小订后退订': 10,
            '首销期留存大定': 0, '首销期净大定': 90,
            '总直接大定': 0, '直接大定量': 20,
            'D1小转大': 0, '首日小转大': 30, 'D1直接大': 0, '首日直接大定': 20,
            'D1直接大/D1大定': 0, '首日直接大定占比': .2}, True)
        for field in ('gross', 'small_to_big', 'cancel', 'net', 'direct', 'd1_small', 'd1_direct', 'd1_direct_share'):
            self.assertEqual(item[field], 0, field)

    def test_blank_primary_quantity_still_uses_legacy_fallback(self):
        item = _history_item({'传播名': 'test', '总大定': None, '大定量': 100,
            '总小转大': '', '小订转大': 80, '总退订': None, '小订后退订': 10}, True)
        self.assertEqual((item['gross'], item['small_to_big'], item['cancel']), (100, 80, 10))

    def comparisons(self, periods):
        pages = {p: {'kpis': [{'label': '大定', 'value': v}]} for p, v in periods}
        board = {'x': {'views': {'week': {'periods': [p for p, _ in periods], 'pages': pages}}}}
        add_kpi_comparisons(board)
        return {p: page['kpis'][0]['comparison'] for p, page in pages.items()}

    def test_first_detail_period_does_not_compare_with_total(self):
        result = self.comparisons([('总计', 1000), ('26WK01', 100)])
        self.assertEqual(result['26WK01']['status'], 'unavailable')

    def test_aggregate_columns_are_skipped_between_comparable_periods(self):
        result = self.comparisons([('26WK01', 100), ('近28天', 700), ('总计', 1000), ('26WK02', 120)])
        self.assertEqual(result['26WK02']['previous'], 100)
        self.assertAlmostEqual(result['26WK02']['rate'], .2)
        self.assertEqual(result['总计']['status'], 'unavailable')

    def test_zero_previous_detail_remains_real_with_undefined_ratio(self):
        result = self.comparisons([('26WK01', 0), ('26WK02', 20)])
        self.assertEqual(result['26WK02']['previous'], 0)
        self.assertEqual(result['26WK02']['delta'], 20)
        self.assertIsNone(result['26WK02']['rate'])
