"""Regressions for real small-order facts, known zero rates and unknown counts."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class TableFactDisplayTests(unittest.TestCase):
    def run_js(self, script):
        preamble = """
const fs=require('fs'),assert=require('assert');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const section=(start,end)=>{const i=source.indexOf(start);assert(i>=0,start);const j=source.indexOf(end,i+start.length);assert(j>i,end);return source.slice(i,j)};
"""
        result = subprocess.run(['node', '-e', preamble + script], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


    def table(self, values, kind):
        return self.run_js(r"""
const helpers=section('  const displayText =','  const LABEL_SCALE_HEADROOM');
const render=new Function(helpers+section('  function formatTableCell(', '\n')+';return formatTableCell;')();
console.log(JSON.stringify(VALUES.map(value=>render(value,KIND))));
""".replace('VALUES', json.dumps(values)).replace('KIND', json.dumps(kind)))

    def test_unknown_numeric_cells_do_not_become_observed_zero(self):
        for kind in ('number', 'percent', 'signed_percent'):
            with self.subTest(kind=kind):
                self.assertEqual(self.table([None, '', '   '], kind), ['—'] * 3)

    def test_known_zero_and_existing_formats_are_preserved(self):
        self.assertEqual(self.table([0, 1234.5], 'number'), ['0', '1,234.5'])
        self.assertEqual(self.table([0, .125], 'percent'), ['0.0%', '12.5%'])
        self.assertEqual(self.table([0, -.125], 'signed_percent'),
                         ['<span class="change pos">+0.0%</span>', '<span class="change neg">-12.5%</span>'])
        self.assertEqual(self.table([None, '', '原始文字'], 'text'), ['', '', '原始文字'])


if __name__ == '__main__':
    unittest.main()
