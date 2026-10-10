// Exercises the formal main.py output, with isolated browser state.
const path=require('path'),fs=require('fs'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',error=>errors.push(error.message));
 try{
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  for(const stage of ['small','launch','steady']){
   await page.locator(`[data-forecast-stage-switch="${stage}"]`).click();
   await page.locator('[data-forecast-tab="evidence"]').click();
   const pane=page.locator(`[data-forecast-stage-pane="${stage}"]`);
   const common=pane.locator('[data-forecast-region="common"]');
   assert(await common.isVisible(),stage+' common controls are in evidence');
   const parameter=pane.locator('[data-forecast-region="parameters"]');
   if(await parameter.count()){
    const p=await parameter.boundingBox(),c=await common.boundingBox();
    assert(p.y<c.y||Math.abs(p.y-c.y)<1&&p.x<c.x,stage+' parameters precede common vertically or left-to-right');
   }
   const cards=pane.locator('[data-lifecycle-reference]');
   if(await cards.count()){
    await cards.first().locator(':scope > .forecast-ref-score-details > summary').click();
    assert.deepEqual(await cards.first().locator('.forecast-ref-comparison thead th').allTextContents(),
      ['参与打分参数',...await cards.first().locator('.forecast-ref-comparison thead th').allTextContents().then(h=>h.slice(1,4)),'单项打分']);
    assert((await cards.first().locator('.forecast-ref-comparison thead').innerText()).includes('问界 M9 2026款'));
   }
   console.log('PASS',stage,'evidence parameters and score table');
  }
  await page.locator('[data-forecast-stage-switch="small"]').click();
  const before=await page.locator('.forecast-workspace').evaluate(root=>JSON.stringify(root._smallForecastResult));
  const slope=page.locator('[data-lifecycle-reference="small-slope"]');
  assert(await slope.isVisible());assert((await slope.innerText()).includes('仅展示'));
  await slope.locator('[data-small-slope-weight="0"]').fill('15');
  assert.equal(before,await page.locator('.forecast-workspace').evaluate(root=>JSON.stringify(root._smallForecastResult)));
  assert(await slope.locator('details.forecast-chart-values, details').count()>0);
  console.log('PASS display-only slope weight does not alter forecast');
  await page.locator('[data-forecast-stage-switch="steady"]').click();
  assert((await page.locator('[data-steady-evidence]').innerText()).includes('发布后同龄周平销趋势'));
  console.log('PASS steady chart uses release-age axis');
  const out=path.join(project,'.test_outputs/forecast_lifecycle_20261008');fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'steady-evidence-1440.png')});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1),'no mobile page horizontal overflow');
  await page.screenshot({path:path.join(out,'steady-evidence-390.png')});
  assert.deepEqual(errors,[]);console.log('PASS mobile layout and no page errors');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
