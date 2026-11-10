from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.server import SERVICE_FINGERPRINT, SnapshotStore, create_app, data_fingerprint


class OrderDashboardServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = self.root / "runtime"
        self.web = self.root / "web"
        self.state = self.root / "state"
        (self.web / "assets").mkdir(parents=True)
        (self.web / "index.html").write_text("<html>订单看板</html>", encoding="utf-8")
        (self.web / "assets/app.js").write_text("window.loaded=true;", encoding="utf-8")
        self.write_snapshot("first", "old", b"first-workbook")
        self.set_current("first")
        self.app = create_app(self.data, self.state, web_dir=self.web)
        self.client = TestClient(self.app, base_url="http://localhost")
        self.addCleanup(self.client.close)

    def write_snapshot(self, dataset, marker, workbook):
        base = self.data / "datasets" / dataset
        for directory in ("boards", "raw", "workbooks", "charts"):
            (base / directory).mkdir(parents=True, exist_ok=True)
        catalog = {
            "subjects": [
                {"id": "group", "name": "鸿蒙智行", "type": "group", "parent": None, "modules": ["overview"]},
                {"id": "brand", "name": "问界", "type": "brand", "parent": "group", "modules": ["overview"]},
            ],
            "config": {},
            "raw_files": [{"name": "测试表.xlsx", "sheets": [{"name": "订单", "total_rows": 5}]}],
            "marker": marker,
            "chart_assets": {f"图表/{suffix}?": f"api/chart?dataset={dataset}&key={suffix}" for suffix in ("png", "jpg", "svg")},
        }
        (base / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")
        board = {"format": "shared-v1", "root": {"marker": marker}, "pool": []}
        key = hashlib.sha256(b"group|overview").hexdigest()
        (base / "boards" / (key + ".json.gz")).write_bytes(gzip.compress(json.dumps(board).encode()))
        rows = [["车型", "数量"], ["M7", 0], ["M9", 12], ["M7 旗舰", 25], ["引号,\"换行\n", None]]
        (base / "raw" / "0_0.json.gz").write_bytes(gzip.compress(json.dumps({"rows": rows}).encode()))
        (base / "workbooks" / "0.xlsx").write_bytes(workbook)
        for suffix in ("png", "jpg", "svg"):
            chart_key = hashlib.sha256(f"图表/{suffix}?".encode("utf-8")).hexdigest()
            (base / "charts" / f"{chart_key}.{suffix}").write_bytes((marker + "-" + suffix).encode("utf-8"))

    def set_current(self, dataset):
        (self.data / "current.json").write_text(json.dumps({"dataset_id": dataset}), encoding="utf-8")

    def test_catalog_is_small_and_health_identifies_instance(self):
        response = self.client.get("/api/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["dataset_id"], "first")
        self.assertNotIn("raw_blocks", response.json())
        self.assertEqual(response.headers["cache-control"], "no-store")
        health = self.client.get("/health").json()
        self.assertEqual(health["application"], "order-dashboard")
        self.assertEqual(health["data_fingerprint"], data_fingerprint(self.data))
        self.assertEqual(health["service_fingerprint"], SERVICE_FINGERPRINT)
        self.assertNotIn(str(self.data), json.dumps(health))

    def test_running_service_fingerprint_does_not_reread_source(self):
        with patch.object(Path, "read_bytes", side_effect=AssertionError("health must not rehash source")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["service_fingerprint"], SERVICE_FINGERPRINT)

    def test_existing_dataset_requests_remain_consistent_after_publish(self):
        first = self.client.get("/api/catalog").json()["dataset_id"]
        self.write_snapshot("second", "new", b"second-workbook")
        self.set_current("second")
        self.assertEqual(self.client.get("/api/catalog").json()["marker"], "new")
        old_board = self.client.get("/api/dashboard", params={"dataset": first, "subject": "group", "module": "overview"})
        self.assertEqual(old_board.status_code, 200)
        self.assertEqual(old_board.json()["root"]["marker"], "old")
        self.assertEqual(old_board.headers["content-encoding"], "gzip")
        old_workbook = self.client.get("/api/workbook", params={"dataset": first, "file": 0})
        self.assertEqual(old_workbook.content, b"first-workbook")
        new_workbook = self.client.get("/api/workbook", params={"dataset": "second", "file": 0})
        self.assertEqual(new_workbook.content, b"second-workbook")

    def test_dashboard_honors_compression_negotiation(self):
        params = {"dataset": "first", "subject": "group", "module": "overview"}
        for encoding in ("identity", "gzip;q=0", "br, gzip;q=0"):
            response = self.client.get("/api/dashboard", params=params, headers={"Accept-Encoding": encoding})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("content-encoding", response.headers)
            self.assertEqual(response.json()["root"]["marker"], "old")
            self.assertEqual(response.headers["vary"], "Accept-Encoding")
        response = self.client.get("/api/dashboard", params=params, headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.headers["content-encoding"], "gzip")

    def test_chart_images_come_from_requested_snapshot_with_separate_web_dir(self):
        for suffix, media_type in (("png", "image/png"), ("jpg", "image/jpeg"), ("svg", "image/svg+xml")):
            params = {"dataset": "first", "key": f"图表/{suffix}?"}
            response = self.client.get("/api/chart", params=params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, ("old-" + suffix).encode())
            self.assertTrue(response.headers["content-type"].startswith(media_type))
            self.assertEqual(self.client.head("/api/chart", params=params).status_code, 200)
            self.assertEqual(self.client.head("/api/chart", params=params).content, b"")
        self.write_snapshot("second", "new", b"new-workbook")
        self.set_current("second")
        params = {"dataset": "second", "key": "图表/png?"}
        self.assertEqual(self.client.get("/api/chart", params=params).content, b"new-png")
        self.assertEqual(self.client.get("/api/chart", params={**params, "dataset": "first"}).content, b"old-png")
        self.assertFalse(any(self.web.glob("assets/*.png")))

    def test_chart_endpoint_requires_declared_key_and_image_suffix(self):
        dataset = self.data / "datasets" / "first"
        undeclared = hashlib.sha256(b"undeclared").hexdigest()
        (dataset / "charts" / (undeclared + ".png")).write_bytes(b"private-image")
        for key in ("undeclared", "../../current.json", "absent"):
            self.assertEqual(self.client.get("/api/chart", params={"dataset": "first", "key": key}).status_code, 404)
        declared = hashlib.sha256("图表/png?".encode()).hexdigest()
        (dataset / "charts" / (declared + ".png")).unlink()
        (dataset / "charts" / (declared + ".js")).write_bytes(b"window.notPublic=true")
        self.assertEqual(self.client.get("/api/chart", params={"dataset": "first", "key": "图表/png?"}).status_code, 404)
        self.assertEqual(self.client.get("/api/chart", params={"dataset": "../escape", "key": "图表/png?"}).status_code, 422)

    def test_raw_search_and_pagination_preserve_header_and_zero(self):
        first = self.client.get("/api/raw", params={"dataset": "first", "q": "m7", "limit": 1}).json()
        self.assertEqual(first["rows"], [["车型", "数量"], ["M7", 0]])
        self.assertEqual(first["total"], 2)
        next_page = self.client.get("/api/raw", params={"dataset": "first", "q": " m7 ", "offset": 1, "limit": 1}).json()
        self.assertEqual(next_page["rows"], [["车型", "数量"], ["M7 旗舰", 25]])
        empty = self.client.get("/api/raw", params={"dataset": "first", "q": "missing"}).json()
        self.assertEqual(empty["rows"], [["车型", "数量"]])
        self.assertEqual(empty["total"], 0)

    def test_csv_exports_every_match_and_quotes_cell_content(self):
        response = self.client.get("/api/export/csv", params={"dataset": "first", "q": "m7"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows, [["车型", "数量"], ["M7", "0"], ["M7 旗舰", "25"]])
        complete = self.client.get("/api/export/csv", params={"dataset": "first"})
        full_rows = list(csv.reader(io.StringIO(complete.content.decode("utf-8-sig"))))
        self.assertEqual(full_rows[-1], ['引号,"换行\n', ""])
        self.assertIn("filename*=UTF-8''", response.headers["content-disposition"])

    def test_only_declared_files_and_modules_are_accessible(self):
        for params in (
            {"dataset": "first", "subject": "unknown", "module": "overview"},
            {"dataset": "first", "subject": "group", "module": "forecast"},
            {"dataset": "missing", "subject": "group", "module": "overview"},
        ):
            self.assertEqual(self.client.get("/api/dashboard", params=params).status_code, 404)
        for path in ("/api/raw", "/api/export/csv", "/api/workbook"):
            self.assertEqual(self.client.get(path, params={"dataset": "first", "file": 20}).status_code, 404)
        self.assertEqual(self.client.get("/api/raw", params={"dataset": "first", "sheet": 20}).status_code, 404)
        for path in ("/datasets/first/catalog.json", "/current.json", "/state/annotations.sqlite3", "/server.py"):
            self.assertEqual(self.client.get(path).status_code, 404)

    def test_invalid_indices_and_path_parameters_are_rejected(self):
        for params in (
            {"dataset": "../state"},
            {"dataset": r"..\state"},
            {"dataset": "first", "file": -1},
            {"dataset": "first", "sheet": -1},
            {"dataset": "first", "limit": 501},
            {"dataset": "first", "limit": 0},
            {"dataset": "first", "offset": -1},
        ):
            self.assertEqual(self.client.get("/api/raw", params=params).status_code, 422)
        self.assertEqual(self.client.get("/assets/%2e%2e/current.json").status_code, 404)

    def test_frontend_aliases_assets_head_and_iframe_headers(self):
        for route in ("/", "/index.html", "/鸿蒙智行订单分析汇总.html"):
            self.assertIn("订单看板", self.client.get(route).text)
            response = self.client.head(route)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, b"")
            self.assertEqual(response.headers["x-frame-options"], "SAMEORIGIN")
        self.assertEqual(self.client.get("/assets/app.js").text, "window.loaded=true;")
        (self.web / "assets/private.sqlite3").write_bytes(b"database")
        self.assertEqual(self.client.get("/assets/private.sqlite3").status_code, 404)
        for route in ("/health", "/api/health", "/api/catalog", "/api/raw?dataset=first",
                      "/api/export/csv?dataset=first", "/api/workbook?dataset=first",
                      "/api/dashboard?dataset=first&subject=group&module=overview"):
            self.assertEqual(self.client.head(route).status_code, 200)
            self.assertEqual(self.client.head(route).content, b"")

    def test_missing_or_invalid_current_pointer_is_not_a_ready_service(self):
        self.set_current("../escape")
        self.assertEqual(self.client.get("/health").status_code, 503)
        (self.data / "current.json").unlink()
        self.assertEqual(self.client.get("/api/catalog").status_code, 503)

    def test_host_allowlist_rejects_unconfigured_hosts(self):
        self.assertEqual(self.client.get("/api/catalog", headers={"Host": "attacker.example"}).status_code, 400)
        configured = TestClient(
            create_app(self.data, self.state, web_dir=self.web, allowed_hosts=["portal.example"]),
            base_url="http://portal.example",
        )
        self.addCleanup(configured.close)
        self.assertEqual(configured.get("/api/catalog").status_code, 200)
        self.assertEqual(configured.get("/health", headers={"Host": "127.0.0.1"}).status_code, 200)

    def test_sheet_cache_is_bounded_and_keyed_by_dataset(self):
        store = SnapshotStore(self.data)
        first = store.rows("first", 0, 0)
        self.assertIs(store.rows("first", 0, 0), first)
        for index in range(6):
            self.write_snapshot("more" + str(index), str(index), b"workbook")
            store.rows("more" + str(index), 0, 0)
        self.assertLessEqual(store.rows.cache_info().currsize, 4)

    def test_catalog_json_error_has_safe_response(self):
        self.write_snapshot("invalid", "bad", b"workbook")
        (self.data / "datasets" / "invalid" / "catalog.json").write_text("{broken", encoding="utf-8")
        self.set_current("invalid")
        response = self.client.get("/api/catalog")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(str(self.data), response.text)


if __name__ == "__main__":
    unittest.main()
