// Formal main output; inspect the production release resolver without changing source data.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'small',forecastView:'evidence'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  const root=page.locator('.forecast-workspace'),pause=()=>page.waitForTimeout(350);
  const actualBefore=await root.evaluate(r=>JSON.stringify(r._forecastComparison.scenarios.parameter.rows));
  const config=JSON.parse(await root.getAttribute('data-forecast-config'));
  for(const [field,raw] of [['smallPeriod',config.target.small_period],['period',config.target.launch_period]]){
   const control=page.locator(`[data-forecast-target="${field}"]`);
   assert.deepEqual(await control.locator('option').evaluateAll(nodes=>nodes.map(n=>n.value)),['上午','下午','晚上','未维护']);
   assert.equal(await control.inputValue(),['上午','下午','晚上'].includes(raw)?raw:'未维护');
  }
  await page.evaluate(()=>{const real=window.ForecastMath.releaseHourForTarget;window.releaseCalls=[];window.ForecastMath.releaseHourForTarget=(target,stage,hours=[])=>{const start=real(target,stage,hours),period=stage==='small'?target.smallPeriod:target.period,field=stage==='small'?'orders':'gross';if(hours.length)window.releaseCalls.push({period,hours,field,start});return start;};});
  for(const [stage,field,metric] of [['small','smallPeriod','orders'],['launch','period','gross']]){
   await page.locator(`[data-forecast-stage-switch="${stage}"]`).click();
   const control=page.locator(`[data-forecast-target="${field}"]`);
   await page.evaluate(()=>window.releaseCalls=[]);await control.selectOption('未维护');await pause();
   const calls=await page.evaluate(()=>window.releaseCalls);
   const automatic=calls.filter(c=>c.field===metric&&c.period==='未维护');
   assert(automatic.length,stage+' uses D1 resolver');
   for(const c of automatic){const positive=c.hours.filter(r=>Number.isFinite(r[metric])&&r[metric]>0).map(r=>r.hour);assert.equal(c.start,positive.length?Math.min(...positive):-1);}
   for(const [period,hour] of [['上午',9],['下午',14],['晚上',19]]){
    await page.evaluate(()=>window.releaseCalls=[]);await control.selectOption(period);await pause();
    const values=await page.evaluate(()=>window.releaseCalls);
    const maintained=values.filter(c=>c.field===metric&&c.period===period);assert(maintained.length);
    const configuredPeriod=stage==='small'?config.target.small_period:config.target.launch_period;
    const configuredHour=config.target[stage+'_release_start_hour'];
    const expected=period===configuredPeriod&&Number.isInteger(configuredHour)?configuredHour:hour;
    assert(maintained.every(c=>c.start===expected),stage+' unchanged inferred period keeps exact summary hour; changed period uses anchor');
   }
   console.log('PASS '+stage+': three periods, exact D1 fallback and maintained priority');
  }
  assert.equal(await root.evaluate(r=>JSON.stringify(r._forecastComparison.scenarios.parameter.rows)),actualBefore,'Ended actuals unchanged');
  await page.reload();await page.waitForSelector('.forecast-workspace');await pause();
  for(const field of ['smallPeriod','period'])assert.equal(await page.locator(`[data-forecast-target="${field}"]`).inputValue(),'晚上');
  assert.deepEqual(errors,[]);console.log('PASS independent persistence and no browser errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
