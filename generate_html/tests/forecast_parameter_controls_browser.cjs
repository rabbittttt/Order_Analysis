// Exercise the formal main.py output; no alternate HTML or business-data fixture.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M7 2024款',forecastStage:'launch',forecastView:'evidence',forecastCampaign:'问界 M7 2024款 Ultra版'});
 const input=field=>page.locator(`[data-forecast-input="${field}"]`);
 const restore=control=>control.locator('..').locator('.forecast-field-reset').click();
 const pause=()=>page.waitForTimeout(300);
 try{
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  await page.locator('[data-forecast-tab="evidence"]').click();
  assert.equal(await page.locator('[data-forecast-apply],[data-forecast-apply-progress]').count(),0);
  const controls=page.locator('[data-forecast-input],[data-bridge-control],[data-small-input]');
  assert.equal(await controls.count(),await page.locator('.forecast-field-reset').count());
  assert(await controls.evaluateAll(nodes=>nodes.every(n=>n.getAttribute('aria-label')&&n.closest('label')?.htmlFor===n.id)));
  console.log('PASS uniform individual reset and accessible labels');
  await input('conversion').fill('22');await input('direct').fill('66');await pause();
  const lockBefore=await input('lock').inputValue();
  await restore(input('conversion'));await pause();
  assert.equal(await input('direct').inputValue(),'66');
  assert.equal(await input('lock').inputValue(),lockBefore);
  assert.deepEqual(await page.locator('.forecast-workspace').evaluate(r=>r._forecastDraftState().parameterOverrides),['direct']);
  await page.reload();await page.waitForSelector('.forecast-workspace');await pause();
  assert.equal(await input('direct').inputValue(),'66');
  assert.deepEqual(await page.locator('.forecast-workspace').evaluate(r=>r._forecastDraftState().parameterOverrides),['direct']);
  // Untouched fields must continue following references even with another manual field.
  const config=JSON.parse(await page.locator('.forecast-workspace').getAttribute('data-forecast-config'));
  const refs=page.locator('[data-forecast-task="conversion"] [data-forecast-ref]');
  const allowed=await refs.first().locator('option:not(:disabled)').evaluateAll(nodes=>nodes.map(n=>n.value));
  const valid=config.history.find(h=>allowed.includes(h.model)&&h.conversion>0&&h.conversion<1&&!(h.quality_issues||'').includes('小订转化率'));
  assert(valid);await refs.first().selectOption(valid.model);await refs.nth(1).selectOption(valid.model);await pause();
  assert(Math.abs(Number(await input('conversion').inputValue())-valid.conversion*100)<.051);
  assert.equal(await input('direct').inputValue(),'66');
  console.log('PASS independent override, reference synchronization and reload persistence');
  await restore(input('direct'));await pause();
  assert.deepEqual(await page.locator('.forecast-workspace').evaluate(r=>r._forecastDraftState().parameterOverrides),[]);
  const bridge=page.locator('[data-bridge-stage="launch"]');
  const weekend=bridge.locator('[data-bridge-control="weekend"]'),holiday=bridge.locator('[data-bridge-control="holiday"]');
  await weekend.fill('1.7');await holiday.fill('1.8');await pause();
  await restore(weekend);await pause();
  assert.equal(await weekend.inputValue(),'1.15');assert.equal(await holiday.inputValue(),'1.8');
  await page.reload();await page.waitForSelector('.forecast-workspace');await pause();
  assert.equal(await weekend.inputValue(),'1.15');assert.equal(await holiday.inputValue(),'1.8');
  await restore(holiday);
  console.log('PASS calendar restore changes only one field and persists');
  await input('progressSmallCompletion').fill('20');await input('progressDirectCompletion').fill('30');await pause();
  await restore(input('progressSmallCompletion'));await pause();
  assert.deepEqual(await page.locator('.forecast-workspace').evaluate(r=>r._forecastDraftState().progressOverride),{small:false,direct:true});
  await restore(input('progressDirectCompletion'));
  // Older saved drafts used a single override flag: preserve them, then allow per-field recovery.
  await page.locator('.forecast-workspace').evaluate(r=>r._forecastRestoreDraft({manualOverride:true}));
  assert.deepEqual(await page.locator('.forecast-workspace').evaluate(r=>r._forecastDraftState().parameterOverrides),['conversion','direct','lock']);
  await restore(input('conversion'));await restore(input('direct'));await restore(input('lock'));
  await input('small').fill('10000');await input('conversion').fill('40');await input('direct').fill('50');
  await page.locator('[data-forecast-target="launchDate"]').fill('2080-01-01');
  await page.locator('[data-forecast-target="launchDate"]').dispatchEvent('change');await pause();
  assert(await page.locator('.forecast-workspace').evaluate(r=>r._forecastComparison.scenarios.parameter.available));
  const before=await page.locator('.forecast-workspace').evaluate(r=>JSON.stringify(r._forecastComparison.scenarios.parameter.rows));
  // Dispatch input only (without change/blur): calendar coefficients must already recalculate.
  await weekend.evaluate(n=>{n.value='2.5';n.dispatchEvent(new Event('input',{bubbles:true}))});await pause();
  const after=await page.locator('.forecast-workspace').evaluate(r=>JSON.stringify(r._forecastComparison.scenarios.parameter.rows));
  assert.notEqual(after,before,'calendar input must recalculate without an apply button or blur');
  console.log('PASS independent completion restore, legacy drafts and realtime calendar distribution');
  // Fresh subject for consistent visual baseline and actual read-only controls.
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'evidence'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');await pause();
  for(const width of [1440,1024,390]){
   await page.setViewportSize({width,height:1000});
   for(const stage of ['launch','small','steady']){
    await page.locator(`[data-forecast-stage-switch="${stage}"]`).click();await page.locator('[data-forecast-tab="evidence"]').click();await pause();
    const section=page.locator(`[data-bridge-stage="${stage}"]`);
    assert(await section.isVisible(),stage+' calendar visible');
    const overflowing=await section.evaluate(root=>[root,...root.querySelectorAll('input,button,label')].filter(n=>n.getBoundingClientRect().width&&n.getBoundingClientRect().right>innerWidth+1).length);
    assert.equal(overflowing,0,`${stage} ${width}px parameter overflow`);
    if(width===1440&&stage==='launch'){
     const box=await page.locator('.forecast-evidence-controls:visible').boundingBox();
     await page.locator('.forecast-evidence-controls:visible').screenshot({path:path.join(project,'.test_outputs/parameter_ui_20261010/after.png')});
     console.log('Parameter area',JSON.stringify(box));
     assert(box.height<465,'parameter area more compact than before');
    }
    if(width===390&&stage==='launch')await page.locator('.forecast-evidence-controls:visible').screenshot({path:path.join(project,'.test_outputs/parameter_ui_20261010/after-mobile.png')});
   }
  }
  console.log('PASS three stages at 1440/1024/390px without parameter overflow');
  assert.deepEqual(errors,[]);console.log('PASS no browser errors');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
