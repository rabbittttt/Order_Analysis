"""Order builds exclude auxiliary inputs and never execute the separate prediction app."""
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
        stack.enter_context(patch.object(generator, 'render_dashboard',
                                        side_effect=lambda manifest, templates, output:
                                        output.write_text('generated', encoding='utf-8')))

    def test_forecast_workbooks_are_excluded_and_remain_unchanged(self):
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
            self.assertEqual(observed, [('鸿蒙智行', [ordinary.name])])
            self.assertEqual([s['name'] for s in manifest['subjects']], ['鸿蒙智行'])
            raw_files = manifest['raw_files']
            self.assertCountEqual([file['name'] for file in raw_files],
                                  [ordinary.name])
            self.assertEqual([p.name for p in root.glob('*.html')], ['dashboard.html'])
            self.assertFalse((root / 'forecast_assets').exists())
            self.assertNotIn('sales_forecast', manifest['config']['module_order'])
            self.assertTrue(all(not key.endswith('|sales_forecast') for key in manifest['dashboards']))
            for name, sheet in auxiliaries.items():
                self.assertEqual((root / name).read_bytes(), original_bytes[name])

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
