"""Shared inputs are selected as one directory; stale local copies stay unused."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.data_paths import orders_input_directory, shared_data_root


class SharedDataPathsTests(TestCase):
    def test_input_state_and_logs_agree_on_workbench_root(self):
        from core.data_paths import dynamic_log_directory, persistent_directory
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {
                "PLANHUB_DATA_ROOT": "  ../内网 工作台  ", "SHARED_DATA_ROOT": "",
                "PLANHUB_APP_LOG_DIR": "", "ORDER_DASHBOARD_INPUT": ""}):
            project = Path(tmp) / "订单分析"
            root = Path(tmp).resolve() / "内网 工作台"
            self.assertEqual(orders_input_directory(project), root / "shared" / "订单汇总")
            self.assertEqual(dynamic_log_directory(project), root / "logs" / "orderiq")
            self.assertEqual(persistent_directory(project), root / "database" / "orderiq")

    def test_standalone_project_keeps_existing_defaults(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"SHARED_DATA_ROOT": ""}):
            project = Path(folder) / "订单分析"
            self.assertEqual(shared_data_root(project), project.parent / "工作台数据" / "shared")
            self.assertEqual(orders_input_directory(project), project.parent / "工作台数据" / "shared" / "订单汇总")

    def test_standalone_and_portal_share_default_input(self):
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"SHARED_DATA_ROOT": ""}):
            project = Path(folder) / "订单分析"
            (project / "output_file").mkdir(parents=True)
            (project / "output_file" / "小订及首销数据整理.xlsx").write_bytes(b"old copy")
            shared = Path(folder) / "工作台数据" / "shared"
            shared.mkdir(parents=True)
            self.assertEqual(orders_input_directory(project), project.parent / "工作台数据" / "shared" / "订单汇总")
            self.assertFalse(orders_input_directory(project).exists())

    def test_explicit_nonexistent_root_remains_authoritative(self):
        with TemporaryDirectory() as folder:
            shared = (Path(folder) / "指定共享目录").resolve()
            with patch.dict(os.environ, {"SHARED_DATA_ROOT": str(shared)}):
                self.assertEqual(orders_input_directory(Path(folder) / "订单分析"), shared / "订单汇总")
                self.assertFalse(shared.exists())

    def test_order_entry_uses_shared_inputs_and_keeps_custom_cli_paths(self):
        # Import in a fresh process, as real launchers do, to check module constants.
        code = r'''
import json, sys
import main
from core.model_identity import STAGE_SOURCE_PATH
sys.argv = ['main.py']
default = main.parse_args()
sys.argv = ['main.py', '--input', 'custom-input', '--output', 'custom-report.html']
custom = main.parse_args()
print(json.dumps({
    'input': str(default.input), 'output': str(default.output),
    'source': str(STAGE_SOURCE_PATH),
    'custom': [str(custom.input), str(custom.output)],
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
            self.assertEqual(Path(paths["source"]), orders / "小订及首销数据整理.xlsx")
            self.assertEqual(Path(paths["output"]).parent.name, "orderiq")
            self.assertEqual(paths["custom"], ["custom-input", "custom-report.html"])
            self.assertFalse(shared.exists())
