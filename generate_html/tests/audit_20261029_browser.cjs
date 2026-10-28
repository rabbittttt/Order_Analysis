// Test main.py output; all example observations live only in isolated browser memory.
const assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'sales_forecast',forecastStage:'small',forecastView:'result'});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 try{
  for(const mode of ['daily','hourly','equal','unknown','zero']){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({mode})=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-01';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const name='问界 M9 2026款',same=v=>String(v||'').replace(/\s/g,'')===name.replace(/\s/g,'');
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:true,small_start_date:'2026-09-01',small_end_date:'2026-09-04',small_days:4,
        launch_date:'2026-09-05',end_date:'2026-09-07',days:3,steady_start_date:'2026-09-08',
        small_period:'未维护',small_release_start_hour:0,tier:'SUV',energy:'BEV',node:'new',
        hard_errors:[],validation_issues:[],data_error:false,data_missing:false
       });
       for(const item of data.small_order_history||[])if(!same(item.generation||item.model))Object.assign(item,{
        total:1000,total_complete:true,days:4,tier:'SUV',energy:'BEV',node:'new',
        small_start_date:'2026-08-01',small_end_date:'2026-08-04',launch_period:'未维护',
        small_progress:[.25,.5,.75,1],daily_orders:[250,250,250,250],d1_share:.25,
        small_start_hour:0,release_start_hour:0,small_hourly_curve:Array.from({length:24},(_,i)=>(i+1)/24),
        quality_issues:[],hard_errors:[],validation_issues:[]
       });
       const hourly=mode==='hourly'||mode==='equal'?1200:20;
       const daily=mode==='unknown'?null:mode==='zero'?0:mode==='hourly'?20:1200;
       const smallDaily=[{date:'2026-09-01',orders:daily}];
       const smallHours=[{date:'2026-09-01',orders:hourly,last_hour:1,
        hours:[{hour:0,orders:hourly/2},{hour:1,orders:hourly/2}]}];
       for(const profile of data.actuals)if(same(profile.model))for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
        days:[],hourly_days:[],small_daily_days:smallDaily,small_hourly_days:smallHours,
        total_small:0,hard_errors:[],validation_issues:[],data_error:false,data_missing:false
       });
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{mode});
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   await page.goto(url.href);
   await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._smallForecastResult);
   await page.locator('.forecast-workspace').evaluate(root=>{
    for(const input of root.querySelectorAll('[data-bridge-stage="small"] input[data-bridge-control]'))if(input.type==='number')input.value='1';
    root._smallForecastUpdate();
   });
   const state=await page.locator('.forecast-workspace').evaluate(root=>({
    ...root._smallForecastResult,
    actual:Number(root.querySelector('[data-small-kpi="actual"]').textContent.replace(/,/g,'')),
    d1:Number(root.querySelector('[data-small-kpi="d1"]').textContent.replace(/,/g,'')),
    source:root.querySelector('[data-small-source]').textContent,
    hourly:root.querySelector('[data-small-hourly-reference-chart]')?.textContent||''
   }));
   const observed=mode==='unknown'||mode==='zero'?20:1200;
   assert.equal(state.error,'',mode+': '+state.error);assert.equal(state.stage,'d1');
   assert.equal(state.actual,observed,mode+' incorrect actual KPI');
   assert(state.d1>=observed,mode+' D1 below observed orders');
   assert(state.total>=state.d1,mode+' terminal below D1');
   assert.equal(state.rows[0].date,'2026-09-01');
   assert.equal(state.rows[0].observed,observed);assert.equal(state.rows[0].actual,false);
   assert(state.rows.slice(1).every(row=>row.observed===undefined),mode+' today attached to future day');
   assert.equal(state.rows.reduce((sum,row)=>sum+row.orders,0),state.total);
   if(mode==='daily'){assert.equal(state.d1,1200);assert.equal(state.total,4800);assert(state.source.includes('下限'));assert(state.hourly.includes('小时归属未知'));}
   if(mode==='unknown'||mode==='zero'){assert.equal(state.d1,240);assert.equal(state.total,960);}
   if(mode==='hourly'||mode==='equal'){assert.equal(state.d1,14400);assert.equal(state.total,57600);}
   checks++;assert.deepEqual(errors,[]);await context.close();
  }
  console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
