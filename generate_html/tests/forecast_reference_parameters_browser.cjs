// Use main.py's real output; no separate HTML or injected business data.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M7 2024款',forecastStage:'launch',forecastCampaign:'问界 M7 2024款 Ultra版'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  await page.locator('[data-forecast-tab="evidence"]').click();
  const data=JSON.parse(await page.locator('.forecast-workspace').getAttribute('data-forecast-config'));
  const history=data.history;
  for(const [task,field,inputKey] of [['conversion','conversion','conversion'],['direct_share','direct_share','direct'],['lock','lock_rate','lock']]){
   const card=page.locator(`[data-forecast-task="${task}"]`),selects=card.locator('[data-forecast-ref]');
   const allowed=await selects.first().locator('option:not(:disabled)').evaluateAll(nodes=>nodes.map(n=>n.value));
   const valid=history.find(item=>allowed.includes(item.model)&&typeof item[field]==='number'&&item[field]>0&&item[field]<1&&!(item.quality_issues||'').includes({conversion:'小订转化率',direct_share:'直接大定占比',lock_rate:'大定到锁单率'}[field]));
   const missing=history.find(item=>allowed.includes(item.model)&&(item[field]==null||item[field]>1));
   assert(valid,task+' needs a valid reference');
   const missingName=missing?.model||'';
   for(const slot of [0,1]){
    await selects.nth(slot).selectOption(valid.model);await page.waitForTimeout(80);
   }
   await selects.first().selectOption(missingName);await page.waitForTimeout(180);
   const predicted=Number(await page.locator(`[data-forecast-input="${inputKey}"]`).inputValue());
   assert(Math.abs(predicted-valid[field]*100)<=.051,task+' missing primary must not dilute auxiliary');
   assert((await card.locator('[data-forecast-parameter-note]').textContent()).includes('有效权重100%'),task+' effective weight explanation');
   if(missing){
    await selects.nth(1).selectOption(missingName);await page.waitForTimeout(180);
    assert.equal(await page.locator(`[data-forecast-input="${inputKey}"]`).inputValue(),'',task+' no valid rates remains blank');
   }else console.log('NOTE '+task+' 本机无缺终值车型，以空选项核对单参考归一；null终值由Python→JS回归验证');
   await selects.first().selectOption(valid.model);await selects.nth(1).selectOption(valid.model);
   console.log('PASS '+task+' real browser missing/valid weights and blanks');
  }
  await page.locator('[data-forecast-tab="evidence"]').click();
  for(const [field,value] of [['small','10000'],['conversion','50'],['direct','98'],['lock','75']]){
   await page.locator(`[data-forecast-input="${field}"]`).fill(value);
  }
  await page.locator('[data-forecast-target="launchDate"]').fill('2080-01-01');
  await page.locator('[data-forecast-target="launchDate"]').dispatchEvent('change');
  await page.waitForTimeout(250);
  const scenario=await page.locator('.forecast-workspace').evaluate(root=>root._forecastComparison.scenarios.parameter);
  assert(scenario.available,'future method2 scenario is available');
  assert(Math.abs(scenario.share-.98)<.0001,'98% input is not silently capped to95%');
  assert(Math.abs(scenario.conversion-.5)<.0001,'method2 terminal uses entered conversion');
  console.log('PASS method2 terminal conversion and 98% direct share');
  assert.deepEqual(errors,[]);console.log('PASS no browser errors');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
