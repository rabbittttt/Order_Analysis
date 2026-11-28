"""Offline CLI exports must not publish a dynamic dataset or start a service."""
from __future__ import annotations

import argparse
import json
import os
import shutil
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook

import main as generator


def write_order_books(source):
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

    def test_static_template_preserves_placeholder_text_inside_board_keys(self):
        import json
        key = "group|__BRAND_LOGO__"
        with TemporaryDirectory() as folder:
            output = Path(folder) / "offline.html"
            generator.render_static_dashboard({"dashboards": {key: {}}}, generator.ROOT / "templates", output)
            html = output.read_text(encoding="utf-8")
            assignment = html.split("window.DASHBOARD_BLOCKS_B64=", 1)[1].split(";</script>", 1)[0]
            self.assertEqual(list(json.loads(assignment)), [key])

    def test_real_static_build_embeds_data_without_changing_dynamic_runtime(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'input'
            source.mkdir()
            write_order_books(source)
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


class ReuseCliTests(TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(TemporaryDirectory()))
        self.source = self.root / "input"
        self.source.mkdir()
        write_order_books(self.source)
        self.app = self.root / "app"
        self.templates = self.app / "templates"
        shutil.copytree(generator.ROOT / "templates", self.templates)
        shutil.copy(generator.ROOT / "config.json", self.app)
        self.stack.enter_context(patch.object(generator, "ROOT", self.app))
        self.stack.enter_context(patch.object(generator, "configure_runtime", return_value=self.root / "run.log"))
        self.stack.enter_context(patch.object(generator, "BUILD_DIAGNOSTICS", []))
        self.stack.enter_context(patch.dict(generator.DIAGNOSTIC_COUNTS, {"WARNING": 0, "ERROR": 0}))
        self.revision = self.stack.enter_context(patch("core.sync.calculation_revision", return_value="data-v2:rules"))
        self.offline = self.root / "offline.html"
        self.runtime = self.root / "runtime"

    def run_cli(self, *flags):
        target = self.offline if "--static" in flags else self.root / "dashboard.html"
        args = ["main.py", "--no-open", "--input", str(self.source), "--output", str(target), *flags]
        with patch("sys.argv", args):
            return generator.main()

    def dataset(self):
        current = json.loads((self.runtime / "current.json").read_bytes())
        return self.runtime / "datasets" / current["dataset_id"]

    def verify_rewrite(self, flags):
        dataset = self.dataset()
        files = {p: p.read_bytes() for p in dataset.rglob("*") if p.is_file()}
        self.assertTrue(any(p.parent.name == "boards" for p in files))
        catalog, raw, boards = generator.read_static_payloads(self.offline)
        self.assertTrue(raw and boards)
        html = self.templates / "dashboard.html"
        html.write_text(html.read_text(encoding="utf-8").replace("</head>", "<!-- UI change --></head>"),
                        encoding="utf-8")
        with patch.object(generator, "build", side_effect=AssertionError("UI change reloaded workbooks")):
            self.assertEqual(self.run_cli(*flags), 0)
            self.assertEqual(self.run_cli("--static", *flags), 0)
        count = html.read_text(encoding="utf-8").count("<!-- UI change -->")
        for entry in (self.runtime / "index.html", self.offline):
            self.assertEqual(entry.read_text(encoding="utf-8").count("<!-- UI change -->"), count)
        self.assertEqual(self.dataset(), dataset)
        self.assertEqual({p: p.read_bytes() for p in dataset.rglob("*") if p.is_file()}, files)
        latest, updated_raw, updated_boards = generator.read_static_payloads(self.offline)
        self.assertEqual(latest["meta"]["generated_at"], catalog["meta"]["generated_at"])
        self.assertEqual((updated_raw, updated_boards), (raw, boards))

    def test_repeated_cli_with_unchanged_inputs_only_rewrites_web_content(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(self.run_cli("--static"), 0)
        self.verify_rewrite([])

    def test_dynamic_ui_only_does_not_start_an_auto_sync_service(self):
        self.assertEqual(self.run_cli(), 0)
        args = ["main.py", "--input", str(self.source), "--output", str(self.root / "dashboard.html"), "--ui-only"]
        with patch("sys.argv", args), patch.object(generator, "open_dynamic_dashboard") as opener:
            self.assertEqual(generator.main(), 0)
            opener.assert_not_called()

    def test_ui_only_reuses_legacy_exports_even_with_offline_source_directory(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(self.run_cli("--static"), 0)
        catalog_path = self.dataset() / "catalog.json"
        dynamic_catalog = json.loads(catalog_path.read_bytes())
        catalog, raw, boards = generator.read_static_payloads(self.offline)
        catalog.pop("static_source_key")
        generator.write_static_shell(catalog, raw, boards, self.templates, self.offline)
        self.source.rename(self.root / "unmounted")
        with patch("core.sync.source_signature", side_effect=AssertionError("UI-only inspected input directory")):
            for has_signature in (True, False):
                with self.subTest(has_signature=has_signature):
                    if has_signature:
                        dynamic_catalog["source_signature"]["calculation_revision"] = "0" * 64
                    else:
                        dynamic_catalog.pop("source_signature")
                    catalog_path.write_text(json.dumps(dynamic_catalog), encoding="utf-8")
                    self.verify_rewrite(["--ui-only"])

    def test_inputs_rules_and_explicit_check_still_rebuild(self):
        self.assertEqual(self.run_cli(), 0)
        self.assertEqual(self.run_cli("--static"), 0)
        for trigger in ("mtime", "rules", "check"):
            with self.subTest(trigger=trigger):
                previous = self.dataset()
                flags = []
                if trigger == "mtime":
                    book = next(self.source.glob("*.xlsx"))
                    stamp = book.stat().st_mtime_ns + 2_000_000_000
                    os.utime(book, ns=(stamp, stamp))
                elif trigger == "rules":
                    self.revision.return_value = "data-v2:new-rules"
                else:
                    flags = ["--check"]
                with patch.object(generator, "validate_manifest", return_value=[]) as validate:
                    self.assertEqual(self.run_cli(*flags), 0)
                    self.assertEqual(self.run_cli("--static", *flags), 0)
                    self.assertEqual(validate.call_count, 2)
                self.assertNotEqual(self.dataset(), previous)
