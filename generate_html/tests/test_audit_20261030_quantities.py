"""Oversized editable quantities must not cause unbounded apportionment loops."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastQuantityLimitsTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(['node', '-e', 'const m=require(' + json.dumps(str(ROOT / 'templates/forecast-math.js')) + ');' + script], capture_output=True, encoding='utf-8', timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_editable_count_validation(self):
        result = self.run_js("console.log(JSON.stringify(['1e40','9007199254740992','2.5','-1','Infinity',true].map(v=>m.launchSmallInput(v))))")
        for row in result:
            self.assertTrue(row['error'])
            self.assertIsNone(row['value'])

    def test_blank_unknown_and_real_zero(self):
        result = self.run_js("console.log(JSON.stringify(['',null,0,'0',1000,'1e3',Number.MAX_SAFE_INTEGER].map(v=>m.launchSmallInput(v))))")
        self.assertEqual([row['value'] for row in result], [None, None, 0, 0, 1000, 1000, 9007199254740991])
        self.assertTrue(all(not row['error'] for row in result))

    def test_extreme_remainder_returns_without_looping(self):
        # Old code needs 140,737,488,355,328 iterations for this input.
        self.assertEqual(self.run_js("console.log(JSON.stringify(m.distributeInteger(1e30,Array.from({length:7},(_,i)=>1/(i+1)))))"), [])

    def test_allocator_rejects_unsafe_total(self):
        result = self.run_js("console.log(JSON.stringify(m.anchoredAllocate({remaining:1e30,shapes:[1,.5,.3],factors:[1,1,1],weights:[1,1,1]})))")
        self.assertTrue(result['error'])
        self.assertEqual(result['values'], [])

    def test_parameter_rejects_unsafe_count_and_result(self):
        result = self.run_js("""
const b={rawDataError:false,endedComplete:false,componentsReady:true,hasSmall:true,small:1000,baseConversion:.5,baseShare:.5,actualSmall:0,actualDirect:0,actualGross:0,anchorSmall:0,anchorDirect:0};
console.log(JSON.stringify([m.launchParameterTerminal(b),m.launchParameterTerminal({...b,small:1e40}),m.launchParameterTerminal({...b,small:Number.MAX_SAFE_INTEGER,baseConversion:1})]));
""")
        self.assertTrue(result[0]['available'])
        self.assertEqual(result[0]['gross'], 1000)
        self.assertFalse(result[1]['available'])
        self.assertFalse(result[2]['available'])
        self.assertTrue(result[2]['quantityError'])

    def test_progress_overflow_preserves_ended_actuals(self):
        result = self.run_js("""
const b={rawDataError:false,historyComplete:true,endedComplete:false,d1Unavailable:false,componentsReady:true,effectiveDays:1,hasSmall:true,smallCompletion:1e-30,directCompletion:1e-30,actualSmall:20,actualDirect:80,actualGross:100,anchorSmall:20,anchorDirect:80};
console.log(JSON.stringify([m.launchProgressTerminal(b),m.launchProgressTerminal({...b,endedComplete:true})]));
""")
        self.assertFalse(result[0]['available'])
        self.assertTrue(result[0]['quantityError'])
        self.assertTrue(result[1]['available'])
        self.assertEqual(result[1]['gross'], 100)

    def test_normal_distribution_unchanged(self):
        self.assertTrue(self.run_js("""
function old(total,w){const n=Math.round(total),sum=w.reduce((a,b)=>a+b,0),q=w.map(v=>n*(sum?v/sum:1/w.length)),v=q.map(Math.floor),r=n-v.reduce((a,b)=>a+b,0),o=q.map((x,i)=>({i,f:x-v[i]})).sort((a,b)=>b.f-a.f||a.i-b.i);for(let i=0;i<r;i++)v[o[i%o.length].i]++;return v;}
for(let seed=1;seed<=1000;seed++){const n=(seed*713)%1000000,w=Array.from({length:seed%90+1},(_,i)=>((seed*17+i*31)%97)/97),v=m.distributeInteger(n,w);if(JSON.stringify(v)!==JSON.stringify(old(n,w))||v.reduce((a,b)=>a+b,0)!==n)throw Error('changed '+seed);}
console.log(JSON.stringify(true));
"""))

    def test_safe_boundary_exact_total(self):
        self.assertTrue(self.run_js("""
for(let count=1;count<90;count++){const n=Number.MAX_SAFE_INTEGER,w=Array.from({length:count},(_,i)=>1/(i+1)),v=m.distributeInteger(n,w);if(v.reduce((a,b)=>a+b,0)!==n||!v.every(x=>Number.isSafeInteger(x)&&x>=0))throw Error('unsafe sum '+count);}
console.log(JSON.stringify(true));
"""))
