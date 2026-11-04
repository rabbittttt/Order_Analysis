// Render production-reader fixtures in the formal main.py page, without editing HTML or inputs.
const assert=require('node:assert/strict'),path=require('node:path');
const {execFileSync}=require('node:child_process'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const fixture=JSON.parse(execFileSync(process.env.PYTHON_BINARY||'python',['-X','utf8','-B','-c',String.raw`
import json
from tests.test_audit_20261103_launch_alias_zero import LaunchAliasZeroTests, MISSING_ROW
t=LaunchAliasZeroTests(); result={}
try:
    for grain in ('day','week'):
        for name, overrides, expected in (
          ('zero',{'累计小订转化率':[0,0,0],'累计小转大率':[.2,.3,.4]},0),
          ('legacy',{'累计小订转化率':MISSING_ROW,'累计小转大率':[.2,.3,.4]},40),
          ('positive',{'累计小转大率':[.7,.8,.9]},30)):
            phase=t.phase(overrides,grain)
            result[name+'_'+grain]={'grain':grain,'expected':expected,
                'view':{'periods':['fixture'],'default_period':'fixture','pages':{'fixture':phase['page']}}}
    print(json.dumps(result,ensure_ascii=False))
finally:t.doCleanups()
`],{cwd:path.resolve(__dirname,'..'),encoding:'utf8'}));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 try{
  for(const [name,scenario] of Object.entries(fixture)){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({view,grain})=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=v=>{if(!v||typeof v!=='object'||seen.has(v))return;seen.add(v);
      if(v.module_id==='launch_rhythm'&&v.views)v.views={[grain]:view};
      Object.values(v).forEach(visit);
     };visit(value);return value;
    };
   },scenario);
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
   url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'launch_rhythm',grain:scenario.grain});
   await page.goto(url.href);await page.waitForSelector('[data-launch-rate="smallRate"]');
   assert.equal(await page.locator('.kpi').nth(2).locator('strong').textContent(),String(scenario.expected),name);
   const values=await page.locator('[data-launch-rate="smallRate"] [data-launch-rate-point]').evaluateAll(nodes=>nodes.map(node=>Number(node.dataset.value)));
   const expected=name.startsWith('zero')?[0,0,0]:name.startsWith('legacy')?[.2,.3,.4]:[.1,.2,.3];
   assert.deepEqual(values,expected,name+' curve must keep original values');
   assert.equal(await page.locator('[data-launch-rate-label="smallRate"]').count(),3);
   checks+=2;assert.deepEqual(errors,[]);await context.close();
  }
  console.log(JSON.stringify({passed:true,checks,pageErrors:0}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
