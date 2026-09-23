// Run after main.py to verify the real generated page at narrow widths.
const path=require('path'),assert=require('assert'),fs=require('fs');
const {pathToFileURL}=require('url');
const codeRoot=path.resolve(__dirname,'../..');
const root=path.basename(codeRoot).toLowerCase()==='scripts'?path.dirname(codeRoot):codeRoot;
const {chromium}=require(path.join(root,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  const url=pathToFileURL(path.join(root,'output_file/鸿蒙智行订单分析汇总.html'));
  await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('#updatedAt')?.textContent);
  for(const width of [1440,1024,768,390]){
   await page.setViewportSize({width,height:900});
   const bounds=await page.evaluate(()=>{
    const selectors=['#updatedAt','#subjectSelect','#grainSelect','#periodSelect'];
    return selectors.map(selector=>{const el=document.querySelector(selector),r=el.getBoundingClientRect(),s=getComputedStyle(el);return {selector,x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height,visible:s.display!=='none'&&s.visibility!=='hidden'&&r.height>0}});
   });
   for(const item of bounds){assert(item.visible,`${width}: ${item.selector} hidden`);assert(item.x>=0&&item.right<=width+1,JSON.stringify({width,item}));}
   for(let i=0;i<bounds.length;i++)for(let j=i+1;j<bounds.length;j++){
    const a=bounds[i],b=bounds[j],overlap=Math.min(a.right,b.right)-Math.max(a.x,b.x)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>1;
    assert(!overlap,JSON.stringify({width,a,b}));
   }
  }
  await page.setViewportSize({width:1440,height:1000});
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'result'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  await page.waitForFunction(()=>document.querySelector('.forecast-workspace')._forecastComparison?.rows?.length);
  assert(!(await page.locator('[data-forecast-decision-chart="parameter"]').textContent()).includes('退订率'));
  assert(await page.locator('[data-forecast-progress-actual-small]').count());
  for(const stage of ['small','steady','launch']){
   url.searchParams.set('forecastStage',stage);await page.goto(url.href);
   await page.waitForSelector(`[data-forecast-stage-pane="${stage}"].active`);
   await page.waitForFunction(()=>!document.querySelector('[data-forecast-current-day]').textContent.includes('判定中'));
  }
  const output=path.join(root,'.test_outputs/forecast_bridge_validation');fs.mkdirSync(output,{recursive:true});
  await page.screenshot({path:path.join(output,'forecast-final-desktop.png')});
  await page.setViewportSize({width:390,height:900});await page.screenshot({path:path.join(output,'forecast-final-mobile.png')});
  assert.deepEqual(errors,[]);console.log('PASS: real page at 390/768/1024/1440px, timestamp, nonoverlapping filters, three stages and no JS errors');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
