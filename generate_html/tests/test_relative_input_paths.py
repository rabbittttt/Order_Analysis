"""Launch path resolution from distinct directories without reading business inputs."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase


PATH_MODULE = Path(__file__).resolve().parents[1] / "core" / "data_paths.py"
RESOLVE_PATHS = """
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location('input_paths', sys.argv[1])
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)
project = Path(sys.argv[2])
print(json.dumps({'orders': str(paths.orders_input_directory(project))}))
"""


class RelativeInputPathsTests(TestCase):
    def check_from_two_directories(self, setting, *, create_shared=False):
        with TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            project = root / "workspace" / "订单分析"
            unrelated = root / "other-working-directory"
            project.mkdir(parents=True)
            unrelated.mkdir()
            shared = project.parent / "共享数据"
            if create_shared:
                shared.mkdir()
            configured = str(shared) if setting == "absolute" else setting
            env = dict(os.environ, SHARED_DATA_ROOT=configured, PYTHONIOENCODING="utf-8")
            outputs = []
            for cwd in (project, unrelated):
                with self.subTest(cwd=cwd, setting=configured):
                    result = subprocess.run(
                        [sys.executable, "-B", "-c", RESOLVE_PATHS, str(PATH_MODULE), str(project)],
                        cwd=cwd, env=env, check=True, capture_output=True, text=True, encoding="utf-8",
                    )
                    actual = Path(json.loads(result.stdout)["orders"])
                    self.assertEqual(actual, shared / "订单汇总" if configured else project / "output_file")
                    outputs.append(actual)
            self.assertEqual(outputs[0], outputs[1])
            if not create_shared:
                self.assertFalse(shared.exists(), "Resolving an explicit root must not create it.")

    def test_relative_override_is_project_relative_from_any_cwd(self):
        self.check_from_two_directories("../共享数据")

    def test_absolute_override_keeps_its_meaning_from_any_cwd(self):
        self.check_from_two_directories("absolute")

    def test_default_sibling_directory_is_independent_of_cwd(self):
        self.check_from_two_directories("", create_shared=True)
