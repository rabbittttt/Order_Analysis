// Layout regression on the formal main.py output; no injected business data.
const path=require('path'),assert=require('assert'),fs=require('fs'),crypto=require('crypto');
const {pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],sizes=[],hashes={};
 const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 const output=path.join(project,'.test_outputs/forecast_density');fs.mkdirSync(output,{recursive:true});
 const expected=process.env.FORECAST_DENSITY_EXPECTED;let checks=0;
 const check=(name,ok)=>{assert(ok,name);checks++;};
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(base.href);await page.waitForFunction(()=>document.querySelector('#subjectSelect option'));
  const names=await page.locator('#subjectSelect optgroup[label="代际"] option').allTextContents();
  const target=process.env.FORECAST_DENSITY_SUBJECT||names.find(name=>name==='问界 M9 2026款')||names[0];
  assert(target,'No forecast generations in formal output');
  for(const stage of ['small','launch','steady'])for(const view of ['result','evidence','score']){
   const url=new URL(base);url.search=new URLSearchParams({subject:target,module:'sales_forecast',forecastStage:stage,forecastView:view});
   await page.setViewportSize({width:1440,height:1100});await page.goto(url.href);
   await page.waitForSelector('.forecast-workspace');
   await page.waitForFunction(()=>document.querySelector('#page').getAttribute('aria-busy')==='false');
   await page.screenshot({path:path.join(output,`after-${stage}-${view}.png`)});
   if(view==='result'){
    const snapshot=await page.evaluate(()=>{
     const root=document.querySelector('.forecast-workspace');
     return {controls:[...root.querySelectorAll('input,select')].map(node=>({key:[...node.attributes].filter(a=>a.name.startsWith('data-')).map(a=>[a.name,a.value]),value:node.value})),comparison:root._forecastComparison||null,kpis:[...root.querySelectorAll('[data-small-kpi],[data-steady-kpi],.forecast-scenario-result strong,.forecast-scenario-breakdown strong')].map(node=>node.textContent)};
    });
    hashes[stage]=crypto.createHash('sha256').update(JSON.stringify(snapshot)).digest('hex');
    if(expected)check(`${stage} parameter/result snapshot unchanged`,hashes[stage]===expected);
    if(stage!=='launch'){
     const selector=stage==='small'?'[data-small-order-workspace]':'[data-steady-workspace]';
     const layout=await page.locator(selector+' .forecast-lifecycle-grid').evaluate(node=>[...node.children].map(child=>{const r=child.getBoundingClientRect();return {x:r.x,top:r.top,bottom:r.bottom,width:r.width,height:r.height};}));
     check(`${stage} controls above full-width chart`,layout[0].bottom<=layout[1].top&&Math.abs(layout[0].x-layout[1].x)<1);
     sizes.push({stage,layout});
    }else{
     const widths=await page.locator('.forecast-control-grid .forecast-input-grid input').evaluateAll(nodes=>nodes.map(node=>Math.round(node.getBoundingClientRect().width)));
     check('launch short numbers do not occupy a full row',widths.every(width=>width<320));sizes.push({stage,widths});
    }
   }
   if(stage==='steady'&&view==='evidence'){
    const widths=await page.locator('[data-steady-workspace] .forecast-ref-grid').evaluate(node=>({grid:node.getBoundingClientRect().width,card:node.firstElementChild.getBoundingClientRect().width}));
    check('single steady reference fills its grid',Math.abs(widths.grid-widths.card)<2);sizes.push({steadyReference:widths});
   }
   for(const width of [1920,1440,1024,768,390]){
    await page.setViewportSize({width,height:1100});await page.waitForTimeout(100);
    const outside=await page.evaluate(width=>[...document.querySelectorAll('.forecast-target-form input,.forecast-target-form select,.forecast-lifecycle-fields input,.forecast-lifecycle-fields select,.forecast-input-grid input,.forecast-lifecycle-controls,.forecast-score-hero,.forecast-score-rules article,.forecast-ref-selects select,.forecast-ref-selects input')].filter(node=>node.getBoundingClientRect().height&&node.checkVisibility()).map(node=>{const r=node.getBoundingClientRect();return {class:node.className,x:r.x,right:r.right};}).filter(r=>r.x<-.5||r.right>width+1),width);
    check(`${stage}/${view}/${width} controls and copy stay within viewport: ${JSON.stringify(outside)}`,outside.length===0);
    check('all nine target controls remain expanded',await page.locator('.forecast-target-form [data-forecast-target]').count()===9);
    if(width===390&&stage==='launch'&&view==='score')await page.screenshot({path:path.join(output,'after-launch-mobile.png')});
   }
  }
  check('no browser runtime errors',errors.length===0);
  console.log(JSON.stringify({checks,target,hashes,sizes,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
