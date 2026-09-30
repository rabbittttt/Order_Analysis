from unittest import TestCase

from modules.sales_forecast import _history_item
from tools.refresh_sales_forecast_data import reorder_summary_sheets
from core.forecast_summary import D12_SHEET, SMALL_DAILY_SHEET, SMALL_CURVE_SHEET
from openpyxl import Workbook


class ReferenceParameterTests(TestCase):
    def test_history_ratios_preserve_missing_and_explicit_zero(self):
        fields = {'小订转化率':'conversion', '直接大定占比':'direct_share',
                  '大定到锁单率':'lock_rate', '留存大定率':'net_rate', '退订率':'cancel_rate'}
        missing = _history_item({'传播名':'测试车'}, True)
        zero = _history_item({'传播名':'测试车', **dict.fromkeys(fields, 0)}, True)
        for field in fields.values():
            self.assertIsNone(missing[field], field)
            self.assertEqual(zero[field], 0, field)

    def test_final_generator_sort_keeps_requested_three_sheets_adjacent(self):
        book = Workbook()
        for name in (D12_SHEET, SMALL_CURVE_SHEET, SMALL_DAILY_SHEET, '其他表'):
            book.create_sheet(name)
        reorder_summary_sheets(book)
        self.assertEqual(book.sheetnames[:3], [SMALL_DAILY_SHEET, SMALL_CURVE_SHEET, D12_SHEET])
        book.close()
