// End-to-end interactions on the actual main.py output, with isolated browser storage.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(project,'.test_runtime/node_modules/playwright'));
const out=path.join(project,'.test_outputs/ui_audit_20261002/after');
const base=new URL(process.env.DASHBOARD_URL||'http://127.0.0.1:8767/');
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'}),checks=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const network=[];page.on('request',request=>{if(/^https?:/.test(request.url()))network.push(request.url())});
 const check=(name,value)=>{assert(value,name);checks.push(name);console.log('PASS',name)};
 const ready=()=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false'&&window.DASHBOARD_DATA);
 try{
  const url=new URL(base);url.search=new URLSearchParams({module:'overview',subject:'问界 M9 2026款'});await page.goto(url.href);await ready();
  for(const grain of ['day','week','month']){
   const button=page.locator('[data-grain="'+grain+'"]');
   if(await button.isEnabled()){
    await button.click();await ready();check('切换粒度 '+grain,new URL(page.url()).searchParams.get('grain')===grain);
    const periods=await page.locator('[data-history-body] tbody tr td:first-child').allTextContents();
    const pattern={day:/^\d{4}-\d{2}-\d{2}$/,week:/^\d{2}WK\d{2}$/,month:/^\d{2}-\d{2}$/}[grain];
    check('经营指标趋势显示对应周期 '+grain,periods.length>0&&periods.every(value=>pattern.test(value.trim())));
   }
  }
  await page.locator('[data-panel-source]').last().scrollIntoViewIfNeeded();
  const originalScroll=await page.locator('#page').evaluate(n=>n.scrollTop);check('来源入口位于滚动后位置',originalScroll>0);
  await page.locator('[data-panel-source]').last().click();await page.waitForSelector('#rawSearch');
  const sourceFile=await page.locator('#rawFile').inputValue(),sourceSheet=await page.locator('#rawSheet').inputValue();
  await page.goBack();await page.waitForSelector('.kpi');await ready();
  check('从来源返回恢复阅读位置',Math.abs(await page.locator('#page').evaluate(n=>n.scrollTop)-originalScroll)<2);
  await page.goForward();await page.waitForSelector('#rawSearch');
  check('前进恢复来源文件和Sheet',await page.locator('#rawFile').inputValue()===sourceFile&&await page.locator('#rawSheet').inputValue()===sourceSheet);
  await page.locator('#rawSearch').fill('NO_MATCH_UI_AUDIT');await page.reload();await page.waitForSelector('#rawSearch');
  check('底表刷新保留搜索和位置',await page.locator('#rawSearch').inputValue()==='NO_MATCH_UI_AUDIT'&&await page.locator('#rawEmpty').isVisible()&&await page.locator('#rawSheet').inputValue()===sourceSheet);
  await page.locator('#clearRawSearch').click();check('清空底表搜索恢复行',!await page.locator('#rawEmpty').isVisible());
  const download=page.waitForEvent('download');await page.locator('#exportRaw').click();check('底表导出可用',(await download).suggestedFilename().endsWith('.csv'));
  await page.waitForFunction(()=>!document.querySelector('#toast').classList.contains('show'));
  check('订单导航无销量预测入口',await page.locator('[data-module="sales_forecast"],#moduleSelect option[value="sales_forecast"]').count()===0);

  check('默认锁定首行和首列',await page.locator('#rawFreezeRow').isChecked()&&await page.locator('#rawFreezeFirstColumn').isChecked()&&!await page.locator('#rawFreezeColumn').isChecked());
  await page.locator('#rawFreezeColumn').check();
  check('标题列与首列互斥',!await page.locator('#rawFreezeFirstColumn').isChecked()&&await page.locator('#rawFreezeColumn').isChecked());
  await page.locator('#rawFreezeFirstColumn').check();
  await page.waitForFunction(()=>document.querySelector('#rawTable [data-raw-col="0"]')?.classList.contains('raw-frozen-column'));
  check('首列固定位置生效',!await page.locator('#rawFreezeColumn').isChecked()&&await page.locator('#rawTable [data-raw-col="0"]').first().evaluate(n=>getComputedStyle(n).position)==='sticky');
  await page.locator('#rawFreezeRow').uncheck();check('解除首行锁定',!await page.locator('#rawTable').evaluate(n=>n.classList.contains('freeze-row')));
  await page.locator('#rawFreezeRow').check();
  const file=await page.evaluate(()=>window.DASHBOARD_DATA.raw_files[Number(document.querySelector('#rawFile').value)]);
  check('当前底表包含完整原始Excel',!!file.workbook_key);
  await page.locator('#rawSearch').fill('NO_MATCH_EXCEL_EXPORT');
  const workbookDownload=page.waitForEvent('download');await page.locator('#exportRawWorkbook').click();const workbook=await workbookDownload;
  check('完整Excel下载保留文件名',workbook.suggestedFilename()===file.name);
  const dataset=await page.evaluate(()=>window.DASHBOARD_DATA.dataset_id);
  const expected=dataset?fs.readFileSync(path.join(project,'output_file/runtime/datasets',dataset,'workbooks',file.workbook_key.split('|')[0]+'.xlsx')):Buffer.from(await page.evaluate(key=>window.DASHBOARD_RAW_B64[key],file.workbook_key),'base64');
  check('全部Sheet和原格式原样导出且不受筛选影响',fs.readFileSync(await workbook.path()).equals(expected));
  await page.locator('#clearRawSearch').click();
  await page.setViewportSize({width:390,height:844});
  check('手机显示模块选择器',await page.locator('#moduleSelect').isVisible());
  check('手机显示底表文件选择器',await page.locator('#rawFile').isVisible());
  check('手机页面无横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  const count=await page.locator('#rawFile option').count();
  if(count>1){
   const next=(Number(await page.locator('#rawFile').inputValue())+1)%count;
   await page.locator('#rawFile').selectOption(String(next));
   await page.waitForFunction(next=>document.querySelector(`[data-file="${next}"]`)?.classList.contains('active'),next);
   check('手机底表文件切换',await page.locator('#rawFile').inputValue()===String(next));
  }
  await page.locator('#moduleSelect').selectOption('overview');await page.waitForSelector('.kpi');await ready();
  check('手机模块切换回订单总览',new URL(page.url()).searchParams.get('module')==='overview');
  const subjects=await page.evaluate(()=>window.DASHBOARD_DATA.subjects.filter(s=>s.modules.includes('overview')).map(s=>s.id));
  const current=await page.locator('#subjectSelect').inputValue(),nextSubject=subjects.find(id=>id!==current);assert(nextSubject,'需要两个可用订单主体');
  await page.locator('#subjectSelect').selectOption(nextSubject);await ready();
  await page.waitForFunction(id=>new URL(location.href).searchParams.get('subject')===id,nextSubject);
  check('手机主体切换同步网址',await page.locator('#subjectSelect').inputValue()===nextSubject);
  check('切换主体后仍有订单指标',await page.locator('.kpi strong').count()>0);
  await page.screenshot({path:path.join(out,'order-overview-390.png')});
  await page.locator('#moduleSelect').selectOption('raw');await page.waitForSelector('#rawSearch');
  check('手机可直接到达底表中心',new URL(page.url()).searchParams.get('module')==='raw');
  await page.screenshot({path:path.join(out,'order-raw-390.png')});
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('[data-module="overview"]').click();await page.waitForSelector('.kpi');await ready();
  check('新模块从顶部开始',await page.locator('#page').evaluate(n=>n.scrollTop)===0);
  check('订单页面没有加载预测引擎',await page.evaluate(()=>window.ForecastMath===undefined&&window.ForecastImport===undefined));
  check('减少动态效果偏好得到尊重',await page.locator('html').evaluate(n=>getComputedStyle(n).scrollBehavior)==='auto');
  if(base.protocol==='file:'){check('静态页没有HTTP请求',network.length===0);check('静态页未启用动态API',!await page.evaluate(()=>window.ORDER_DASHBOARD_API_BASE));}
  check('无浏览器异常',errors.length===0);
 }finally{await browser.close();fs.writeFileSync(path.join(out,'workflow-report.json'),JSON.stringify({checks,errors},null,2));}
 console.log(JSON.stringify({checks:checks.length,errors}));
})().catch(error=>{console.error(error);process.exitCode=1});
