// Run --before, regenerate with main.py, then run without flags.
// Geometry and numeric invariance on main.py's real output; no test HTML.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const before=process.argv.includes('--before'),out=path.join(project,'.test_outputs/forecast_layout_20261009');
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],records=[];
 const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
 page.on('pageerror',e=>errors.push(e.message));
 try{
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'small',forecastView:'result'});
  await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
  const snapshot=await page.locator('.forecast-workspace').evaluate(root=>({
   launch:root._forecastComparison,small:root._smallForecastResult,steady:root.querySelector('[data-steady-workspace]')._steadyDaily}));
  if(before)fs.writeFileSync(path.join(out,'baseline.json'),JSON.stringify(snapshot));
  else assert.deepStrictEqual(JSON.parse(JSON.stringify(snapshot)),JSON.parse(fs.readFileSync(path.join(out,'baseline.json'),'utf8')),'CSS must not change forecast data (same JSON representation for missing/non-finite values)');
  for(const width of [1440,1200,900,390]){
   await page.setViewportSize({width,height:width===390?844:1000});
   for(const stage of ['small','launch','steady']){
    await page.locator(`[data-forecast-stage-switch="${stage}"]`).click();
    for(const view of ['result','evidence','score']){
     await page.locator(`[data-forecast-tab="${view}"]`).click();
     await page.locator('#page').evaluate(n=>n.scrollTop=0);
     const layout=await page.evaluate(()=>{
      const box=n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
      const visible=n=>n.getBoundingClientRect().width>0;
      const main=[...document.querySelectorAll('.forecast-result-main')].find(visible);
      const section=n=>n?box(n):null;
      const controlOverflows=[...document.querySelectorAll('.forecast-workspace input,.forecast-workspace select,.forecast-workspace button')].filter(visible).filter(n=>{const r=n.getBoundingClientRect();return !n.closest('.forecast-chart-scroll,.forecast-score-table')&&(r.right>innerWidth+1||r.left<0)}).map(n=>n.outerHTML.slice(0,140));
      return {pageOverflow:document.documentElement.scrollWidth>innerWidth+1,controlOverflows,
       main:section(main),summary:section(main?.querySelector('[data-forecast-region="summary"]')),scale:section(main?.querySelector('.forecast-scale-check')),
       curves:section(main?.querySelector('[data-forecast-region="curves"]')),import:section(main?.querySelector('[data-forecast-region="import"]')),
       cards:[...document.querySelectorAll('.forecast-ref-card')].filter(visible).map(section),
       referencePairs:[...document.querySelectorAll('.forecast-ref-grid')].filter(visible).map(n=>[...n.children].filter(c=>c.matches('.forecast-ref-card')).map(box)).filter(items=>items.length>=2),
       inputPairs:[...document.querySelectorAll('.forecast-input-grid')].filter(visible).map(n=>[...n.children].filter(c=>c.matches('label')&&c.querySelector('input')).map(c=>({label:box(c),input:box(c.querySelector('input'))}))).filter(items=>items.length>=2)};
     });
     records.push({width,stage,view,...layout});
     if(!before){
      assert(!layout.pageOverflow,`${width} ${stage} ${view}: page overflow`);
      assert.deepStrictEqual(layout.controlOverflows,[],`${width} ${stage} ${view}: controls outside viewport`);
      if(view==='evidence'){
       if(width===1440)for(const [a,b] of layout.referencePairs){
        assert(Math.abs(a.y-b.y)<2&&Math.abs(a.width-b.width)<2&&b.x>=a.right,'reference cards remain equal half-width columns');
       }
       for(const pair of layout.inputPairs)for(let i=1;i<pair.length;i++){
        const a=pair[i-1],b=pair[i];
        if(Math.abs(a.label.y-b.label.y)<2)assert(Math.abs(a.input.y-b.input.y)<2,`${stage}: inputs in the same row align despite wrapped labels`);
       }
      }
      if(view==='result'){
       assert(Math.abs(layout.curves.width-layout.main.width)<2,`${stage}: curves use full width`);
       assert(Math.abs(layout.import.width-layout.main.width)<2,`${stage}: import uses full width`);
       if(stage==='launch'&&width>1200){
        assert(layout.scale.x>=layout.summary.right, 'launch check is on right');
        assert(Math.abs(layout.scale.y-layout.summary.y)<2,'launch check top aligned');
        assert(layout.curves.y-layout.summary.bottom<120,'compact check must not leave a large gap below the launch summary');
       }else assert(Math.abs(layout.summary.width-layout.main.width)<2,`${stage}: no empty column`);
      }
     }
     if(width===1440||width===390){
      await page.screenshot({path:path.join(out,`${before?'before':'after'}-${stage}-${view}-${width}.png`)});
      if(width===390){await page.locator('[role="tabpanel"]:visible').last().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`${before?'before':'after'}-${stage}-${view}-${width}-content.png`)});}
     }
     console.log(before?'BASELINE':'PASS',width,stage,view);
    }
   }
  }
  assert.deepStrictEqual(errors,[]);
  fs.writeFileSync(path.join(out,`${before?'before':'after'}-geometry.json`),JSON.stringify(records,null,2));
  console.log(JSON.stringify({views:records.length,errors,numericInvariant:!before}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
