"""Cross-stage baselines must remove the source stage's calendar effect."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class StageCalendarWiringTests(unittest.TestCase):
    def baseline(self, launch_factor, steady_factor):
        setup = r'''
const fs=require('fs'),math=require('./templates/forecast-math.js');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const lines=source.split('\n'),line=marker=>lines.find(text=>text.includes(marker));
const target={launchDate:'2026-01-01',endDate:'2026-01-03',steadyStartDate:'2026-01-04'};
const rows=[1,2,3].map(day=>({date:'2026-01-0'+day,gross:100,direct:80,lock:50}));
const launchProfile={days:rows},projectedRows=rows,today='2026-01-04';
const calendar=()=>({type:'weekend'});
const context={calendarType:calendar,factors:stage=>({weekend:stage==='launch'?LAUNCH_FACTOR:STEADY_FACTOR})};
const factor=day=>context.factors('steady')[calendar(day,0).type]||1;
const calculate=new Function('window','context','calendar','target','factor','launchProfile','projectedRows','today',
 [line('const launchCalendarFactor=')||'',line('const projectedBaseline='),line('const launchBaseline=')].join('\n')+
 ';return {actual:launchBaseline,projected:projectedBaseline};');
console.log(JSON.stringify(calculate({ForecastMath:math},context,calendar,target,factor,launchProfile,projectedRows,today)));
'''
        setup = setup.replace('LAUNCH_FACTOR', str(launch_factor)).replace('STEADY_FACTOR', str(steady_factor))
        result = subprocess.run(['node', '-e', setup], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_actual_and_projected_launch_use_launch_calendar(self):
        result = self.baseline(2, 4)
        for kind in ('actual', 'projected'):
            with self.subTest(kind=kind):
                self.assertTrue(result[kind]['available'])
                self.assertEqual(result[kind]['level'], 20)  # 80 / launch 2 * lock rate .5
                self.assertEqual(result[kind]['curve'], [40, 40, 40])

    def test_steady_calendar_does_not_rewrite_launch_baseline(self):
        self.assertEqual(self.baseline(2, 4), self.baseline(2, 5))

    def test_launch_calendar_control_changes_both_upstream_paths(self):
        first, second = self.baseline(1, 4), self.baseline(2, 4)
        for kind in ('actual', 'projected'):
            self.assertEqual(first[kind]['level'], 40)
            self.assertEqual(second[kind]['level'], 20)

    def test_identical_stage_factors_preserve_previous_result(self):
        result = self.baseline(1.15, 1.15)
        for kind in ('actual', 'projected'):
            self.assertAlmostEqual(result[kind]['level'], 80 / 1.15 * .5)
