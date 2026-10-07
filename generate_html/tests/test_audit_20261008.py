"""Run production helpers to protect missing observations and reference validity."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class OctoberEightAuditTests(unittest.TestCase):
    def js(self, body):
        setup = r'''
const fs=require('fs'),m=require('./templates/forecast-math.js');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const window={ForecastMath:m};
const line=marker=>source.split('\n').find(text=>text.includes(marker));
const component=new Function('window','slotWeight',line('const dailyComponentShare=')+';return dailyComponentShare;')(window,slot=>slot?30:70);
const completion=new Function('window',[
 line('const observedDailyPrefix='),line('const forecastReferenceCurve='),
 line('const adaptedForecastCompletion='),line('const rebasedForecastCompletionCurve=')
].join('\n')+';return rebasedForecastCompletionCurve;')(window);
'''
        result = subprocess.run(['node', '-e', setup+body], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_intraday_missing_component_renormalizes_usable_reference(self):
        result = self.js(r'''
const reference=[{daily_orders:[100],daily_small:[null],daily_direct:[40]}, {daily_orders:[100],daily_small:[60],daily_direct:[40]}];
const share=component(reference,0,'daily_small',.4,'small_progress');
const direct=component(reference,0,'daily_direct',.4,'direct_progress');
console.log(JSON.stringify({share,estimate:m.intradayComponents({gross:100},.5,share/(share+direct))}));
''')
        self.assertAlmostEqual(result['share'], .6)
        self.assertEqual(result['estimate']['small'], 120)
        self.assertEqual(result['estimate']['direct'], 80)
        self.assertEqual(result['estimate']['gross'], 200)

    def test_intraday_zero_is_real_but_invalid_component_uses_fallback(self):
        result = self.js(r'''
const ref=value=>({daily_orders:[100],daily_small:[value]});
console.log(JSON.stringify({zero:component([ref(0),ref(60)],0,'daily_small',.4,'small_progress'),
 invalid:[null,'',true,-1,101].map(value=>component([ref(value)],0,'daily_small',.4,'small_progress'))}));
''')
        self.assertAlmostEqual(result['zero'], .18)
        self.assertEqual(result['invalid'], [.4]*5)

    def test_decreasing_completion_is_not_silently_repaired(self):
        result = self.js(r'''
console.log(JSON.stringify(['small_progress','direct_progress'].map(field=>completion({days:5,[field]:[.2,.6,.4,.8,1]},field,10))));
''')
        for curve in result:
            self.assertEqual(curve, [None]*10)

    def test_valid_completion_still_preserves_edges_and_zero_increments(self):
        result = self.js(r'''
const curve=[.2,.4,.4,.8,1];
console.log(JSON.stringify({same:completion({days:5,small_progress:curve},'small_progress',5),
 stretched:completion({days:5,small_progress:curve},'small_progress',10),
 expected:m.stretchCompletion(curve,10)}));
''')
        self.assertEqual(result['same'], [.2,.4,.4,.8,1])
        self.assertEqual(result['stretched'], result['expected'])

    def test_invalid_completion_exits_method_one_weighting(self):
        result = self.js(r'''
const estimate=new Function('window','slotWeight','protectCompletion',[
 line('const observedDailyPrefix='),line('const forecastReferenceCurve='),
 line('const adaptedForecastCompletion='),line('const rebasedForecastCompletion='),
 line('const progressEstimate=')
].join('\n')+';return progressEstimate;')(window,slot=>slot?30:70,m.protectCompletion);
const bad={days:5,small_progress:[.2,.6,.4,.8,1]},good={days:5,small_progress:[.2,.4,.6,.8,1]};
console.log(JSON.stringify({mixed:estimate([bad,good],'small_progress',2,5,'small_progress'),
 none:estimate([bad],'small_progress',2,5,'small_progress')}));
''')
        self.assertAlmostEqual(result['mixed']['applied'], .4)
        self.assertTrue(result['mixed']['valid'])
        self.assertFalse(result['none']['valid'])
        self.assertIsNone(result['none']['applied'])

    def test_small_missing_diagnostics_use_dates_not_d_labels(self):
        result = self.js(r'''
const actual={small_daily_days:[{date:'2026-09-01',orders:10},{date:'2026-09-03',orders:0},{date:'2026-09-05',orders:null}]},fallback=[];
const checked=m.completedSmallOrderDays('2026-09-01','2026-09-10','2026-09-07',actual.small_daily_days,fallback),actualRows=checked.rows;
const classify=new Function('checked','actualRows','actual','fallback',line('const latest=actualRows.at(-1)?.date')+';return {latest,unupdated,gaps};');
console.log(JSON.stringify({checked,classified:classify(checked,actualRows,actual,fallback)}));
''')
        self.assertEqual(result['checked']['missing'], ['D2','D4','D5','D6'])
        self.assertEqual(result['checked'].get('missingDates'), ['2026-09-02','2026-09-04','2026-09-05','2026-09-06'])
        self.assertEqual(result['classified']['gaps'], ['2026-09-02','2026-09-05'])
        self.assertEqual(result['classified']['unupdated'], ['2026-09-04','2026-09-06'])

    def test_small_missing_dates_are_empty_for_d1_and_invalid_window(self):
        result = self.js(r'''
console.log(JSON.stringify([
 m.completedSmallOrderDays('2026-09-01','2026-09-10','2026-09-01'),
 m.completedSmallOrderDays('','2026-09-10','2026-09-01')
]));
''')
        for case in result:
            self.assertEqual(case.get('missingDates'), [])
