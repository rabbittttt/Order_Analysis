"""Small forecast evidence must not move observations across missing dates."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class SmallEvidenceCalendarTests(unittest.TestCase):
    def chart_values(self, observations, total=100, error=''):
        script = r'''
const fs=require('fs'),m=require('./templates/forecast-math.js'),window={ForecastMath:m};
const source=fs.readFileSync('templates/dashboard.js','utf8');
const section=source.slice(source.indexOf('const renderEvidence=(target,stage,forecast)=>'),source.indexOf('function bindSteadyForecast'));
const cut=(start,end)=>section.slice(section.indexOf(start),section.indexOf(end,section.indexOf(start)));
const target={smallStartDate:'2026-09-01',smallDays:5};
const context={factors:()=>({workday:1,holiday:2}),calendarType:(start,index)=>({type:index===1?'holiday':'workday'})};
const rows=OBSERVATIONS.map(row=>({...row,label:'D'+Number(row.date.slice(-2)),actual:row.actual!==false}));
const forecast={rows,actualRows:rows.filter(r=>r.actual),targetDays:5,total:TOTAL,error:ERROR};
const code=cut('const days=Math.max(Number(forecast?.targetDays','const chartSeries=[]')+
 cut(section.includes('const current=evidence.daily')?'const current=evidence.daily':'const current=(forecast.rows','if(actual.some(Number.isFinite))')+
 cut(section.includes('const rows=evidence.rows')?'const rows=evidence.rows':'const rows=forecast.rows||[],normalized=','series.unshift({label:target.name')+
 ';return {actualValues,forecastValues,actual,predicted,slopes:values};';
const result=new Function('window','target','context','forecast',code)(window,target,context,forecast);
console.log(JSON.stringify(result));
'''.replace('OBSERVATIONS', json.dumps(observations)).replace('TOTAL', str(total)).replace('ERROR', json.dumps(error))
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_missing_middle_day_keeps_date_and_invalidates_cumulative_and_slope(self):
        result = self.chart_values([{'date':'2026-09-01','orders':10}, {'date':'2026-09-03','orders':40}])
        self.assertEqual(result['actual'], [1,None,4,None,None])
        self.assertEqual(result['actualValues'], [.1,None,None,None,None])
        self.assertEqual(result['slopes'], [None]*5)

    def test_missing_d1_does_not_promote_d2_to_anchor(self):
        result = self.chart_values([{'date':'2026-09-02','orders':20}])
        self.assertEqual(result['actual'], [None]*5)
        self.assertEqual(result['actualValues'], [None]*5)

    def test_zero_d1_is_not_replaced_by_first_positive_day(self):
        result = self.chart_values([{'date':'2026-09-01','orders':0}, {'date':'2026-09-02','orders':20}])
        self.assertEqual(result['actual'], [None]*5)
        self.assertEqual(result['actualValues'], [0,.2,None,None,None])

    def test_contiguous_actual_and_forecast_keep_transition_and_total(self):
        rows=[{'date':f'2026-09-0{i}','orders':v,'actual':i<3} for i,v in enumerate([10,20,30,20,20],1)]
        result = self.chart_values(rows)
        self.assertEqual(result['actual'], [1,1,None,None,None])
        self.assertEqual(result['predicted'], [None,1,3,2,2])
        self.assertEqual(result['actualValues'], [.1,.3,None,None,None])
        self.assertEqual(result['forecastValues'], [None,.3,.6,.8,1])

    def test_duplicate_date_is_unknown_not_another_lifecycle_day(self):
        result = self.chart_values([{'date':'2026-09-01','orders':10}, {'date':'2026-09-01','orders':20},
                                    {'date':'2026-09-03','orders':30}])
        self.assertEqual(result['actual'], [None]*5)
        self.assertEqual(result['actualValues'], [None]*5)

    def test_explicit_zero_day_is_not_a_gap(self):
        result = self.chart_values([{'date':'2026-09-01','orders':10}, {'date':'2026-09-02','orders':0},
                                    {'date':'2026-09-03','orders':40}])
        self.assertEqual(result['actual'], [1,0,4,None,None])
        self.assertEqual(result['actualValues'], [.1,.1,.5,None,None])
        self.assertEqual(result['slopes'], [None,-1,None,None,None])

    def test_unsorted_and_outside_window_rows_do_not_change_day_positions(self):
        result = self.chart_values([{'date':'2026-09-03','orders':40}, {'date':'2026-08-31','orders':999},
                                    {'date':'2026-09-01','orders':10}, {'date':'2026-09-06','orders':999}])
        self.assertEqual(result['actual'], [1,None,4,None,None])
        self.assertEqual(result['actualValues'], [.1,None,None,None,None])
