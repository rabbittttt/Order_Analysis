"""Regression checks for source-date calendars and manual percentage inputs."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastCalendarAndRateTests(unittest.TestCase):
    def run_js(self, body):
        script = "const m=require('./templates/forecast-math.js'),window={ForecastMath:m};" + body
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def shape(self, stage, target_days, factors):
        source = (ROOT / 'templates/dashboard.js').read_text(encoding='utf-8').splitlines()
        names = ['referenceDailyShape'] if stage == 'small' else ['adaptedDailyOrders', 'naturalDailyOrders', 'dailyShape']
        # Optional new declaration lets the same regression execute before the fix.
        declarations = ''.join(next((line.strip() for line in source if line.strip().startswith('const '+name+'=')), '') for name in names)
        return self.run_js(
            'const factors='+json.dumps(factors)+';'
            "const historicalFactor=(item,i)=>factors[i%factors.length],slotWeight=()=>1,todayIso=()=> '2026-10-11',genericDailyShape=m.genericDailyShape;"
            "const context={factors:()=>Object.fromEntries(factors.map((v,i)=>[i,v])),calendarType:(date,i)=>({type:i%factors.length})};"
            "const item={days:8,small_start_date:'2026-09-01',launch_date:'2026-09-01',end_date:'2026-09-08',daily_orders:[100,100,200,100,100,100,100,100]};"
            + declarations + 'console.log(JSON.stringify(Array.from({length:'+str(target_days)+'},(_,i)=>'
            + ('referenceDailyShape(item,i,' if stage == 'small' else 'dailyShape([item],i,')+str(target_days)+'))));')

    def assert_shape(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for index, (left, right) in enumerate(zip(actual, expected)):
            self.assertAlmostEqual(left, right, msg=f'D{index+1}')

    def test_source_calendar_is_removed_before_stretching(self):
        for stage in ('small', 'launch'):
            with self.subTest(stage=stage):
                self.assert_shape(self.shape(stage, 12, [1,1,2,1,1,1,1,1]), [1,1]+[.5]*8+[1,1])

    def test_same_duration_keeps_existing_calendar_result(self):
        for stage in ('small', 'launch'):
            self.assert_shape(self.shape(stage, 8, [1,1,2,1,1,1,1,1]), [1]*8)

    def test_no_calendar_effect_preserves_source_orders(self):
        for stage in ('small', 'launch'):
            self.assert_shape(self.shape(stage, 8, [1]*8), [1,1,2,1,1,1,1,1])

    def page_rates(self, values):
        source = (ROOT / 'templates/dashboard.js').read_text(encoding='utf-8')
        declaration = source.split('rate=id=>', 1)[1].split(',target=targetState()', 1)[0]
        return self.run_js('let value;const root={querySelector:()=>({value})};const rate=id=>'+declaration+';'
                           'console.log(JSON.stringify('+json.dumps(values)+'.map(raw=>{value=raw;return rate("lock")})));')

    def test_manual_rates_reject_out_of_range_without_coercing_to_zero(self):
        self.assertEqual(self.page_rates(['-1','101','150','','Infinity','NaN']), [None]*6)

    def test_manual_valid_rates_include_real_zero_and_one_hundred(self):
        self.assertEqual(self.page_rates(['0','75','100']), [0,.75,1])

    def test_calendar_adjustment_does_not_change_raw_d1_share_api(self):
        result = self.run_js("const item={days:8,launch_date:'2026-09-01',end_date:'2026-09-08',daily_orders:[100,100,200,100,100,100,100,100]};"
                             "console.log(JSON.stringify(m.adaptLaunchDailyOrders(item,8,'2026-10-11')));")
        self.assert_shape(result, [100,100,200,100,100,100,100,100])

    def test_standard_small_curve_uses_source_dates_too(self):
        result = self.run_js("const item={days:8,small_progress:[100,200,400,500,600,700,800,900]};"
                             "const values=m.adaptSmallDailyOrders(item,12,i=>i===2?2:1);console.log(JSON.stringify(values.map(v=>v/values[0])));")
        self.assert_shape(result, [1,1]+[.5]*8+[1,1])

    def test_partial_and_invalid_calendar_are_not_used(self):
        result = self.run_js("const item={days:8,launch_date:'2026-09-01',end_date:'2026-09-08',daily_orders:[100,100,200,100,100,100,100,100]};"
                             "console.log(JSON.stringify([m.adaptSmallDailyOrders({...item,total_complete:false},12,i=>2),"
                             "m.adaptLaunchDailyOrders({...item,daily_orders:[100]},12,'2026-10-11',i=>2),"
                             "m.adaptSmallDailyOrders(item,12,i=>i===2?0:1),"
                             "m.adaptLaunchDailyOrders(item,12,'2026-10-11',i=>NaN)]));")
        self.assertEqual(result, [[],[],[],[]])

    def test_reference_plot_does_not_remove_calendar_twice(self):
        source = (ROOT / 'templates/dashboard.js').read_text(encoding='utf-8').splitlines()
        declaration = next(line.strip() for line in source if line.strip().startswith('const references=items.map'))
        result = self.run_js("const item={model:'参考',days:8,launch_date:'2026-09-01',end_date:'2026-09-08',daily_orders:[100,100,200,100,100,100,100,100]};"
                             "const items=[item],spec={metric:'daily_orders'},task='daily',targetDays=12,card={};"
                             "const factor=(item,i)=>i===2?2:1,root={_forecastDailyEvidence:{"
                             "naturalDailyOrders:(item,days)=>m.adaptLaunchDailyOrders(item,days,'2026-10-11',i=>factor(item,i)),"
                             "historicalFactor:factor,referenceStatus:item=>m.launchDailyReference(item,'2026-10-11')}};"
                             "const referenceMeta=()=>({label:'参考',color:'blue',core:true});"
                             +declaration+"console.log(JSON.stringify(references[0].values));")
        self.assert_shape(result, [1,1]+[.5]*8+[1,1])
