from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from check_merge_config import check


class IntranetConfigTests(unittest.TestCase):
    def test_recognised_aggregate_and_drift(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "shared_config.py"
            path.write_text("MERGE_GROUPS = {'测试界 A&B 2026款': ['测试界 A 2026款','测试界 B 2026款']}", encoding="utf8")
            self.assertEqual(check(path), 1)
            path.write_text("MERGE_GROUPS = {'测试界 A&B 2026款': ['测试界 C 2026款']}", encoding="utf8")
            with self.assertRaisesRegex(ValueError, "不一致"):
                check(path)
