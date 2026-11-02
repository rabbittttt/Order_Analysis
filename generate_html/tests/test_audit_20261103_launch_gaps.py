"""Unavailable launch predictions must not turn missing actual days into facts."""
import json
import shutil
import subprocess
from pathlib import Path
from unittest import TestCase, skipUnless

ROOT=Path(__file__).resolve().parents[1]


@skipUnless(shutil.which('node'),'Node.js required')
class LaunchActualGapTests(TestCase):
    def run_case(self, rows, days=3, factors=None, lock_reference=None):
        script=r"""
const fs=require('fs'),vm=require('vm'),m=require('./templates/forecast-math.js');
const source=fs.readFileSync('templates/dashboard.js','utf8'),input=JSON.parse(process.argv[1]);
const start=source.indexOf('      let knownGross='),end=source.indexOf('      root._forecastComparison=',start);
if(start<0||end<0)throw Error('Known-actual adapter missing');
const target={name:'target',launchDate:'2026-09-01',days:input.days};
const calendarType=(date,index)=>({date:new Date(Date.parse(date+'T00:00:00Z')+index*86400000).toISOString().slice(0,10)});
const resolvedFixed=input.rows.map(row=>({...row,date:calendarType(target.launchDate,row.index).date,day:'D'+(row.index+1)}));
const actualGross=resolvedFixed.reduce((sum,row)=>sum+Number(row.gross||0),0),actualLock=input.lock_reference??resolvedFixed.reduce((sum,row)=>sum+Number(row.lock||0),0);
const adapted=new Function('resolvedFixed','validQuantity','hasSmall','small','calendarCompletedDays','calendarType','target','actualGross','actualLock','endedLockReference',source.slice(start,end)+';return {known:knownActualRows,actualLockRate};')(
 resolvedFixed,v=>v!==null&&v!==undefined&&v!==''&&typeof v!=='boolean'&&Number.isFinite(Number(v))&&Number(v)>=0,true,1000,input.days,calendarType,target,actualGross,actualLock,input.lock_reference!=null?{lock:input.lock_reference}:null);
const known=adapted.known;
const a=source.indexOf('  function renderForecastReferenceChartV2('),b=source.indexOf('  // All stages share chart geometry',a),charts=[];
const ctx={window:{ForecastMath:m},fmt:String,esc:String,renderForecastEvidenceLines:args=>{charts.push(args);return '';}};
vm.createContext(ctx);vm.runInContext(source.slice(a,b)+';globalThis.render=renderForecastReferenceChartV2;',ctx);
const root={_forecastComparison:{name:'target',rows:known,progressRows:[],parameterRows:[]},_forecastDailyEvidence:{targetFactor:index=>input.factors?.[index]??1}};
for(const task of ['daily','daily_slope'])ctx.render(root,{target},new Map(),{dataset:{forecastTask:task},querySelector:()=>({}),querySelectorAll:()=>[]});
const c=source.indexOf('  function renderForecastWeeklyV2('),d=source.indexOf('  let forecastRailObserver',c),node={innerHTML:''};
vm.runInContext(source.slice(c,d)+';globalThis.weekly=renderForecastWeeklyV2;',ctx);ctx.weekly({querySelector:()=>node},known);
console.log(JSON.stringify({known,actualLockRate:adapted.actualLockRate,charts:charts.map(c=>({title:c.title,labels:c.labels,series:c.series})),weekly:node.innerHTML}));
"""
        run=subprocess.run(['node','-e',script,json.dumps({'rows':rows,'days':days,'factors':factors,'lock_reference':lock_reference})],cwd=ROOT,text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        return json.loads(run.stdout)

    @staticmethod
    def row(index,gross,small=None,direct=None):
        return {'index':index,'gross':gross,'lock':None if gross is None else gross*.5,'small_to_big':gross*.2 if small is None and gross is not None else small,
                'direct':gross*.8 if direct is None and gross is not None else direct}

    @staticmethod
    def chart(result,title):
        return next((row for row in result['charts'] if title in row['title']),None)

    def test_middle_unknown_preserves_dn_and_invalidates_later_cumulative(self):
        result=self.run_case([self.row(0,100),self.row(1,None),self.row(2,300)])
        rows=result['known']
        self.assertEqual([r['day'] for r in rows],['D1','D2','D3'])
        self.assertEqual([r['daily_gross'] for r in rows],[100,None,300])
        self.assertEqual([r['cumulative_gross'] for r in rows],[100,None,None])
        self.assertEqual([r['cumulative_small'] for r in rows],[20,None,None])
        self.assertEqual([r['small_conversion'] for r in rows],[.02,None,None])
        self.assertEqual([r['direct_share'] for r in rows],[.8,None,None])

    def test_absent_middle_day_is_not_shifted_or_compared_across_gap(self):
        result=self.run_case([self.row(0,100),self.row(2,300)])
        chart=self.chart(result,'基础曲线')
        self.assertEqual(chart['labels'],['D1','D2','D3'])
        self.assertEqual(chart['series'][0]['values'],[1,None,3])
        slope=self.chart(result,'每日斜率')
        self.assertTrue(slope is None or all(v is None for curve in slope['series'] for v in curve['values']))

    def test_calendar_factor_uses_actual_day_index(self):
        result=self.run_case([self.row(0,100),self.row(2,300)],factors=[1,2,1])
        self.assertEqual(self.chart(result,'基础曲线')['series'][0]['values'],[1,None,3])

    def test_missing_d1_cannot_be_replaced_by_first_positive_later_day(self):
        result=self.run_case([self.row(1,200),self.row(2,300)])
        self.assertEqual([r['cumulative_gross'] for r in result['known']],[None,None,None])
        self.assertIsNone(self.chart(result,'基础曲线'))
        slope=self.chart(result,'每日斜率')
        self.assertEqual(slope['labels'],['D1','D2','D3'])
        self.assertEqual(slope['series'][0]['values'],[None,None,.5])

    def test_true_zero_is_not_a_gap(self):
        result=self.run_case([self.row(0,100),self.row(1,0),self.row(2,300)])
        self.assertEqual([r['cumulative_gross'] for r in result['known']],[100,100,400])
        self.assertEqual(self.chart(result,'基础曲线')['series'][0]['values'],[1,0,3])
        self.assertEqual(self.chart(result,'每日斜率')['series'][0]['values'],[None,-1,None])
        self.assertIn('<strong>400</strong>',result['weekly'])
        self.assertIn('全部真实',result['weekly'])

    def test_component_unknown_does_not_erase_independent_known_gross_or_direct(self):
        rows=[self.row(0,100),{**self.row(1,200),'small_to_big':None},self.row(2,300)]
        result=self.run_case(rows)
        self.assertEqual([r['cumulative_gross'] for r in result['known']],[100,300,600])
        self.assertEqual([r['cumulative_direct'] for r in result['known']],[80,240,480])
        self.assertEqual([r['cumulative_small'] for r in result['known']],[20,None,None])
        self.assertEqual([r['small_conversion'] for r in result['known']],[.02,None,None])

    def test_partial_week_is_not_advertised_as_complete_total(self):
        result=self.run_case([self.row(0,100),self.row(2,300)])
        self.assertIn('<strong>—</strong>',result['weekly'])
        self.assertIn('已知400',result['weekly'])
        self.assertIn('缺失1天',result['weekly'])
        self.assertNotIn('全部真实',result['weekly'])
        self.assertNotIn('期末累计400',result['weekly'])

    def test_complete_actuals_remain_unchanged(self):
        result=self.run_case([self.row(0,100),self.row(1,200),self.row(2,300)])
        self.assertEqual([r['cumulative_gross'] for r in result['known']],[100,300,600])
        self.assertEqual(self.chart(result,'基础曲线')['series'][0]['values'],[1,2,3])
        self.assertEqual(self.chart(result,'每日斜率')['series'][0]['values'],[None,1,.5])
        self.assertIn('<strong>600</strong>',result['weekly'])
        self.assertIn('期末累计600',result['weekly'])

    def test_actual_lock_rate_requires_complete_same_period_observations(self):
        self.assertIsNone(self.run_case([self.row(0,100),self.row(2,300)])['actualLockRate'])
        self.assertIsNone(self.run_case([self.row(0,100),self.row(1,None),self.row(2,300)])['actualLockRate'])
        unknown_lock=[self.row(0,100),{**self.row(1,200),'lock':None},self.row(2,300)]
        self.assertIsNone(self.run_case(unknown_lock)['actualLockRate'])
        self.assertEqual(self.run_case([self.row(0,100),self.row(1,0),self.row(2,300)])['actualLockRate'],.5)
        self.assertEqual(self.run_case([{**self.row(i,100),'lock':0} for i in range(3)])['actualLockRate'],0)
        self.assertIsNone(self.run_case([self.row(i,0) for i in range(3)])['actualLockRate'])
        self.assertIsNone(self.run_case([],days=0)['actualLockRate'])

    def test_independent_trusted_lock_terminal_survives_missing_daily_locks(self):
        rows=[{**self.row(i,100),'lock':None} for i in range(3)]
        self.assertEqual(self.run_case(rows,lock_reference=150)['actualLockRate'],.5)
        self.assertIsNone(self.run_case(rows[::2],lock_reference=150)['actualLockRate'])

    def test_zero_d1_does_not_promote_later_day_to_d1(self):
        result=self.run_case([self.row(0,0),self.row(1,200),self.row(2,300)])
        self.assertIsNone(self.chart(result,'基础曲线'))
        self.assertEqual(self.chart(result,'每日斜率')['series'][0]['values'],[None,None,.5])
        self.assertEqual([r['cumulative_gross'] for r in result['known']],[0,200,500])
