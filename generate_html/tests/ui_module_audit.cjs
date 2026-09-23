// Visit every module with an available subject, in desktop and mobile viewports.
// This is a visual/rendering smoke audit, not exhaustive data validation.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'analysis_outputs/ui_ux_audit_20260922');
const {chromium}=require(path.join(root,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),report=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const current=process.env.UI_AUDIT_FINAL?path.join(root,'output_file/鸿蒙智行订单分析汇总.html'):path.join(out,'preview.html');
  await page.goto(pathToFileURL(current).href);await page.waitForSelector('.kpi');
  const modules=await page.evaluate(()=>window.DASHBOARD_DATA.config.module_order.map(id=>{
   const data=window.DASHBOARD_DATA,subject=data.subjects.find(s=>s.type==='generation'&&s.modules.includes(id))||data.subjects.find(s=>s.modules.includes(id));
   return {id,label:data.config.module_labels[id],subject:subject?.id};
  }));
  for(const module of modules){
   if(['overview','sales_forecast','raw'].includes(module.id))continue;
   if(!module.subject){report.push({...module,skipped:'当前样例无可用主体'});continue;}
   for(const [version,file] of [['before',path.join(out,'baseline.html')],['after',current]]){
    const url=pathToFileURL(file);url.search=new URLSearchParams({module:module.id,subject:module.subject});
    await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('#page')?.children.length);
    for(const width of [1440,390]){
     await page.setViewportSize({width,height:width===1440?1000:900});
     const dimensions=await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,content:document.querySelector('#page').innerText.slice(0,100)}));
     await page.screenshot({path:path.join(out,version,module.id+'-'+(width===1440?'desktop':'mobile')+'.png')});
     report.push({...module,version,...dimensions});
    }
   }
   console.log('AUDITED',module.label);
  }
  report.push({errors});
  fs.writeFileSync(path.join(out,'module-audit.json'),JSON.stringify(report,null,2));
  assert.equal(errors.length,0);
  const overflow=report.filter(r=>r.version==='after'&&r.documentWidth>r.width+1);
  console.log(JSON.stringify({modules:modules.length,overflow},null,2));assert.equal(overflow.length,0);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
