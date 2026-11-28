"""Order builds exclude auxiliary inputs and never execute the separate prediction app."""
import base64
import gzip
import json
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook

import main as generator
from core.model_identity import STAGE_SOURCE_PATH

SUMMARY_NAME = "鸿蒙智行销量数据汇总.xlsx"

class OrderProjectIsolationTests(TestCase):
    def write_book(self, path, sheet_name):
        book = Workbook()
        book.active.title = sheet_name
        book.active.append(['指标', '数量'])
        book.active.append(['留存大定', 3])
        book.save(path)
        book.close()

    def patch_build(self, stack):
        config = dict(title='测试', chart_render_mode='generated',
                      build_manifest_mode='off', module_order=['overview', 'raw'])
        stack.enter_context(patch.object(generator, 'load_config', return_value=config))
        stack.enter_context(patch('core.discovery.generation_records', return_value=[]))
        stack.enter_context(patch.object(generator, 'validate_manifest', return_value=[]))
        def render(manifest, templates, output):
            runtime = output.parent / 'runtime'
            runtime.mkdir(exist_ok=True)
            (runtime / 'index.html').write_text('generated', encoding='utf-8')

        stack.enter_context(patch.object(generator, 'render_dashboard', side_effect=render))

    def test_sales_summary_is_downloadable_and_isolated_from_order_modules(self):
        with TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            ordinary = root / '订单分析.xlsx'
            self.write_book(ordinary, '鸿蒙智行')
            auxiliaries = {
                STAGE_SOURCE_PATH.name: '智界 R9 2027款',
                SUMMARY_NAME: '问界 M1 2027款',
            }
            original_bytes = {}
            for name, sheet in auxiliaries.items():
                self.write_book(root / name, sheet)
                original_bytes[name] = (root / name).read_bytes()
            self.patch_build(stack)
            observed = []

            def observe(store, subject):
                observed.append((subject.name, [item.path.name for item in store.items]))

            stack.enter_context(patch.object(generator, 'MODULES', [
                SimpleNamespace(id='overview', label='订单总览', build=observe),
            ]))
            manifest, _ = generator.build(root, root / 'dashboard.html')
            self.assertEqual(set(row[0] for row in manifest["source_signature"]["files"]),
                             {ordinary.name, STAGE_SOURCE_PATH.name, SUMMARY_NAME})
            self.assertEqual(observed, [('鸿蒙智行', [ordinary.name])])
            self.assertEqual([s['name'] for s in manifest['subjects']], ['鸿蒙智行'])
            raw_files = manifest['raw_files']
            self.assertCountEqual([file['name'] for file in raw_files],
                                  [ordinary.name, SUMMARY_NAME])
            summary = next(file for file in raw_files if file['name'] == SUMMARY_NAME)
            self.assertEqual(base64.b64decode(manifest['raw_blocks'][summary['workbook_key']]), original_bytes[SUMMARY_NAME])
            sheet, = summary['sheets']
            self.assertEqual(sheet['source_sheet'], auxiliaries[SUMMARY_NAME])
            sheet_key = f'{raw_files.index(summary)}|0'
            block = gzip.decompress(base64.b64decode(manifest['raw_blocks'][sheet_key]))
            self.assertEqual(json.loads(block)['rows'][1][0], '留存大定')
            self.assertEqual(list(root.glob('*.html')), [])
            self.assertTrue((root / 'runtime/index.html').is_file())
            self.assertFalse((root / 'forecast_assets').exists())
            self.assertNotIn('sales_forecast', manifest['config']['module_order'])
            self.assertTrue(all(not key.endswith('|sales_forecast') for key in manifest['dashboards']))
            for name, sheet in auxiliaries.items():
                self.assertEqual((root / name).read_bytes(), original_bytes[name])

    def test_unmapped_import_is_logged_and_kept_in_raw_for_both_outputs(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            book = root / '区域销售分析.xlsx'
            self.write_book(book, '问界 M6 2026款_区域分析')
            for static in (False, True):
                with self.subTest(static=static), self.assertLogs('core.validation', level='WARNING') as logs:
                    manifest, _ = generator.build(root, root / '订单.html', static=static, publish_only=not static)
                self.assertTrue(any(book.name in line and '未识别到专属看板映射' in line for line in logs.output))
                self.assertNotIn('generic', manifest['config']['module_order'])
                self.assertNotIn('generic', manifest['config']['module_labels'])
                self.assertFalse(any(key.endswith('|generic') for key in manifest['dashboards']))
                self.assertTrue(all('generic' not in subject['modules'] for subject in manifest['subjects']))
                self.assertEqual([file['name'] for file in manifest['raw_files']], [book.name])

    def test_unreadable_workbook_logs_filename_and_stops_publication(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            self.write_book(root / '订单分析.xlsx', '鸿蒙智行')
            invalid = root / '损坏订单.xlsx'
            invalid.write_bytes(b'invalid workbook')
            with self.assertLogs('core.excel', level='ERROR') as logs:
                with self.assertRaisesRegex(RuntimeError, 'Excel 读取不完整'):
                    generator.build(root, root / '订单.html', publish_only=True)
            self.assertTrue(any(invalid.name in line and 'Excel读取失败' in line for line in logs.output))
            self.assertFalse((root / 'runtime/current.json').exists())

    def test_dynamic_raw_blocks_stream_to_unpublished_snapshot(self):
        with TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            source = root / 'in'
            source.mkdir()
            path = source / '订单分析.xlsx'
            self.write_book(path, '鸿蒙智行')
            output = root / 'out' / '订单.html'
            config = dict(title='测试', chart_render_mode='generated',
                          build_manifest_mode='off', module_order=['raw'])
            stack.enter_context(patch.object(generator, 'load_config', return_value=config))
            stack.enter_context(patch.object(generator, 'MODULES', []))
            stack.enter_context(patch('core.discovery.generation_records', return_value=[]))
            stack.enter_context(patch.object(generator, 'b64gzip', side_effect=AssertionError('embedded raw data')))
            manifest, _ = generator.build(source, output, publish_only=True)
            self.assertEqual(manifest['raw_blocks'], {})
            self.assertFalse((output.parent / '.cache' / 'excel').exists())
            runtime = output.parent / 'runtime'
            pointer = (runtime / 'current.json').read_bytes()
            dataset = runtime / 'datasets' / json.loads(pointer)['dataset_id']
            catalog = json.loads((dataset / 'catalog.json').read_text(encoding='utf-8'))
            self.assertEqual(catalog['raw_files'], manifest['raw_files'])
            self.assertEqual(json.loads(gzip.decompress((dataset / 'raw/0_0.json.gz').read_bytes())),
                             {'rows': [['指标', '数量'], ['留存大定', '3']]})
            self.assertEqual((dataset / 'workbooks/0.xlsx').read_bytes(), path.read_bytes())
            original_open = Path.open
            def reject_download_write(target, *args, **kwargs):
                if target.parent.name == 'workbooks':
                    raise OSError('disk full')
                return original_open(target, *args, **kwargs)
            with patch.object(Path, 'open', reject_download_write):
                with self.assertRaisesRegex(OSError, 'disk full'):
                    generator.build(source, output, publish_only=True)
            self.assertEqual((runtime / 'current.json').read_bytes(), pointer)
            self.assertEqual(list((runtime / 'datasets').iterdir()), [dataset])

    def test_auxiliary_workbooks_alone_do_not_count_as_analysis_inputs(self):
        with TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            self.write_book(root / STAGE_SOURCE_PATH.name, '智界 R9 2027款')
            self.write_book(root / SUMMARY_NAME, '问界 M1 2027款')
            self.patch_build(stack)
            with self.assertRaisesRegex(RuntimeError, '没有成功读取任何Excel'):
                generator.build(root, root / 'dashboard.html')

    def test_entry_point_does_not_import_prediction_or_spawn_refresh_process(self):
        code = "import json,sys; import main; print(json.dumps(sorted(sys.modules)))"
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=generator.ROOT,
                                capture_output=True, text=True, check=True)
        loaded = json.loads(result.stdout)
        for name in ('modules.sales_forecast', 'core.forecast_summary', 'tools.refresh_sales_forecast_data'):
            self.assertNotIn(name, loaded)
        config = generator.load_config(generator.ROOT / 'config.json')
        self.assertNotIn('sales_forecast', [module.id for module in generator.MODULES])
        self.assertNotIn('sales_forecast', config['module_order'])
        for name in ('refresh_sales_forecast_data', 'forecast_target_names'):
            self.assertFalse(hasattr(generator, name))
        with patch.object(sys, 'argv', ['main.py']):
            self.assertFalse(hasattr(generator.parse_args(), 'disable_sales_forecast'))
