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
            self.assertFalse(output.exists())
            html = (runtime / "index.html").read_text(encoding="utf-8")
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

    def test_legacy_duplicate_is_removed_only_after_successful_publish(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            entry = output.parent / "runtime/index.html"
            output.write_bytes(entry.read_bytes())
            with patch("core.renderer.pack_dashboard", side_effect=ValueError("bad board")):
                with self.assertRaises(ValueError):
                    render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            self.assertEqual(output.read_bytes(), entry.read_bytes())
            render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            self.assertFalse(output.exists())
            self.assertTrue(entry.is_file())

    def test_unrelated_html_is_preserved(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            output.write_text("previous report", encoding="utf-8")
            render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous report")

    def test_publish_succeeds_when_windows_denies_populated_directory_rename(self):
        from core.server import SnapshotStore

        original_rename = Path.rename

        def reject_populated_directory(source, target):
            if source.is_dir() and any(source.iterdir()):
                error = PermissionError(13, "Access is denied", str(source))
                error.winerror = 5
                raise error
            return original_rename(source, target)

        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            with patch.object(Path, "rename", autospec=True, side_effect=reject_populated_directory):
                render_dynamic_dashboard(self.manifest(), TEMPLATES, output)

            runtime = output.parent / "runtime"
            store = SnapshotStore(runtime)
            version = store.current_id()
            self.assertEqual(store.catalog()["dataset_id"], version)
            self.assertEqual(store.rows(version, 0, 0), [["比例"], ["37.5%"]])
            snapshot = runtime / "datasets" / version
            self.assertEqual((snapshot / "workbooks/0.xlsx").read_bytes(), b"original-workbook")
            board_name = hashlib.sha256(b"group|overview").hexdigest() + ".json.gz"
            self.assertTrue((snapshot / "boards" / board_name).is_file())

    def test_partial_data_write_keeps_previous_snapshot_readable_and_unpublished(self):
        from fastapi import HTTPException
        from core.server import SnapshotStore

        original_write_bytes = Path.write_bytes

        def reject_workbook_write(destination, data):
            if destination.parent.name == "workbooks":
                raise PermissionError(13, "Workbook write denied", str(destination))
            return original_write_bytes(destination, data)

        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            runtime = output.parent / "runtime"
            pointer = runtime / "current.json"
            previous_pointer = pointer.read_bytes()
            datasets = runtime / "datasets"
            previous_directories = set(datasets.iterdir())

            with patch.object(Path, "write_bytes", autospec=True, side_effect=reject_workbook_write):
                with self.assertRaises(PermissionError):
                    render_dynamic_dashboard(self.manifest(), TEMPLATES, output)

            self.assertEqual(pointer.read_bytes(), previous_pointer)
            incomplete_directories = set(datasets.iterdir()) - previous_directories
            self.assertEqual(len(incomplete_directories), 1)
            incomplete = incomplete_directories.pop()
            self.assertFalse((incomplete / "catalog.json").exists())
            store = SnapshotStore(runtime)
            self.assertEqual(store.rows(store.current_id(), 0, 0), [["比例"], ["37.5%"]])
            with self.assertRaises(HTTPException) as rejected:
                store.catalog(incomplete.name)
            self.assertEqual(rejected.exception.status_code, 404)

    def test_pointer_replace_failure_keeps_previous_snapshot_readable(self):
        from core.server import SnapshotStore

        original_replace = Path.replace
        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            runtime = output.parent / "runtime"
            pointer = runtime / "current.json"
            previous_pointer = pointer.read_bytes()
            previous_version = json.loads(previous_pointer)["dataset_id"]
            new_data = self.manifest()
            new_data["raw_blocks"]["0|xlsx"] = base64.b64encode(b"new-workbook").decode()

            def reject_pointer_replace(source, destination):
                if Path(destination) == pointer:
                    error = PermissionError(13, "Pointer replacement denied", str(destination))
                    error.winerror = 5
                    raise error
                return original_replace(source, destination)

            with patch.object(Path, "replace", autospec=True, side_effect=reject_pointer_replace):
                with self.assertRaises(PermissionError):
                    render_dynamic_dashboard(new_data, TEMPLATES, output)

            self.assertEqual(pointer.read_bytes(), previous_pointer)
            store = SnapshotStore(runtime)
            self.assertEqual(store.current_id(), previous_version)
            self.assertEqual(store.catalog()["dataset_id"], previous_version)
            self.assertEqual(store.rows(previous_version, 0, 0), [["比例"], ["37.5%"]])
            old_workbook = runtime / "datasets" / previous_version / "workbooks/0.xlsx"
            self.assertEqual(old_workbook.read_bytes(), b"original-workbook")

    def test_catalog_replace_failure_leaves_new_snapshot_unreadable(self):
        from fastapi import HTTPException
        from core.server import SnapshotStore

        original_replace = Path.replace

        def reject_catalog_replace(source, destination):
            if Path(destination).name == "catalog.json":
                raise PermissionError(13, "Catalog replacement denied", str(destination))
            return original_replace(source, destination)

        with TemporaryDirectory() as folder:
            output = Path(folder) / "dashboard.html"
            render_dynamic_dashboard(self.manifest(), TEMPLATES, output)
            runtime = output.parent / "runtime"
            pointer = runtime / "current.json"
            previous_pointer = pointer.read_bytes()
            datasets = runtime / "datasets"
            previous_directories = set(datasets.iterdir())

            with patch.object(Path, "replace", autospec=True, side_effect=reject_catalog_replace):
                with self.assertRaises(PermissionError):
                    render_dynamic_dashboard(self.manifest(), TEMPLATES, output)

            self.assertEqual(pointer.read_bytes(), previous_pointer)
            incomplete_directories = set(datasets.iterdir()) - previous_directories
            self.assertEqual(len(incomplete_directories), 1)
            incomplete = incomplete_directories.pop()
            self.assertFalse((incomplete / "catalog.json").exists())
            store = SnapshotStore(runtime)
            self.assertEqual(store.rows(store.current_id(), 0, 0), [["比例"], ["37.5%"]])
            with self.assertRaises(HTTPException) as rejected:
                store.catalog(incomplete.name)
            self.assertEqual(rejected.exception.status_code, 404)
