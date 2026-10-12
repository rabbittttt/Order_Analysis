"""Source-mix correction must preserve daily gross, terminals and frozen days."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class LaunchSourceMixTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run(['node', '-e',
            "const m=require('./templates/forecast-math.js'),assert=require('assert');"+code],
            cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout or 'null')

    def test_before_launch_structure_varies_but_totals_match(self):
        self.run_js("""
const gross=[100,100,100,100,100],baselineDirect=[60,60,60,60,60];
const r=m.splitLaunchSources({gross,baselineDirect,smallShape:[.4,.3,.15,.1,.05],
directShape:[.05,.1,.15,.3,.4],smallTotal:200,directTotal:300,mobility:[1,1,1,1,1]});
assert.equal(r.direct.reduce((s,v)=>s+v,0),300);
assert(r.direct[0]<r.direct[4]);assert.notEqual(r.direct[0],60);
r.direct.forEach((v,i)=>assert(Number.isInteger(v)&&v>=0&&v<=gross[i]));
assert.deepEqual(baselineDirect,[60,60,60,60,60]);assert.deepEqual(r.warnings,[]);
""")

    def test_progressive_bridge_and_locked_snapshot(self):
        self.run_js("""
const baselineDirect=[60,50,40,30,20],gross=[100,100,100,100,100];
const r=m.splitLaunchSources({gross,baselineDirect,smallShape:[.4,.3,.15,.1,.05],
directShape:[.05,.1,.15,.3,.4],smallTotal:300,directTotal:200,mobility:[0,0,.5,1,1]});
assert.equal(r.direct[0],60);assert.equal(r.direct[1],50);
assert.equal(r.direct.reduce((a,b)=>a+b,0),200);
assert.notDeepEqual(r.direct,baselineDirect);
""")

    def test_missing_shapes_and_zero_components_do_not_invent_trends(self):
        self.run_js("""
const base={gross:[100,100],baselineDirect:[60,60],smallShape:[],directShape:[],
smallTotal:80,directTotal:120,mobility:[1,1]};
assert.deepEqual(m.splitLaunchSources(base).direct,base.baselineDirect);
assert(m.splitLaunchSources(base).warnings[0].includes('曲线不足'));
assert.deepEqual(m.splitLaunchSources({...base,smallTotal:0,baselineDirect:[100,100]}).direct,[100,100]);
assert.deepEqual(m.splitLaunchSources({...base,smallShape:[.5,.5],directShape:[.5,.5]}).direct,[60,60]);
""")

    def test_capacity_integer_terminal_and_edge_cases(self):
        self.run_js("""
let seed=19;const rand=()=>((seed=(seed*1664525+1013904223)>>>0)/4294967296);
for(let test=0;test<300;test++){
const n=1+Math.floor(rand()*60),gross=Array.from({length:n},()=>Math.floor(rand()*500));
const baselineDirect=gross.map(v=>Math.floor(rand()*(v+1)));
const mobility=gross.map(()=>rand()<.2?0:rand()*3);
const r=m.splitLaunchSources({gross,baselineDirect,mobility,smallTotal:200,directTotal:300,
smallShape:gross.map(()=>rand()),directShape:gross.map(()=>rand())});
assert.equal(r.direct.reduce((a,b)=>a+b,0),baselineDirect.reduce((a,b)=>a+b,0));
r.direct.forEach((v,i)=>{assert(Number.isInteger(v)&&v>=0&&v<=gross[i]);if(!mobility[i])assert.equal(v,baselineDirect[i]);});
assert.deepEqual(r.warnings,[]);
}
""")

    def test_reference_calendar_stretch_and_invalid_weight_renormalization(self):
        self.run_js("""
const item={days:8,launch_date:'2026-01-01',end_date:'2026-01-08',
daily_orders:[100,100,200,100,100,100,100,100],
daily_small:[50,50,100,50,50,50,50,50],daily_direct:[50,50,100,50,50,50,50,50]};
const shape=items=>m.launchComponentShape(items,'daily_small',12,'2026-10-12',(r,i)=>i===2?2:1);
const good=shape([{item,weight:30}]);
assert.equal(good.length,12);
good.forEach((v,i)=>assert(Math.abs(v-([0,1,10,11].includes(i)?.125:.0625))<1e-9));
for(const bad of [{...item,end_date:'2026-10-12'}, {...item,daily_direct:[null]},
{...item,daily_small:[10,10,10,10,10,10,10,10]}]){
assert.deepEqual(shape([{item:bad,weight:70},{item,weight:30}]),good);
}
assert.deepEqual(shape([{item,weight:0}]),[]);
""")

    def test_page_wiring_keeps_actual_and_partial_rows_outside_split(self):
        self.run_js("""
const fs=require('fs'),source=fs.readFileSync('templates/dashboard.js','utf8');
const code=source.slice(source.indexOf('const recomposeSources='),source.indexOf('const dailyShape=',source.indexOf('const recomposeSources=')));
const item={days:5,launch_date:'2026-01-01',end_date:'2026-01-05',
daily_orders:[100,100,100,100,100],daily_small:[80,70,50,30,20],daily_direct:[20,30,50,70,80]};
const run=new Function('window','slotWeight','todayIso','historicalFactor','bridgeSettings','root',
code+';return recomposeSources;')({ForecastMath:m},()=>1,()=> '2026-10-12',()=>1,()=>({weights:[0,.5,1]}),{});
for(const method of ['progress','parameter']){
const rows=[{index:0,gross:100,small_to_big:80,direct:20,actual:true},
{index:1,gross:100,small_to_big:70,direct:30,partial:true},
...[2,3,4].map(index=>({index,gross:100,small_to_big:50,direct:50}))];
const before=JSON.parse(JSON.stringify(rows)),scenario={small:300,direct:200,bridgeWarnings:[]};
const refs=Object.fromEntries(['small_progress','direct_progress','conversion','direct_share'].map(k=>[k,[item]]));
run(rows,scenario,method,refs,{days:5},before[0],[{index:2},{index:3},{index:4}]);
assert.deepEqual(rows.slice(0,3),before.slice(0,3));
assert.deepEqual(rows.map(r=>r.gross),before.map(r=>r.gross));
assert.equal(rows.reduce((s,r)=>s+r.direct,0),200);
assert.equal(rows.reduce((s,r)=>s+r.small_to_big,0),300);
assert(rows[3].direct<rows[4].direct);
}
""")
