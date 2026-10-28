"""D1 forecasts preserve newer same-day observations without inventing hours."""
import unittest
from tests import test_audit_20261026_small_snapshot as snapshot_fixture


class SmallOrderD1SnapshotTests(unittest.TestCase):
    run_cases = snapshot_fixture.SmallOrderSnapshotFloorTests.run_cases

    def d1_case(self, **overrides):
        return {'today': '2026-09-01', 'fixed': [], 'hour': 20,
                'hours': [{'hour': 0, 'orders': 10}, {'hour': 1, 'orders': 10}],
                **overrides}

    def test_newer_daily_snapshot_bounds_d1_actual_and_terminal(self):
        result = self.run_cases([self.d1_case(day=1200)])[0]
        self.assertEqual(result['error'], '')
        self.assertEqual((result['d1'], result['actual'], result['total']), ('1200', '1200', 4800))
        self.assertEqual(result['rows'][0]['orders'], 1200)
        self.assertEqual(result['rows'][0]['observed'], 1200)
        self.assertFalse(result['rows'][0]['actual'])
        self.assertEqual(sum(row['orders'] for row in result['rows']), result['total'])
        self.assertIn('下限', result['source'])

    def test_newer_daily_snapshot_below_fit_only_updates_actuals(self):
        result = self.run_cases([self.d1_case(day=100)])[0]
        self.assertEqual((result['d1'], result['actual'], result['total']), ('240', '100', 960))
        self.assertEqual(result['rows'][0]['observed'], 100)

    def test_stale_equal_zero_and_unknown_daily_snapshots_keep_hourly_fit(self):
        invalid = [None, '', '  ', True, False, -1, 'invalid', 'NaN', 'Infinity']
        cases = [self.d1_case(), *[self.d1_case(day=value) for value in [0, 10, 20, *invalid]]]
        for result in self.run_cases(cases):
            with self.subTest(result=result):
                self.assertEqual(result['error'], '')
                self.assertEqual((result['d1'], result['actual'], result['total']), ('240', '20', 960))
                self.assertEqual(result['rows'][0]['observed'], 20)

    def test_today_observed_does_not_leak_onto_tomorrow(self):
        for result in self.run_cases([self.d1_case(day=1200), self.d1_case(day=20), self.d1_case()]):
            self.assertTrue(all('observed' not in row for row in result['rows'][1:]))

    def test_no_hourly_fit_stays_unavailable_even_with_daily_snapshot(self):
        result = self.run_cases([self.d1_case(day=1200, hours=[])])[0]
        self.assertTrue(result['error'])
        self.assertIsNone(result['total'])
        self.assertEqual(result['d1'], '—')

    def test_hourly_count_and_daily_snapshot_are_never_added(self):
        case = self.d1_case(day=1200, hour=1200,
                            hours=[{'hour': 0, 'orders': 600}, {'hour': 1, 'orders': 600}])
        result = self.run_cases([case])[0]
        self.assertEqual((result['d1'], result['actual'], result['total']), ('14400', '1200', 57600))
        self.assertEqual(result['rows'][0]['observed'], 1200)
