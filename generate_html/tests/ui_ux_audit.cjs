// Local, offline end-to-end UX audit. Run from the repository root.
// UI_AUDIT_FINAL=1 tests the official generated page; otherwise rebuild a preview
// from the immutable audit baseline and current templates (same data, new UI).
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const codeRoot=path.resolve(__dirname,'../..');
const root=path.basename(codeRoot).toLowerCase()==='scripts'?path.dirname(codeRoot):codeRoot;
const templates=path.join(codeRoot,'generate_html/templates');
const output=path.join(root,'analysis_outputs/ui_ux_audit_20260922');
const baseline=path.join(output,'baseline.html'),preview=path.join(output,'preview.html');
const {chromium}=require(path.join(root,'.test_runtime/node_modules/playwright'));
function buildPreview(){
 const original=fs.readFileSync(baseline,'utf8'),data=original.match(/window.DASHBOARD_DATA_B64="([^"]+)"/)[1],
 raw=original.match(/window.DASHBOARD_RAW_B64=([\s\S]*?);<\/script>/)[1],
 logo=original.match(/class="brand-mark" src="([^"]+)"/)[1];
 let html=fs.readFileSync(path.join(templates,'dashboard.html'),'utf8');
 const values={__DASHBOARD_CSS__:fs.readFileSync(path.join(templates,'dashboard.css'),'utf8'),
 __DASHBOARD_DATA__:data,__DASHBOARD_RAW__:raw,__BRAND_LOGO__:logo,
 __DASHBOARD_JS__:['forecast-import.js','forecast-math.js','dashboard.js'].map(file=>fs.readFileSync(path.join(templates,file),'utf8')).join('\n')};
 for(const [key,value] of Object.entries(values))html=html.replace(key,()=>value);
 fs.writeFileSync(preview,html);
}
if(!process.env.UI_AUDIT_FINAL)buildPreview();
if(process.argv.includes('--build-only'))process.exit(0);
const file=process.env.UI_AUDIT_FINAL?path.join(root,'output_file/鸿蒙智行订单分析汇总.html'):preview;
const target='问界 M9 2026款',results={checks:[],screenshots:[],metrics:[],errors:[]};
const check=(name,value)=>{assert(value,name);results.checks.push(name);};
const urlFor=(file,params={})=>{const url=pathToFileURL(file);url.search=new URLSearchParams(params);return url.href;};
const waitForecast=page=>page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison?.rows?.length);
const numericSnapshot=page=>page.evaluate(()=>{
 const root=document.querySelector('.forecast-workspace'),c=root._forecastComparison;
 return {launch:{progress:c.progressRows,parameter:c.parameterRows},
 small:root._smallForecastResult,steady:root._steadyForecastResult};
});
(async()=>{
 fs.mkdirSync(path.join(output,'after'),{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
 page.on('pageerror',e=>results.errors.push(e.message));
 const shot=async name=>{await page.screenshot({path:path.join(output,'after',name+'.png')});results.screenshots.push(name+'.png');};
 await page.goto(urlFor(file));await page.waitForSelector('.kpi');await shot('overview-desktop');
 for(const grain of ['day','month','week']){
  const button=page.locator('[data-grain="'+grain+'"]');
  if(await button.isEnabled()){await button.click();await page.waitForFunction(grain=>new URL(location.href).searchParams.get('grain')===grain,grain);check('总览切换粒度 '+grain,true);}
 }
 const periods=await page.locator('#periodSelect option').count();
 if(periods>1){await page.selectOption('#periodSelect',{index:0});check('总览选择周期',await page.inputValue('#periodSelect')!==null);}
 await page.setViewportSize({width:390,height:900});await shot('overview-mobile');await page.setViewportSize({width:1440,height:1000});
 await page.selectOption('#subjectSelect',{label:target});await page.locator('[data-module="sales_forecast"]').click();await waitForecast(page);
 await page.locator('[data-forecast-stage-switch="launch"]').click();
 await shot('forecast-desktop');
 const finalUrl=page.url();await page.reload();await waitForecast(page);
 check('阶段入口仅保留顶部三项，左侧无重复',await page.locator('[data-forecast-stage-switch]').count()===3&&await page.locator('[data-forecast-stage-nav],#moduleNav .module-subnav').count()===0);
 check('操作按钮不再混在顶部导航',await page.locator('.forecast-target [data-forecast-jump]').count()===0);
 await page.locator('[data-forecast-tab="result"]').focus();await page.keyboard.press('ArrowRight');
 check('预测标签支持方向键',await page.locator('[data-forecast-tab="evidence"]').getAttribute('aria-selected')==='true');
 await shot('evidence-desktop');await page.keyboard.press('End');
 check('预测标签支持End键',await page.locator('[data-forecast-tab="score"]').getAttribute('aria-selected')==='true');
 await page.locator('[data-forecast-tab="result"]').click();
 for(const stage of ['small','steady','launch']){
  await page.locator('[data-forecast-stage-switch="'+stage+'"]').click();
  check('阶段切换 '+stage,await page.locator('[data-forecast-stage-pane="'+stage+'"]').evaluate(n=>n.classList.contains('active')));
  check('选中阶段反馈 '+stage,await page.locator('[data-forecast-stage-switch="'+stage+'"]').getAttribute('aria-pressed')==='true');
  check('快捷操作随当前阶段结果展示 '+stage,await page.locator('.forecast-stage-pane.active .forecast-result-actions button:visible').count()===2);
 }
 const unchanged=await numericSnapshot(page);
 const old=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
 await old.goto(urlFor(baseline,{module:'sales_forecast',subject:target,forecastStage:'launch',forecastView:'result'}));await waitForecast(old);
 assert.deepStrictEqual(await numericSnapshot(page),await numericSnapshot(old));check('三阶段计算结果与优化前一致',true);await old.close();
 for(const width of [1440,1024,768,390]){
  await page.setViewportSize({width,height:width===1440?1000:900});
  const metrics=await page.evaluate(()=>{
   const stage=document.querySelector('[data-forecast-stage-pane].active'),result=stage.querySelector('.forecast-scenarios,.forecast-lifecycle-kpis');
   return {width:innerWidth,documentWidth:document.documentElement.scrollWidth,firstResultTop:result.getBoundingClientRect().top,
    timestamp:document.querySelector('#updatedAt').getBoundingClientRect().toJSON(),
    controls:[...document.querySelectorAll('#updatedAt,#subjectSelect,#grainSelect,#periodSelect')].map(n=>n.getBoundingClientRect().toJSON())};
  });
  results.metrics.push(metrics);check(width+'px无整页横向溢出',metrics.documentWidth<=width+1);
  for(const a of metrics.controls)check(width+'px顶部控件在视口内',a.x>=0&&a.right<=width+1&&a.height>0);
  for(let i=0;i<metrics.controls.length;i++)for(let j=i+1;j<metrics.controls.length;j++){
   const a=metrics.controls[i],b=metrics.controls[j];assert(!(Math.min(a.right,b.right)-Math.max(a.x,b.x)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>1),'topbar overlap');
  }
  if(width===390){check('窄屏首屏可见预测结论',metrics.firstResultTop<900);const hero=await page.locator('[data-forecast-value="progress-gross"]').boundingBox();check('窄屏首屏可读到主要销量数值',hero.y+hero.height<=900);await shot('forecast-mobile');}
 }
 const settings=page.locator('.forecast-target-settings');
 check('车型与时间参数始终展开',await settings.evaluate(n=>n.tagName==='DIV'&&n.querySelectorAll('[data-forecast-target]').length===7&&!n.querySelector('summary')));
 await shot('settings-mobile');
 check('参数直接展开后无整页溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 const sourceDetails=page.locator('.forecast-source-details');await sourceDetails.locator('summary').click();
 check('数据来源展开后仍完整可读',await page.locator('[data-forecast-day-source]').isVisible()&&await page.locator('[data-forecast-time-summary]').isVisible());
 await sourceDetails.locator('summary').click();
 await page.locator('.forecast-stage-pane.active [data-forecast-jump="curve"]').click();check('曲线快捷定位',await page.locator('[data-forecast-decision-chart="progress"]').evaluate(n=>n===document.activeElement));
 await page.locator('.forecast-stage-pane.active [data-forecast-jump="import"]').click();
 const card=page.locator('[data-forecast-import="launch"]'),beforeImport=await numericSnapshot(page);
 const config=await page.locator('.forecast-workspace').evaluate(n=>JSON.parse(n.dataset.forecastConfig)),date=config.target.launch_date;
 const csv='车型（代际）,日期,预测数量\n'+target+','+date+',123';
 await card.locator('[data-forecast-import-file]').setInputFiles({name:'audit-forecast.csv',mimeType:'text/csv',buffer:Buffer.from(csv)});
 await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').dataset.state==='success');
 await card.locator('input[value="all"]').check();
 check('整个阶段导入包含已过日期',(await card.locator('[data-forecast-import-result]').innerText()).includes('123'));
 await card.locator('[data-forecast-import-file]').setInputFiles({name:'invalid.csv',mimeType:'text/csv',buffer:Buffer.from('车型,日期,预测数量\n'+target+','+date+',-1')});
 await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').dataset.state==='error');
 check('导入失败保留上次有效数据',(await card.locator('[data-forecast-import-result]').innerText()).includes('123'));
 await shot('import-error-mobile');
 assert.deepStrictEqual(await numericSnapshot(page),beforeImport);check('外部导入不改变真实值和算法结果',true);
 const download=page.waitForEvent('download');await card.locator('[data-forecast-import-template]').click();
 check('可下载逐日预测模板',(await download).suggestedFilename().endsWith('.csv'));
 await card.locator('[data-forecast-import-clear]').click();
 check('明确清除当前车型所有导入',(await card.locator('[data-forecast-import-result]').innerText()).includes('暂无'));
 await page.setViewportSize({width:1440,height:1000});
 const input=page.locator('[data-forecast-input="conversion"]');await input.fill('41.2');
 await page.waitForFunction(()=>document.querySelector('[data-forecast-feedback]').dataset.state==='success');
 check('参数更新有反馈且解除busy',await page.locator('.forecast-workspace').getAttribute('aria-busy')==='false');
 await page.locator('[data-module="overview"]').click();await page.locator('[data-module="sales_forecast"]').click();await waitForecast(page);
 check('切回预测保留参数草稿',await page.locator('[data-forecast-input="conversion"]').inputValue()==='41.2');
 await page.locator('[data-module="overview"]').click();await page.waitForSelector('[data-panel-source]');
 await page.locator('[data-panel-source]').first().click();await page.waitForSelector('#rawSearch');
 check('来源跳转同步URL便于后退',new URL(page.url()).searchParams.get('module')==='raw');
 await page.goBack();await page.waitForSelector('.kpi');check('来源返回恢复分析模块',new URL(page.url()).searchParams.get('module')==='overview');
 await page.locator('[data-module="raw"]').click();await page.waitForSelector('#rawSearch');
 await page.locator('[data-file="0"]').click();await page.waitForFunction(()=>document.querySelector('#rawFile')?.value==='0');
 await page.fill('#rawSearch','NO_MATCH_87654321');
 check('底表无结果明确提示',await page.locator('#rawEmpty').isVisible());
 check('底表搜索计数实时更新',(await page.locator('#rawMatchCount').innerText()).startsWith('0 '));
 await shot('raw-empty-desktop');
 await page.locator('#clearRawSearch').click();check('一键清空恢复数据',!(await page.locator('#rawEmpty').isVisible())&&await page.locator('#rawSearch').inputValue()==='');
 const exportDownload=page.waitForEvent('download');await page.locator('#exportRaw').click();check('底表CSV导出可用',(await exportDownload).suggestedFilename().endsWith('.csv'));
 await page.waitForFunction(()=>!document.querySelector('#toast').classList.contains('show'));
 await page.setViewportSize({width:390,height:900});
 await page.selectOption('#rawFile','1');await page.waitForFunction(()=>document.querySelector('#rawFile')?.value==='1'&&document.querySelector('[data-file="1"]')?.classList.contains('active'));
 check('手机文件下拉切换可用',await page.locator('#rawFile').isVisible());
 await page.selectOption('#rawFile','0');await page.waitForFunction(()=>document.querySelector('[data-file="0"]')?.classList.contains('active'));await shot('raw-mobile');
 check('底表窄屏无整页溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
 const checkbox=await page.locator('#rawFreezeRow').boundingBox();check('手机底表勾选框尺寸正常',checkbox.width<=22&&checkbox.height<=22);
 await page.goto(finalUrl);await waitForecast(page);
 const animation=await page.evaluate(()=>({duration:getComputedStyle(document.querySelector('.forecast-pane.active')).animationDuration,scroll:getComputedStyle(document.documentElement).scrollBehavior}));
 check('减少动态效果偏好得到尊重',animation.duration==='0s'&&animation.scroll==='auto');
 await page.emulateMedia({reducedMotion:'no-preference'});
 await page.locator('[data-forecast-tab="evidence"]').click();
 check('正常偏好有短促切换反馈',await page.locator('.forecast-pane.active').evaluate(n=>getComputedStyle(n).animationName==='forecast-pane-enter'));
 await page.locator('[data-forecast-tab="result"]').click();
 const busy=await page.locator('[data-forecast-input="conversion"]').evaluate(n=>{n.value='42';n.dispatchEvent(new Event('input',{bubbles:true}));return document.querySelector('[data-forecast-feedback]').dataset.state});
 check('参数输入立即反馈处理中',busy==='loading');
 await page.waitForFunction(()=>document.querySelector('[data-forecast-feedback]').dataset.state==='success');
 check('浏览器无脚本异常',results.errors.length===0);
 console.log(JSON.stringify({checks:results.checks.length,metrics:results.metrics.map(({width,firstResultTop,documentWidth})=>({width,firstResultTop,documentWidth})),errors:results.errors},null,2));
 }finally{await browser.close();fs.writeFileSync(path.join(output,process.env.UI_AUDIT_FINAL?'verification-final.json':'verification-preview.json'),JSON.stringify(results,null,2));}
})().catch(error=>{console.error(error);process.exitCode=1});
