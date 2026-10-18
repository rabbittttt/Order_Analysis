// Use the formal main output; inject isolated evidence, never write test pages.
const path=require('path'),assert=require('assert'),fs=require('fs'),{pathToFileURL}=require('url'),{execFileSync}=require('child_process');
const project=path.resolve(__dirname,'../../..'),root=path.resolve(__dirname,'..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const check=(name,value)=>{assert(value,name);checks++;console.log('PASS '+name)};
 const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 const artifact=process.env.AUDIT_ARTIFACT_DIR;if(artifact)fs.mkdirSync(artifact,{recursive:true});
 try{
  for(const mode of ['zero','unknown','positive','excess','daily']){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({mode})=>{
    const parse=JSON.parse;JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-30';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const name='问界 M9 2026款',same=v=>String(v||'').replace(/\s/g,'')===name.replace(/\s/g,'');
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:true,launch_date:'2026-09-28',end_date:'2026-09-29',days:2,
        small:10000,hard_errors:[],validation_issues:[],data_error:false
       });
       for(const item of data.history)if(same(item.generation||item.model)||same(item.model))Object.assign(item,{
        launch_date:'2026-09-28',end_date:'2026-09-29',days:2,gross:200,
        lock:mode==='unknown'?null:mode==='positive'?80:mode==='excess'?201:0,
        lock_rate:mode==='unknown'?null:0,terminal_available:true
       });
       for(const profile of data.actuals)if(same(profile.model))
        for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
         days:[28,29].map((day,i)=>({date:'2026-09-'+day,day:'D'+(i+1),gross:100,
           small_to_big:40,direct:60,lock:mode==='daily'?10:null})),
         hourly_days:[],hard_errors:[],validation_issues:[],data_error:false
        });
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{mode});
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   const url=new URL(base);url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'sales_forecast',forecastStage:'launch',forecastView:'result'});
   await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
   const result=await page.locator('.forecast-workspace').evaluate(root=>JSON.parse(JSON.stringify(root._forecastComparison))),expected={zero:0,unknown:null,positive:80,excess:null,daily:20}[mode];
   // JSON serializes unavailable NaN to null; real zero must stay numeric.
   for(const method of ['parameter','progress']){
    check(mode+' '+method+' retains actual gross',result.scenarios[method].gross===200);
    check(mode+' '+method+' lock terminal',Object.is(result.scenarios[method].lock,expected));
   }
   const text=await page.locator('[data-forecast-value$="-lock"]').allTextContents();
   check(mode+' two lock metrics rendered',text.length===2);
   check(mode+' visible lock matches confirmed value',text.every(value=>value===(expected===null?'—':String(expected))));
   check(mode+' no NaN/Infinity in cards',!text.some(value=>/NaN|Infinity/.test(value)));
   if(mode==='zero'){
    check('confirmed zero is visible',await page.locator('[data-forecast-value="parameter-lock"]').innerText()==='0');
    if(artifact)await page.screenshot({path:path.join(artifact,'confirmed-zero-lock.png'),fullPage:true});
   }
   await context.close();
  }
  const fixture=execFileSync(process.env.PYTHON_EXE||'python',['-c',
   "import json;from tests.test_audit_20261019 import SkuPeriodAlignmentTests; t=SkuPeriodAlignmentTests(); scenarios={};\ntry:\n for key,periods in [('shifted',['26WK02','26WK03']),('cumulative_only',['26WK02','26WK03','26WK04']),('share_only',['26WK01','26WK02'])]:\n  scenarios[key]=t.build(['26WK01','26WK02','26WK03'],periods)[0]\n print(json.dumps(scenarios,ensure_ascii=False))\nfinally:t.doCleanups()"
  ],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});
  const views=JSON.parse(fixture);
  for(const mode of Object.keys(views)){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({view})=>{
    const parse=JSON.parse;JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.module_id==='sku'&&data.views)data.views={week:view};Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{view:views[mode]});
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   await page.goto(base.href);await page.waitForFunction(()=>document.querySelector('#subjectSelect option'));
   const subject=await page.evaluate(()=>window.DASHBOARD_DATA.subjects.find(s=>s.modules.includes('sku')));
   assert(subject,'formal output needs a SKU subject');
   const url=new URL(base);url.search=new URLSearchParams({subject:subject.id,module:'sku',grain:'week'});
   await page.goto(url.href);await page.waitForSelector('.heatmap');
   const metrics=await page.locator('.kpi').evaluateAll(nodes=>Object.fromEntries(nodes.map(node=>[node.querySelector('span').textContent,node.querySelector('strong').textContent])));
   check(mode+' active SKU',metrics['有效SKU']===(mode==='cumulative_only'?'—':'1'));
   check(mode+' TOP3',metrics['TOP3累计']===(mode==='share_only'?'—':mode==='cumulative_only'?'95':'90'));
   if(mode==='share_only')check('missing cumulative week is not 0%',await page.locator('.heatmap [title="该周期未提供累计锁单占比"]').count()===2);
   if(mode==='cumulative_only')check('missing SKU week is not a zero tail',await page.locator('.trend [title="该周期数据未提供"]').count()===1);
   check(mode+' no nonfinite output',!/NaN|Infinity/.test(await page.locator('#page').innerText()));
   for(const width of [1440,768,390]){
    await page.setViewportSize({width,height:1000});
    check(mode+' '+width+' no page overflow',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   }
   if(artifact)await page.screenshot({path:path.join(artifact,'sku-'+mode+'.png'),fullPage:true});
   await context.close();
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
