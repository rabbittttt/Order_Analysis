// Functional guards for lazy score explanations; use the formal generated dashboard.
const assert=require('assert'),path=require('path'),fs=require('fs'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage({reducedMotion:'reduce'}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'result'});
 const ready=()=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false');
 const snapshot=()=>page.locator('.forecast-workspace').evaluate(n=>JSON.stringify({launch:n._forecastComparison,small:n._smallForecastResult,steady:n._steadyForecastResult}));
 try{
  await page.goto(url.href);await ready();
  assert.equal(await page.locator('[data-forecast-score-dashboard]').innerHTML(),'','hidden score explanation must not be built');
  const before=await snapshot();
  await page.locator('[data-forecast-tab="score"]').click();
  assert(await page.locator('[data-forecast-score-task]').isVisible(),'score tab renders on first visit');
  assert.equal(await snapshot(),before,'opening scores cannot change predictions');
  const baseline=path.join(project,'.test_outputs/performance_20261002/score-before.json');
  if(process.argv.includes('--compare-baseline'))assert.equal(await page.locator('[data-forecast-score-dashboard]').innerText(),JSON.parse(fs.readFileSync(baseline,'utf8')),'score values and explanations unchanged');
  const task=page.locator('[data-forecast-score-task]');await task.selectOption({index:1});const selected=await task.inputValue();
  await page.locator('[data-forecast-stage-switch="steady"]').click();await page.locator('[data-forecast-stage-switch="launch"]').click();
  assert.equal(await task.inputValue(),selected,'cross-stage return keeps selected scoring task');
  await page.locator('[data-forecast-tab="result"]').click();
  const days=page.locator('[data-forecast-target="days"]'),next=Number(await days.inputValue())+1;
  await days.fill(String(next));await days.dispatchEvent('change');
  await page.waitForFunction(()=>document.querySelector('[data-forecast-feedback]').dataset.state==='success');
  await page.locator('[data-forecast-tab="score"]').click();
  assert((await page.locator('[data-forecast-score-dashboard]').innerText()).includes(next+'天'),'score page must use updated target days');
  url.searchParams.set('forecastView','score');await page.goto(url.href);await ready();assert(await task.isVisible(),'score deep link renders');
  await page.locator('[data-forecast-stage-switch="small"]').click();await page.locator('[data-forecast-stage-switch="launch"]').click();assert(await task.isVisible(),'small to launch score renders');
  assert.deepEqual(errors,[]);console.log('PASS lazy score: hidden/deep-link/stage return/task preservation/current parameters/numeric and text equivalence');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
