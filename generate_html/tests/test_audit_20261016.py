"""Unknown date cells, unverified D1 snapshots and real zero remainders."""
from datetime import date, datetime, time
import json
from pathlib import Path
import shutil
import subprocess
from unittest import TestCase, skipUnless
from unittest.mock import patch

from openpyxl.utils.datetime import to_excel

from core.forecast_summary import DAILY_SHEET, MASTER_SHEET, table_records, iso_day
from modules.sales_forecast import (_as_date, _as_datetime, _iso,
    _attach_actual_shapes, _attach_small_hourly_curves)
from tests import test_forecast_source_backfill_e2e as fixtures


class DateCellIsolationTests(TestCase):
    def test_time_only_excel_serials_and_booleans_are_not_calendar_dates(self):
        for value in (0, .5, True, False, time(12)):
            with self.subTest(value=value):
                self.assertIsNone(_as_date(value))
                self.assertIsNone(_as_datetime(value))
                self.assertEqual(_iso(value), '')

    def test_real_excel_dates_keep_their_date_and_hour(self):
        stamp = datetime(2026, 10, 8, 20, 30)
        serial = to_excel(stamp)
        self.assertEqual(_as_date(serial), stamp.date())
        self.assertEqual(_as_datetime(serial), stamp)
        for value in ('26/10/8', '2026-10-08', stamp, stamp.date()):
            self.assertEqual(_as_date(value), stamp.date())

    def test_bad_tail_date_does_not_abort_summary_or_invent_final_day(self):
        for daily, hourly in ((True, False), (False, True)):
            with self.subTest(daily=daily, hourly=hourly):
                helper = fixtures.SourceBackfillEndToEndTests()
                self.addCleanup(helper.doCleanups)
                book = helper.build(daily=daily, hourly=hourly,
                    dates=[datetime(2026, 9, 1, 20), datetime(2026, 9, 2, 20), 0])
                for row in table_records(book, DAILY_SHEET):
                    date.fromisoformat(iso_day(row['日期']))
                master = table_records(book, MASTER_SHEET)[0]
                self.assertIsNone(master['总小转大'])
                self.assertIsNone(master['总直接大定'])


class HourlyReferenceProofTests(TestCase):
    def curves(self, hours, daily_total=None):
        launch = {'model': '测试车', 'launch_date': '2026-09-01', 'daily_orders': []}
        small = {'model': '测试车', 'small_start_date': '2026-09-01',
                 'daily_orders': [], 'daily_actual': True}
        profile = {'model': '测试车', 'days': [], 'small_daily_days': [],
            'hourly_days': [{'date': '2026-09-01', 'hours':
                [{'hour': hour, 'gross': value} for hour, value in hours]}],
            'small_hourly_days': [{'date': '2026-09-01', 'hours':
                [{'hour': hour, 'orders': value} for hour, value in hours]}]}
        if daily_total is not None:
            profile['days'] = [{'date': '2026-09-01', 'gross': daily_total}]
            profile['small_daily_days'] = [{'date': '2026-09-01', 'orders': daily_total}]
        with patch('modules.sales_forecast._read_model_mapping', return_value={}):
            _attach_actual_shapes([launch], [profile], today=date(2026, 9, 2))
            _attach_small_hourly_curves([small], [profile], today=date(2026, 9, 2))
        return launch['hourly_curve'], small['small_hourly_curve']

    def test_unverified_partial_snapshot_is_not_a_finished_d1_reference(self):
        self.assertEqual(self.curves([(20, 40), (21, 60)]), ([], []))

    def test_known_daily_total_still_validates_sparse_omitted_zero_hours(self):
        for curve in self.curves([(20, 40), (21, 60)], daily_total=100):
            self.assertEqual(curve[19:23], [0, .4, 1, 1])

    def test_unique_complete_24_hours_needs_no_separate_daily_total(self):
        hours = [(hour, 40 if hour == 20 else 60 if hour == 21 else 0)
                 for hour in range(24)]
        for curve in self.curves(hours):
            self.assertEqual(curve[19:23], [0, .4, 1, 1])
        self.assertEqual(self.curves(hours[:-1]), ([], []))
        self.assertEqual(self.curves(hours + [(0, 0)]), ([], []))


@skipUnless(shutil.which('node'), 'Node.js required')
class ZeroRemainderAllocationTests(TestCase):
    def plan(self, remaining, shapes, **overrides):
        n = len(shapes)
        args = dict(remaining=remaining, anchor=10, anchorFactor=1, anchorShape=1,
                    shapes=shapes, factors=[1]*n, weights=[0, .5]+[1]*max(0, n-2))
        args['weights'] = args['weights'][:n]
        args.update(overrides)
        result = subprocess.run(['node', '-e',
            "const m=require('./templates/forecast-math.js');console.log(JSON.stringify(m.anchoredAllocate("
            + json.dumps(args) + ')));'], cwd=Path(__file__).resolve().parents[1],
            capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_known_zero_remainder_accepts_a_zero_future_reference_tail(self):
        for n in (1, 3, 30):
            for anchor in (None, 0, 10):
                with self.subTest(n=n, anchor=anchor):
                    result = self.plan(0, [0]*n, anchor=anchor)
                    self.assertEqual(result['error'], '')
                    self.assertEqual(result['values'], [0]*n)
                    self.assertEqual(result['base'], [0]*n)

    def test_positive_remainder_still_requires_nonzero_reference_mass(self):
        self.assertIn('没有有效量', self.plan(10, [0, 0, 0])['error'])

    def test_zero_remainder_does_not_bypass_invalid_factors_or_missing_shape(self):
        self.assertTrue(self.plan(0, [0, 0], factors=[1, 0])['error'])
        self.assertTrue(self.plan(0, [0, None])['error'])
