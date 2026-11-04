// Local, offline end-to-end UX audit. Run from the repository root.
// UI_AUDIT_FINAL=1 tests the official generated page; otherwise rebuild a preview
// from the immutable audit baseline and current templates (same data, new UI).
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const codeRoot=path.resolve(__dirname,'../..');
const root=path.basename(codeRoot).toLowerCase()==='scripts'?path.dirname(codeRoot):codeRoot;
const templates=path.join(codeRoot,'generate_html/templates');
const output=path.join(root,'analysis_outputs/ui_ux_audit_20260922');
const baseline=path.join(output,'baseline.html'),preview=path.join(output,'preview.html');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(root,'.test_runtime/node_modules/playwright'));
function buildPreview(){
 const original=fs.readFileSync(baseline,'utf8'),data=original.match(/window.DASHBOARD_DATA_B64="([^"]+)"/)[1],
 raw=original.match(/window.DASHBOARD_RAW_B64=([\s\S]*?);<\/script>/)[1],
 logo=original.match(/class="brand-mark" src="([^"]+)"/)[1];
 let html=fs.readFileSync(path.join(templates,'dashboard.html'),'utf8');
 const values={__DASHBOARD_CSS__:fs.readFileSync(path.join(templates,'dashboard.css'),'utf8'),
 __DASHBOARD_DATA__:data,__DASHBOARD_RAW__:raw,__BRAND_LOGO__:logo,
 __DASHBOARD_BLOCKS__:original.match(/window.DASHBOARD_BLOCKS_B64=([\s\S]*?);<\/script>/)?.[1]||'{}',
 __DASHBOARD_JS__:fs.readFileSync(path.join(templates,'dashboard.js'),'utf8')};
 for(const [key,value] of Object.entries(values))html=html.replace(key,()=>value);
 fs.writeFileSync(preview,html);
}
if(!process.env.UI_AUDIT_FINAL)buildPreview();
if(process.argv.includes('--build-only'))process.exit(0);
const file=process.env.UI_AUDIT_FINAL?path.join(root,'output_file/鸿蒙智行订单分析汇总.html'):preview;
const results={checks:[],screenshots:[],metrics:[],errors:[]};
const check=(name,value)=>{assert(value,name);results.checks.push(name);};
const urlFor=(file,params={})=>{const url=pathToFileURL(file);url.search=new URLSearchParams(params);return url.href;};
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
 check('浏览器无脚本异常',results.errors.length===0);
 console.log(JSON.stringify({checks:results.checks.length,metrics:results.metrics,errors:results.errors},null,2));
 }finally{await browser.close();fs.writeFileSync(path.join(output,process.env.UI_AUDIT_FINAL?'verification-final.json':'verification-preview.json'),JSON.stringify(results,null,2));}
})().catch(error=>{console.error(error);process.exitCode=1});
