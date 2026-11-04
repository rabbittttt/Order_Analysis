"""Preserve usable weeks, intentional D1 zero and failed-build exit status."""
from argparse import Namespace
from datetime import date
import json
import logging
from pathlib import Path
import shutil
import subprocess
from unittest import TestCase, skipUnless
from unittest.mock import patch

from openpyxl import Workbook

import main as generator

ROOT = Path(__file__).resolve().parents[1]


class GenerationOutcomeTests(TestCase):
    def run_main(self, severity=None, *, strict=False, auto_open=False, failure=None):
        args = Namespace(input=Path('input'), output=Path('output/report.html'), debug=False,
                         check=strict, no_open=not auto_open)
        def configure(*_):
            generator.DIAGNOSTIC_COUNTS.update(WARNING=0, ERROR=0)
            return Path('test.log')
        def build(*_, **__):
            if failure:
                raise failure
            if severity is not None:
                record = logging.LogRecord('audit', severity, __file__, 0, '生成阶段问题', (), None)
                generator.DiagnosticCollector().handle(record)
            return {'subjects': [], 'dashboards': {}}, ['生成阶段问题'] if severity else []
        with patch.object(generator, 'parse_args', return_value=args), \
             patch.object(generator, 'configure_runtime', side_effect=configure), \
             patch.object(generator, 'build', side_effect=build), \
             patch.object(generator, 'cleanup_input_cache') as cleanup, \
             patch.object(generator, 'AUTO_OPEN_HTML', True), \
             patch.object(generator.os, 'startfile', create=True) as startfile, \
             patch.object(generator.webbrowser, 'open', return_value=True) as browser, \
             self.assertLogs(generator.LOGGER, level='INFO') as captured:
            code = generator.main()
        cleanup.assert_called_once_with(args.output.parent)
        return code, captured.output, startfile, browser

    def test_non_strict_run_with_module_or_excel_error_is_not_success(self):
        code, output, _, _ = self.run_main(logging.ERROR)
        self.assertEqual(code, 1)
        self.assertFalse(any('生成成功:' in message for message in output))

    def test_incomplete_build_does_not_auto_open_as_success(self):
        code, _, startfile, browser = self.run_main(logging.ERROR, auto_open=True)
        self.assertEqual(code, 1)
        startfile.assert_not_called()
        browser.assert_not_called()

    def test_warning_only_status_preserves_normal_and_strict_modes(self):
        self.assertEqual(self.run_main(logging.WARNING)[0], 0)
        self.assertEqual(self.run_main(logging.WARNING, strict=True)[0], 1)
        self.assertEqual(self.run_main()[0], 0)

    def test_fatal_exception_still_fails_and_cleans_cache(self):
        code, _, startfile, browser = self.run_main(failure=RuntimeError('failed'), auto_open=True)
        self.assertEqual(code, 1)
        startfile.assert_not_called()
        browser.assert_not_called()
