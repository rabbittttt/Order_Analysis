// Formal main.py page only: visual parity, compactness and unchanged forecast outputs.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const before=process.argv.includes('--before'),out=path.join(project,'.test_outputs/forecast_studio_20261007');
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'small',forecastView:'result'});
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'}),checks=[],errors=[],geometry={};
 const check=(name,value)=>{assert(value,name);checks.push(name);console.log('PASS '+name)};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
  page.on('pageerror',error=>errors.push(error.message));await page.goto(url.href);
  await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
  const snapshot=await page.locator('.forecast-workspace').evaluate(root=>JSON.stringify({launch:root._forecastComparison,small:root._smallForecastResult,steady:root.querySelector('[data-steady-workspace]')._steadyDaily}));
  if(before)fs.writeFileSync(path.join(out,'baseline.json'),snapshot);
  else check('三个阶段的计算输出与改版前逐字段一致',snapshot===fs.readFileSync(path.join(out,'baseline.json'),'utf8'));
  for(const stage of ['small','launch','steady']){
   await page.locator(`[data-forecast-stage-switch="${stage}"]`).click();
   const stagePane=page.locator(`[data-forecast-stage-pane="${stage}"]`);
   for(const view of ['result','evidence','score']){
    await page.locator(`[data-forecast-tab="${view}"]`).click();
    const pane=stagePane.locator(stage==='launch'?`[data-forecast-pane="${view}"]`:`[data-lifecycle-subpane="${stage}-${view}"]`);
    await page.setViewportSize({width:1440,height:1000});
    await pane.scrollIntoViewIfNeeded();
    // Start each screenshot at the beginning of the formal page, not at a prior tab's offset.
    await page.locator('.forecast-target').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,`${before?'before':'after'}-${stage}-${view}-1440.png`)});
    if(view==='result'){
     geometry[stage]=await pane.evaluate(node=>({parameters:node.querySelector('.forecast-parameter-rail')?.getBoundingClientRect().height||0,chartTop:node.querySelector('.forecast-decision-card').getBoundingClientRect().top}));
     if(!before){
      const regions=await pane.locator('.forecast-result-main > [data-forecast-region]').evaluateAll(nodes=>nodes.map(node=>node.dataset.forecastRegion));
      check(stage+'区域顺序统一',JSON.stringify(regions)===JSON.stringify(['summary','parameters','curves','import','common']));
      check(stage+'统一指标卡组件',await pane.locator('.forecast-metric-strip').count()===(stage==='launch'?2:1));
      check(stage+'结果图使用同一SVG和数值入口',await pane.locator('.forecast-result-chart-scroll svg').count()>0&&await pane.locator('.forecast-result-values summary').count()>0);
      check(stage+'公共参数只有一组',await pane.locator('[data-bridge-stage]').count()===1);
      if(stage==='small')check('线索与热度同排且短输入不过宽',await pane.locator('[data-small-input]').evaluateAll(nodes=>nodes.length===2&&Math.abs(nodes[0].getBoundingClientRect().top-nodes[1].getBoundingClientRect().top)<2&&nodes.every(node=>node.getBoundingClientRect().width<=240)));
      const table=pane.locator('.forecast-result-values').first();await table.locator('summary').click();
      check(stage+'数值表可展开且有记录',await table.locator('tbody tr').count()>0);await table.locator('summary').click();
     }
    }
    if(!before&&view==='evidence'){
     check(stage+'参考卡包含主辅、权重及评分入口',await pane.locator('.forecast-ref-selects').count()>0&&await pane.locator('.forecast-ref-weights').count()>0&&await pane.locator('.forecast-ref-score-details summary').count()>0);
     check(stage+'参考曲线共用数值查看入口',await pane.locator('summary').filter({hasText:'查看图表数值'}).count()>0);
    }
    if(!before)for(const width of [1024,390]){
     await page.setViewportSize({width,height:1000});
     check(`${stage}/${view}/${width} 无页面横向溢出`,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
     check(`${stage}/${view}/${width} 卡片边界不越界`,await pane.locator('.forecast-scenario,.forecast-ref-card,.forecast-decision-card').evaluateAll(nodes=>nodes.every(node=>{const r=node.getBoundingClientRect();return r.width===0||r.left>=0&&r.right<=innerWidth+1})));
     if(width===390){await pane.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`after-${stage}-${view}-390.png`)});}
    }
    await page.setViewportSize({width:1440,height:1000});
   }
  }
  if(before)fs.writeFileSync(path.join(out,'geometry-before.json'),JSON.stringify(geometry,null,2));
  else{
   const baseline=JSON.parse(fs.readFileSync(path.join(out,'geometry-before.json'),'utf8'));
   check('小订参数区高度明显减少',geometry.small.parameters<baseline.small.parameters*.75);
   fs.writeFileSync(path.join(out,'geometry-after.json'),JSON.stringify(geometry,null,2));
  }
  check('没有浏览器运行异常',errors.length===0);
 }finally{await browser.close();}
 console.log(JSON.stringify({checks:checks.length,errors,geometry}));
})().catch(error=>{console.error(error);process.exitCode=1});
