// Real generated dashboard: invalid edits and saved drafts must remain recoverable.
const assert=require('assert'),path=require('path'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'result'});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  const ready=()=>page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
  await page.goto(url.href);await ready();
  const root=page.locator('.forecast-workspace'),source=await root.getAttribute('data-forecast-config');
  const initial=await page.locator('[data-forecast-target="days"],[data-forecast-target="smallDays"]').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.dataset.forecastTarget,n.value])));
  const state=()=>root.evaluate(n=>({launch:Object.fromEntries(Object.entries(n._forecastComparison.scenarios).map(([k,s])=>[k,{available:s.available,gross:s.gross}])),small:{total:n._smallForecastResult.total,error:n._smallForecastResult.error}}));
  const baseline=await state();
  const change=async(key,value)=>{const input=page.locator(`[data-forecast-target="${key}"]`);await input.fill(value);await input.dispatchEvent('change');await page.waitForTimeout(350);};
  for(const [key,limit,label] of [['days',90,'首销天数'],['smallDays',366,'小订天数']]){
   for(const value of ['1e20','1000000000',String(limit+1),'0','-2','1.5']){
    await change(key,value);
    assert.deepEqual(errors,[],key+'='+value+' runtime error');
    const notice=await page.locator(key==='days'?'[data-forecast-data-error]':'[data-small-error]').textContent();
    assert(notice.includes(label+'须为1～'+limit+'的整数'),key+' invalid edit needs a precise error');
    const result=await state();
    assert(key==='days'?Object.values(result.launch).every(s=>!s.available):!!result.small.error,key+' invalid input must not leave a usable prediction');
    assert.equal(await root.getAttribute('data-forecast-config'),source,'raw source payload changed');
    await change(key,initial[key]);
    assert.deepEqual(await state(),baseline,'valid correction must restore the original prediction');
    checks++;
   }
   await change(key,String(limit));
   assert(!(await page.locator(key==='days'?'[data-forecast-data-error]':'[data-small-error]').textContent()).includes(label+'须为'),'declared maximum remains valid');
   await change(key,initial[key]);checks++;
  }
  await change('days','1e20');await page.waitForTimeout(250);await page.reload();await ready();
  assert.deepEqual(errors,[],'invalid saved draft must not crash after reload');
  assert((await page.locator('[data-forecast-data-error]').textContent()).includes('首销天数须为'));
  await change('days',initial.days);assert.deepEqual(await state(),baseline,'saved draft is recoverable');checks++;
  assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
