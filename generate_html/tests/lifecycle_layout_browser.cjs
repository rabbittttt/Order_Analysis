// Exercise only the formal main.py output. --before saves a numerical baseline.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const before=process.argv.includes('--before'),out=path.join(project,'.test_outputs/lifecycle_layout_20261003');
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'small',forecastView:'result'});
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],checks=[];
 const check=(label,value)=>{assert(value,label);checks.push(label);console.log('PASS '+label)};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
  page.on('pageerror',e=>errors.push(e.message));await page.goto(url.href);
  await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
  const snapshot=await page.locator('.forecast-workspace').evaluate(root=>JSON.stringify({launch:root._forecastComparison,small:root._smallForecastResult,steady:root.querySelector('[data-steady-workspace]')._steadyDaily}));
  if(before)fs.writeFileSync(path.join(out,'baseline.json'),snapshot);
  else check('只改布局，三个阶段的计算结果与修改前完全一致',snapshot===fs.readFileSync(path.join(out,'baseline.json'),'utf8'));
  for(const stage of ['small','steady']){
   await page.locator('[data-forecast-stage-switch="'+stage+'"]').click();
   for(const view of ['result','evidence']){
    await page.locator('[data-forecast-tab="'+view+'"]').click();
    const pane=page.locator('[data-lifecycle-subpane="'+stage+'-'+view+'"]');
    await page.screenshot({path:path.join(out,(before?'before-':'after-')+stage+'-'+view+'-1440.png')});
    if(before)continue;
    if(view==='result'){
     check(stage+'复用首销结果卡',await pane.locator('.forecast-scenario').count()===1);
     check(stage+'外部预测紧接图表且不嵌入图表卡',await pane.locator('[data-forecast-import-anchor]').evaluate(n=>!n.closest('.forecast-decision-card')&&n.previousElementSibling.classList.contains('forecast-decision-card')));
     check(stage+'仅一个公共参数卡',await pane.locator('.forecast-common-controls').count()===1);
    }else{
     check(stage+'依据使用首销参考分组',await pane.locator('.forecast-evidence-group').count()===(stage==='small'?2:1));
     check(stage+'长规则在底部折叠',await pane.locator(':scope > details.forecast-method').count()===1&&!await pane.locator(':scope > details.forecast-method').evaluate(n=>n.open));
     check(stage+'参考曲线有数值查看入口',await pane.locator('summary').filter({hasText:'查看图表数值'}).count()>0);
     const refs=await pane.locator('[data-lifecycle-ref]').count();check(stage+'参考与权重数量不变',refs===(stage==='small'?6:2)&&await pane.locator('[data-lifecycle-weight]').count()===refs);
     if(stage==='steady')check('平销两张趋势图共用一套主辅',await pane.locator('[data-lifecycle-reference="steady-weekly"] [data-steady-evidence]').count()===1);
    }
    for(const width of [1024,390]){
     await page.setViewportSize({width,height:900});
     check(stage+' '+view+' '+width+'无页面横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
     check(stage+' '+view+' '+width+'内容卡不超出页面',await pane.locator('.forecast-scenario,.forecast-ref-card,.forecast-decision-card').evaluateAll(nodes=>nodes.every(n=>n.getBoundingClientRect().right<=innerWidth+1&&n.getBoundingClientRect().left>=0)));
     if(width===390){await pane.locator('.forecast-scenario,.forecast-evidence-group').first().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'after-'+stage+'-'+view+'-390.png')});}
    }
    await page.setViewportSize({width:1440,height:1000});
   }
  }
  check('没有浏览器异常',errors.length===0);
 }finally{await browser.close();}
 console.log(JSON.stringify({checks:checks.length,errors}));
})().catch(e=>{console.error(e);process.exitCode=1});
