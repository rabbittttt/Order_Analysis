// Browser regression for local drafts and external forecast merge/replace.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const root=path.resolve(__dirname,'../..'),{chromium}=require(path.join(root,'.test_runtime/node_modules/playwright'));
const file=process.env.FORECAST_STATE_HTML||path.join(root,'analysis_outputs/ui_ux_audit_20260922/preview.html');
const out=path.join(root,'analysis_outputs/forecast_compact_20260923');fs.mkdirSync(out,{recursive:true});
const target='问界 M9 2026款',report={checks:[],errors:[],layout:[]},check=(name,value)=>{assert(value,name);report.checks.push(name);console.log('PASS',name);};
const url=pathToFileURL(path.resolve(file));url.search=new URLSearchParams({module:'sales_forecast',subject:target,forecastStage:'launch',forecastView:'result'});
const ready=page=>page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison?.rows?.length);
const storage=page=>page.evaluate(()=>JSON.parse(localStorage.getItem('harmony-forecast-v1:'+location.pathname)||'{}'));
const records=async page=>(await storage(page)).imports?.find(([name])=>name===target)?.[1]?.rows||[];
const values=page=>page.evaluate(()=>{const r=document.querySelector('.forecast-workspace'),c=r._forecastComparison;return {progress:c.progressRows,parameter:c.parameterRows};});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  let page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(url.href);await ready(page);
  const original=await values(page),defaultConversion=await page.locator('[data-forecast-input="conversion"]').inputValue();
  check('车型时间参数不是折叠组件',await page.locator('.forecast-target-settings').evaluate(n=>n.tagName==='DIV'&&!n.querySelector('summary')));
  const enter=async(selector,value)=>{await page.locator(selector).fill(value);await page.locator(selector).dispatchEvent('change');await page.waitForFunction(()=>document.querySelector('[data-forecast-feedback]').dataset.state==='success');};
  await enter('[data-forecast-input="conversion"]','41.2');
  await enter('[data-bridge-stage="launch"] [data-bridge-control="holiday"]','1.8');
  let saved=await storage(page),draft=saved.drafts[0][1];
  check('未修改的总小订与同期完成率不写进草稿',!draft.controls.some(c=>/data-forecast-input=(small|progressSmallCompletion|progressDirectCompletion)(?:\||$)/.test(c.key)));
  await page.reload();await ready(page);
  check('刷新恢复人工转化率',await page.locator('[data-forecast-input="conversion"]').inputValue()==='41.2');
  check('刷新恢复节假日倍率',await page.locator('[data-bridge-stage="launch"] [data-bridge-control="holiday"]').inputValue()==='1.8');
  check('恢复后有明确反馈',(await page.locator('[data-forecast-feedback]').innerText()).includes('已恢复'));
  await page.locator('[data-forecast-stage-switch="small"]').click();
  await enter('[data-small-weight="0"]','65');
  await page.locator('[data-forecast-stage-switch="steady"]').click();
  await enter('[data-steady-weight="0"]','66');
  await page.reload();await ready(page);
  check('三个阶段分别保留人工参数',await page.locator('[data-small-weight="0"]').inputValue()==='65'&&await page.locator('[data-steady-weight="0"]').inputValue()==='66'&&await page.locator('[data-forecast-input="conversion"]').inputValue()==='41.2');
  await page.locator('[data-forecast-stage-switch="launch"]').click();
  const config=await page.locator('.forecast-workspace').evaluate(n=>JSON.parse(n.dataset.forecastConfig));
  const d1=config.target.launch_date,d2=new Date(Date.parse(d1+'T00:00:00Z')+86400000).toISOString().slice(0,10);
  const csv=rows=>'车型（代际）,日期,预测数量\n'+rows.map(([date,quantity])=>[target,date,quantity].join(',')).join('\n');
  const upload=async(stage,name,rows)=>{
   await page.locator('[data-forecast-stage-switch="'+stage+'"]').click();
   const panel=page.locator('[data-forecast-import="'+stage+'"]');
   await panel.locator('[data-forecast-import-file]').setInputFiles({name,mimeType:'text/csv',buffer:Buffer.from(csv(rows))});
   await page.waitForFunction(stage=>document.querySelector('[data-forecast-import="'+stage+'"] [data-forecast-import-status]').textContent.includes('导入成功'),stage);
   return panel;
  };
  let launch=await upload('launch','first.csv',[[d1,100]]);await launch.locator('input[value="all"]').check();
  await upload('launch','second.csv',[[d2,200]]);
  check('默认合并保留原有日期',(await records(page)).length===2&&(await launch.locator('[data-forecast-import-result]').innerText()).includes('300'));
  await upload('launch','correction.csv',[[d2,250]]);
  check('同阶段同日更新而非重复相加',(await records(page)).length===2&&(await launch.locator('[data-forecast-import-result]').innerText()).includes('350'));
  check('保留每条记录的来源文件',(await records(page)).find(r=>r.date===d1).source==='first.csv'&&(await records(page)).find(r=>r.date===d2).source==='correction.csv');
  const beforeBad=JSON.stringify(await records(page));
  await launch.locator('[data-forecast-import-file]').setInputFiles({name:'bad.csv',mimeType:'text/csv',buffer:Buffer.from(csv([[d1,-1]]))});
  await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').dataset.state==='error');
  check('错误文件不改内存或本机保存数据',JSON.stringify(await records(page))===beforeBad);
  await page.reload();await ready(page);
  launch=page.locator('[data-forecast-import="launch"]');
  check('刷新恢复外部预测及整个阶段范围',await launch.locator('input[value="all"]').isChecked()&&(await launch.locator('[data-forecast-import-result]').innerText()).includes('350'));
  const small=await upload('small','small.csv',[[d1,7]]);await small.locator('input[value="all"]').check();
  const overlap=await records(page);check('交界同日不同阶段不互相覆盖',overlap.filter(r=>r.date===d1).length===2&&overlap.some(r=>r.stage==='small'&&r.quantity===7)&&overlap.some(r=>r.stage==='launch'&&r.quantity===100));
  await page.locator('[data-forecast-stage-switch="launch"]').click();
  await launch.locator('[data-forecast-import-mode]').selectOption('replace');
  page.once('dialog',dialog=>dialog.dismiss());
  await launch.locator('[data-forecast-import-file]').setInputFiles({name:'replace.csv',mimeType:'text/csv',buffer:Buffer.from(csv([[d1,9]]))});
  await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').textContent.includes('已取消'));
  check('取消替换保留所有阶段记录',(await records(page)).length===3);
  page.once('dialog',dialog=>dialog.accept());
  await upload('launch','replace.csv',[[d1,9]]);
  check('确认全部替换后仅保留本文件',(await records(page)).length===1&&(await records(page))[0].quantity===9);
  assert.deepStrictEqual(await values(page),original);check('本次界面和导入操作不改变已结束日真实结果',true);
  await page.locator('.forecast-source-details summary').click();
  page.once('dialog',dialog=>dialog.accept());await page.locator('[data-forecast-reset]').click();
  await page.waitForFunction(v=>document.querySelector('[data-forecast-input="conversion"]')?.value===v,defaultConversion);
  check('恢复系统参数不删除外部导入',(await records(page)).length===1&&(await storage(page)).drafts.length===0);
  await page.reload();await ready(page);
  check('系统参数重置也能跨刷新保持',await page.locator('[data-forecast-input="conversion"]').inputValue()===defaultConversion);
  await page.locator('[data-forecast-import="launch"] [data-forecast-import-clear]').click();
  await page.reload();await ready(page);
  check('清除导入同步删除本机保存',(await records(page)).length===0);
  // Closing and reopening a page in the same browser context retains local storage.
  await enter('[data-forecast-input="conversion"]','42.7');
  await page.close();page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));await page.goto(url.href);await ready(page);
  check('关闭页面再打开仍能恢复',await page.locator('[data-forecast-input="conversion"]').inputValue()==='42.7');
  // Switching model must not move the current model's draft to the next one.
  const other=await page.evaluate(name=>window.DASHBOARD_DATA.subjects.find(s=>s.type==='generation'&&s.name!==name)?.id,target);
  await page.selectOption('#subjectSelect',other);
  await page.waitForFunction(id=>document.querySelector('.forecast-workspace')?._forecastSubjectId===id,other);
  check('切换车型不会把原车型草稿错存给新车型',!(await storage(page)).drafts.some(([key])=>key===other));
  await page.selectOption('#subjectSelect',{label:target});await ready(page);
  check('切回原车型恢复该车型自己的参数',await page.locator('[data-forecast-input="conversion"]').inputValue()==='42.7');
  // Restore defaults before layout screenshots.
  await page.locator('.forecast-source-details summary').click();page.once('dialog',d=>d.accept());await page.locator('[data-forecast-reset]').click();await page.waitForFunction(v=>document.querySelector('[data-forecast-input="conversion"]')?.value===v,defaultConversion);
  await page.waitForFunction(()=>!document.querySelector('#toast').classList.contains('show'));
  await page.locator('[data-forecast-stage-switch="launch"]').click();
  for(const width of [1440,1024,768,390]){
   await page.setViewportSize({width,height:900});
   const layout=await page.evaluate(()=>({width:innerWidth,pageWidth:document.documentElement.scrollWidth,scoreBottom:document.querySelector('[data-forecast-tab="score"]').getBoundingClientRect().bottom,targetHeight:document.querySelector('.forecast-target').getBoundingClientRect().height,
    fields:[...document.querySelectorAll('[data-forecast-target]')].map(n=>({key:n.dataset.forecastTarget,width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height,left:n.getBoundingClientRect().left,right:n.getBoundingClientRect().right}))}));
   report.layout.push(layout);check(width+'px全部7项参数直接可见',layout.fields.length===7&&layout.fields.every(f=>f.width>0&&f.height>0&&f.left>=0&&f.right<=width+1));
   check(width+'px无整页横向溢出',layout.pageWidth<=width+1);
   const limits={1440:200,1024:290,768:390,390:600};
   check(width+'px顶部至预测打分保持紧凑',layout.scoreBottom<=limits[width]);
   await page.screenshot({path:path.join(out,'forecast-'+width+'.png')});
  }
  for(const width of [1280,1180,1100,1030,1001,1000,900,820,640,600,360]){
   await page.setViewportSize({width,height:900});
   check(width+'px断点附近日期有足够显示宽度',await page.locator('.forecast-target input[type=date]').evaluateAll(inputs=>inputs.every(n=>n.clientWidth>=108)));
   check(width+'px断点附近无整页溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  }
  await page.evaluate(()=>localStorage.setItem('harmony-forecast-v1:'+location.pathname,'{broken'));
  await page.reload();await ready(page);
  check('损坏的本机记录不会阻止页面预测',(await page.locator('[data-forecast-feedback]').innerText()).includes('不可用'));
  check('不会静默删除损坏的原记录',await page.evaluate(()=>localStorage.getItem('harmony-forecast-v1:'+location.pathname))==='{broken');
  await page.close();await context.close();
  const limited=await browser.newContext({viewport:{width:1440,height:900}});
  await limited.addInitScript(()=>{Storage.prototype.setItem=function(){throw new DOMException('full','QuotaExceededError')}});
  const blocked=await limited.newPage();blocked.on('pageerror',e=>report.errors.push(e.message));await blocked.goto(url.href);await ready(blocked);
  await blocked.locator('[data-forecast-input="conversion"]').fill('43.5');
  await blocked.waitForFunction(()=>document.querySelector('[data-forecast-feedback]').textContent.includes('保存失败'));
  check('浏览器空间不足时明确提示但不阻断计算',await blocked.locator('.forecast-workspace').getAttribute('aria-busy')==='false');
  await limited.close();check('没有脚本异常',report.errors.length===0);
 }finally{await browser.close();fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify({checks:report.checks.length,layout:report.layout.map(({width,scoreBottom,targetHeight})=>({width,scoreBottom,targetHeight})),errors:report.errors},null,2));
})().catch(error=>{console.error(error);process.exitCode=1});
