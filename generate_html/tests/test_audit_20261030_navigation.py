"""Late asynchronous navigation must not overwrite the latest user's selection."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class NavigationOrderTests(unittest.TestCase):
    def run_js(self, body):
        script = r'''
const fs=require('fs'),assert=require('assert');
const source=fs.readFileSync('templates/dashboard.js','utf8');
const extract=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));
const state={subject:'A',module:'overview',grain:'week',period:null};
const pending=[];
const getDashboard=()=>new Promise(resolve=>pending.push(resolve));
const board=(grain,period)=>({views:{[grain]:{periods:[period],default_period:period}}});
const ensure=new Function('DATA','state','subject','moduleAvailable','getDashboard',
 extract('  async function ensureState()','  function renderSubjectSelect()')+';return ensureState;')(
 {},state,()=>({modules:['overview','sku','raw']}),()=>true,getDashboard);
''' + '\n(async()=>{\n' + body + '\n})().catch(e=>{console.error(e);process.exitCode=1});'
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_late_subject_cannot_replace_current_grain_or_period(self):
        result = self.run_js(r'''
const old=ensure();state.subject='B';const latest=ensure();
pending[1](board('week','26WK43'));await latest;
pending[0](board('day','2025-05-01'));await old;
console.log(JSON.stringify(state));
''')
        self.assertEqual((result['subject'], result['grain'], result['period']), ('B', 'week', '26WK43'))

    def test_leaving_analysis_for_raw_does_not_mutate_period(self):
        result = self.run_js(r'''
const old=ensure();state.module='raw';state.period='kept';await ensure();
pending[0](board('day','2025-05-01'));await old;
console.log(JSON.stringify(state));
''')
        self.assertEqual((result['module'], result['grain'], result['period']), ('raw', 'week', 'kept'))

    def test_returning_to_same_subject_discards_first_request(self):
        result = self.run_js(r'''
const first=ensure();state.subject='B';const middle=ensure();state.subject='A';const latest=ensure();
pending[2](board('week','26WK43'));await latest;
pending[1](board('month','25-01'));await middle;
pending[0](board('day','2025-05-01'));await first;
console.log(JSON.stringify(state));
''')
        self.assertEqual((result['subject'], result['grain'], result['period']), ('A', 'week', '26WK43'))

    def test_normal_navigation_still_uses_available_default_period(self):
        result = self.run_js(r'''
const current=ensure();pending[0](board('day','2026-10-30'));await current;
console.log(JSON.stringify(state));
''')
        self.assertEqual((result['grain'], result['period']), ('day', '2026-10-30'))

    def test_obsolete_subject_handler_does_not_redraw_or_lose_new_edits(self):
        result = self.run_js(r'''
const control={},draws=[];let editor='';
const line=source.split('\n').find(line=>line.includes('$("#subjectSelect").onchange='));
new Function('$','state','ensureState','renderAll','syncUrl',line)(
 ()=>control,state,ensure,async()=>{draws.push(state.subject);editor='default';},()=>{});
const old=control.onchange({target:{value:'A'}}),latest=control.onchange({target:{value:'B'}});
pending[1](board('week','26WK43'));await latest;editor='new user input';
pending[0](board('day','2025-05-01'));await old;
console.log(JSON.stringify({draws,editor}));
''')
        self.assertEqual(result, {'draws': ['B'], 'editor': 'new user input'})

    def test_late_filters_cannot_replace_current_period_choices(self):
        result = self.run_js(r'''
const elements=new Map();
const $=selector=>{if(!elements.has(selector))elements.set(selector,{
 dataset:{},style:{},hidden:false,innerHTML:'',value:'',closest(){return this;}
});return elements.get(selector)};
const DATA={config:{grain_labels:{day:'日',week:'周',month:'月'}}};
const render=new Function('state','$','DATA','getDashboard','sortPeriods','esc',
 extract('  async function renderFilters()','  function alignOverviewChartScrollbars()')+';return renderFilters;')(
 state,$,DATA,getDashboard,p=>p,String);
const old=render();state.subject='B';state.period='26WK43';const latest=render();
pending[1](board('week','26WK43'));await latest;
pending[0](board('day','2025-05-01'));await old;
console.log(JSON.stringify({periods:$('#periodSelect').innerHTML,grain:$('#grainSelect').innerHTML}));
''')
        self.assertIn('26WK43', result['periods'])
        self.assertNotIn('2025-05-01', result['periods'])


if __name__ == '__main__':
    unittest.main()
