"""Public small-order references must preserve calendar positions and cutoff."""
from datetime import date
from unittest import TestCase

from core.forecast_summary import DAILY_SHEET, read_public_forecast
from tests import test_public_forecast_tables


class SmallReferenceCalendarTests(TestCase):
    def workbook(self, observations, today=date(2026, 1, 4)):
        def customize(data):
            data['small_order_history'] = []
            data['targets'][0].update(small_end_date='2026-01-07')
            data['actuals'][0]['small_daily_days'] = [
                {'date': day, 'orders': count} for day, count in observations]
        book = test_public_forecast_tables.PublicForecastTablesTests().make_public(customize=customize, as_of=today)
        self.addCleanup(book.close)
        return book

    def test_unfinished_day_is_not_historical_but_remains_an_actual_snapshot(self):
        book = self.workbook([('2026-01-01', 20), ('2026-01-02', 10), ('2026-01-04', 999)])
        profiles, _, history, _ = read_public_forecast(book, [], today=date(2026, 1, 4))
        item = history[0]
        self.assertEqual(item['daily_orders'], [20, 10])
        self.assertEqual(item['dates'], ['2026-01-01', '2026-01-02'])
        self.assertEqual(item['total'], 30)
        self.assertFalse(item['total_complete'])
        self.assertIn({'date': '2026-01-04', 'orders': 999}, profiles[0]['small_daily_days'])

    def test_replay_does_not_read_later_observations(self):
        book = self.workbook([('2026-01-01', 20), ('2026-01-02', 10), ('2026-01-03', 800)])
        item = read_public_forecast(book, [], today=date(2026, 1, 2))[2][0]
        self.assertEqual(item['daily_orders'], [20])
        self.assertEqual(item['total'], 20)

    def test_missing_day_never_moves_later_quantity_or_calendar_factor(self):
        book = self.workbook([('2026-01-01', 20), ('2026-01-03', 40)])
        item = read_public_forecast(book, [], today=date(2026, 1, 4))[2][0]
        self.assertEqual(item['dates'], ['2026-01-01', '2026-01-02', '2026-01-03'])
        self.assertEqual(item['daily_orders'], [20, None, 40])
        self.assertEqual(item['small_progress'], [None, None, None])

    def test_missing_first_day_is_not_replaced_by_d2(self):
        book = self.workbook([('2026-01-02', 10)])
        item = read_public_forecast(book, [], today=date(2026, 1, 4))[2][0]
        self.assertEqual(item['daily_orders'], [None, 10])
        self.assertEqual(item['dates'][0], '2026-01-01')

    def test_duplicate_date_is_unknown_not_two_lifecycle_days(self):
        book = self.workbook([('2026-01-01', 20), ('2026-01-02', 10)])
        sheet = book[DAILY_SHEET]
        headers = [c.value for c in sheet[1]]
        row = next(list(values) for values in sheet.iter_rows(min_row=2, values_only=True)
                   if values[headers.index('日期')].date() == date(2026, 1, 2))
        sheet.append(row)
        item = read_public_forecast(book, [], today=date(2026, 1, 4))[2][0]
        self.assertEqual(item['daily_orders'], [20, None])
        self.assertEqual(item['total'], 20)

    def test_confirmed_zero_is_retained_and_no_future_day_is_padded(self):
        book = self.workbook([('2026-01-01', 20), ('2026-01-02', 0), ('2026-01-03', 40)])
        item = read_public_forecast(book, [], today=date(2026, 1, 4))[2][0]
        self.assertEqual(item['daily_orders'], [20, 0, 40])
        self.assertEqual(item['total'], 60)
        self.assertEqual(len(item['dates']), 3)

    def test_only_today_does_not_become_a_completed_d1_reference(self):
        book = self.workbook([('2026-01-01', 99)], today=date(2026, 1, 1))
        item = read_public_forecast(book, [], today=date(2026, 1, 1))[2][0]
        self.assertEqual(item['daily_orders'], [])
        self.assertEqual(item['total'], 0)
        self.assertTrue(item['daily_actual'])
