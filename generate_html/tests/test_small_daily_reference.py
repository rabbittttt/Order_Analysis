"""Small daily allocation must never stretch an incomplete actual prefix."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class SmallDailyReferenceTests(unittest.TestCase):
    def js(self, body):
        setup = r'''
const fs=require('fs'),m=require('./templates/forecast-math.js');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const line=source.split('\n').find(line=>line.includes('const referenceDailyShape='));
const context={factors:()=>({workday:1,weekend:2}),calendarType:(start,index)=>({type:index===1?'weekend':'workday'})};
const shape=new Function('window','context',line+';return referenceDailyShape;')({ForecastMath:m},context);
'''
        result = subprocess.run(['node', '-e', setup+body], cwd=ROOT,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_missing_actual_days_are_not_stretched_or_replaced(self):
        result = self.js(r'''
const base={days:10,total_complete:true,standard_progress:Array.from({length:10},(_,i)=>(i+1)/10)};
const probes=[
 [100,80,60,40,20],
 [100,80,60,40,20,null,null,null,null,null],
 [100,80,60,40,20,'',10,10,10,10],
 [100,80,60,40,20,undefined,10,10,10,10],
 [100,80,60,40,20,NaN,10,10,10,10],
 [100,80,60,40,20,-1,10,10,10,10],
 [100,80,60,40,20,true,10,10,10,10]
];
console.log(JSON.stringify(probes.map(daily_orders=>({
 orders:m.adaptSmallDailyOrders({...base,daily_orders},10),
 shape:shape({...base,daily_orders},7,10)
}))));
''')
        for case in result:
            self.assertEqual(case['orders'], [])
            self.assertIsNone(case['shape'])

    def test_valid_daily_shape_and_calendar_adjustment_unchanged(self):
        result = self.js(r'''
const cases=[];
for(const days of [5,10,36])for(const target of [5,10,36]){
 const orders=Array.from({length:days},(_,i)=>i===2?0:100/(i+1));
 const item={days,total_complete:true,daily_orders:orders};
 let running=0;const old=m.stretchCompletion(orders.map(value=>(running+=value)),target);
 const expected=old.map((value,i)=>value-(i?old[i-1]:0));
 const actual=m.adaptSmallDailyOrders(item,target);
 cases.push({same:JSON.stringify(expected)===JSON.stringify(actual),
  calendar:shape(item,1,target),expectedCalendar:expected[1]/2/expected[0]});
}
console.log(JSON.stringify(cases));
''')
        for case in result:
            self.assertTrue(case['same'])
            self.assertAlmostEqual(case['calendar'], case['expectedCalendar'])

    def test_standard_curve_is_allowed_only_when_complete_and_no_actual_series(self):
        result = self.js(r'''
const curve=[.2,.4,.6,.8,1],base={days:5,standard_progress:curve};
console.log(JSON.stringify({valid:m.adaptSmallDailyOrders(base,10),
 short:m.adaptSmallDailyOrders({...base,days:10},10),
 gap:m.adaptSmallDailyOrders({...base,standard_progress:[.2,.4,null,.8,1]},10),
 unfinished:m.adaptSmallDailyOrders({...base,total_complete:false},10),
 zeros:m.adaptSmallDailyOrders({...base,daily_orders:[0,0,0,0,0]},10)}));
''')
        self.assertEqual(len(result['valid']), 10)
        self.assertAlmostEqual(sum(result['valid']), 1)
        for key in ('short', 'gap', 'unfinished', 'zeros'):
            self.assertEqual(result[key], [])

    def test_invalid_primary_is_removed_before_weight_normalization(self):
        result = self.js(r'''
const bad={days:10,total_complete:true,daily_orders:[100,80,60,40,20,null,null,null,null,null]};
const good={days:10,total_complete:true,daily_orders:[100,80,60,40,20,10,10,10,10,10]};
const reference=shape(good,6,10);
console.log(JSON.stringify({reference,
 mixed:m.weightedObserved([{value:shape(bad,6,10),weight:70},{value:reference,weight:30}]),
 none:m.weightedObserved([{value:shape(bad,6,10),weight:100}])}));
''')
        self.assertAlmostEqual(result['mixed'], result['reference'])
        self.assertIsNone(result['none'])

    def test_no_usable_daily_reference_reports_curve_not_calendar_error(self):
        result = self.js(r'''
const args={remaining:100,shapes:[1,NaN],factors:[1,1],weights:[.5,1]};
console.log(JSON.stringify({missing:m.anchoredAllocate(args),
 calendar:m.anchoredAllocate({...args,shapes:[1,1],factors:[1,0]})}));
''')
        self.assertEqual(result['missing']['values'], [])
        self.assertIn('到天基础曲线缺失或无效', result['missing']['error'])
        self.assertNotIn('日历系数', result['missing']['error'])
        self.assertIn('日历系数', result['calendar']['error'])

    def test_automatic_daily_selection_skips_incomplete_high_score_reference(self):
        result = self.js(r'''
const good={model:'good',days:10,total_complete:true,daily_orders:Array(10).fill(10)};
const bad={...good,model:'bad',daily_orders:[100,80,60,40,20,null,null,null,null,null]};
const history=[bad,good],select={value:'',options:history.map(item=>({value:item.model,dataset:{model:item.model}}))};
const groups={daily:{selects:[select]}};
const initializeLine=source.split('\n').find(line=>line.includes('const initializeReferences=()=>{const target=targetState();Object.entries(groups)'));
const initialize=new Function('targetState','groups','ranked','referenceDailyShape','stageEligible',
 'rebasedForecastCompletionCurve','sameModel','lifecycleUnavailable','history','itemKey',initializeLine+';return initializeReferences;')(
 ()=>({name:'target',smallDays:10}),groups,()=>history.map(item=>({item,eligible:true})),shape,
 ()=>true,()=>[1],(a,b)=>a===b,()=>false,history,item=>item.model);
initialize();
console.log(JSON.stringify({selected:select.value}));
''')
        self.assertEqual(result['selected'], 'good')
