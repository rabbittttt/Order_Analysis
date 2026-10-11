// Formal main.py output only. Scenario changes are isolated in browser memory.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'small',forecastView:'evidence'});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  for(const ongoing of [false,true]){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({ongoing})=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-06';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const same=value=>String(value||'').replace(/\s/g,'')==='问界M92026款';
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:true,small_start_date:'2026-09-01',small_end_date:ongoing?'2026-09-08':'2026-09-05',small_days:ongoing?8:5,
        launch_date:ongoing?'2026-09-09':'2026-09-06',end_date:'2026-09-13',days:ongoing?5:8,
        small:100,hard_errors:[],validation_issues:[],data_error:false
       });
       data.small_order_history=(data.small_order_history||[]).filter(item=>!same(item.model)&&!same(item.generation));
       for(const profile of data.actuals)if(same(profile.model))for(const item of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(item,{
        small_daily_days:[{date:'2026-09-01',orders:10},{date:'2026-09-03',orders:40},{date:'2026-09-04',orders:20}],
        small_hourly_days:[],total_small:100,hard_errors:[],validation_issues:[],data_error:false
       });
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{ongoing});
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._smallForecastResult);
   for(const control of ['workday','weekend','holiday']){
    const input=page.locator(`[data-bridge-stage="small"] [data-bridge-control="${control}"]`);
    await input.fill('1');await input.dispatchEvent('change');
   }
   const result=await page.locator('.forecast-workspace').evaluate(r=>r._smallForecastResult);
   assert.deepEqual(result.rows.map(r=>[r.date,r.orders]),[['2026-09-01',10],['2026-09-03',40],['2026-09-04',20]]);
   assert.equal(result.total,ongoing?null:100);
   assert.equal(Boolean(result.error),ongoing);
   const cells=async selector=>page.locator(selector+' tbody tr').filter({hasText:'问界 M9 2026款 · 真实'}).first().locator('td').allTextContents();
   const daily=await cells('[data-small-daily-reference-chart]');
   assert.deepEqual(daily.slice(0,5),['100%','—','400%','200%','—']);
   const slope=await cells('[data-small-slope-reference-chart]');
   assert.deepEqual(slope.slice(0,5),['—','—','—','-50.0%','—']);
   if(!ongoing){
    const cumulative=await cells('[data-small-reference-chart]');
    assert.deepEqual(cumulative,['10%','—','—','—','—']);
   }else assert((await page.locator('[data-small-error]').innerText()).includes('2026-09-02'));
   const labels=await page.locator('[data-small-daily-reference-chart] circle[aria-label]').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('aria-label')).filter(s=>s.includes('问界 M9 2026款 · 真实')));
   assert(labels.some(s=>s.includes('D3')&&s.includes('400%')));
   assert(!labels.some(s=>s.includes('D2')));
   console.log('PASS '+(ongoing?'ongoing gaps remain blocked':'ended known total retained')+'; daily/cumulative/slope and SVG use actual calendar positions');
   await context.close();
  }
  assert.deepEqual(errors,[]);console.log('PASS no browser errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
