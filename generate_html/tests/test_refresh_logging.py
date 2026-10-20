"""CLI logging keeps operational messages without the retired G9 diagnostics."""
from pathlib import Path
import subprocess
import sys
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
POLLUTED = {
    'root_warning': 'logging.basicConfig(level=logging.WARNING,stream=sys.stdout)',
    'handler_warning': 'handler=logging.StreamHandler(sys.stdout);handler.setLevel(logging.WARNING);logging.basicConfig(level=logging.INFO,handlers=[handler])',
    'named_warning': 'LOGGER.setLevel(logging.WARNING)',
    'named_disabled': 'LOGGER.disabled=True',
    'no_propagation': 'LOGGER.propagate=False',
    'global_disable_info': 'logging.disable(logging.INFO)',
}


class RefreshLoggingTests(TestCase):
    def process(self, script):
        result = subprocess.run([sys.executable, '-X', 'utf8', '-c', script], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def refresh(self, setup='', *, reuse=False, debug=False, fail=False):
        return self.process('''
import logging, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import tools.refresh_sales_forecast_data as refresh
LOGGER=refresh.LOGGER
SETUP
args=SimpleNamespace(source=Path('source.xlsx'),mapping=refresh.DEFAULT_MAPPING,
 output=Path('summary.xlsx'),orders=Path('orders'),as_of_date='',force=False,debug=DEBUG)
def build(*args):
 LOGGER.info('正常刷新信息')
 LOGGER.debug('DEBUG探针')
 LOGGER.warning('业务告警样例')
book=MagicMock();book.sheetnames=[]
with patch.object(refresh,'parse_args',return_value=args), \\
 patch.object(refresh,'resolve_source_path',side_effect=RuntimeError('测试读取失败') if FAIL else lambda p:p), \\
 patch.object(refresh,'resolve_mapping_path',side_effect=lambda p:p), \\
 patch.object(refresh,'ensure_mapping'),patch.object(refresh,'summary_is_current',return_value=REUSE), \\
 patch.object(refresh,'build_secondary',side_effect=build) as rebuilt, \\
 patch.object(refresh,'load_workbook',return_value=book),patch.object(refresh,'audit_final_forecast'):
 code=refresh.main()
 assert code==(1 if FAIL else 0), code
 assert rebuilt.call_count==(0 if REUSE or FAIL else 1),rebuilt.call_count
 if REUSE:book.close.assert_called_once()
'''.replace('SETUP', setup).replace('debug=DEBUG', 'debug='+str(debug)).replace('REUSE', str(reuse)).replace('FAIL', str(fail)))

    def test_refresh_entry_and_info_survive_all_reproduced_launcher_states(self):
        for name, setup in {'clean':'', **POLLUTED}.items():
            with self.subTest(state=name):
                output = self.refresh(setup)
                self.assertNotIn('[G9取数排查]', output)
                self.assertIn('[INFO] 正常刷新信息', output)
                self.assertIn('[WARNING] 业务告警样例', output)
                self.assertNotIn('DEBUG探针', output)

    def test_debug_option_still_controls_debug_output(self):
        output = self.refresh(POLLUTED['root_warning'], debug=True)
        self.assertIn('[DEBUG] DEBUG探针', output)
        self.assertNotIn('[G9取数排查]', output)

    def test_reuse_reports_status_without_retired_model_diagnostics(self):
        output = self.refresh(POLLUTED['global_disable_info'], reuse=True)
        self.assertNotIn('[G9取数排查]', output)
        self.assertIn('销量数据汇总已是最新，跳过刷新', output)
        self.assertNotIn('正常刷新信息', output)

    def test_source_resolution_failure_is_reported_without_retired_self_check(self):
        output = self.refresh(POLLUTED['root_warning'], fail=True)
        self.assertNotIn('[G9取数排查]', output)
        self.assertIn('[ERROR] 刷新失败', output)

    def test_parent_relays_info_into_console_and_file_without_warning_counts(self):
        for name, setup in POLLUTED.items():
            with self.subTest(state=name):
                output = self.process('''
import json, logging, sys
from pathlib import Path
from tempfile import TemporaryDirectory
import main
LOGGER=main.LOGGER
SETUP
with TemporaryDirectory() as folder:
 path=main.configure_runtime(Path(folder))
 LOGGER.info('父进程INFO正常')
 main.relay_refresh_line('[INFO] 正常子进程转发')
 logging.shutdown()
 content=path.read_text(encoding='utf-8')
 assert '正常子进程转发' in content,content
 assert '父进程INFO正常' in content,content
 assert main.DIAGNOSTIC_COUNTS=={'WARNING':0,'ERROR':0},main.DIAGNOSTIC_COUNTS
 print('FILE_AND_COUNTS_OK')
'''.replace('SETUP', setup))
                self.assertIn('正常子进程转发', output)
                self.assertIn('FILE_AND_COUNTS_OK', output)
