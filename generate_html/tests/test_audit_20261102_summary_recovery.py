"""A damaged generated summary is rebuilt; input and filesystem failures stay fatal."""
from argparse import Namespace
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl import Workbook, load_workbook

from core.forecast_summary import DAILY_SHEET, GUIDE_SHEET, table_records
from tools import refresh_sales_forecast_data as refresh
from tests import test_forecast_source_backfill_e2e as fixtures


class SummaryRecoveryTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.output = self.root / 'source.xlsx', self.root / 'summary.xlsx'
        self.source.write_bytes(b'source signature only')
        book = Workbook()
        book.active.title = GUIDE_SHEET
        book.create_sheet(DAILY_SHEET)
        book.properties.identifier = refresh.forecast_signature(self.source, self.source, self.root, '2026-09-05')
        book.save(self.output)
        book.close()
        self.touch_output()

    def touch_output(self):
        stamp = time.time() + 120
        os.utime(self.output, (stamp, stamp))

    def current(self):
        return refresh.summary_is_current(self.source, self.output, self.source, self.root, '2026-09-05')

    def replace_part(self, name, content):
        original = self.output.read_bytes()
        with ZipFile(BytesIO(original)) as source, ZipFile(self.output, 'w', ZIP_DEFLATED) as target:
            for entry in source.infolist():
                if entry.filename != name:
                    target.writestr(entry, source.read(entry.filename))
                elif content is not None:
                    target.writestr(entry, content)
        self.touch_output()

    def test_valid_current_summary_reuses_signature(self):
        self.assertTrue(self.current())
        self.source.write_bytes(b'changed source')
        self.assertFalse(self.current())

    def test_truncated_zip_is_cache_miss_and_releases_output(self):
        self.output.write_bytes(b'PK\x03\x04truncated workbook')
        self.touch_output()
        self.assertFalse(self.current())
        self.output.unlink()  # Windows cannot remove an outstanding workbook handle.

    def test_missing_ooxml_component_is_cache_miss(self):
        self.replace_part('[Content_Types].xml', None)
        self.assertFalse(self.current())
        self.output.unlink()

    def test_malformed_workbook_xml_is_cache_miss(self):
        self.replace_part('xl/workbook.xml', b'<workbook><broken>')
        self.assertFalse(self.current())
        self.output.unlink()

    def test_read_permission_and_io_errors_still_propagate(self):
        for error in (PermissionError('occupied output'), OSError('disk read error')):
            with self.subTest(error=type(error).__name__):
                with patch.object(refresh, 'load_workbook', side_effect=error):
                    with self.assertRaises(type(error)):
                        self.current()


