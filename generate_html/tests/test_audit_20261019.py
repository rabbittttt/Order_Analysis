"""Confirmed terminal zero, independently dated SKU blocks and safe HTML output."""
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch

from openpyxl import Workbook
from core.excel import WorkbookItem, WorkbookStore
from core.models import Subject
from core.renderer import render_dashboard
from modules.sales_forecast import _history_item
from modules.sku import SkuModule

ROOT = Path(__file__).resolve().parents[1]


class ConfirmedLockTerminalTests(TestCase):
    def test_missing_lock_is_not_a_zero_terminal(self):
        for value in (None, '', '#DIV/0!', True, -1, float('nan'), float('inf')):
            with self.subTest(value=value):
                self.assertIsNone(_history_item({'首销期锁单': value}, True)['lock'])

    def test_confirmed_zero_and_positive_lock_are_retained(self):
        for value, expected in ((0, 0), ('0', 0), (80, 80), ('1,234', 1234)):
            with self.subTest(value=value):
                self.assertEqual(_history_item({'首销期锁单': value}, True)['lock'], expected)

    @skipUnless(shutil.which('node'), 'Node.js required')
    def test_ended_fallback_distinguishes_zero_unknown_and_mismatched_values(self):
        source = (ROOT / 'templates/dashboard.js').read_text(encoding='utf-8')
        expression = re.search(r'endedLockReference=(.*?),actualLock=', source)[1]
        script = r'''
const choose=new Function('stageInfo','completeLock','historyList','target','actualGross','sameModel','return '+JSON.parse(process.argv[1]));
const base={model:'测试车',launch_date:'2026-01-01',days:2,gross:200,lock:0};
const cases=[base,{...base,lock:80},{...base,lock:null},{...base,lock:-1},
 {...base,lock:201},{...base,gross:201},{...base,days:3},{...base,model:'其他车'}];
console.log(JSON.stringify(cases.map(item=>choose({key:'ended'},false,[item],
 {name:'测试车',launchDate:'2026-01-01',days:2},200,(a,b)=>a===b)?.lock??null)));
'''
        result = subprocess.run(['node', '-e', script, json.dumps(expression)],
                                capture_output=True, text=True, encoding='utf-8', cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [0, 80, None, None, None, None, None, None])


