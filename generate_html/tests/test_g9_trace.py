"""Targeted G9 diagnostics observe source/cache/resolution without changing facts."""
import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook, load_workbook

import tests.test_forecast_source_backfill_e2e as fixtures
from core.forecast_summary import (G9_TRACE_MODEL, MASTER_SHEET, D12_SHEET, DAILY_SHEET,
    table_records, forecast_trace, forecast_trace_series, forecast_trace_enabled)
from tools.refresh_sales_forecast_data import trace_g9_source, trace_g9_workbook


class G9TraceTests(TestCase):
    def fixture(self, **kwargs):
        helper = fixtures.SourceBackfillEndToEndTests()
        self.addCleanup(helper.doCleanups)
        return helper, helper.build(**kwargs)

    def payloads(self, records, step):
        return [json.loads(r.getMessage().split(' | ', 2)[2]) for r in records
                if '[G9取数排查]' in r.getMessage() and f'环节={step} | ' in r.getMessage()]

    def test_filter_is_exact_generation_and_preserves_zero_vs_missing(self):
        self.assertTrue(forecast_trace_enabled('享界G9 2027款'))
        for name in ('享界 G9 2026款', '智界 RX 2027款', '鸿蒙智行', None):
            self.assertFalse(forecast_trace_enabled(name))
        values = [0, None, 12, -1]
        self.assertEqual(forecast_trace_series(values)['零值数'], 1)
        self.assertEqual(forecast_trace_series(values)['有效数'], 2)
        self.assertEqual(values, [0, None, 12, -1])
        with self.assertLogs('sales_forecast_refresh', level='INFO') as logs:
            forecast_trace(G9_TRACE_MODEL, '测试', 零值=0, 空白=None)
            forecast_trace('智界 RX 2027款', '测试', 隐私值=999)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(self.payloads(logs.records, '测试')[0], {'零值':0, '空白':None})

    def test_full_pipeline_logs_every_stage_and_each_final_quantity_sheet(self):
        with self.assertLogs('sales_forecast_refresh', level='INFO') as logs:
            helper, book = self.fixture()
        helper.assert_complete(book)
        for step in ('刷新启动','整理表读取','原始Sheet缓存值','原始公式缓存',
                     '首销Sheet匹配','首销日期解析','解析后候选','退订表头匹配',
                     '逐日选值概况','逐日选值明细','累计源接受', '小订参考计算',
                     'Dn映射及累计结果','终值判定','比例判定','D1D2计算',
                     '保存前Sheet核对','正式文件已保存'):
            self.assertTrue(self.payloads(logs.records, step), step)
        sheets = {r['Sheet'] for r in self.payloads(logs.records, '保存前Sheet核对')}
        self.assertEqual(sheets, set(book.sheetnames)-{'说明与来源'})
        self.assertTrue(all(s.sheet_state == 'visible' for s in book))

    def test_blank_terminal_prints_first_gap_and_denominator_not_a_guessed_total(self):
        def edit(folder):
            path = folder/'鸿蒙智行首销期订单节奏.xlsx'
            book = load_workbook(path)
            for sheet in book:
                for row in (4,5,6,7):
                    sheet.cell(row,4).value = None
            book.save(path); book.close()
        with self.assertLogs('sales_forecast_refresh', level='INFO') as logs:
            _, book = self.fixture(add_sources=edit)
        master = table_records(book, MASTER_SHEET)[0]
        self.assertIsNone(master['总小转大'])
        terminal = next(r for r in self.payloads(logs.records,'终值判定') if r['字段']=='总小转大')
        self.assertIsNone(terminal['结束日累计'])
        mapped = self.payloads(logs.records,'Dn映射及累计结果')[0]
        self.assertEqual(mapped['日量']['小转大']['空白或无效范围'], 'D3')
        final = next(r for r in self.payloads(logs.records,'保存前Sheet核对') if r['Sheet']=='小转大累计完成度')
        self.assertEqual(final['Dn']['有效数'], 0)
        self.assertEqual(table_records(book,D12_SHEET)[0]['D1小转大'], 10)

    def test_conflicting_cumulative_logs_exact_rejection_interval(self):
        with self.assertLogs('sales_forecast_refresh', level='INFO') as logs:
            _, book = self.fixture(source_quantities={'小转大进度':[0,None,None]})
        rejected = next(r for r in self.payloads(logs.records,'累计源拒绝') if r['字段']=='小转大')
        self.assertEqual(rejected['首冲突日期'],'2026-09-01')
        self.assertEqual(rejected['高优先级日量合计'],0)
        self.assertEqual(rejected['累计增量'],10)
        self.assertEqual(table_records(book,MASTER_SHEET)[0]['总小转大'],30)

    def test_physical_formula_cache_and_missing_date_are_visible(self):
        def edit(folder):
            path = folder/'鸿蒙智行首销期订单节奏.xlsx'
            book = load_workbook(path)
            sheet = book[G9_TRACE_MODEL+'by天']
            sheet['D2'] = '=DATE(2026,9,3)'
            sheet['D4'] = '=5+5'
            # The maintained terminal is not necessarily the physical last
            # column: the source can continue updating after launch ends.
            for day in range(4,11):
                sheet.cell(1,day+1,f'D{day}')
                sheet.cell(2,day+1,datetime(2026,9,day))
                sheet.cell(3,day+1,3)
                sheet.cell(4,day+1,1)
                sheet.cell(6,day+1,2)
            book.save(path); book.close()
        with self.assertLogs('sales_forecast_refresh', level='INFO') as logs:
            _, book = self.fixture(add_sources=edit)
        cached = next(r for r in self.payloads(logs.records,'原始公式缓存') if r['Sheet'].endswith('by天'))
        self.assertEqual(cached['采样内公式']['D4']['公式'], '5+5')
        self.assertEqual(cached['采样内公式']['D4']['状态'], '无缓存结果')
        self.assertEqual(cached['采样内公式']['D2']['状态'], '无缓存结果')
        parsed = self.payloads(logs.records,'首销日期解析')[0]
        self.assertEqual(parsed['无法解析列'][0]['周期'],'D3')
        self.assertIsNone(table_records(book,MASTER_SHEET)[0]['总小转大'])
        def uncached_tail(folder):
            path=folder/'鸿蒙智行首销期订单节奏.xlsx'
            source=load_workbook(path); sheet=source[G9_TRACE_MODEL+'by天']
            for row, formula in enumerate(('="D3"','=DATE(2026,9,3)','=30','=10','=40','=20','=90','=15'),1):
                sheet.cell(row,4,formula)
            source.save(path); source.close()
        with self.assertLogs('sales_forecast_refresh',level='INFO') as logs:
            _, book=self.fixture(add_sources=uncached_tail)
        raw=next(r for r in self.payloads(logs.records,'原始公式缓存') if r['Sheet'].endswith('by天'))
        self.assertEqual(raw['缓存可见列数'],3)
        self.assertEqual(raw['原始声明范围'],'A1:D8')
        self.assertEqual(raw['缓存范围外公式样例']['D4']['状态'],'无缓存结果')
        self.assertIsNone(table_records(book,MASTER_SHEET)[0]['总小转大'])

    def test_diagnostics_do_not_change_saved_cells(self):
        with patch('core.forecast_summary.forecast_trace_enabled', return_value=False), \
             patch('modules.sales_forecast.forecast_trace_enabled', return_value=False), \
             patch('tools.refresh_sales_forecast_data.forecast_trace_enabled', return_value=False):
            _, baseline = self.fixture()
        with self.assertLogs('sales_forecast_refresh', level='INFO'):
            _, traced = self.fixture()
        self.assertEqual(baseline.sheetnames,traced.sheetnames)
        for name in baseline.sheetnames:
            self.assertEqual(list(baseline[name].values),list(traced[name].values),name)

    def test_other_models_skip_physical_xml_and_final_deep_scans(self):
        book = Workbook(); sheet=book.active; sheet.title='智界 RX 2027款by天'
        with patch('zipfile.ZipFile') as zipped:
            trace_g9_source(Path('不存在.xlsx'),sheet)
            zipped.assert_not_called()
        master = book.create_sheet(MASTER_SHEET)
        master.append(['代际名']); master.append(['智界 RX 2027款'])
        with self.assertLogs('sales_forecast_refresh', level='INFO') as logs:
            trace_g9_workbook(book)
        self.assertEqual(len(logs.records),1)
        self.assertIn('未匹配到目标代际',logs.output[0])
        self.assertNotIn('智界 RX',logs.output[0])
        book.close()

    def test_hourly_source_probes_are_bounded_not_every_hour_of_each_focus_day(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'首销期订单节奏.xlsx'
            book=Workbook(); sheet=book.active; sheet.title=G9_TRACE_MODEL+'by时'
            stamps=[datetime(2026,9,1)+timedelta(hours=i) for i in range(24*14)]
            sheet.append(['周期',*[f'H{i+1}' for i in range(len(stamps))]])
            sheet.append(['时间',*stamps]); sheet.append(['当日大定数量',*[1]*len(stamps)])
            book.save(path)
            with self.assertLogs('sales_forecast_refresh',level='INFO') as logs:
                trace_g9_source(path,sheet,{date(2026,9,i) for i in (1,2,8,9,10)})
            sample=self.payloads(logs.records,'原始Sheet缓存值')[0]['采样单元格']
            self.assertLess(len(sample),100)
            book.close()

    def test_reused_summary_is_labelled_without_replaying_source_parsing(self):
        _, book = self.fixture()
        before = deepcopy(list(book[MASTER_SHEET].values))
        with self.assertLogs('sales_forecast_refresh', level='INFO') as logs:
            trace_g9_workbook(book,'复用Sheet核对')
        self.assertTrue(self.payloads(logs.records,'复用Sheet核对'))
        self.assertFalse(self.payloads(logs.records,'原始Sheet缓存值'))
        self.assertEqual(before,list(book[MASTER_SHEET].values))
