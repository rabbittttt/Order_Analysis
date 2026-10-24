"""Current-day known locks bound launch forecasts without double counting snapshots."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class LaunchObservedLockFloorTests(unittest.TestCase):
    def run_cases(self, cases):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const math=require('./templates/forecast-math.js');
const section=(a,b)=>{const i=source.indexOf(a),j=source.indexOf(b,i+a.length);assert(i>=0&&j>i);return source.slice(i,j)};
const actuals=section('      const sum=field=>resolvedFixed.reduce(', '      const hourlyFallbackUsed=');
const build=section('      const buildRows=(scenario,availableScenario,method)=>', '      const scenarios=');
function run(input){
 const fixed=input.fixed??[{index:0,date:'2026-01-01',gross:100,small_to_big:0,direct:100,lock:10}];
 const hourly=input.hourly===null?null:input.hourly??{index:1,date:'2026-01-02',gross:100,small_to_big:0,direct:100,lock:90,last_hour:20};
 const day=input.day??null,partial=input.noPartial?null:hourly;
 const ended=!!input.ended,days=input.days??3,rate=input.rate??.1,estimate=math.intradayComponents(partial,1,0);
 const today=new Date(Date.parse('2026-01-01T00:00:00Z')+(input.todayIndex??1)*86400000).toISOString().slice(0,10);
 const ctx={stageInfo:{key:ended?'ended':'active'},endedComplete:ended,d1InputError:'',lockRate:rate,resolvedFixed:fixed,latestHourly:hourly,todayRow:day,partial,
 target:{days,launchDate:'2026-01-01'},historyList:input.history??[],sameModel:(a,b)=>a===b,
 todayIndex:input.todayIndex??1,today,calendarCompletedDays:fixed.length,d1Fit:null,rollingHourlyCompletion:()=>1,
 partialGross:estimate.gross,partialSmall:estimate.small,partialDirect:estimate.direct,observedPartialSmall:estimate.observedSmall,observedPartialDirect:estimate.observedDirect,
 calendarType:(date,i)=>({date:new Date(Date.parse(date+'T00:00:00Z')+i*86400000).toISOString().slice(0,10),type:'workday'}),
 dailyShape:()=>1,bridgeSettings:()=>({factors:{workday:1}}),root:{},refs:{daily:[]},
 planBridge:(_r,_c,_s,p)=>math.anchoredAllocate({...p,anchorFactor:1,factors:p.dates.map(()=>1),weights:math.defaultBridgeWeights(p.dates.length)}),
 d1Unavailable:!!input.d1Unavailable,hasSmall:false,small:0,effectiveDays:fixed.length+(partial?1:0),observed:math.observedQuantity,
 validQuantity:v=>Number.isFinite(math.observedQuantity(v)),window:{ForecastMath:math}};
 vm.createContext(ctx);
 vm.runInContext(actuals+build+';globalThis.buildRows=buildRows;globalThis.actualLockResult=actualLock;',ctx);
 const gross=input.gross??300,scenario={small:0,direct:gross,gross,lock:ended?ctx.actualLockResult:gross*rate};
 const rows=ctx.buildRows(scenario,true,'parameter');
 return {lock:scenario.lock,gross:scenario.gross,actualLock:ctx.actualLockResult,rowGross:rows.reduce((s,r)=>s+r.gross,0),rowActual:rows.filter(r=>r.actual).map(r=>({gross:r.gross,lock:r.lock}))};
}
console.log(JSON.stringify(JSON.parse(process.argv[1]).map(run)));
'''
        result = subprocess.run(['node', '-e', script, json.dumps(cases)], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_current_hourly_locks_bound_both_valid_rates(self):
        results = self.run_cases([{'rate': 0}, {'rate': .1}])
        self.assertEqual([row['lock'] for row in results], [100, 100])
        for row in results:
            self.assertEqual(row['actualLock'], 10)
            self.assertEqual(row['rowGross'], 300)
            self.assertEqual(row['rowActual'], [{'gross': 100, 'lock': 10}])

    def test_same_day_snapshots_take_largest_known_value_without_summing(self):
        results = self.run_cases([{'day': {'lock': 120}}, {'day': {'lock': 90}},
                                  {'day': {'lock': 60}}])
        self.assertEqual([row['lock'] for row in results], [130, 100, 100])

    def test_known_locks_survive_missing_gross_and_components(self):
        results = self.run_cases([{'noPartial': True, 'day': {'lock': 80},
                                  'hourly': {'lock': 90, 'gross': None}},
                                 {'noPartial': True, 'hourly': None, 'day': {'lock': 120}}])
        self.assertEqual([row['lock'] for row in results], [100, 130])

    def test_unknown_or_invalid_current_locks_do_not_replace_existing_prediction(self):
        invalid = [None, '', '  ', True, False, -1, 'NaN', 'Infinity', 'invalid']
        results = self.run_cases([{'hourly': {'gross': None, 'lock': value},
                                  'day': {'lock': value}, 'noPartial': True}
                                 for value in invalid])
        self.assertEqual([row['lock'] for row in results], [30] * len(invalid))

    def test_real_zero_remains_valid_and_invalid_rate_stays_unknown(self):
        results = self.run_cases([{'hourly': {'lock': 0}, 'noPartial': True, 'rate': 0},
                                 {'hourly': None, 'day': {'lock': 90}, 'noPartial': True, 'rate': 'invalid'}])
        self.assertEqual(results[0]['lock'], 10)
        self.assertIsNone(results[1]['lock'])

    def test_last_day_terminal_recalculation_keeps_known_lock_floor(self):
        result = self.run_cases([{'days': 2}])[0]
        self.assertEqual(result['lock'], 100)
        self.assertEqual(result['rowGross'], 300)

    def test_d1_snapshot_raising_gross_keeps_known_lock_floor(self):
        result = self.run_cases([{'fixed': [], 'todayIndex': 0, 'noPartial': True,
                                 'd1Unavailable': True, 'hourly': {'date': '2026-01-01',
                                 'gross': 500, 'direct': 500, 'small_to_big': 0, 'lock': 400}}])[0]
        self.assertEqual(result['gross'], 500)
        self.assertEqual(result['rowGross'], 500)
        self.assertEqual(result['lock'], 400)

    def test_ended_actual_locks_are_not_changed_by_current_day_snapshots(self):
        fixed = [{'index': 0, 'date': '2026-01-01', 'gross': 100,
                  'small_to_big': 0, 'direct': 100, 'lock': 10},
                 {'index': 1, 'date': '2026-01-02', 'gross': 100,
                  'small_to_big': 0, 'direct': 100, 'lock': 20}]
        result = self.run_cases([{'ended': True, 'days': 2, 'fixed': fixed,
                                 'day': {'lock': 900}, 'hourly': None, 'gross': 200}])[0]
        self.assertEqual(result['lock'], 30)
        self.assertEqual(result['actualLock'], 30)
        self.assertEqual(result['rowGross'], 200)


if __name__ == '__main__':
    unittest.main()
