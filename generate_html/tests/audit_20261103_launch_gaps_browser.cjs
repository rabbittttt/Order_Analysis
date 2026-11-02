// Exercise the formal main page; all example facts live in isolated browser memory.
const assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'sales_forecast',forecastStage:'launch',forecastView:'result'});
const cases=[
 {name:'middle',gross:[100,null,300],locks:[10,null,90],cumulative:[100,null,null],rate:null,known:400},
 {name:'first',gross:[null,200,300],locks:[null,20,30],cumulative:[null,null,null],rate:null,known:500},
 {name:'zero',gross:[100,0,300],locks:[10,0,90],cumulative:[100,100,400],rate:.25,known:400},
 {name:'complete',gross:[100,200,300],locks:[10,20,30],cumulative:[100,300,600],rate:.1,known:600},
 {name:'missing-lock',gross:[100,200,300],locks:[10,null,30],cumulative:[100,300,600],rate:null,known:600}
];
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 try{
  for(const scenario of cases){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(scenario=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-05';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const name='问界 M9 2026款',same=v=>String(v||'').replace(/\s/g,'')===name.replace(/\s/g,'');
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:true,small:1000,small_start_date:'2026-08-28',small_end_date:'2026-08-31',small_days:4,
        launch_date:'2026-09-01',end_date:'2026-09-03',days:3,steady_start_date:'2026-09-04',
        hard_errors:[],validation_issues:[],data_error:false,data_missing:false
       });
       data.history=[];data.small_order_history=[];
       const days=scenario.gross.map((gross,index)=>({date:'2026-09-0'+(index+1),day:index+1,gross,
        small_to_big:gross===null?null:gross*.2,direct:gross===null?null:gross*.8,lock:scenario.locks[index]}));
       for(const profile of data.actuals)if(same(profile.model))for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
        launch_date:'2026-09-01',days,hourly_days:[],small_daily_days:[],small_hourly_days:[],cancel_days:[],
        day_source:{file:'隔离回归.xlsx',sheet:'首销三日'},hard_errors:[],validation_issues:[],data_error:false,data_missing:false
       });
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },scenario);
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
   await page.locator('[data-forecast-weekly="progress"]').locator('..').locator('summary').click();
   const current=await page.locator('.forecast-workspace').evaluate(root=>({
    rows:root._forecastComparison.rows.map(row=>({day:row.day,daily:row.daily_gross,cumulative:row.cumulative_gross})),
    rate:Number.isFinite(root._forecastComparison.actualRates.lock_rate)?root._forecastComparison.actualRates.lock_rate:null,
    weekly:root.querySelector('[data-forecast-weekly="progress"]').innerText,
    total:root.querySelector('[data-forecast-weekly="progress"] strong')?.textContent
   }));
   assert.deepEqual(current.rows.map(row=>String(row.day).replace(/^D/,'')),['1','2','3'],scenario.name+' calendar positions');
   assert.deepEqual(current.rows.map(row=>row.daily),scenario.gross,scenario.name+' daily facts');
   assert.deepEqual(current.rows.map(row=>row.cumulative),scenario.cumulative,scenario.name+' cumulative facts');
   assert.equal(current.rate,scenario.rate,scenario.name+' real lock ratio');checks+=2;
   if(scenario.gross.includes(null)){
    assert.equal(current.total,'—');assert.match(current.weekly,new RegExp('已知'+scenario.known));
    assert.match(current.weekly,/缺失1天/);assert.doesNotMatch(current.weekly,/全部真实/);
   }else assert.equal(current.total,String(scenario.known));
   checks++;assert.deepEqual(errors,[]);await context.close();
  }
  console.log(JSON.stringify({passed:true,checks,pageErrors:0}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
