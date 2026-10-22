"""Regressions for real small-order facts, known zero rates and unknown counts."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastFactDisplayTests(unittest.TestCase):
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

    def ended(self, daily, actual, *, derived=False):
        return self.run_js(r"""
const block=section("      }else if(stage.key==='ended'){",'      }else{');
const body=block.slice(block.indexOf('{')+1);
const run=new Function('daily','current','actualRows','target','transitionTotal','checked','actualTotal',
 'let total=0,d1=NaN,completion=NaN,confidence="",message="";'+body+';return {d1:Number.isFinite(d1)?d1:null,total,message};');
console.log(JSON.stringify(run(INPUT.daily,{total:100,total_complete:true,daily_actual:!INPUT.derived},INPUT.actual,
 {smallStartDate:'2026-09-01'},100,{missing:[]},100)));
""".replace('INPUT', json.dumps({'daily': daily, 'actual': actual, 'derived': derived})))

    def test_ended_d1_prefers_resolved_actual_over_history(self):
        result = self.ended([20, 80], [{'date': '2026-09-01', 'orders': 50},
                                      {'date': '2026-09-02', 'orders': 50}])
        self.assertEqual(result, {'d1': 50, 'total': 100, 'message': ''})

    def test_ended_missing_d1_is_not_a_zero_or_later_day(self):
        for history in ([None, 100], [20, 80], []):
            with self.subTest(history=history):
                result = self.ended(history, [{'date': '2026-09-02', 'orders': 100}])
                self.assertIsNone(result['d1'])
                self.assertEqual(result['total'], 100)

    def test_derived_history_d1_is_not_a_real_fact(self):
        self.assertIsNone(self.ended([20, 80], [], derived=True)['d1'])
        self.assertEqual(self.ended([20, 80], [{'date': '2026-09-01', 'orders': 0}], derived=True)['d1'], 0)

    def test_real_zero_and_unordered_actual_d1_are_retained(self):
        for value in (0, 50):
            with self.subTest(value=value):
                result = self.ended([99, 1], [{'date': '2026-09-02', 'orders': 100-value},
                                            {'date': '2026-09-01', 'orders': value}])
                self.assertEqual(result['d1'], value)

    def rates(self):
        return self.run_js(r"""
const declaration=section('      const lockRate=rawRate', '\n');
const run=new Function('rawRate','root','forecastDraftControlKey',declaration+';return validRate?Math.round(100*lockRate):null;');
const root={_forecastTouched:new Set(),querySelector:()=>({value:'0'})};
console.log(JSON.stringify(['0','50','100','','   ',undefined,'invalid','-1','101'].map(value=>run(value,root,()=> 'lock'))));
""")

    def test_automatic_zero_lock_rate_converts_imported_orders_to_zero(self):
        self.assertEqual(self.rates()[:3], [0, 50, 100])

    def test_missing_or_invalid_import_lock_rates_stay_unknown(self):
        self.assertEqual(self.rates()[3:], [None] * 6)

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
