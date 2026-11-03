from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import main as generator
from core.models import Dashboard, Subject


class ForecastDisabledRunTests(unittest.TestCase):
    def test_flag_is_opt_in(self):
        with patch.object(sys, "argv", ["main.py"]):
            self.assertFalse(generator.parse_args().disable_sales_forecast)
        with patch.object(sys, "argv", ["main.py", "--disable-sales-forecast"]):
            self.assertTrue(generator.parse_args().disable_sales_forecast)

    def test_order_build_never_runs_forecast_even_with_legacy_config(self):
        for disabled in (True, False):
            with self.subTest(disabled=disabled), TemporaryDirectory() as directory, ExitStack() as stack:
                root = Path(directory)
                output = root / "dashboard.html"
                config = generator.load_config(generator.ROOT / "config.json")
                config["refresh_sales_forecast_data_before_build"] = True
                config["module_order"] = [*config["module_order"], "sales_forecast"]
                original = dict(config)
                subjects = [Subject("group", "鸿蒙智行", "group"), Subject("model", "问界M9", "generation")]
                store = Mock(items=[Mock()], load_errors=[], multi_source_groups={}, chart_assets={})
                store.resolve_dashboard_sources.side_effect = lambda board: board
                modules = []
                for module_id in config["module_order"]:
                    if module_id == "raw":
                        continue
                    module = Mock(id=module_id, label=module_id)
                    module.build.side_effect = lambda store, subject, mid=module_id: Dashboard(mid, subject.id, {})
                    modules.append(module)
                forecast = next(module for module in modules if module.id == "sales_forecast")
                stack.enter_context(patch.object(generator, "load_config", side_effect=lambda _: dict(config)))
                refresh = stack.enter_context(patch.object(generator, "refresh_sales_forecast_data"))
                stack.enter_context(patch.object(generator, "WorkbookStore", return_value=store))
                stack.enter_context(patch.object(generator, "discover_subjects", return_value=subjects))
                stack.enter_context(patch.object(generator, "forecast_target_names", return_value=[]))
                stack.enter_context(patch.object(generator, "MODULES", modules))
                stack.enter_context(patch.object(generator, "raw_tables", return_value=([], {})))
                stack.enter_context(patch.object(generator, "add_kpi_comparisons"))
                stack.enter_context(patch.object(generator, "validate_manifest", return_value=[]))
                render = stack.enter_context(patch.object(generator, "render_dashboard", side_effect=lambda *args: output.write_text("generated", encoding="utf-8")))
                manifest, _ = generator.build(root, output, disable_sales_forecast=disabled)
                self.assertEqual(config, original)
                self.assertEqual(render.call_count, 1)
                self.assertEqual(render.call_args.args[0]["app_mode"], "order")
                self.assertEqual(render.call_args.args[2], output)
                self.assertFalse((root / "forecast_assets").exists())
                self.assertNotIn("sales_forecast", manifest["config"]["module_order"])
                refresh.assert_not_called()
                self.assertEqual(forecast.build.call_count, 0)
                for subject in manifest["subjects"]:
                    self.assertNotIn("sales_forecast", subject["modules"])
                    self.assertIn("overview", subject["modules"])
                    self.assertIn("raw", subject["modules"])
                    self.assertIn(subject["id"] + "|overview", manifest["dashboards"])
                    self.assertNotIn(subject["id"] + "|sales_forecast", manifest["dashboards"])


if __name__ == "__main__":
    unittest.main()
