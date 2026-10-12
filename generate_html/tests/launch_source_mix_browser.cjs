// Formal main output; scenario controls and compatibility baseline are isolated in browser memory.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'evidence'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  const root=page.locator('.forecast-workspace'),input=k=>page.locator('[data-forecast-input="'+k+'"]');
  const snapshot=async()=>{await page.waitForTimeout(200);return root.evaluate(r=>r._forecastComparison.scenarios)};
  const actual=await snapshot();
  assert(actual.parameter.rows.length&&actual.parameter.rows.every(r=>r.actual));
  const date=page.locator('[data-forecast-target="launchDate"]');
  await date.fill('2080-01-01');await date.dispatchEvent('change');
  const reference=await root.evaluate(r=>{
   const config=JSON.parse(r.getAttribute('data-forecast-config')),m=window.ForecastMath;
   return config.history.find(item=>{
    const a=m.launchComponentShape([{item,weight:1}],'daily_small',35,'2026-10-12');
    const b=m.launchComponentShape([{item,weight:1}],'daily_direct',35,'2026-10-12');
    return a.length&&b.length&&a.some((v,i)=>Math.abs(v-b[i])>.001);
   })?.model;
  });
  assert(reference,'complete nonconstant component reference');
  for(const task of ['conversion','direct_share']){
   const refs=page.locator('[data-forecast-task="'+task+'"] [data-forecast-ref]');
   await refs.nth(0).selectOption(reference);await refs.nth(1).selectOption(reference);
  }
  for(const [k,v] of [['small','10000'],['conversion','40'],['direct','60'],['d1Gross','1000']]){
   await input(k).fill(v);await input(k).dispatchEvent('change');
  }
  const changed=await snapshot(),result=changed.parameter;
  assert(result.available&&!result.bridgeError);assert.equal(result.small,4000);assert.equal(result.direct,6000);
  assert.deepEqual(result.sourceMixWarnings,[]);
  for(const [selector,field] of [['[data-forecast-d1-small]','small_to_big'],['[data-forecast-d1-direct]','direct']]){
   assert.equal(Number((await page.locator(selector).innerText()).replaceAll(',','')),result.rows[0][field]);
  }
  assert(new Set(result.rows.map(r=>r.direct_share.toFixed(3))).size>3);
  assert.equal(result.rows.at(-1).direct_share,.6);
  result.rows.forEach(r=>assert.equal(r.small_to_big+r.direct,r.daily_gross));
  // Disable only the new composition step to compare exact gross and terminal invariants.
  await page.evaluate(()=>{window.savedSplit=window.ForecastMath.splitLaunchSources;window.ForecastMath.splitLaunchSources=({baselineDirect})=>({direct:baselineDirect,warnings:[]});});
  await input('direct').dispatchEvent('input');
  const old=(await snapshot()).parameter;
  assert.deepEqual(result.rows.map(r=>r.daily_gross),old.rows.map(r=>r.daily_gross));
  assert.equal(result.gross,old.gross);assert.equal(result.small,old.small);assert.equal(result.direct,old.direct);
  assert(old.rows.every(r=>Math.abs(r.direct_share-.6)<.005));
  await page.evaluate(()=>{window.ForecastMath.splitLaunchSources=window.savedSplit;});
  await input('direct').dispatchEvent('input');
  await snapshot();
  const chart=page.locator('[data-forecast-task="direct_share"] [data-forecast-task-chart]');
  const chartRows=await chart.locator('tbody tr').allTextContents();
  assert(chartRows.some(t=>t.includes('方法二预测')&&t.includes('60.0%')));
  await chart.screenshot({path:path.join(project,'.test_outputs/launch_source_mix_after.png')});
  await input('direct').fill('55');await input('direct').dispatchEvent('input');
  assert(Math.abs((await snapshot()).parameter.rows.at(-1).direct_share-.55)<.0001);
  await page.reload();await page.waitForSelector('.forecast-workspace');
  // Fresh context avoids saved what-if inputs when checking ended actuals.
  const fresh=await browser.newPage();await fresh.goto(url.href);await fresh.waitForSelector('.forecast-workspace');
  assert.deepEqual(await fresh.locator('.forecast-workspace').evaluate(r=>r._forecastComparison.scenarios.parameter.rows),actual.parameter.rows);
  const activeContext=await browser.newContext();
  await activeContext.addInitScript(()=>{
   const parse=JSON.parse;
   JSON.parse=function(text,...args){
    const value=parse.call(this,text,...args);
    if(value?.config&&value?.subjects)value.config.forecast_as_of_date='2026-05-30';
    return value;
   };
  });
  const active=await activeContext.newPage();active.on('pageerror',e=>errors.push(e.message));
  await active.goto(url.href);await active.waitForSelector('.forecast-workspace');
  for(const task of ['small_progress','direct_progress','conversion','direct_share']){
   const refs=active.locator('[data-forecast-task="'+task+'"] [data-forecast-ref]');
   await refs.nth(0).selectOption(reference);await refs.nth(1).selectOption(reference);
  }
  for(const [k,v] of [['conversion','40'],['direct','60'],['progressSmallCompletion','20'],['progressDirectCompletion','20']]){
   await active.locator('[data-forecast-input="'+k+'"]').fill(v);
  }
  await active.waitForTimeout(250);
  const activeResult=await active.locator('.forecast-workspace').evaluate(r=>r._forecastComparison.scenarios);
  await active.evaluate(()=>{window.savedSplit=window.ForecastMath.splitLaunchSources;window.ForecastMath.splitLaunchSources=({baselineDirect})=>({direct:baselineDirect,warnings:[]});});
  await active.locator('[data-forecast-input="direct"]').dispatchEvent('input');await active.waitForTimeout(250);
  const activeOld=await active.locator('.forecast-workspace').evaluate(r=>r._forecastComparison.scenarios);
  for(const method of ['progress','parameter']){
   const a=activeResult[method],b=activeOld[method];
   assert(a.available&&!a.bridgeError);assert.deepEqual(a.sourceMixWarnings,[]);
   assert(a.rows.some(r=>r.actual)&&a.rows.some(r=>!r.actual));
   assert.deepEqual(a.rows.filter(r=>r.actual||r.partial),b.rows.filter(r=>r.actual||r.partial));
   assert.deepEqual(a.rows.map(r=>r.daily_gross),b.rows.map(r=>r.daily_gross));
   assert.equal(a.small,b.small);assert.equal(a.direct,b.direct);assert.equal(a.gross,b.gross);
   const future=a.rows.filter(r=>!r.actual&&!r.partial),previous=b.rows.filter(r=>!r.actual&&!r.partial);
   assert.deepEqual(future[0],previous[0],'first zero-weight bridge day unchanged');
   assert.notDeepEqual(future.map(r=>r.direct),previous.map(r=>r.direct),method+' source shape used');
   assert.equal(a.rows.at(-1).cumulative_direct,a.direct);assert.equal(a.rows.at(-1).cumulative_small,a.small);
  }
  await activeContext.close();
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({reference,before:old.rows.filter((r,i)=>i%7===0||i===old.rows.length-1).map(r=>[r.day,r.direct_share]),after:result.rows.filter((r,i)=>i%7===0||i===result.rows.length-1).map(r=>[r.day,r.direct_share])}));
  console.log('PASS source curve, realtime input, exact daily gross/terminals, chart table, ended actuals and both ongoing methods');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
