// Inspect the formal main output; never create a separate test page.
const path=require('path'),fs=require('fs'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  const out=path.join(project,'.test_outputs/ui_cleanup_20261008');fs.mkdirSync(out,{recursive:true});
  assert.equal(await page.locator('[data-small-input]').count(),0,'retired lead/heat controls removed');
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:width===390?844:1000});
   for(const stage of ['small','launch','steady']){
    await page.locator(`[data-forecast-stage-switch="${stage}"]`).click();
    await page.locator('[data-forecast-tab="evidence"]').click();
    const pane=page.locator(`[data-forecast-stage-pane="${stage}"]`);
    assert(await pane.locator('[data-forecast-region="common"]').isVisible());
    const weight=pane.locator('[data-bridge-control="weights"]');
    assert(await weight.evaluate(input=>Math.abs(input.getBoundingClientRect().left-input.parentElement.getBoundingClientRect().left)<4),'weight input stays with its label');
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'no page overflow');
    await page.screenshot({path:path.join(out,`after-${stage}-${width}.png`)});
    console.log('PASS',stage,width,'evidence visible, no overflow');
   }
  }
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-forecast-stage-switch="small"]').click();
  await page.locator('[data-forecast-target="smallStartDate"]').fill('2027-01-01');
  await page.locator('[data-forecast-target="smallStartDate"]').dispatchEvent('change');
  const result=await page.locator('.forecast-workspace').evaluate(root=>root._smallForecastResult);
  assert.equal(result.stage,'before');
  assert(!errors.length,'pre-small forecast still executes without retired variables');
  console.log('PASS before-small stage without retired drivers',JSON.stringify({total:result.total,error:result.error}));
  assert.deepEqual(errors,[]);
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
