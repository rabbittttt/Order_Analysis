"""Real page helpers: preserve calendar positions and avoid quadratic adaptation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastTimelineTests(unittest.TestCase):
    def js(self, body, timezone='Asia/Shanghai'):
        setup = "const fs=require('fs'),m=require('./templates/forecast-math.js'),source=fs.readFileSync('templates/dashboard.js','utf8');"
        result = subprocess.run(['node','-e',setup+body], cwd=ROOT, capture_output=True,
                                encoding='utf-8', env={**os.environ,'TZ':timezone})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def feature(self, rows, today='2026-09-05', timezone='Asia/Shanghai'):
        return self.js(r'''
const rows=ROWS, today=TODAY;
const target={name:'test',launchDate:'2026-09-01',endDate:'2026-09-04',days:4};
const context={todayIso:()=>today,factors:()=>({workday:1,weekend:2}),
 calendarType:(start,index)=>({type:index===1?'weekend':'workday'}),findStageActual:()=>({days:rows})};
const start=source.indexOf('    const directFeature='),end=source.indexOf('    const scoreResult=',start);
if(start<0||end<start)throw Error('Feature helper not found');
const feature=new Function('context','targetLaunch','observedDailyPrefix','window','target',
 source.slice(start,end)+'return directFeature({},target);')(
 context,()=>({days:4,lock_rate:.8}),values=>values,{ForecastMath:m},target);
const score=m.steadyReferenceScore({tier:'SUV',energy:'EV',node:'new',launch_days:4,direct_curve:[100,30,40,10]},
 {tier:'SUV',energy:'EV',node:'new'},feature);
console.log(JSON.stringify({...feature,eligible:score.eligible}));
'''.replace('ROWS', json.dumps(rows)).replace('TODAY', json.dumps(today)), timezone)

    def test_gap_keeps_its_day_and_later_calendar_factors(self):
        rows=[{'date':'2026-09-01','direct':100},{'date':'2026-09-03','direct':30},{'date':'2026-09-04','direct':40}]
        for tz in ('Asia/Shanghai','America/New_York'):
            result=self.feature(rows, timezone=tz)
            self.assertEqual(result['direct_curve'], [100,None,30,40])
            self.assertFalse(result['eligible'])

    def test_first_day_gap_and_duplicate_never_shift_or_choose_an_arbitrary_row(self):
        rows=[{'date':'2026-09-02','direct':30},{'date':'2026-09-03','direct':40},
              {'date':'2026-09-03','direct':50},{'date':'2026-09-04','direct':60}]
        self.assertEqual(self.feature(rows)['direct_curve'], [None,15,None,60])

    def test_real_zero_is_kept_and_today_or_future_is_not_observed(self):
        rows=[{'date':'2026-08-31','direct':999},{'date':'2026-09-01','direct':100},
              {'date':'2026-09-02','direct':0},{'date':'2026-09-03','direct':30},{'date':'2026-09-04','direct':40}]
        self.assertEqual(self.feature(rows,'2026-09-03')['direct_curve'], [100,0])
        self.assertEqual(self.feature(rows,'2026-09-01')['direct_curve'], [])
        self.assertEqual(self.feature(rows)['direct_curve'], [100,0,30,40])

    def test_whole_completion_curve_equals_daily_queries_with_one_adaptation(self):
        result=self.js(r'''
const vm=require('vm');let calls=0;
const sandbox={window:{ForecastMath:{...m,stretchCompletion(...args){calls++;return m.stretchCompletion(...args)}}}};
vm.createContext(sandbox);
const first=source.indexOf('  const observedDailyPrefix='),last=source.indexOf('  function createForecastEstimateLogger(',first);
vm.runInContext(source.slice(first,last)+';this.one=rebasedForecastCompletion;this.all=rebasedForecastCompletionCurve;',sandbox);
const results=[];
for(const days of [4,10,90])for(const target of [3,5,30,90])for(const missing of [false,true]){
 const item={days,small_progress:Array.from({length:days},(_,i)=>(i+1)/days),daily_small:Array(days).fill(1)};
 if(missing)item.daily_small[Math.floor(days/2)]=null;
 const expected=Array.from({length:target},(_,i)=>sandbox.one(item,'small_progress',i+1,target).value);
 calls=0;const actual=sandbox.all(item,'small_progress',target);
 results.push({equal:JSON.stringify(expected)===JSON.stringify(actual),calls,missing});
}
console.log(JSON.stringify(results));
''')
        for case in result:
            self.assertTrue(case['equal'], case)
            self.assertLessEqual(case['calls'], 1, case)