class SummaryRecoveryEndToEndTests(TestCase):
    def setUp(self):
        # The CLI enables process-wide diagnostic deduplication. Restore the
        # caller's state after each test instead of changing later test runs.
        self.enterContext(patch('core.excel._CONFLICT_CHECKS', None))

    def fixture(self):
        fixture = fixtures.SourceBackfillEndToEndTests()
        self.addCleanup(fixture.doCleanups)
        book = fixture.build()
        output = book._test_path
        expected = table_records(book, DAILY_SHEET)
        book.close()
        root = output.parent
        source = root / '小订及首销数据整理.xlsx'
        self.inputs = {p: sha256(p.read_bytes()).hexdigest() for p in [source, *root.joinpath('orders').glob('*.xlsx')]}
        args = Namespace(source=source, output=output, mapping=source, orders=root / 'orders',
                         as_of_date='2026-09-05', force=False, debug=False)
        return args, expected

    def run_refresh(self, args, build=None):
        with patch.object(refresh, 'parse_args', return_value=args), \
             patch.object(refresh, 'configure_refresh_logging'), \
             patch.object(refresh, 'build_secondary', wraps=build or refresh.build_secondary) as rebuilt:
            result = refresh.main()
        return result, rebuilt.call_count

    def assert_inputs_unchanged(self):
        for path, digest in self.inputs.items():
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), digest)

    def test_truncated_summary_is_automatically_rebuilt_from_real_inputs(self):
        args, expected = self.fixture()
        args.output.write_bytes(b'PK\x03\x04truncated summary')
        result, rebuilt = self.run_refresh(args)
        self.assertEqual((result, rebuilt), (0, 1))
        book = load_workbook(args.output, read_only=True, data_only=True)
        try:
            self.assertEqual(table_records(book, DAILY_SHEET), expected)
        finally:
            book.close()
        self.assert_inputs_unchanged()

    def test_late_invalid_cell_in_cached_summary_also_rebuilds(self):
        args, expected = self.fixture()
        raw = args.output.read_bytes()
        # Keep metadata and worksheet dimensions valid; fail during lazy row iteration.
        with ZipFile(BytesIO(raw)) as source, ZipFile(args.output, 'w', ZIP_DEFLATED) as target:
            for entry in source.infolist():
                content = source.read(entry.filename)
                if entry.filename.startswith('xl/worksheets/'):
                    content = content.replace(b'<v>40</v>', b'<v>not-a-number</v>')
                target.writestr(entry, content)
        self.assertTrue(refresh.summary_is_current(args.source, args.output, args.mapping, args.orders, args.as_of_date))
        result, rebuilt = self.run_refresh(args)
        self.assertEqual((result, rebuilt), (0, 1))
        book = load_workbook(args.output, read_only=True, data_only=True)
        try:
            self.assertEqual(table_records(book, DAILY_SHEET), expected)
        finally:
            book.close()
        self.assert_inputs_unchanged()

    def test_valid_summary_hit_does_not_rebuild_or_rewrite(self):
        args, _ = self.fixture()
        before = args.output.read_bytes()
        self.assertEqual(self.run_refresh(args), (0, 0))
        self.assertEqual(args.output.read_bytes(), before)
        self.assert_inputs_unchanged()

    def test_rebuild_source_error_is_not_swallowed_and_output_is_preserved(self):
        args, _ = self.fixture()
        broken = b'PK\x03\x04truncated summary'
        args.output.write_bytes(broken)
        def fail(*_):
            raise ValueError('invalid original source')
        self.assertEqual(self.run_refresh(args, fail), (1, 1))
        self.assertEqual(args.output.read_bytes(), broken)
        self.assert_inputs_unchanged()

    def test_real_invalid_input_does_not_replace_existing_summary(self):
        args, _ = self.fixture()
        before = args.output.read_bytes()
        args.force = True
        args.source.write_bytes(b'invalid original workbook')
        self.inputs[args.source] = sha256(args.source.read_bytes()).hexdigest()
        self.assertEqual(self.run_refresh(args), (1, 1))
        self.assertEqual(args.output.read_bytes(), before)
        self.assert_inputs_unchanged()

    def test_replace_permission_error_keeps_previous_summary(self):
        args, _ = self.fixture()
        before = args.output.read_bytes()
        args.force = True
        with patch.object(refresh.os, 'replace', side_effect=PermissionError('output occupied')):
            self.assertEqual(self.run_refresh(args), (1, 1))
        self.assertEqual(args.output.read_bytes(), before)
        self.assert_inputs_unchanged()

    def test_missing_ooxml_component_is_automatically_rebuilt(self):
        args, expected = self.fixture()
        raw = args.output.read_bytes()
        with ZipFile(BytesIO(raw)) as source, ZipFile(args.output, 'w', ZIP_DEFLATED) as target:
            for entry in source.infolist():
                if entry.filename != '[Content_Types].xml':
                    target.writestr(entry, source.read(entry.filename))
        self.assertEqual(self.run_refresh(args), (0, 1))
        book = load_workbook(args.output, read_only=True, data_only=True)
        try:
            self.assertEqual(table_records(book, DAILY_SHEET), expected)
        finally:
            book.close()
        self.assert_inputs_unchanged()
