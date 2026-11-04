"""Confirmed audit regressions; do not replace absent observations with sales."""
from datetime import date
from unittest import TestCase
from unittest.mock import patch

from core.components import add_kpi_comparisons


class OctoberAuditTests(TestCase):


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
