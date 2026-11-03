"""One calculation build, two entry pages, and immutable lazy source snapshots."""
from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import json
import re
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import main as generator
from core.models import Dashboard, Subject
from core.renderer import (
    FORECAST_PAGE_NAME, b64gzip, render_dashboard, split_dashboard_pages,
    write_raw_block_assets,
)


def embedded(output):
    text = output.read_text(encoding="utf-8")
    bootstrap = re.search(r'window.DASHBOARD_DATA_B64="([^"]+)"', text)[1]
    manifest = json.loads(gzip.decompress(base64.b64decode(bootstrap)))
    boards = json.loads(re.search(r'window.DASHBOARD_BLOCKS_B64=(.*?);</script>', text)[1])
    raw = json.loads(re.search(r'window.DASHBOARD_RAW_B64=(.*?);</script>', text)[1])
    return manifest, boards, raw


class StandaloneForecastTests(TestCase):
    def fixture(self):
        actual = {"model": "智界 R7", "days": [{"gross": 0}, {"gross": None}]}
        prediction = {"subject_id": "group", "module_id": "sales_forecast",
                      "views": {}, "actuals": [actual], "shared_actual": actual,
                      "targets": [{"name": "智界 R7"}, {"name": "问界 M9"}],
                      "history": [{"model": "历史参考", "conversion": .2}]}
        raw = {"0|0": b64gzip(json.dumps({"rows": [["数量"], [0], [None]]})),
               "0|xlsx": base64.b64encode(b"original XLSX bytes\x00\xff").decode()}
        return {
            "meta": {"title": "订单分析", "generated_at": "2026-11-03T05:20:00"},
            "config": {"module_order": ["overview", "sales_forecast", "raw"],
                       "module_labels": {"overview": "订单总览", "sales_forecast": "销量预测", "raw": "底表中心"}},
            "subjects": [{"id": "group", "type": "group", "modules": ["overview", "sales_forecast", "raw"]},
                         {"id": "r7", "type": "generation", "modules": ["overview", "raw"]}],
            "dashboards": {"group|sales_forecast": prediction, "r7|overview": {"views": {}}},
            "raw_files": [{"name": "原始数据.xlsx", "workbook_key": "0|xlsx",
                           "sheets": [{"name": "展示块", "source_sheet": "原Sheet"}]}],
            "raw_blocks": raw,
            "chart_assets": {"order-only-chart": "asset"},
        }

    def test_split_preserves_business_identity_and_navigation_without_mutation(self):
        original = self.fixture()
        before = copy.deepcopy(original)
        order, forecast, output = split_dashboard_pages(original, Path("分析.html"))
        self.assertEqual(original, before)
        self.assertEqual(output.name, FORECAST_PAGE_NAME)
        self.assertEqual(order["app_mode"], "order")
        self.assertEqual(order["forecast_page"], FORECAST_PAGE_NAME)
        self.assertEqual(list(order["dashboards"]), ["r7|overview"])
        self.assertIs(order["subjects"], original["subjects"])
        self.assertIs(order["raw_blocks"], original["raw_blocks"])
        self.assertIs(forecast["dashboards"]["group|sales_forecast"], original["dashboards"]["group|sales_forecast"])
        self.assertEqual(forecast["subjects"][0]["modules"], ["sales_forecast", "raw"])
        self.assertEqual(forecast["subjects"][1]["modules"], ["raw"])
        self.assertEqual(forecast["config"]["module_order"], ["sales_forecast", "raw"])
        self.assertEqual(forecast["order_page"], "分析.html")
        self.assertEqual(forecast["forecast_legacy_page"], "分析.html")
        self.assertEqual(forecast["meta"]["generated_at"], order["meta"]["generated_at"])
        self.assertEqual(forecast["chart_assets"], {})
        self.assertEqual(forecast["raw_blocks"], {})
        self.assertEqual(forecast["raw_files"], original["raw_files"])

    def test_emitted_payloads_are_isolated_and_raw_urls_restore_exact_blocks(self):
        original = self.fixture()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            order, forecast, output = split_dashboard_pages(original, root / "分析.html")
            forecast["raw_block_urls"] = write_raw_block_assets(original["raw_blocks"], output)
            render_dashboard(forecast, generator.ROOT / "templates", output)
            render_dashboard(order, generator.ROOT / "templates", root / "分析.html")
            meta, boards, raw = embedded(output)
            order_meta, order_boards, order_raw = embedded(root / "分析.html")
            self.assertEqual(set(boards), {"group|sales_forecast"})
            self.assertEqual(set(order_boards), {"r7|overview"})
            self.assertEqual(raw, {})
            self.assertEqual(order_raw, original["raw_blocks"])
            self.assertEqual(meta["raw_files"], original["raw_files"])
            self.assertEqual(order_meta["forecast_page"], output.name)
            for key, url in meta["raw_block_urls"].items():
                content = (root / url).read_bytes()
                digest = hashlib.sha256(content).hexdigest()
                self.assertEqual(Path(url).name, f"raw-{digest}.js")
                assignment = re.search(r'window.DASHBOARD_RAW_B64\[(".*?")\]=(".*?");', content.decode())
                self.assertEqual(json.loads(assignment[1]), key)
                self.assertEqual(json.loads(assignment[2]), original["raw_blocks"][key])

    def test_resources_are_immutable_and_new_build_does_not_invalidate_old_page(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / FORECAST_PAGE_NAME
            first = write_raw_block_assets({"0|0": "old value", "0|xlsx": "snapshot"}, output)
            old_paths = {key: (output.parent / url) for key, url in first.items()}
            old_bytes = {key: path.read_bytes() for key, path in old_paths.items()}
            with patch.object(Path, "write_text", side_effect=AssertionError("existing hash was rewritten")):
                self.assertEqual(write_raw_block_assets({"0|0": "old value", "0|xlsx": "snapshot"}, output), first)
            second = write_raw_block_assets({"0|0": "new value", "0|xlsx": "snapshot"}, output)
            self.assertNotEqual(first["0|0"], second["0|0"])
            self.assertEqual(first["0|xlsx"], second["0|xlsx"])
            self.assertEqual({key: path.read_bytes() for key, path in old_paths.items()}, old_bytes)

    def test_corrupt_hash_resource_is_reported_and_never_silently_overwritten(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / FORECAST_PAGE_NAME
            urls = write_raw_block_assets({"0|0": "data"}, output)
            path = output.parent / urls["0|0"]
            path.write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "资源校验失败"):
                write_raw_block_assets({"0|0": "data"}, output)
            self.assertEqual(path.read_bytes(), b"damaged")

    def test_disabled_or_unavailable_prediction_does_not_link_stale_page(self):
        for disabled, absent in [(True, False), (False, True)]:
            with self.subTest(disabled=disabled, absent=absent):
                original = self.fixture()
                if absent:
                    del original["dashboards"]["group|sales_forecast"]
                order, forecast, _ = split_dashboard_pages(original, Path("分析.html"), forecast_disabled=disabled)
                self.assertNotIn("forecast_page", order)
                self.assertEqual(forecast["forecast_disabled"], disabled)
                self.assertEqual(forecast["dashboards"], {})
                self.assertEqual(forecast["raw_files"], [])
                self.assertEqual(forecast["raw_block_urls"], {})

    def test_reserved_filename_cannot_overwrite_other_page(self):
        with self.assertRaisesRegex(ValueError, "保留名称"):
            split_dashboard_pages(self.fixture(), Path(FORECAST_PAGE_NAME))
