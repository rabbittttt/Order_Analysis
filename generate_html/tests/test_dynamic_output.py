import base64
import gzip
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from core.renderer import b64gzip, pack_dashboard, render_dynamic_dashboard

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"

class DynamicOutputTests(TestCase):
    def manifest(self):
        return {"meta": {"input_dir": "private", "generated_at": "2026-11-10"},
                "subjects": [{"id": "group", "name": "鸿蒙智行"}], "config": {},
                "dashboards": {"group|overview": {"views": {"day": {"pages": {"latest": {"value": 42}}}}}},
                "raw_files": [{"name": "测试.xlsx", "sheets": [{"name": "总览"}]}],
                "raw_blocks": {"0|0": b64gzip(json.dumps({"rows": [["比例"], ["37.5%"]]})),
                               "0|xlsx": base64.b64encode(b"original-workbook").decode()}, "chart_assets": {}}

    def test_shell_and_snapshots_preserve_payload_without_embedding(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            data = self.manifest()
            render_dynamic_dashboard(data, TEMPLATES, output)
            runtime = output.parent / "runtime"
            version = json.loads((runtime / "current.json").read_text())["dataset_id"]
            snapshot = runtime / "datasets" / version
            catalog = json.loads((snapshot / "catalog.json").read_text(encoding="utf-8"))
            self.assertNotIn("input_dir", catalog["meta"])
            self.assertNotIn("raw_blocks", catalog)
            self.assertNotIn("dashboards", catalog)
            self.assertEqual(catalog["dataset_id"], version)
            name = hashlib.sha256(b"group|overview").hexdigest() + ".json.gz"
            board = json.loads(gzip.decompress((snapshot / "boards" / name).read_bytes()))
            self.assertEqual(board, pack_dashboard(data["dashboards"]["group|overview"]))
            self.assertEqual(json.loads(gzip.decompress((snapshot / "raw/0_0.json.gz").read_bytes()))["rows"][1], ["37.5%"])
            self.assertEqual((snapshot / "workbooks/0.xlsx").read_bytes(), b"original-workbook")
            html = output.read_text(encoding="utf-8")
            self.assertNotIn("DASHBOARD_RAW_B64", html)
            self.assertNotIn("DASHBOARD_BLOCKS_B64", html)
            self.assertLess(len(html.encode()), 16000)
            self.assertEqual((runtime / "index.html").read_text(encoding="utf-8"), html)
            render_dynamic_dashboard(data, TEMPLATES, output)
            self.assertNotEqual(json.loads((runtime / "current.json").read_text())["dataset_id"], version)
            self.assertTrue(snapshot.exists(), "already-open pages keep their dataset")

    def test_failed_build_keeps_current_dataset(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            pointer = output.parent / "runtime/current.json"
            previous = pointer.read_bytes()
            with patch("core.renderer.pack_dashboard", side_effect=ValueError("bad board")):
                with self.assertRaises(ValueError):
                    render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            self.assertEqual(pointer.read_bytes(), previous)

    def test_release_excludes_data_and_rejects_stale_frontend(self):
        from package_release import package
        with TemporaryDirectory() as folder:
            base = Path(folder)
            render_dynamic_dashboard(self.manifest(), TEMPLATES, base / "dashboard.html")
            runtime = base / "runtime"
            (runtime / "assets" / "unrelated-private-image.png").write_bytes(b"business-data")
            package(base / "release", runtime)
            self.assertTrue((base / "release/server.py").is_file())
            self.assertTrue((base / "release/requirements.txt").is_file())
            self.assertFalse((base / "release/web/assets/unrelated-private-image.png").exists())
            self.assertFalse((base / "release/datasets").exists())
            self.assertEqual(len(list((base / "release/web/assets").iterdir())), 4)
            (runtime / "web-build.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "前端源码"):
                package(base / "stale-release", runtime)
            self.assertFalse((base / "stale-release").exists())
