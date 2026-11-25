from __future__ import annotations
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from core.sync import BATCH_WORKBOOKS, calculation_revision, AutoSync, BuildLock, RefreshSchedule, copy_stable_inputs, source_signature, published_signature, run_worker
from core.server import create_app


class AutoSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'input'
        self.source.mkdir()
        self.books = [self.source / name for name in BATCH_WORKBOOKS]
        for book in self.books:
            book.write_bytes(b'first')
        self.book = self.books[0]
        self.runtime = self.root / 'runtime'

    def test_each_watched_mtime_alone_triggers_after_stability(self):
        old = source_signature(self.source)
        for row in old["files"]:
            with self.subTest(name=row[0]):
                rows = [list(item) for item in old["files"]]
                next(item for item in rows if item[0] == row[0])[2] += 1
                new = {**old, "files": rows}
                schedule = RefreshSchedule()
                self.assertEqual(schedule.observe(new, old, 0), (False, 60))
                self.assertEqual(schedule.observe(new, old, 59), (False, 1))
                self.assertEqual(schedule.observe(new, old, 60), (True, 0))
                self.assertEqual(schedule.observe(new, new, 61), (False, 300))

    def test_stage_workbook_edit_waits_for_next_order_batch(self):
        stage = self.source / '小订及首销数据整理.xlsx'
        stage.write_bytes(b'previous')
        published = source_signature(self.source)
        stage.write_bytes(b'updated stage dates')
        stamp = stage.stat().st_mtime_ns + 2_000_000_000
        os.utime(stage, ns=(stamp, stamp))
        schedule = RefreshSchedule()
        self.assertEqual(schedule.observe(source_signature(self.source), published, 0), (False, 300))

        rhythm = self.source / '鸿蒙智行首销期订单节奏.xlsx'
        stamp = rhythm.stat().st_mtime_ns + 2_000_000_000
        os.utime(rhythm, ns=(stamp, stamp))
        current = source_signature(self.source)
        self.assertEqual(schedule.observe(current, published, 300), (False, 60))
        self.assertEqual(schedule.observe(current, published, 360), (True, 0))
        snapshot = self.root / 'snapshot'
        snapshot.mkdir()
        copy_stable_inputs(self.source, snapshot, current)
        self.assertEqual((snapshot / stage.name).read_bytes(), b'updated stage dates')

    def test_stale_marker_and_absent_peer_do_not_block_resaved_file(self):
        self.books[-1].unlink()
        marker = self.source / "orders.ready"
        marker.touch()
        os.utime(marker, (1, 1))
        old = source_signature(self.source)
        old["ready"] = [0, 1, 1]  # Previously published catalog.
        schedule = RefreshSchedule()
        (self.source / "临时备份.xlsx").write_bytes(b"other")
        self.assertEqual(schedule.observe(source_signature(self.source), old, 0), (False, 300))
        stamp = self.book.stat().st_mtime_ns
        os.utime(self.book, ns=(stamp, stamp + 2_000_000_000))
        new = source_signature(self.source)
        self.assertEqual(schedule.observe(new, old, 300), (False, 60))
        os.utime(self.book, ns=(stamp, stamp + 4_000_000_000))
        new = source_signature(self.source)
        self.assertEqual(schedule.observe(new, old, 360), (False, 60))
        self.assertEqual(schedule.observe(new, old, 420), (True, 0))

    def test_checks_only_metadata_and_detects_add_edit_delete(self):
        read_bytes = Path.read_bytes
        def read_program_only(path):
            self.assertFalse(path.is_relative_to(self.source), 'must not read Excel')
            return read_bytes(path)
        with patch.object(Path, 'read_bytes', autospec=True, side_effect=read_program_only):
            before = source_signature(self.source)
            (self.source / '~$orders.xlsx').write_text('lock')
            self.assertEqual(source_signature(self.source), before)
            (self.source / '鸿蒙智行销量数据汇总.xlsx').write_bytes(b'raw-only')
            current = source_signature(self.source)
            self.assertNotEqual(current, before)
            self.assertEqual(RefreshSchedule().observe(current, before, 0), (False, 300))
            before = current
            (self.source / 'extra.xlsx').write_text('new')
            self.assertNotEqual(source_signature(self.source), before)
            (self.source / 'extra.xlsx').unlink()
            self.assertEqual(source_signature(self.source), before)
            self.book.write_text('changed content')
            self.assertNotEqual(source_signature(self.source), before)

    def test_copy_uses_original_bytes_and_rejects_concurrent_edit(self):
        expected = source_signature(self.source)
        destination = self.root / 'snapshot'
        destination.mkdir()
        copy_stable_inputs(self.source, destination, expected)
        self.assertEqual((destination / self.book.name).read_bytes(), b'first')
        original_copy = shutil.copy2
        def changing_copy(src, dst):
            original_copy(src, dst)
            if src == self.book:
                self.book.write_bytes(b'changed while copying')
        with patch('core.sync.shutil.copy2', side_effect=changing_copy):
            with self.assertRaisesRegex(RuntimeError, '复制期间'):
                copy_stable_inputs(self.source, destination, expected)

    def test_lock_excludes_other_builds_and_recovers_on_release(self):
        with BuildLock(self.runtime):
            with self.assertRaisesRegex(RuntimeError, '正在运行'):
                with BuildLock(self.runtime):
                    self.fail('second builder acquired lock')
        with BuildLock(self.runtime):
            pass

    def test_rejected_manual_build_does_not_remove_active_worker_cache(self):
        import main
        from types import SimpleNamespace
        args = SimpleNamespace(input=self.source, output=self.root / 'dashboard.html', debug=False)
        with patch('main.parse_args', return_value=args), patch('main.configure_runtime'), \
             patch('core.sync.BuildLock', side_effect=RuntimeError('busy')), \
             patch('main.cleanup_input_cache') as cleanup, patch('main.LOGGER'):
            self.assertEqual(main.main(), 1)
            cleanup.assert_not_called()

    def test_failed_worker_keeps_previous_pointer(self):
        self.runtime.mkdir()
        pointer = self.runtime / 'current.json'
        pointer.write_text('{"dataset_id":"old"}')
        expected = source_signature(self.source)
        with patch.dict(os.environ), patch('main.configure_runtime'), patch('main.build', side_effect=RuntimeError('bad data')):
            with self.assertRaisesRegex(RuntimeError, 'bad data'):
                run_worker(self.source, self.runtime, expected)
        self.assertEqual(pointer.read_text(), '{"dataset_id":"old"}')
        self.assertFalse(list(self.root.glob('.order-input-*')))

    def test_service_without_dataset_starts_and_reports_pending(self):
        app = create_app(self.runtime, self.root / 'state', input_dir=self.source,
                         check_seconds=300, stable_seconds=60)
        with TestClient(app, base_url='http://localhost') as client:
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/health').status_code, 200)
            status = client.get('/api/sync').json()
            self.assertIsNone(status['dataset_id'])
            self.assertEqual(status['check_seconds'], 300)
            self.assertEqual(status['stable_seconds'], 60)
            self.assertNotIn(str(self.source), json.dumps(status))
            self.assertEqual(client.get('/api/catalog').status_code, 503)

    def test_signature_is_internal_and_restart_skips_unchanged_input(self):
        expected = source_signature(self.source)
        batch = self.runtime / 'datasets' / 'old'
        batch.mkdir(parents=True)
        (batch / 'catalog.json').write_text(json.dumps({'source_signature':expected, 'subjects':[]}), encoding='utf-8')
        (self.runtime / 'current.json').write_text('{"dataset_id":"old"}')
        self.assertEqual(published_signature(self.runtime), expected)
        app = create_app(self.runtime, self.root / 'state', input_dir=self.source)
        with patch.object(AutoSync, '_build', side_effect=AssertionError('unchanged must not build')) as build:
            with TestClient(app, base_url='http://localhost') as client:
                deadline = time.monotonic() + 3
                while app.state.sync.checked_at is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(client.get('/api/sync').json()['phase'], 'idle')
                self.assertNotIn('source_signature', client.get('/api/catalog').json())
                build.assert_not_called()

    def test_shutdown_interrupts_long_wait(self):
        sync = AutoSync(self.source, self.runtime)
        start = time.monotonic()
        sync.start()
        sync.stop()
        self.assertLess(time.monotonic() - start, 2)

    def test_scheduler_coalesces_changes_after_long_build(self):
        sync = AutoSync(self.source, self.runtime, check_seconds=.05, stable_seconds=.02)
        published = [None]
        calls = []
        def build(signature):
            calls.append(signature)
            if len(calls) == 1:
                for book in self.books:
                    book.write_bytes(b'second')
                self.book.write_bytes(b'latest')
                time.sleep(.1)  # longer than both configured intervals
            published[0] = signature
            if len(calls) == 2:
                sync.stop_event.set()
            return True
        with patch.object(sync, '_build', side_effect=build), patch('core.sync.published_signature', side_effect=lambda _:published[0]):
            sync.start()
            sync.thread.join(timeout=3)
            sync.stop()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[-1], source_signature(self.source))


class CalculationRevisionTests(unittest.TestCase):
    def test_recipe_tracks_code_rules_and_templates_not_path_or_runtime_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';root.mkdir()
            for name in ('main.py','server.py','config.json','requirements.txt','core/a.py','modules/a.py','templates/dashboard.js'):
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('v1')
            original=calculation_revision(root)
            (root/'output_file').mkdir();(root/'output_file'/'data.json').write_text('business fixture')
            self.assertEqual(calculation_revision(root),original)
            moved=Path(folder)/'moved';shutil.copytree(root,moved)
            self.assertEqual(calculation_revision(moved),original)
            for name in ('config.json','core/a.py','modules/a.py','templates/dashboard.js'):
                target=moved/name;target.write_text('v2')
                self.assertNotEqual(calculation_revision(moved),original)
                target.write_text('v1')

    def test_code_only_upgrade_refreshes_existing_batch(self):
        old = {"directory": "inputs", "files": [], "calculation_revision": "old"}
        new = {**old, "calculation_revision": "new"}
        schedule = RefreshSchedule()
        self.assertEqual(schedule.observe(new, old, 0), (False, 60))
        self.assertEqual(schedule.observe(new, old, 60), (True, 0))
