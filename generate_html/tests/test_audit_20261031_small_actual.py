"""Unavailable D1 fitting must not erase independently known actual quantities."""
import unittest
from tests import test_audit_20261026_small_snapshot as snapshot_fixture


class SmallOrderD1ActualTests(unittest.TestCase):
    run_cases = snapshot_fixture.SmallOrderSnapshotFloorTests.run_cases

    def case(self, **overrides):
        return {'today': '2026-09-01', 'fixed': [], **overrides}

    def assert_unavailable(self, result, actual):
        self.assertEqual(result['actual'], actual)
        self.assertIsNone(result['total'])
        self.assertEqual(result['d1'], '—')
        self.assertTrue(result['error'])
        self.assertEqual(result['rows'], [])

    def test_daily_snapshot_survives_missing_hourly_bucket(self):
        self.assert_unavailable(self.run_cases([self.case(day=1200)])[0], '1200')

    def test_summary_survives_missing_hours_without_double_counting(self):
        for result in self.run_cases([self.case(day=1000, hour=1200), self.case(day=1200, hour=1200), self.case(day=1200, hour=1000)]):
            self.assert_unavailable(result, '1200')

    def test_zero_hourly_fit_does_not_erase_newer_daily_actual(self):
        self.assert_unavailable(self.run_cases([self.case(day=1200, hour=0, hours=[{'hour': 0, 'orders': 0}])])[0], '1200')

    def test_invalid_hourly_points_do_not_invalidate_known_daily_actual(self):
        for bad in [None, True, -1, 'invalid']:
            result = self.run_cases([self.case(day=1200, hour=None, hours=[{'hour': 0, 'orders': bad}])])[0]
            self.assert_unavailable(result, '1200')

    def test_explicit_zero_is_distinct_from_unknown(self):
        for result in self.run_cases([self.case(day=0), self.case(hour=0), self.case(day='0')]):
            self.assert_unavailable(result, '0')
        invalid = [None, '', '  ', True, False, -1, 'invalid', 'NaN', 'Infinity']
        for result in self.run_cases([self.case(), *[self.case(day=v, hour=v) for v in invalid]]):
            self.assert_unavailable(result, '—')

    def test_other_dates_do_not_supply_d1_actual(self):
        result = self.run_cases([self.case(fixed=[{'date': '2026-08-31', 'orders': 9000}, {'date': '2026-09-02', 'orders': 8000}])])[0]
        self.assert_unavailable(result, '—')

    def test_valid_hourly_forecast_is_unchanged(self):
        result = self.run_cases([self.case(day=1200, hour=20, hours=[{'hour': 0, 'orders': 10}, {'hour': 1, 'orders': 10}])])[0]
        self.assertEqual((result['actual'], result['d1'], result['total']), ('1200', '1200', 4800))
        self.assertEqual(result['error'], '')
        self.assertEqual(sum(row['orders'] for row in result['rows']), 4800)
        self.assertEqual(result['rows'][0]['observed'], 1200)
        self.assertNotIn('observed', result['rows'][1])

    def test_actual_history_supplies_only_missing_d1_daily_quantity(self):
        fallback = [{'date': '2026-09-01', 'orders': 1200}]
        cases = [self.case(fallback=fallback), self.case(day=None, fallback=fallback), self.case(day=0, fallback=fallback), self.case(day=50, fallback=fallback)]
        for result, expected in zip(self.run_cases(cases), ['1200', '1200', '0', '50']):
            self.assert_unavailable(result, expected)

    def test_progress_history_is_not_a_real_snapshot(self):
        result = self.run_cases([self.case(fallback=[{'date': '2026-09-01', 'orders': 1200}], fallback_actual=False)])[0]
        self.assert_unavailable(result, '—')

    def test_actual_history_also_bounds_an_existing_hourly_fit(self):
        result = self.run_cases([self.case(hour=20, hours=[{'hour': 0, 'orders': 10}, {'hour': 1, 'orders': 10}], fallback=[{'date': '2026-09-01', 'orders': 1200}])])[0]
        self.assertEqual((result['actual'], result['d1'], result['total']), ('1200', '1200', 4800))
