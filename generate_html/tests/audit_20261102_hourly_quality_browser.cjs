// Use main.py's generated page with isolated input; never edit original workbooks.
const assert=require('node:assert/strict'),path=require('node:path'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'sales_forecast',forecastStage:'small',forecastView:'result'});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 try{
  for(const daily of [1200,0,null]){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({daily})=>{
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
       for(const profile of data.actuals)if(same(profile.model))for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
        days:[],hourly_days:[],small_daily_days:[{date:'2026-09-01',orders:daily}],
        small_hourly_days:[{date:'2026-09-01',orders:null,last_hour:1,hourly_valid:false,
         hourly_status:'分时数据异常：小时重复',hours:[{hour:0,orders:10},{hour:1,orders:10}]}],
        total_small:0,hard_errors:[],validation_issues:[],data_error:false,data_missing:false
       });
       // A stale history must not supply missing actuals in this quality fixture.
       data.small_order_history=(data.small_order_history||[]).filter(item=>!same(item.generation||item.model));
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{daily});
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   await page.goto(url.href);
   await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._smallForecastResult);
   const result=await page.locator('.forecast-workspace').evaluate(root=>({
    ...root._smallForecastResult,
    actual:root.querySelector('[data-small-kpi="actual"]').textContent.replace(/,/g,''),
    d1:root.querySelector('[data-small-kpi="d1"]').textContent.replace(/,/g,''),
    source:root.querySelector('[data-small-source]').textContent
   }));
   assert.equal(result.stage,'d1');
   assert.equal(result.actual,daily===null?'—':String(daily),'bad hourly bucket must not replace independent daily fact');
   assert.equal(result.d1,'—');assert.equal(result.total,null);assert(result.error);
   assert.deepEqual(result.rows,[],'bad hours must not yield a forecast');
   assert.match(result.source,/分时|小时/);checks+=2;
   assert.deepEqual(errors,[]);await context.close();
  }
  console.log(JSON.stringify({passed:true,checks,pageErrors:errors.length}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
