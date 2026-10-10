import json
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import unittest

from openpyxl import Workbook
from openpyxl.utils.datetime import CALENDAR_MAC_1904, to_excel

from core.excel import WorkbookItem, merge_source_sheets
from modules.launch_rhythm import _read_hourly


ROOT = Path(__file__).resolve().parents[1]


class LaunchHourlyTimeTests(unittest.TestCase):
    def sheet(self, times, headers=None):
        book = Workbook()
        self.addCleanup(book.close)
        sheet = book.active
        sheet.title = '智界 RX 2027款by时'
        sheet.append(['周期', *(headers or [f'H{i+87}' for i in range(len(times))])])
        sheet.append(['时间', *times])
        for label, values in (
            ('当日小订转大定数量', [0, 1, 1, 2]),
            ('当日直接大定数量', [1, 1, 0, 1]),
            ('当日大定数量', [1, 2, 1, 3]),
        ):
            sheet.append([label, *values[:len(times)]])
        return sheet

    def test_text_timestamps_ignore_elapsed_H_numbers(self):
        for times in (
            ['26-10-03 20:00', '26-10-03 22:00', '26-10-04 10:00', '26-10-04 11:00'],
            ['2026/10/3 20:00', '2026/10/3 22:00', '2026/10/4 10:00', '2026/10/4 11:00'],
            ['2026-10-03T20:00:00', '2026-10-03T22:00:00', '2026-10-04T10:00:00', '2026-10-04T11:00:00'],
        ):
            with self.subTest(times=times):
                rows, start = _read_hourly(self.sheet(times))
                self.assertEqual([row['hour'] for row in rows], [20, 22, 10, 11])
                self.assertEqual([row['period'] for row in rows], ['2026-10-03'] * 2 + ['2026-10-04'] * 2)
                self.assertEqual(start, '2026-10-03 20:00')
                self.assertEqual(rows[2]['small'], 1)
                self.assertEqual(rows[2]['direct'], 0)

    def test_native_and_serial_timestamps_preserve_values_and_epoch(self):
        times = [datetime(2026, 10, 3, 20), datetime(2026, 10, 3, 22), datetime(2026, 10, 4, 10), datetime(2026, 10, 4, 11)]
        expected = _read_hourly(self.sheet(times))
        for epoch in (Workbook().epoch, CALENDAR_MAC_1904):
            sheet = self.sheet([to_excel(value, epoch=epoch) for value in times])
            sheet.parent.epoch = epoch
            self.assertEqual(_read_hourly(sheet), expected)

    def test_unreadable_time_is_reported_not_guessed_from_H(self):
        sheet = self.sheet(['日期错误', '26-10-04 25:00', '2026-10-04', '26-10-04 11:00'])
        with self.assertLogs('modules.launch_rhythm', level='WARNING') as captured:
            rows, _ = _read_hourly(sheet)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['hour'], 11)
        self.assertEqual(len(captured.output), 1)
        self.assertIn('3列', captured.output[0])
        self.assertIn('B2', captured.output[0])

    def test_multiple_files_keep_sparse_clock_hours(self):
        first = self.sheet(['26-10-03 20:00', '26-10-03 22:00'])
        second = self.sheet(['26-10-04 10:00', '26-10-04 11:00'], ['H89', 'H90'])
        matches = [(WorkbookItem(Path(f'首销期订单节奏_{i}.xlsx'), sheet.parent), sheet) for i, sheet in enumerate((first, second))]
        _, merged = merge_source_sheets(matches)
        rows, _ = _read_hourly(merged)
        self.assertEqual([row['hour'] for row in rows], [20, 22, 10, 11])
        self.assertEqual(sum(row['orders'] for row in rows), 6)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_production_chart_keeps_nonzero_orders_on_second_day(self):
        rows, _ = _read_hourly(self.sheet(['26-10-03 20:00', '26-10-03 22:00', '26-10-04 10:00', '26-10-04 11:00']))
        script = r'''
const fs=require('fs'),source=fs.readFileSync('templates/dashboard.js','utf8');
const text=source.slice(source.indexOf('  function renderLaunchHourlyChart('),source.indexOf('  function renderLaunchHourly(rows)'));
const chart=new Function('rows','day','chartMax','colors','fmt','esc',text+';return renderLaunchHourlyChart(rows,day)');
const html=chart(JSON.parse(process.argv[1]),'2026-10-04',values=>Math.max(...values,1),{green:'green',blue:'blue'},String,String);
console.log(JSON.stringify([...html.matchAll(/class="total">([^<]+)</g)].map(match=>Number(match[1]))));
'''
        result = subprocess.run(['node', '-e', script, json.dumps(rows)], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        totals = json.loads(result.stdout)
        self.assertEqual(len(totals), 24)
        self.assertEqual(totals[10:12], [1, 3])
        self.assertEqual(sum(totals), 4)
