import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class SmallForecastRuntimeTests(unittest.TestCase):
    def test_active_small_initializes_and_predicts_without_current_final_total(self):
        script = r'''
const fs=require('fs');
const {smallReferenceScore,distributeInteger,completedSmallOrderDays,anchoredAllocate}=require(MATH);
const source=fs.readFileSync(DASHBOARD,'utf8');
const start=source.indexOf('  function bindSmallOrderForecast(');
const end=source.indexOf('  function bindSteadyForecast(',start);
const nodes=new Map(),node=key=>{if(!nodes.has(key))nodes.set(key,{value:'',textContent:'',innerHTML:'',hidden:true});return nodes.get(key)};
const select={value:'',options:[{value:'ref',dataset:{model:'reference'}}]},weight={value:'100'};
const workspace={querySelector:node,querySelectorAll:key=>key==='[data-small-ref]'?[select]:key==='[data-small-weight]'?[weight]:[]};
const root={querySelector:()=>workspace};
const status={};
const setForecastStageSummary=(root,id,label,text)=>{status[id]={label,text}};
const esc=String,fmt=String,renderLifecycleBars=()=>'',renderLifecycleLineChart=()=>'',renderLifecycleScorePage=()=>'';
const rebasedForecastCompletion=()=>({value:.5}),rebasedForecastCompletionCurve=()=>[.25,.5,.75,1];
const window={ForecastMath:require(MATH)};console.warn=()=>{};
eval(source.slice(source.indexOf('  function createForecastEstimateLogger('),source.lastIndexOf('  init();')));
eval(source.slice(start,end));
const target={name:'current',smallStartDate:'2026-09-01',smallEndDate:'2026-09-04',smallDays:4,tier:'SUV',energy:'增程',node:'年度换代'};
const reference={model:'reference',event_id:'ref',total:1000,days:4,tier:'SUV',energy:'增程',node:'年度换代',small_progress:[.25,.5,.75,1]};
const actual={total_small:0,small_daily_days:[{date:'2026-09-01',orders:100},{date:'2026-09-02',orders:200},{date:'2026-09-03',orders:999}]};
const calendarType=(start,index)=>({date:new Date(Date.parse(start+'T00:00:00Z')+index*86400000).toISOString().slice(0,10),type:'workday'});
const planBridge=(stage,args)=>anchoredAllocate({...args,factors:args.dates.map(()=>1),weights:args.dates.map((_,i)=>i===0?0:i===1?.5:1)});
reference.small_start_date='2026-08-01';
bindSmallOrderForecast(root,{small_order_history:[reference]},{sameModel:(a,b)=>a===b,targetState:()=>target,findActual:()=>actual,findStageActual:()=>actual,todayIso:()=> '2026-09-03',calendarType,planBridge,factors:()=>({workday:1,weekend:1,holiday:1})});
console.log(JSON.stringify({status,total:node('[data-small-kpi="total"]').textContent,actual:node('[data-small-kpi="actual"]').textContent,error:node('[data-small-error]').textContent,hidden:node('[data-small-error]').hidden}));
'''.replace('MATH', json.dumps(str(ROOT / 'templates/forecast-math.js'))).replace('DASHBOARD', json.dumps(str(ROOT / 'templates/dashboard.js')))
        result = subprocess.run(['node','-e',script], capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        # Today's 999 is not a complete real day, but the forecast cannot be lower.
        self.assertEqual(data['total'], '1299')
        self.assertEqual(data['actual'], '300')
        self.assertTrue(data['hidden'])
        self.assertIn('D3', data['status']['small']['label'])
        self.assertNotIn('判定中', data['status']['small']['label'])
