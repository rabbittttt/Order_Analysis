from __future__ import annotations

import os
import unittest
from copy import copy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill, Protection
from openpyxl.utils.indexed_list import IndexedList

from core.excel import parse_metric_sheet
from modules.option_fee import _option_layout


class PerformanceGuardTests(unittest.TestCase):


    def test_metric_and_option_layout_results_are_cached_per_sheet(self):
        workbook = Workbook()
        metric = workbook.active
        metric.cell(1, 4, "26WK35")
        metric.cell(2, 1, "大定")
        metric.cell(2, 2, "数量")
        metric.cell(2, 3, "数量")
        metric.cell(2, 4, 100)
        self.assertIs(parse_metric_sheet(metric), parse_metric_sheet(metric))

        option = workbook.create_sheet("选配金")
        option.cell(3, 3, "26-08")
        option.cell(4, 3, "免费")
        option.cell(4, 4, "0-5000")
        option.cell(5, 2, "订单数量")
        option.cell(5, 3, 10)
        option.cell(5, 4, 20)
        first = _option_layout(option)
        self.assertEqual(first, (3, 4, 5))
        self.assertIs(first, _option_layout(option))


if __name__ == "__main__":
    unittest.main()
