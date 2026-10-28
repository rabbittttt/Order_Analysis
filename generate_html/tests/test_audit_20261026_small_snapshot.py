"""Active small-order forecasts conserve the largest known same-day snapshot."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class SmallOrderSnapshotFloorTests(unittest.TestCase):
    def run_cases(self, cases):
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const math=require('./templates/forecast-math.js'),source=fs.readFileSync('templates/dashboard.js','utf8');
const section=(a,b)=>{const i=source.indexOf(a),j=source.indexOf(b,i+a.length);assert(i>=0&&j>i);return source.slice(i,j)};
const helpers=section('  function lifecycleReferenceOptions(', '  function renderSmallOrderWorkspace(')+
 section('  const observedDailyPrefix=', '  function createForecastEstimateLogger(')+
 section('  function createForecastEstimateLogger(', '  init();');
const binding=section('  function bindSmallOrderForecast(', '  function bindSteadyForecast(');
function run(input){
 const nodes=new Map(),node=key=>{if(!nodes.has(key))nodes.set(key,{value:'',textContent:'',innerHTML:'',hidden:true});return nodes.get(key)};
 const select={value:'ref',options:[{value:'ref',dataset:{model:'reference'}}]},weight={value:'100'};
 const workspace={querySelector:node,querySelectorAll:key=>key==='[data-small-ref]'?[select]:key==='[data-small-weight]'?[weight]:[]};
 const root={querySelector:()=>workspace};
 const target={name:'current',smallStartDate:'2026-09-01',smallEndDate:'2026-09-04',smallDays:4,tier:'SUV',energy:'BEV',node:'new'};
 const reference={model:'reference',event_id:'ref',total:1000,days:4,tier:'SUV',energy:'BEV',node:'new',
  small_start_date:'2026-08-01',small_progress:input.curve??[.25,.5,.75,1],daily_orders:[250,250,250,250],d1_share:.25,
  small_start_hour:0,small_hourly_curve:Array.from({length:24},(_,i)=>(i+1)/24)};
 const today=input.today??'2026-09-03';
 const fixed=input.fixed??[{date:'2026-09-01',orders:100},{date:'2026-09-02',orders:200}];
 const actual={total_small:input.terminal??0,small_daily_days:[...fixed],small_hourly_days:[]};
 if('day' in input)actual.small_daily_days.push({date:today,orders:input.day});
 if('hour' in input)actual.small_hourly_days.push({date:today,orders:input.hour,hours:input.hours??[]});
 const calendarType=(start,index)=>({date:new Date(Date.parse(start+'T00:00:00Z')+index*86400000).toISOString().slice(0,10),type:'workday'});
 const ctx={window:{ForecastMath:math},console:{warn:()=>{}},smallReferenceScore:math.smallReferenceScore,completedSmallOrderDays:math.completedSmallOrderDays,
  fmt:String,esc:String,renderLifecycleBars:()=>'',renderLifecycleLineChart:()=>'',renderLifecycleScorePage:()=>'',
  forecastDateRanges:dates=>dates.join(', '),setForecastStageSummary:()=>{},
  showForecastCondition:(node,{reasons})=>{node.hidden=!reasons.filter(Boolean).length;node.textContent=reasons.filter(Boolean).join('; ');}};
 vm.createContext(ctx);vm.runInContext(helpers+binding+';globalThis.bindSmallOrderForecast=bindSmallOrderForecast;',ctx);
 const context={sameModel:(a,b)=>a===b,targetState:()=>target,findActual:()=>actual,findStageActual:()=>actual,todayIso:()=>today,
  calendarType,factors:()=>({workday:1,weekend:1,holiday:1}),
  planBridge:(_stage,args)=>math.anchoredAllocate({...args,factors:args.dates.map(()=>1),weights:math.defaultBridgeWeights(args.dates.length)})};
 ctx.bindSmallOrderForecast(root,{small_order_history:[reference]},context);
 return {total:root._smallForecastResult.total,stage:root._smallForecastResult.stage,error:root._smallForecastResult.error,
  actual:node('[data-small-kpi="actual"]').textContent,d1:node('[data-small-kpi="d1"]').textContent,
  rows:root._smallForecastResult.rows.map(row=>({date:row.date,orders:row.orders,actual:row.actual,observed:row.observed})),
  source:node('[data-small-source]').textContent};
}
console.log(JSON.stringify(JSON.parse(process.argv[1]).map(run)));
'''
        result = subprocess.run(['node', '-e', script, json.dumps(cases)], cwd=ROOT,
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def assert_known_days_preserved(self, result):
        self.assertEqual(result['error'], '')
        self.assertEqual(result['actual'], '300')
        self.assertEqual(result['rows'][:2], [
            {'date': '2026-09-01', 'orders': 100, 'actual': True},
            {'date': '2026-09-02', 'orders': 200, 'actual': True}])
        self.assertEqual(sum(row['orders'] for row in result['rows']), result['total'])

    def test_more_recent_hourly_snapshot_bounds_today_and_terminal(self):
        result = self.run_cases([{'day': 999, 'hour': 1200}])[0]
        self.assert_known_days_preserved(result)
        self.assertEqual(result['total'], 1500)
        self.assertEqual(result['rows'][2]['orders'], 1200)
        self.assertEqual(result['rows'][2]['observed'], 1200)
        self.assertEqual(result['rows'][3]['orders'], 0)

    def test_higher_daily_snapshot_is_not_replaced_or_double_counted(self):
        results = self.run_cases([{'day': 1200, 'hour': 999}, {'day': 1200, 'hour': 1200}])
        for result in results:
            self.assert_known_days_preserved(result)
            self.assertEqual(result['total'], 1500)
            self.assertEqual(result['rows'][2]['observed'], 1200)

    def test_each_known_source_survives_unknown_other_source(self):
        results = self.run_cases([{'day': None, 'hour': 1200}, {'day': 1200, 'hour': None},
                                  {'hour': 1200}, {'day': 1200}])
        for result in results:
            self.assert_known_days_preserved(result)
            self.assertEqual(result['total'], 1500)

    def test_real_zero_does_not_hide_higher_other_snapshot(self):
        results = self.run_cases([{'day': 0, 'hour': 1200}, {'day': 1200, 'hour': 0},
                                  {'day': 0, 'hour': 0}, {'day': 0, 'hour': None}])
        self.assertEqual([row['total'] for row in results], [1500, 1500, 600, 600])
        self.assertEqual([row['rows'][2]['observed'] for row in results], [1200, 1200, 0, 0])
        for result in results:
            self.assert_known_days_preserved(result)

    def test_unknown_and_invalid_snapshots_keep_existing_prediction(self):
        invalid = [None, '', '  ', True, False, -1, 'invalid', 'NaN', 'Infinity']
        results = self.run_cases([{'day': value, 'hour': value} for value in invalid])
        for result in results:
            self.assert_known_days_preserved(result)
            self.assertEqual(result['total'], 600)

    def test_largest_snapshot_floor_is_independent_of_selected_reference(self):
        results = self.run_cases([{'day': 999, 'hour': 1200, 'curve': curve}
                                 for curve in ([.25, .5, .75, 1], [.1, .3, .7, 1])])
        for result in results:
            self.assert_known_days_preserved(result)
            self.assertEqual(result['total'], 1500)
            self.assertGreaterEqual(result['rows'][2]['orders'], 1200)

    def test_d2_uses_snapshot_without_making_it_a_complete_real_day(self):
        result = self.run_cases([{'today': '2026-09-02',
                                 'fixed': [{'date': '2026-09-01', 'orders': 100}],
                                 'day': 0, 'hour': 500}])[0]
        self.assertEqual(result['stage'], 'active')
        self.assertEqual(result['actual'], '100')
        self.assertEqual(result['total'], 600)
        self.assertEqual(result['rows'][0], {'date': '2026-09-01', 'orders': 100, 'actual': True})
        self.assertFalse(result['rows'][1]['actual'])
        self.assertEqual(result['rows'][1]['orders'], 500)

    def test_d1_hourly_fit_and_ended_actual_total_are_unchanged(self):
        d1 = {'today': '2026-09-01', 'fixed': [], 'hour': 20,
              'hours': [{'hour': 0, 'orders': 10}, {'hour': 1, 'orders': 10}]}
        fixed = [{'date': f'2026-09-0{i}', 'orders': i * 100} for i in range(1, 5)]
        ended = {'today': '2026-09-05', 'fixed': fixed, 'terminal': 1000}
        base_d1, with_day, base_ended, with_snapshots = self.run_cases([
            d1, {**d1, 'day': 0}, ended, {**ended, 'day': 9999, 'hour': 12000}])
        self.assertEqual(base_d1['stage'], 'd1')
        self.assertEqual(base_d1['d1'], with_day['d1'])
        self.assertEqual(base_d1['total'], with_day['total'])
        quantities = lambda result: [(row['date'], row['orders'], row['actual']) for row in result['rows']]
        self.assertEqual(quantities(base_d1), quantities(with_day))
        # D1 snapshots belong to D1, never tomorrow's first forecast row.
        self.assertEqual(base_d1['rows'][0]['observed'], 20)
        self.assertEqual(with_day['rows'][0]['observed'], 20)
        self.assertNotIn('observed', base_d1['rows'][1])
        self.assertNotIn('observed', with_day['rows'][1])
        self.assertEqual(base_ended, with_snapshots)
        self.assertEqual(base_ended['total'], 1000)


if __name__ == '__main__':
    unittest.main()