class SkuPeriodAlignmentTests(TestCase):
    def build(self, share_periods, cumulative_periods):
        book = Workbook()
        self.addCleanup(book.close)
        sku = book.active
        sku.title = '测试车_SKU'
        sku.append(['SKU', '版本', '外观', '内饰', '轮毂', *share_periods, '总计占比',
                    '累计锁单', *cumulative_periods, '总计'])
        shares = [{'26WK01': 0, '26WK02': .6, '26WK03': 1},
                  {'26WK01': 1, '26WK02': .4, '26WK03': 0}]
        cumulative = [{'26WK01': .5, '26WK02': .6, '26WK03': .9, '26WK04': .95},
                      {'26WK01': .8, '26WK02': .85, '26WK03': 1, '26WK04': 1}]
        for index in range(2):
            sku.append([f'SKU{index+1}', 'Max', '黑', '灰', '20',
                        *[shares[index].get(p, 0) for p in share_periods], .5,
                        ('TOP3', 'TOP5')[index], *[cumulative[index][p] for p in cumulative_periods], 1])
        combo = book.create_sheet('测试车_组合')
        combo.append(['累计锁单', '配置', *cumulative_periods, '总计'])
        combo.append(['TOP1', 'Max', *[.5 for _ in cumulative_periods], .5])
        store = WorkbookStore(Path('.'))
        store.items = [WorkbookItem(Path('鸿蒙智行SKU收敛度.xlsx'), book)]
        view = SkuModule().build(store, Subject('car', '测试车', 'generation')).to_dict()['views']['week']
        return view, view['pages'][view['default_period']]

    def test_shifted_headers_join_by_week_not_column_index(self):
        view, page = self.build(['26WK01', '26WK02', '26WK03'], ['26WK02', '26WK03'])
        kpis = {k['label']: k for k in page['kpis']}
        self.assertEqual(view['default_period'], '26WK03')
        self.assertEqual(kpis['有效SKU']['value'], 1)
        self.assertEqual(kpis['有效SKU']['comparison']['previous'], 2)
        ranking = next(s['data']['rows'] for s in page['sections'] if s['kind'] == 'table')
        self.assertEqual([(r[1], r[-1]) for r in ranking], [('SKU1', 1), ('SKU2', 0)])
        self.assertEqual(ranking[0][2:6], ['Max', '黑', '灰', '20'])

    def test_cumulative_only_week_does_not_fabricate_sku_sales(self):
        view, page = self.build(['26WK01', '26WK02', '26WK03'], ['26WK02', '26WK03', '26WK04'])
        kpis = {k['label']: k for k in page['kpis']}
        self.assertEqual(view['default_period'], '26WK04')
        self.assertIsNone(kpis['有效SKU']['value'])
        self.assertEqual(kpis['TOP3累计']['value'], 95)
        self.assertEqual(next(s['data']['rows'] for s in page['sections'] if s['kind'] == 'table'), [])
        tails = next(s['data'] for s in page['sections'] if s['kind'] == 'tail_distribution')
        self.assertIsNone(next(r['value'] for r in tails if r['label'] == '26WK04'))

    def test_share_only_latest_week_does_not_relabel_old_cumulative_values(self):
        view, page = self.build(['26WK01', '26WK02', '26WK03'], ['26WK01', '26WK02'])
        kpis = {k['label']: k for k in page['kpis']}
        self.assertEqual(view['default_period'], '26WK03')
        self.assertEqual(kpis['有效SKU']['value'], 1)
        self.assertIsNone(kpis['TOP3累计']['value'])
        heat = next(s['data'] for s in page['sections'] if s['kind'] == 'sku_heatmap')
        self.assertEqual(heat['periods'], ['26WK01', '26WK02', '26WK03'])
        self.assertEqual(heat['rows'][0]['values'], [.5, .6, None])

    def test_identical_headers_preserve_existing_results(self):
        _, page = self.build(['26WK01', '26WK02', '26WK03'], ['26WK01', '26WK02', '26WK03'])
        self.assertEqual([k['value'] for k in page['kpis']], [1, 90, 100, 3])


class AtomicHtmlOutputTests(TestCase):
    def render(self, output):
        render_dashboard({'subjects': [], 'dashboards': {}, 'raw_blocks': {}}, ROOT / 'templates', output)

    def test_partial_write_failure_preserves_previous_html_and_cleans_up(self):
        original = Path.write_text
        def fail_after_partial_write(path, text, *args, **kwargs):
            original(path, text[:20], *args, **kwargs)
            raise OSError('simulated disk full')
        with TemporaryDirectory() as folder:
            output = Path(folder) / '看板.html'
            output.write_text('previous usable report', encoding='utf-8')
            with patch.object(Path, 'write_text', fail_after_partial_write), self.assertRaisesRegex(OSError, 'disk full'):
                self.render(output)
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous usable report')
            self.assertEqual(list(Path(folder).iterdir()), [output])

    def test_replace_failure_preserves_previous_html_and_cleans_up(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / '看板.html'
            output.write_text('previous usable report', encoding='utf-8')
            with patch.object(Path, 'replace', side_effect=PermissionError('simulated locked destination')), \
                 self.assertRaisesRegex(PermissionError, 'locked destination'):
                self.render(output)
            self.assertEqual(output.read_text(encoding='utf-8'), 'previous usable report')
            self.assertEqual(list(Path(folder).iterdir()), [output])

    def test_success_replaces_complete_html_without_leaving_temporary_files(self):
        with TemporaryDirectory() as folder:
            output = Path(folder) / '看板.html'
            output.write_text('old', encoding='utf-8')
            self.render(output)
            self.assertIn('window.DASHBOARD_BLOCKS_B64=', output.read_text(encoding='utf-8'))
            self.assertEqual(list(Path(folder).iterdir()), [output])
