"""Shared boundary inputs run against both Python and the actual JS math owner."""
import json
import os
import shutil
import subprocess
import unittest
from datetime import date
from pathlib import Path

from modules.sales_forecast import _forecast_stage, _small_order_stage, _profile_issues, _profile_hard_errors

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastContractTests(unittest.TestCase):
    def js(self, expression, timezone='Asia/Shanghai'):
        result = subprocess.run(['node', '-e',
            'const m=require('+json.dumps(str(ROOT/'templates/forecast-math.js'))+');console.log(JSON.stringify('+expression+'));'],
            capture_output=True, encoding='utf-8', env={**os.environ, 'TZ': timezone})
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_shared_launch_boundary_cases(self):
        cases = [
            ('2026-09-01','2026-09-03',3,today) for today in
            ('2026-08-31','2026-09-01','2026-09-03','2026-09-04')]
        cases += [
            ('2026-12-30','',4,'2027-01-01'),
            ('2024-02-28','2024-03-01',99,'2024-02-29'),
            ('2026-03-07','2026-03-10',4,'2026-03-09'),
            ('2026-11-01','2026-11-03',3,'2026-11-02'),
            ('2026-09-02','2026-09-01',3,'2026-09-02'),
            ('2026-09-01','2026-02-30',3,'2026-09-02'),
            ('2026-02-30','',3,'2026-03-02'),
            ('','',3,'2026-09-02'),
            ('2026-09-01','',None,'2026-09-02'),
            ('2026-09-01','',2.5,'2026-09-02'),
            ('2026-09-01','',True,'2026-09-02'),
            ('2026-09-01','2026-09-03',0,'2026-09-02'),
            ('2026-09-01','2026-09-01',1,'2026-09-01'),
        ]
        expected=[]
        for start,end,days,today in cases:
            result=_forecast_stage(start,end,days,date.fromisoformat(today))
            expected.append({**{k:result[k] for k in ('key','label','day','days')},
                             'start':result['launch_date'],'end':result['end_date']})
        for tz in ('Asia/Shanghai','America/New_York','UTC'):
            with self.subTest(timezone=tz):
                actual=self.js(json.dumps(cases)+'.map(([launchDate,endDate,days,today])=>m.launchStage({launchDate,endDate,days},today))', tz)
                self.assertEqual(actual, expected)

    def test_shared_small_boundary_cases(self):
        cases=[('2026-09-01','2026-09-03',day) for day in ('2026-08-31','2026-09-01','2026-09-03','2026-09-04')]
        cases += [('2026-09-01','2026-09-01','2026-09-01'),('2026-09-02','2026-09-01','2026-09-02'),
                  ('2026-03-07','2026-03-10','2026-03-09'),('2026-09-01','','2026-09-02'),
                  ('2026-02-30','2026-03-03','2026-03-02')]
        expected=[{k:v for k,v in _small_order_stage(start,end,date.fromisoformat(today)).items()
                   if k in ('key','label','day','days')} for start,end,today in cases]
        for tz in ('Asia/Shanghai','America/New_York'):
            self.assertEqual(self.js(json.dumps(cases)+'.map(([smallStartDate,smallEndDate,today])=>m.smallStage({smallStartDate,smallEndDate},today))',tz),expected)

    def test_structured_issues_are_independent_of_messages(self):
        issues=[{'code':code,'message':'任意修改后的展示文案'} for code in
                ('COMPLETED_DAYS_MISSING','COMPLETED_DAYS_INVALID','LAUNCH_DAYS_INVALID','ACTUAL_START_MISMATCH','UNRECOGNIZED_SOURCE_ERROR')]
        self.assertEqual([r['code'] for r in self.js('m.sourceBlockingIssues('+json.dumps(issues)+',[],true)')], ['UNRECOGNIZED_SOURCE_ERROR'])
        self.assertEqual([r['code'] for r in self.js('m.sourceBlockingIssues('+json.dumps(issues)+',[],false)')],
                         ['LAUNCH_DAYS_INVALID','ACTUAL_START_MISMATCH','UNRECOGNIZED_SOURCE_ERROR'])
        self.assertEqual(self.js("m.sourceBlockingIssues(undefined,['总小订缺失或不大于0'],true)[0].code"),'LEGACY_SOURCE_ERROR')

    def test_python_issue_codes_keep_dates_and_display_compatibility(self):
        target={'launch_date':'2026-09-01','days':3,'stage':'active'}
        profile={'days':[{'date':'2026-09-01','gross':None}]}
        issues=_profile_issues(target,profile,date(2026,9,3))
        self.assertEqual({r['code'] for r in issues},{'COMPLETED_DAYS_MISSING','COMPLETED_DAYS_INVALID'})
        self.assertEqual(issues[0]['dates'],['2026-09-02'])
        self.assertEqual(issues[1]['details'],[{'date':'2026-09-01','fields':['gross']}])
        self.assertEqual(_profile_hard_errors(target,profile,date(2026,9,3)),[r['message'] for r in issues])

    def test_live_rows_are_rechecked_after_changing_window(self):
        rows=[{'date':'2026-09-01','gross':10,'small_to_big':2,'direct':8},
              {'date':'2026-09-02','gross':None},
              {'date':'2026-09-03','gross':10,'small_to_big':8,'direct':8}]
        self.assertEqual(self.js('m.launchRowIssues('+json.dumps(rows[:1])+')'),[])
        self.assertEqual([r['code'] for r in self.js('m.launchRowIssues('+json.dumps(rows)+')')],['GROSS_INVALID','COMPONENTS_INCONSISTENT'])
        self.assertEqual([r['code'] for r in self.js('m.launchRowIssues('+json.dumps(rows)+',true)')],['GROSS_INVALID'])

    def test_extracted_terminal_arithmetic(self):
        args={'rawDataError':False,'endedComplete':False,'componentsReady':True,'hasSmall':True,
              'small':1000,'baseConversion':.4,'baseShare':.2,'directD1':30,'d1Ratio':.1,
              'actualSmall':60,'actualDirect':20,'actualGross':80,'anchorSmall':100,'anchorDirect':50,
              'historyComplete':True,'d1Unavailable':False,'effectiveDays':2,'smallCompletion':.25,'directCompletion':.2}
        for changes,expected in [({},(400,100,500)),({'anchorSmall':450},(450,100,550)),
                                 ({'hasSmall':False,'anchorSmall':0},(0,300,300)),
                                 ({'endedComplete':True},(60,20,80))]:
            result=self.js('m.launchParameterTerminal('+json.dumps({**args,**changes})+')')
            self.assertEqual((result['small'],result['direct'],result['gross']),expected)
        result=self.js('m.launchProgressTerminal('+json.dumps(args)+')')
        self.assertEqual((result['small'],result['direct'],result['gross']),(400,250,650))
        for method in ('launchParameterTerminal','launchProgressTerminal'):
            self.assertFalse(self.js('m.'+method+'('+json.dumps({**args,'rawDataError':True})+').available'))

    def test_dashboard_no_longer_branches_on_error_prose(self):
        script=(ROOT/'templates/dashboard.js').read_text(encoding='utf-8')
        self.assertNotIn("startsWith('已结束日期缺少真实数据",script)
        self.assertNotIn("item==='无法按绝对日期判断首销阶段'",script)
        self.assertIn('ForecastMath.launchStage(target,todayIso())',script)
        self.assertIn('ForecastMath.smallStage(target,today())',script)
        self.assertIn('ForecastMath.launchParameterTerminal(',script)
        self.assertIn('ForecastMath.launchProgressTerminal(',script)

    def test_progress_terminal_rejects_invalid_completion_without_infinity(self):
        args = dict(rawDataError=False, historyComplete=True, endedComplete=False,
                    d1Unavailable=False, componentsReady=True, effectiveDays=2,
                    hasSmall=True, anchorSmall=100, anchorDirect=50,
                    smallCompletion=.25, directCompletion=.2,
                    actualSmall=100, actualDirect=50, actualGross=150)
        for field in ('smallCompletion', 'directCompletion'):
            for value in (None, False, '', 0, -1, 1.2):
                result = self.js('m.launchProgressTerminal('+json.dumps({**args, field:value})+')')
                self.assertFalse(result['available'], (field, value))
                self.assertEqual(result['gross'], 0)
        args.update(endedComplete=True, smallCompletion=None, directCompletion=None)
        result = self.js('m.launchProgressTerminal('+json.dumps(args)+')')
        self.assertTrue(result['available'])
        self.assertEqual(result['gross'], 150)
        args.update(endedComplete=False, hasSmall=False, anchorSmall=0, directCompletion=.2)
        self.assertTrue(self.js('m.launchProgressTerminal('+json.dumps(args)+').available'))

    def test_manual_completion_empty_restores_reference_invalid_never_falls_back(self):
        for value in ('0', '-10', '120', 'Infinity', 'abc'):
            self.assertIsNone(self.js('m.launchCompletion(.25,'+json.dumps(value)+',true)'))
        self.assertEqual(self.js("m.launchCompletion(.25,'',true)"), .25)
        self.assertEqual(self.js("m.launchCompletion(.25,'120',false)"), .25)
        self.assertEqual(self.js("m.launchCompletion(.25,'100',true)"), 1)
        self.assertEqual(self.js("m.launchCompletion(.25,'0.1',true)"), .001)
