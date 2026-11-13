"""Offline CLI exports must not publish a dynamic dataset or start a service."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook

import main as generator


class StaticEntryTests(TestCase):
    def test_static_and_dynamic_default_outputs_are_distinct(self):
        with patch('sys.argv', ['main.py']):
            dynamic = generator.parse_args()
        with patch('sys.argv', ['main.py', '--static']):
            static = generator.parse_args()
        self.assertFalse(dynamic.static)
        self.assertTrue(static.static)
        self.assertEqual(dynamic.output.name, '鸿蒙智行订单分析汇总.html')
        self.assertEqual(static.output.name, '鸿蒙智行订单分析汇总_静态版.html')
        self.assertEqual(dynamic.input, static.input)
        with patch('sys.argv', ['main.py', '--static', '--output', 'custom report.html', '--no-open']):
            custom = generator.parse_args()
        self.assertEqual(custom.output, Path('custom report.html'))
        self.assertTrue(custom.no_open)

    def test_static_main_opens_file_uri_and_never_starts_service(self):
        for no_open in (False, True):
            with self.subTest(no_open=no_open), TemporaryDirectory() as folder:
                root = Path(folder)
                output = root / '静态 report.html'
                args = argparse.Namespace(input=root/'input', output=output, static=True,
                                          debug=False, check=False, no_open=no_open, port=8767)
                manifest = {'subjects': [], 'dashboards': {}}
                def export(*_, **kwargs):
                    self.assertTrue(kwargs['static'])
                    output.write_text('<html>offline</html>', encoding='utf-8')
                    return manifest, []
                with ExitStack() as stack:
                    stack.enter_context(patch.object(generator, 'parse_args', return_value=args))
                    stack.enter_context(patch.object(generator, 'configure_runtime', return_value=root/'run.log'))
                    stack.enter_context(patch.dict(generator.DIAGNOSTIC_COUNTS, {'ERROR':0, 'WARNING':0}))
                    stack.enter_context(patch.object(generator, 'build', side_effect=export))
                    stack.enter_context(patch.object(generator, 'LOGGER'))
                    service = stack.enter_context(patch.object(generator, 'open_dynamic_dashboard'))
                    browser = stack.enter_context(patch.object(generator.webbrowser, 'open'))
                    self.assertEqual(generator.main(), 0)
                    service.assert_not_called()
                    if no_open:
                        browser.assert_not_called()
                    else:
                        browser.assert_called_once_with(output.resolve().as_uri())

    def test_real_static_build_embeds_data_without_changing_dynamic_runtime(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'input'
            source.mkdir()
            for filename, primary, secondary in (
                ('鸿蒙智行大定选配比例分析.xlsx', '大定', '留存大定'),
                ('鸿蒙智行锁单选配比例分析.xlsx', '交车锁单', '已交付'),
            ):
                book = Workbook()
                sheet = book.active
                sheet.title = '鸿蒙智行by天'
                sheet.append(['指标','统计类型','分类',date(2026,11,1),date(2026,11,2)])
                sheet.append([primary,'数量','数量',10,20])
                sheet.append([secondary,'数量','数量',8,16])
                book.save(source/filename)
                book.close()
            runtime = root/'runtime'
            runtime.mkdir()
            pointer = runtime/'current.json'
            pointer.write_text('{"dataset_id":"existing"}',encoding='utf-8')
            entry = runtime/'index.html'
            entry.write_text('<html>existing dynamic</html>',encoding='utf-8')
            output = root/'offline.html'
            with patch.dict(generator.DIAGNOSTIC_COUNTS, {'ERROR':0,'WARNING':0}), \
                 patch('core.discovery.generation_records',return_value=[]):
                manifest, _ = generator.build(source, output, static=True)
            self.assertTrue(manifest['dashboards'])
            html = output.read_text(encoding='utf-8')
            self.assertIn('window.DASHBOARD_DATA_B64=',html)
            self.assertIn('window.DASHBOARD_BLOCKS_B64=',html)
            self.assertIn('window.DASHBOARD_RAW_B64=',html)
            self.assertNotIn('window.ORDER_DASHBOARD_API_BASE="api/"',html)
            self.assertNotIn('<script src=',html)
            self.assertEqual(pointer.read_text(encoding='utf-8'),'{"dataset_id":"existing"}')
            self.assertEqual(entry.read_text(encoding='utf-8'),'<html>existing dynamic</html>')
            self.assertEqual(set(path.name for path in runtime.iterdir()),{'current.json','index.html'})
