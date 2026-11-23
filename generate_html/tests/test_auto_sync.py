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

    def test_default_timing_and_change_debounce(self):
        schedule = RefreshSchedule()
        old = source_signature(self.source)
        self.assertEqual(schedule.observe(old, old, 0), (False, 300))
        for book in self.books[:-1]:
            book.write_bytes(b'updated')
            self.assertEqual(schedule.observe(source_signature(self.source), old, 300), (False, 300))
        restarted = RefreshSchedule()
        self.assertEqual(restarted.observe(source_signature(self.source), old, 600), (False, 300))
        self.assertEqual(restarted.waiting_for, [self.books[-1].name])
        self.books[-1].write_bytes(b'updated')
        complete = source_signature(self.source)
        self.assertEqual(restarted.observe(complete, old, 900), (False, 60))
        self.assertEqual(restarted.observe(complete, old, 959), (False, 1))
        self.book.write_bytes(b'changed again')
        complete = source_signature(self.source)
        self.assertEqual(restarted.observe(complete, old, 960), (False, 60))
        self.assertEqual(restarted.observe(complete, old, 1020), (True, 0))
        self.assertEqual(restarted.observe(complete, complete, 1021), (False, 300))
        self.assertEqual(restarted.waiting_for, [])

    def test_one_hour_deadline_survives_restart_and_later_edits(self):
        old = source_signature(self.source)
        schedule = RefreshSchedule(runtime=self.runtime)
        self.book.write_bytes(b'updated')
        self.assertEqual(schedule.observe(source_signature(self.source), old, 100), (False, 300))
        self.books[1].write_bytes(b'updated later')
        partial = source_signature(self.source)
        restarted = RefreshSchedule(runtime=self.runtime)
        self.assertEqual(restarted.observe(partial, old, 3650), (False, 50))
        self.assertEqual(restarted.observe(partial, old, 3700), (False, 60))
        self.books[1].write_bytes(b'still changing')
        partial = source_signature(self.source)
        self.assertEqual(restarted.observe(partial, old, 3760), (False, 60))
        self.assertEqual(restarted.observe(partial, old, 3820), (True, 0))
        self.assertEqual(restarted.observe(partial, partial, 3821), (False, 300))
        self.books[-1].write_bytes(b'next round')
        next_batch = source_signature(self.source)
        self.assertEqual(restarted.observe(next_batch, partial, 3900), (False, 300))
        self.assertEqual(restarted.observe(next_batch, partial, 4200), (False, 300))

    def test_first_batch_requires_all_named_files_and_a_stable_minute(self):
        self.book.unlink()
        (self.source / "备份.xlsx").write_bytes(b'extra')
        schedule = RefreshSchedule()
        missing = source_signature(self.source)
        self.assertEqual(schedule.observe(missing, None, 0), (False, 300))
        self.assertEqual(schedule.waiting_for, [self.book.name])
        self.book.write_bytes(b'first')
        complete = source_signature(self.source)
        self.assertEqual(schedule.observe(complete, None, 300), (False, 60))
        self.assertEqual(schedule.observe(complete, None, 360), (True, 0))
        (self.source / "备份.xlsx").unlink()
        self.assertEqual(schedule.observe(source_signature(self.source), complete, 400), (False, 300))

    def test_checks_only_metadata_and_detects_add_edit_delete(self):
        read_bytes = Path.read_bytes
        def read_program_only(path):
            self.assertFalse(path.is_relative_to(self.source), 'must not read Excel')
            return read_bytes(path)
        with patch.object(Path, 'read_bytes', autospec=True, side_effect=read_program_only):
            before = source_signature(self.source)
            (self.source / '~$orders.xlsx').write_text('lock')
            (self.source / '鸿蒙智行销量数据汇总.xlsx').write_text('excluded')
            self.assertEqual(source_signature(self.source), before)
            (self.source / 'extra.xlsx').write_text('new')
            self.assertNotEqual(source_signature(self.source), before)
            (self.source / 'extra.xlsx').unlink()
            self.assertEqual(source_signature(self.source), before)
            self.book.write_text('changed content')
            self.assertNotEqual(source_signature(self.source), before)

    def test_existing_marker_must_advance_for_next_batch(self):
        schedule = RefreshSchedule()
        stamp = time.time_ns() + 10_000_000_000
        old = {**source_signature(self.source), "ready": [10, stamp, stamp]}
        for book in self.books:
            book.write_bytes(b'updated')
        new = {**source_signature(self.source), "ready": old["ready"]}
        self.assertEqual(schedule.observe(new, old, 300), (False, 300))
        self.assertEqual(schedule.observe(new, old, 600), (False, 300))
        stale = {**new, "ready": [10, 1, 1]}
        self.assertEqual(schedule.observe(stale, old, 700), (False, 300))
        self.assertEqual(schedule.waiting_for, ["orders.ready"])
        new = {**new, "ready": [10, stamp + 1, stamp + 1]}
        self.assertEqual(schedule.observe(new, old, 900), (False, 60))
        self.assertEqual(schedule.observe(new, old, 960), (True, 0))

    def test_copy_uses_original_bytes_and_rejects_concurrent_edit(self):
        expected = source_signature(self.source)
        destination = self.root / 'snapshot'
        destination.mkdir()
        copy_stable_inputs(self.source, destination, expected)
        self.assertEqual((destination / self.book.name).read_bytes(), b'first')
        original_copy = shutil.copy2
        def changing_copy(src, dst):
            original_copy(src, dst)
            self.book.write_bytes(b'changed while copying')
        with patch('core.sync.shutil.copy2', side_effect=changing_copy):
            with self.assertRaisesRegex(RuntimeError, '复制期间'):
                copy_stable_inputs(self.source, destination, expected)

    def test_optional_completion_marker_waits_for_latest_excel(self):
        marker = self.source / 'orders.ready'
        marker.write_text('done')
        os.utime(marker, (1, 1))
        with self.assertRaisesRegex(ValueError, 'orders.ready'):
            source_signature(self.source)
        os.utime(marker, None)
        self.assertIsNotNone(source_signature(self.source)['ready'])

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

    def test_revision_and_marker_cannot_bypass_batch_rule(self):
        files = [[name, 10, 1, 1] for name in BATCH_WORKBOOKS]
        old = {"directory": "inputs", "files": files, "ready": [1, 2, 2], "calculation_revision": "old"}
        new = {**old, "calculation_revision": "new", "ready": [1, 3, 3]}
        schedule = RefreshSchedule()
        self.assertEqual(schedule.observe(new, old, 0), (False, 300))
        partial = {**new, "files": [[files[0][0], 11, 2, 2], *files[1:]]}
        self.assertEqual(schedule.observe(partial, old, 300), (False, 300))
        self.assertEqual(schedule.observe(partial, old, 600), (False, 300))
        self.assertEqual(schedule.waiting_for, list(BATCH_WORKBOOKS[1:]))
