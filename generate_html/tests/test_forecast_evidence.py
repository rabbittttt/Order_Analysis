"""Exercise the actual dashboard scorer, not a reimplementation of its formula."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastEvidenceTests(unittest.TestCase):
    def score(self, item, days, task='conversion'):
        script = r'''
const fs=require('fs'),m=require('./templates/forecast-math.js');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const start=source.indexOf('    const observed=window.ForecastMath.observedQuantity'),end=source.indexOf('    const scoreSummary=',start);
if(start<0||end<=start)throw Error('Dashboard scoring block not found');
const calculate=new Function('window','actualSignals','item','task',`
const sameModel=(a,b)=>a===b,calendarProfile=()=>({}),calendarSimilarity=()=>NaN,
calendarText=()=>'',adaptationText=()=>'',dailyUnavailable=()=>'',fmt=String;
${source.slice(start,end)}
return scoreParts(item,task,{name:'target',small:1000,days:10});`);
const days=DAYS;
console.log(JSON.stringify(calculate({ForecastMath:m},()=>({days,d1:days[0],d2:days[1]}),ITEM,TASK)));
'''.replace('DAYS', json.dumps(days)).replace('ITEM', json.dumps({'model': 'reference', 'small': 1000, **item})).replace('TASK', json.dumps(task))
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return {part['key']: part for part in json.loads(result.stdout)}

    def test_missing_reference_metrics_never_score_as_matching_zero(self):
        item = dict.fromkeys(('d1_small','d1_small_share','d2_small_share','small_d2_d1','small_d1_d12','d1_cancel_rate','d2_cancel_rate','d12_cancel_rate'))
        item['daily_small'] = [10, None, 10]
        days = [{'gross':10, 'small_to_big':value, 'direct':10-value, 'cancel':0} for value in (0,0,10)]
        parts = self.score(item, days)
        self.assertTrue({'earlySmall','smallSlope','dnSmallShape','earlyCancel'}.isdisjoint(parts), parts)

    def test_missing_target_components_do_not_create_scoring_evidence(self):
        days = [{'gross':10,'small_to_big':None,'direct':None,'cancel':None} for _ in range(3)]
        item = {'d1_small':0,'d1_small_share':0,'d2_small_share':0,'small_d2_d1':0,'small_d1_d12':0,
                'd1_direct_share':0,'d2_direct_share':0,'direct_d2_d1':0,'direct_d1_d12':0,
                'daily_small':[1,2,3],'daily_direct':[1,2,3]}
        for task, keys in [('conversion', {'earlySmall','smallSlope','dnSmallShape'}),
                           ('direct_share', {'earlyDirect','directSlope','dnDirectShape'})]:
            self.assertTrue(keys.isdisjoint(self.score(item, days, task)))

    def test_observed_zero_and_complete_curves_remain_valid_evidence(self):
        days = [{'gross':10,'small_to_big':value,'direct':10-value,'cancel':0} for value in (0,5,10)]
        parts = self.score({'d1_small':0,'d1_small_share':0,'d1_cancel_rate':0,'d2_cancel_rate':0,
                            'd12_cancel_rate':0,'daily_small':[0,5,10],'conversion':0}, days)
        for key in ('earlySmall','earlyCancel','dnSmallShape','final'):
            self.assertEqual(parts[key]['value'], 1, key)

    def test_lock_availability_uses_valid_rates_including_zero(self):
        self.assertEqual(self.score({'net_rate':0,'lock_rate':0}, [], 'lock')['lock']['value'], 1)
        self.assertEqual(self.score({'net_rate':None,'lock_rate':1.2}, [], 'lock')['lock']['value'], 0)

    def test_python_history_to_actual_js_score_preserves_missing_evidence(self):
        from modules.sales_forecast import _history_item
        fields = ('d1_small','d1_small_share','d2_small_share','small_d2_d1','small_d1_d12',
                  'd1_direct_share','d2_direct_share','direct_d2_d1','direct_d1_d12',
                  'd1_cancel_rate','d2_cancel_rate','d12_cancel_rate')
        for processed in (False, True):
            item = _history_item({'传播名':'reference','总小订':1000,'D1大定':10}, processed)
            for field in fields:
                self.assertIsNone(item[field], field)
            days = [{'gross':10,'small_to_big':0,'direct':10,'cancel':0} for _ in range(3)]
            self.assertTrue({'earlySmall','smallSlope','earlyCancel'}.isdisjoint(self.score(item, days)))
        zero = _history_item({'传播名':'reference','D1小转大':0,'D1大定':10,'D1退订率':0}, True)
        self.assertEqual(zero['d1_small'], 0)
        self.assertEqual(zero['d1_small_share'], 0)
        self.assertEqual(zero['d1_cancel_rate'], 0)
        ratio_only = _history_item({'传播名':'reference','D1小转大/D1大定':.4}, True)
        self.assertEqual(ratio_only['d1_small_share'], .4)
