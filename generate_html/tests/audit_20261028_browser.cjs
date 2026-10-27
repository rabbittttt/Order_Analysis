// Run against main.py output. Fixtures only alter this isolated browser context.
const assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'sales_forecast',forecastStage:'launch',forecastView:'result'});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 try{
  for(const mode of ['daily','hourly','equal','no-hourly']){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({mode})=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-02';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const name='问界 M9 2026款',same=v=>String(v||'').replace(/\s/g,'')===name.replace(/\s/g,'');
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:true,small_start_date:'2026-08-30',small_end_date:'2026-08-31',small_days:2,
        launch_date:'2026-09-01',end_date:'2026-09-03',days:3,steady_start_date:'2026-09-04',small:10000,
        hard_errors:[],validation_issues:[],data_error:false
       });
       for(const item of data.history)if(!same(item.generation||item.model))Object.assign(item,{
        launch_date:'2026-08-01',end_date:'2026-08-03',days:3,small:10000,gross:300,lock:150,lock_rate:.5,
        conversion:.015,direct_share:.5,daily_orders:[100,100,100],daily_small:[50,50,50],daily_direct:[50,50,50],
        small_progress:[1/3,2/3,1],direct_progress:[1/3,2/3,1],quality_issues:[],
        hourly_curve:Array.from({length:24},(_,i)=>(i+1)/24)
       });
       const daily=mode==='hourly'?200:800,hourly=mode==='daily'?200:800;
       const days=[{date:'2026-09-01',gross:100,small_to_big:50,direct:50,lock:25},
        {date:'2026-09-02',gross:daily,small_to_big:daily/2,direct:daily/2,lock:100}];
       const hours=mode==='no-hourly'?[]:[{date:'2026-09-02',gross:hourly,small_to_big:hourly/2,direct:hourly/2,lock:100,last_hour:23,
        hours:[{hour:23,gross:hourly,small_to_big:hourly/2,direct:hourly/2,lock:100}]}];
       for(const profile of data.actuals)if(same(profile.model))for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
        days,hourly_days:hours,total_small:10000,hard_errors:[],validation_issues:[],data_error:false,
        small_daily_days:[{date:'2026-08-30',orders:5000},{date:'2026-08-31',orders:5000}],small_hourly_days:[]
       });
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{mode});
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto(url.href);
   await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
   await page.locator('[data-forecast-input="conversion"]').evaluate(input=>{input.value='1';input.dispatchEvent(new Event('input',{bubbles:true}));});
   const state=await page.locator('.forecast-workspace').evaluate(root=>root._forecastComparison);
   for(const [method,scenario] of Object.entries(state.scenarios)){
    assert(scenario.available,mode+' '+method+' unavailable: '+JSON.stringify(scenario));
    const today=scenario.rows.find(row=>row.date==='2026-09-02');
    assert(today.gross>=800,mode+' '+method+' forgot newer snapshot');
    assert(today.small_to_big>=400&&today.direct>=400);
    assert.equal(today.actual,false);
    assert.equal(scenario.rows[0].gross,100);
    assert.equal(scenario.rows.reduce((s,row)=>s+row.gross,0),scenario.gross);
    checks++;
   }
   // With a valid hourly observation there is no extrapolation beyond 23:00.
   if(mode!=='no-hourly')assert.equal(state.scenarios.parameter.gross,900);
   assert.deepEqual(errors,[]);await context.close();
  }
  console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
