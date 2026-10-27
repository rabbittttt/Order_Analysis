"""An unknown cancellation rate must not become a measured zero."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from openpyxl import Workbook
from modules.cancellation import _parse_daily_retreat


class CancellationUnknownRateTests(unittest.TestCase):
    def parse(self, values):
        book = Workbook()
        self.addCleanup(book.close)
        sheet = book.active
        sheet.append(['日期', '当日小订退', '累计小订退', '当日大定退',
                      '小转大率', '小订退订率', '大定退订率'])
        for i, value in enumerate(values, 1):
            sheet.append([f'2026-10-{i:02}', 10, i*10, 2, value, value, value])
        return _parse_daily_retreat(sheet)

    def test_empty_error_and_invalid_rates_stay_unknown(self):
        rows = self.parse([None, '', ' ', '—', '#DIV/0!', '#N/A', '待更新',
                           True, False, 'NaN', 'Infinity', '-Infinity'])
        for row in rows:
            self.assertEqual([row[field] for field in ('convert_rate', 'small_rate', 'big_rate')], [None]*3)
            self.assertEqual((row['daily'], row['big_daily']), (10, 2))

    def test_zero_and_supported_percent_encodings_keep_original_meaning(self):
        rows = self.parse([0, .25, 25, '25', '25%', '25％'])
        self.assertEqual([row['small_rate'] for row in rows], [0, .25, .25, .25, .25, .25])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_source_to_chart_has_a_gap_and_preserves_zero_label_rule(self):
        rows = self.parse([.1, None, '#DIV/0!', 0, .2])
        script = r'''
const fs=require('fs'),vm=require('vm');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const start=source.indexOf('  function renderDailyCancel('),end=source.indexOf('  function renderHourlyChart(',start);
const ctx={colors:{coral:'red',orange:'orange',purple:'purple'},fmt:String,chartMax:()=>1,
 rhythmKnown:v=>typeof v==='number'&&Number.isFinite(v),renderRhythmChart:spec=>spec};
vm.createContext(ctx);vm.runInContext(source.slice(start,end)+';globalThis.render=renderDailyCancel;',ctx);
console.log(JSON.stringify(ctx.render(JSON.parse(process.argv[1]))));
'''
        result = subprocess.run(['node', '-e', script, json.dumps(rows)],
                                cwd=Path(__file__).resolve().parents[1], text=True,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = json.loads(result.stdout)
        self.assertEqual([row['rates']['small_rate'] for row in spec['rows']], [.1, None, None, 0, .2])
        self.assertIn('小订退率 —', spec['rows'][1]['tooltip'])
        self.assertIn('小订退率 0.0%', spec['rows'][3]['tooltip'])


if __name__ == '__main__':
    unittest.main()
