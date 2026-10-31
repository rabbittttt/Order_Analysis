"""Explicit zero reservation days are facts even without a positive final volume."""
import json
from datetime import date
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
from unittest import TestCase, skipUnless

from openpyxl import Workbook, load_workbook

from core.forecast_summary import DAILY_SHEET, SMALL_DAILY_SHEET, SMALL_CURVE_SHEET, table_records
from tests import test_audit_20261031_small_sources as prior_sources
from tests import test_forecast_source_backfill_e2e as fixtures

ROOT = Path(__file__).resolve().parents[1]


class ZeroMaintainedActualTests(TestCase):
    model = prior_sources.SmallMaintainedCellTests.model
    read = prior_sources.SmallMaintainedCellTests.read

    def test_all_zero_days_are_actuals_without_invented_completion(self):
        item = self.read([0, 0, 0], total=0, summary_total=0)
        self.assertTrue(item['daily_actual'])
        self.assertEqual(item['daily_orders'], [0, 0, 0])
        self.assertEqual(item['dates'], ['2026-09-01', '2026-09-02', '2026-09-03'])
        self.assertEqual(item['total'], 0)
        self.assertEqual(item['small_progress'], [None, None, None])
        self.assertIsNone(item['d1_share'])

    def test_partial_known_zeros_do_not_turn_unknown_days_into_zero(self):
        for values in ([0, None, 0], ['0', '待更新', 0]):
            with self.subTest(values=values):
                item = self.read(values, total=0, summary_total=None)
                self.assertTrue(item['daily_actual'])
                self.assertEqual(item['daily_orders'], [0, None, 0])
                self.assertFalse(item['total_complete'])
                self.assertEqual(item['small_progress'], [None, None, None])
                self.assertIsNone(item['d1_share'])

    def test_missing_sum_with_known_zero_remains_a_partial_observation(self):
        item = self.read([None, 0, None], total=None, summary_total=None)
        self.assertEqual(item['daily_orders'], [None, 0, None])
        self.assertFalse(item['total_complete'])
        self.assertEqual(item['small_progress'], [None, None, None])

    def test_zero_day_with_positive_maintained_denominator_can_have_zero_completion(self):
        item = self.read([0, None, 0], total=0, summary_total=100)
        self.assertEqual(item['daily_orders'], [0, None, 0])
        self.assertEqual(item['total'], 100)
        self.assertEqual(item['small_progress'], [0, None, None])
        self.assertEqual(item['d1_share'], 0)

    def test_positive_complete_record_is_unchanged(self):
        item = self.read([40, 40, 20], total=100, summary_total=100)
        self.assertTrue(item['daily_actual'])
        self.assertTrue(item['total_complete'])
        self.assertEqual(item['daily_orders'], [40, 40, 20])
        self.assertEqual(item['small_progress'], [.4, .8, 1])

    @skipUnless(shutil.which('node'), 'Node.js required')
    def test_zero_terminal_is_not_a_forecasting_reference(self):
        item = self.read([0, 0, 0], total=0, summary_total=0)
        positive = self.read([40, 40, 20], total=100, summary_total=100)
        positive['small_start_hour'] = 0
        positive['small_hourly_curve'] = [.5] * 23 + [1]
        code = "const m=require('./templates/forecast-math.js'),items=JSON.parse(process.argv[1]); console.log(JSON.stringify(items.map(i=>['total','progress','daily','slope','hourly'].map(task=>m.smallReferenceAvailable(i,task)))));"
        run = subprocess.run(['node', '-e', code, json.dumps([item, positive])], cwd=ROOT, text=True, encoding='utf-8', capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout), [[False] * 5, [True] * 5])


class ZeroMaintainedActualEndToEndTests(TestCase):
    def build(self, values, *, total=0, fallback=None):
        fixture = fixtures.SourceBackfillEndToEndTests()
        self.addCleanup(fixture.doCleanups)
        digest = {}

        def edit(path):
            book = load_workbook(path)
            for col, value in enumerate([*values, total], 2):
                book['小订by天'].cell(2, col).value = value
            book.save(path)
            book.close()
            digest['source'] = sha256(path.read_bytes()).hexdigest()

        def add(folder):
            if fallback is None:
                return
            book = Workbook()
            sheet = book.active
            sheet.title = fixture.model + 'by天'
            sheet.append(['指标', '统计类型', '分类', date(2026, 8, 30), date(2026, 8, 31)])
            sheet.append(['小订', '数量', '数量', *fallback])
            book.save(folder / '鸿蒙智行小订选配比例分析.xlsx')
            book.close()

        book = fixture.build(maintained={'总小订': 0}, source_edit=edit, add_sources=add)
        source = book._test_path.parent / '小订及首销数据整理.xlsx'
        self.assertEqual(sha256(source.read_bytes()).hexdigest(), digest['source'])
        rows = {str(row['日期'])[:10]: row for row in table_records(book, DAILY_SHEET)}
        _, profiles, _, history, _ = fixture.web_inputs(book, date(2026, 9, 5))
        return fixture, book, rows, profiles, history

    def test_zero_primary_days_win_over_positive_fallback_in_summary_and_web(self):
        fixture, book, rows, profiles, history = self.build([0, 0], fallback=[99, 30])
        for day in ('2026-08-30', '2026-08-31'):
            self.assertEqual(rows[day]['小订数量'], 0)
            self.assertIn('小订及首销数据整理.xlsx', rows[day]['字段来源'])
            self.assertNotIn('小订选配比例分析', rows[day]['字段来源'])
        profile = next(row for row in profiles if row['model'] == fixture.model)
        self.assertEqual([row['orders'] for row in profile['small_daily_days']], [0, 0])
        event = next(row for row in history if row['generation'] == fixture.model)
        self.assertEqual(event['daily_orders'], [0, 0])
        self.assertFalse(event['total_complete'])
        self.assertEqual(event['small_progress'], [None, None])
        curve = table_records(book, SMALL_CURVE_SHEET)[0]
        self.assertEqual([curve['D1'], curve['D2']], [None, None])

    def test_zero_day_retained_and_only_unknown_day_filled(self):
        _, book, rows, _, _ = self.build([0, None], fallback=[99, 30])
        self.assertEqual([rows[d]['小订数量'] for d in ('2026-08-30', '2026-08-31')], [0, 30])
        self.assertIn('小订及首销数据整理.xlsx', rows['2026-08-30']['字段来源'])
        self.assertIn('小订选配比例分析.xlsx', rows['2026-08-31']['字段来源'])
        curve = table_records(book, SMALL_CURVE_SHEET)[0]
        self.assertEqual([curve['D1'], curve['D2']], [None, None])

    def test_all_unknown_days_do_not_become_zero_facts(self):
        _, book, rows, _, _ = self.build([None, None], total=None)
        self.assertTrue(all(rows.get(d, {}).get('小订数量') is None for d in ('2026-08-30', '2026-08-31')))
        daily = table_records(book, SMALL_DAILY_SHEET)[0]
        self.assertEqual([daily['D1'], daily['D2']], [None, None])
