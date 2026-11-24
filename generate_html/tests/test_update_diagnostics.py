import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from core.server import create_app
from core.sync import BATCH_WORKBOOKS


class DiagnosticsTest(unittest.TestCase):
    def test_compares_visible_batch_and_published_file_timestamp(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "inputs"
            source.mkdir()
            book = source / BATCH_WORKBOOKS[0]
            book.touch()
            stamp = book.stat().st_mtime_ns
            runtime = root / "runtime"
            batch = runtime / "datasets" / "new"
            batch.mkdir(parents=True)
            baseline = {"directory": str(source), "files": [[book.name, 0, stamp, stamp]]}
            (batch / "catalog.json").write_text(json.dumps({"source_signature": baseline}))
            (runtime / "current.json").write_text('{"dataset_id":"new"}')
            # No lifespan context: the test samples read-only diagnostics, without starting a worker.
            client = TestClient(create_app(runtime, root / "state", input_dir=source), base_url="http://localhost")
            self.addCleanup(client.close)
            def sample():
                return client.get("/api/diagnostics", params={"page_dataset":"old"}).json()
            report = sample()
            self.assertFalse(report["page_is_current"])
            self.assertTrue(report["published_input_matches"])
            self.assertEqual(len(report["watched_files"]), len(BATCH_WORKBOOKS))
            self.assertFalse(report["watched_files"][0]["changed"])
            os.utime(book, ns=(stamp, stamp + 2_000_000_000))
            self.assertTrue(sample()["watched_files"][0]["changed"])
