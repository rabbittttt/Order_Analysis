from __future__ import annotations

import argparse
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import main as generator


class CacheCleanupTests(unittest.TestCase):
    def make_files(self, root: Path) -> Path:
        cache = root / ".cache" / "excel"
        cache.mkdir(parents=True)
        (cache / "parsed.jsonl.gz").write_bytes(b"derived cache")
        (root / "source.xlsx").write_bytes(b"original data")
        (root / "dashboard.html").write_text("generated output", encoding="utf-8")
        (root / "log").mkdir()
        (root / "log" / "run.log").write_text("log", encoding="utf-8")
        return root / ".cache"

    def test_removes_entire_cache_but_preserves_input_and_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = self.make_files(root)
            generator.cleanup_input_cache(root)
            self.assertFalse(cache.exists())
            self.assertEqual((root / "source.xlsx").read_bytes(), b"original data")
            self.assertEqual((root / "dashboard.html").read_text(encoding="utf-8"), "generated output")
            self.assertTrue((root / "log" / "run.log").exists())

    def test_missing_cache_is_a_noop(self):
        with TemporaryDirectory() as directory, patch.object(generator.shutil, "rmtree") as remove:
            generator.cleanup_input_cache(Path(directory))
            remove.assert_not_called()

    def test_non_directory_cache_is_not_removed(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".cache").write_bytes(b"not a cache directory")
            with self.assertLogs(generator.LOGGER, level="WARNING"):
                generator.cleanup_input_cache(root)
            self.assertTrue((root / ".cache").is_file())

    def test_link_outside_input_directory_is_not_followed(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as other:
            root = Path(directory).resolve()
            cache = self.make_files(root)
            outside = Path(other).resolve()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            original_resolve = Path.resolve

            def resolve(path, *args, **kwargs):
                return outside if path == cache else original_resolve(path, *args, **kwargs)

            with patch.object(Path, "resolve", resolve), patch.object(generator.shutil, "rmtree") as remove:
                with self.assertLogs(generator.LOGGER, level="WARNING"):
                    generator.cleanup_input_cache(root)
                remove.assert_not_called()
            self.assertTrue(cache.exists())
            self.assertTrue((outside / "keep.txt").exists())

    def test_permission_error_is_reported_without_raising(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = self.make_files(root)
            with patch.object(generator.shutil, "rmtree", side_effect=PermissionError("in use")):
                with self.assertLogs(generator.LOGGER, level="WARNING") as logs:
                    generator.cleanup_input_cache(root)
            self.assertTrue(cache.exists())
            self.assertIn("运行缓存未能清理", "\n".join(logs.output))

    def test_main_cleans_cache_on_success_failure_validation_and_interrupt(self):
        manifest = {"subjects": [], "dashboards": {}}
        cases = [(None, [], 0), (None, ["validation warning"], 1),
                 (RuntimeError("build failed"), [], 1), (KeyboardInterrupt(), [], None)]
        for error, warnings, expected in cases:
            with self.subTest(error=type(error).__name__, warnings=warnings), TemporaryDirectory() as directory:
                root = Path(directory)
                cache = self.make_files(root)
                args = argparse.Namespace(input=root, output=root / "dashboard.html", debug=False, check=True, no_open=True, disable_sales_forecast=False)
                with ExitStack() as stack:
                    stack.enter_context(patch.object(generator, "parse_args", return_value=args))
                    stack.enter_context(patch.object(generator, "configure_runtime", return_value=root / "log" / "run.log"))
                    stack.enter_context(patch.object(generator, "build", return_value=(manifest, warnings), side_effect=error))
                    stack.enter_context(patch.object(generator, "LOGGER"))
                    if isinstance(error, KeyboardInterrupt):
                        with self.assertRaises(KeyboardInterrupt):
                            generator.main()
                    else:
                        self.assertEqual(generator.main(), expected)
                self.assertFalse(cache.exists())
                self.assertTrue((root / "source.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
