"""Daily and hourly launch snapshots describe overlapping, known orders."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class LaunchSnapshotTests(unittest.TestCase):
    def evaluate(self, cases):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert'),math=require('./templates/forecast-math.js');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const section=(a,b)=>{const i=source.indexOf(a),j=source.indexOf(b,i+a.length);assert(i>=0&&j>i);return source.slice(i,j)};
const estimate=section('      const partialSmallRatio=', '      const validQuantity=');
const build=section('      const buildRows=(scenario,availableScenario,method)=>', '      const scenarios=');
function run(input){
 const day=input.day??null,hour=input.hour??null,hasSmall=input.hasSmall!==false,d1=!!input.d1;
 const partial=input.noPartial?null:hour??day;
 const fixed=d1?[]:[{index:0,date:'2026-01-01',gross:100,small_to_big:hasSmall?50:0,direct:hasSmall?50:100,lock:0}];
 const share=hasSmall?.5:0,days=input.days??3,todayIndex=d1?0:1;
 const dateAt=i=>new Date(Date.parse('2026-01-01T00:00:00Z')+i*86400000).toISOString().slice(0,10);
 const ctx={window:{ForecastMath:math},root:{},refs:{daily:[],small_progress:[],direct_progress:[]},
  target:{hasSmall,days,launchDate:'2026-01-01'},hasSmall,small:10000,
  stageInfo:{key:'active'},todayRow:day,latestHourly:hour,partial:partial?{...partial,index:todayIndex,date:dateAt(todayIndex)}:null,
  todayIndex,dayIndex:todayIndex,elapsed:todayIndex,actualSmall:fixed.reduce((s,r)=>s+r.small_to_big,0),actualDirect:fixed.reduce((s,r)=>s+r.direct,0),
  partialFactor:input.completion??1,defaultSmallShare:share,baseShare:1-share,
  weighted:(a,b,c)=>c,dailyComponentShare:(a,b,c,d)=>d,resolvedFixed:fixed,
  endedComplete:false,d1InputError:'',lockRate:.1,observedLockFloor:0,
  calendarType:(start,i)=>({date:dateAt(i),type:'workday'}),dailyShape:()=>1,
  bridgeSettings:()=>({factors:{workday:1}}),calendarCompletedDays:todayIndex,
  planBridge:(_r,_c,_s,p)=>math.anchoredAllocate({...p,anchorFactor:1,factors:p.dates.map(()=>1),weights:math.defaultBridgeWeights(p.dates.length)}),
  d1Unavailable:!!input.noPartial,today:dateAt(todayIndex),validQuantity:v=>Number.isFinite(math.observedQuantity(v)),
  recomposeSources:()=>{}};
 vm.createContext(ctx);
 vm.runInContext(estimate+build+`;globalThis.estimate=partialEstimate;
  globalThis.scenario=window.ForecastMath.launchParameterTerminal({rawDataError:false,endedComplete:false,componentsReady:true,
   hasSmall,small:hasSmall?100:0,baseConversion:1,baseShare:.5,directD1:100,d1Ratio:1,
   actualSmall,actualDirect,actualGross:actualSmall+actualDirect,anchorSmall,anchorDirect});
  globalThis.rows=buildRows(scenario,scenario.available,'parameter');`,ctx);
 return {estimate:ctx.estimate,scenario:ctx.scenario,rows:ctx.rows};
}
console.log(JSON.stringify(JSON.parse(process.argv[1]).map(run)));
'''
        result = subprocess.run(['node', '-e', script, json.dumps(cases)], cwd=ROOT,
                                text=True, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_conserved(self, result, gross, small, direct):
        estimate, scenario, rows = result['estimate'], result['scenario'], result['rows']
        self.assertGreaterEqual(estimate['gross'], gross)
        self.assertGreaterEqual(estimate['observedSmall'], small)
        self.assertGreaterEqual(estimate['observedDirect'], direct)
        self.assertEqual(estimate['observed'], estimate['observedSmall']+estimate['observedDirect'])
        self.assertEqual(sum(r['gross'] for r in rows), scenario['gross'])
        self.assertTrue(all(r['gross'] == r['small_to_big']+r['direct'] for r in rows))
        self.assertTrue(scenario['available'])

    def test_newer_daily_snapshot_bounds_both_components_and_terminal(self):
        result = self.evaluate([{'hour': {'gross': 200, 'small_to_big': 100, 'direct': 100},
                                 'day': {'gross': 800, 'small_to_big': 400, 'direct': 400}}])[0]
        self.assert_conserved(result, 800, 400, 400)
        self.assertEqual(result['scenario']['gross'], 900)
        self.assertEqual(result['rows'][0]['gross'], 100)
        self.assertEqual(result['rows'][1]['gross'], 800)
        self.assertFalse(result['rows'][1]['actual'])

    def test_overlapping_snapshots_are_not_summed_or_extrapolated_twice(self):
        results = self.evaluate([{'hour': {'gross': 200, 'small_to_big': 100, 'direct': 100},
                                  'day': {'gross': 800, 'small_to_big': 400, 'direct': 400}, 'completion': .5},
                                 {'hour': {'gross': 800, 'small_to_big': 400, 'direct': 400},
                                  'day': {'gross': 200, 'small_to_big': 100, 'direct': 100}},
                                 {'hour': {'gross': 800, 'small_to_big': 400, 'direct': 400},
                                  'day': {'gross': 800, 'small_to_big': 400, 'direct': 400}}])
        for result in results:
            self.assert_conserved(result, 800, 400, 400)
            self.assertEqual(result['estimate']['gross'], 800)
            self.assertEqual(result['scenario']['gross'], 900)

    def test_missing_or_invalid_snapshot_keeps_known_source_and_real_zero(self):
        for invalid in (None, '', ' ', True, False, -1, 'NaN', 'Infinity'):
            with self.subTest(value=invalid):
                result = self.evaluate([{'hour': {'gross': invalid, 'small_to_big': invalid, 'direct': invalid},
                                         'day': {'gross': 800, 'small_to_big': 0, 'direct': 800}}])[0]
                self.assert_conserved(result, 800, 0, 800)
                self.assertEqual(result['estimate']['small'], 0)

    def test_each_source_can_supply_known_component_lower_bounds(self):
        result = self.evaluate([{'hour': {'gross': 800, 'small_to_big': 100},
                                 'day': {'small_to_big': 400, 'direct': 400}}])[0]
        self.assert_conserved(result, 800, 400, 400)
        self.assertEqual(result['estimate']['gross'], 800)
        self.assertEqual(result['estimate']['small'], 400)
        self.assertEqual(result['estimate']['direct'], 400)

    def test_hourly_projection_above_snapshot_remains_a_forecast(self):
        result = self.evaluate([{'hour': {'gross': 200, 'small_to_big': 100, 'direct': 100},
                                 'day': {'gross': 300, 'small_to_big': 0, 'direct': 300}, 'completion': .25}])[0]
        self.assert_conserved(result, 300, 100, 300)
        self.assertEqual(result['estimate']['gross'], 800)
        self.assertEqual(result['estimate']['observed'], 400)

    def test_d1_without_usable_hourly_curve_still_respects_daily_snapshot(self):
        result = self.evaluate([{'d1': True, 'noPartial': True,
                                 'hour': {'gross': 100, 'small_to_big': 50, 'direct': 50},
                                 'day': {'gross': 800, 'small_to_big': 400, 'direct': 400}}])[0]
        self.assert_conserved(result, 800, 400, 400)
        self.assertEqual(result['rows'][0]['gross'], 800)
        self.assertFalse(result['rows'][0]['actual'])

    def test_final_launch_day_and_no_reservation_preserve_total(self):
        results = self.evaluate([{'days': 2, 'hour': {'gross': 200}, 'day': {'gross': 800}},
                                 {'hasSmall': False, 'hour': {'gross': 200}, 'day': {'gross': 800}}])
        for result in results:
            self.assert_conserved(result, 800, 0, 0)
            self.assertEqual(result['scenario']['gross'], 900)
        self.assertEqual(results[1]['scenario']['small'], 0)
        self.assertEqual(results[1]['rows'][1]['direct'], 800)

    def test_duplicate_or_older_snapshots_keep_existing_rounding_and_inputs(self):
        script = r'''
const assert=require('assert'),m=require('./templates/forecast-math.js');
for(let i=0;i<1000;i++){
 const small=i%101,direct=i%83,source={gross:small+direct,small_to_big:small,direct};
 const before=JSON.stringify(source),completion=(i%99+1)/100,share=(i%101)/100;
 const baseline=m.intradayComponents(source,completion,share);
 assert.deepStrictEqual(m.intradayComponents(source,completion,share,[source]),baseline);
 assert.deepStrictEqual(m.intradayComponents(source,completion,share,[{gross:0,small_to_big:0,direct:0}]),baseline);
 assert.equal(JSON.stringify(source),before);
}
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, text=True,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
