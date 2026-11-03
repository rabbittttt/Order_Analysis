"""Shared inputs are selected as one directory; stale local copies stay unused."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.data_paths import (
    forecast_reference_directory, model_information_directory,
    orders_input_directory, shared_data_root,
)


class SharedDataPathsTests(TestCase):
    def test_standalone_project_keeps_existing_defaults(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"SHARED_DATA_ROOT": ""}):
            project = Path(folder) / "订单分析"
            self.assertIsNone(shared_data_root(project))
            self.assertEqual(orders_input_directory(project), project / "output_file")
            self.assertEqual(forecast_reference_directory(project), project / "input_file" / "销量预测输入文件")
            self.assertEqual(model_information_directory(project), forecast_reference_directory(project))

    def test_shared_root_never_falls_back_when_category_or_file_is_missing(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"SHARED_DATA_ROOT": ""}):
            project = Path(folder) / "订单分析"
            (project / "output_file").mkdir(parents=True)
            (project / "output_file" / "小订及首销数据整理.xlsx").write_bytes(b"old copy")
            shared = Path(folder) / "共享数据"
            shared.mkdir()
            self.assertEqual(orders_input_directory(project), shared / "订单汇总")
            self.assertEqual(forecast_reference_directory(project), shared / "订单汇总")
            self.assertEqual(model_information_directory(project), shared / "车型信息")
            self.assertFalse(orders_input_directory(project).exists())

    def test_explicit_nonexistent_root_remains_authoritative(self):
        with TemporaryDirectory() as folder:
            shared = (Path(folder) / "指定共享目录").resolve()
            with patch.dict(os.environ, {"SHARED_DATA_ROOT": str(shared)}):
                self.assertEqual(orders_input_directory(Path(folder) / "订单分析"), shared / "订单汇总")
                self.assertFalse(shared.exists())

    def test_all_entry_points_share_inputs_and_keep_custom_cli_paths(self):
        # Import in a fresh process, as real launchers do, to check module constants.
        code = r'''
import importlib.util, json, sys
from pathlib import Path
import main
from core.model_identity import FORECAST_SOURCE_PATH
from modules import sales_forecast as forecast
from tools import refresh_sales_forecast_data as refresh
sys.argv = ['main.py']
default = main.parse_args()
sys.argv = ['main.py', '--input', 'custom-input', '--output', 'custom-report.html']
custom = main.parse_args()
sys.argv = ['refresh.py', '--orders', 'custom-orders', '--source', 'source.xlsx', '--output', 'summary.xlsx', '--mapping', 'mapping.xlsx']
custom_refresh = refresh.parse_args()
spec = importlib.util.spec_from_file_location('sales_patterns', Path.cwd().parent / '销量规律' / 'analyze_sales_patterns.py')
patterns = importlib.util.module_from_spec(spec); spec.loader.exec_module(patterns)
print(json.dumps({
    'input': str(default.input), 'output': str(default.output),
    'source': str(FORECAST_SOURCE_PATH), 'orders': str(refresh.DEFAULT_ORDERS),
    'summary': str(refresh.DEFAULT_OUTPUT), 'model': str(forecast.MODEL_MASTER_PATH),
    'history': [str(p) for p in forecast.HISTORY_CANDIDATES],
    'mappings': [str(p) for p in forecast.MODEL_MAPPING_CANDIDATES],
    'patterns': str(patterns.default_input_path()),
    'custom': [str(custom.input), str(custom.output)],
    'custom_refresh': [str(custom_refresh.orders), str(custom_refresh.source), str(custom_refresh.output), str(custom_refresh.mapping)],
}))
'''
        with TemporaryDirectory() as folder:
            shared = (Path(folder) / "统一输入").resolve()
            env = dict(os.environ, SHARED_DATA_ROOT=str(shared), PYTHONIOENCODING="utf-8")
            result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                    env=env, capture_output=True, text=True, encoding="utf-8", check=True)
            paths = json.loads(result.stdout)
            orders = shared / "订单汇总"
            self.assertEqual(Path(paths["input"]), orders)
            self.assertEqual(Path(paths["orders"]), orders)
            self.assertEqual(Path(paths["source"]), orders / "小订及首销数据整理.xlsx")
            self.assertEqual(Path(paths["summary"]), orders / "鸿蒙智行销量数据汇总.xlsx")
            self.assertEqual(Path(paths["patterns"]), Path(paths["summary"]))
            self.assertEqual(Path(paths["model"]), shared / "车型信息" / "车型基本信息.xlsx")
            self.assertEqual(Path(paths["output"]).parent.name, "output_file")
            self.assertTrue(all(Path(p).is_relative_to(shared) for p in paths["history"] + paths["mappings"]))
            self.assertEqual(paths["custom"], ["custom-input", "custom-report.html"])
            self.assertEqual(paths["custom_refresh"], ["custom-orders", "source.xlsx", "summary.xlsx", "mapping.xlsx"])
            self.assertFalse(shared.exists())
