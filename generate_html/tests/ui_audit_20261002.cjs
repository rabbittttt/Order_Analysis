// Audit the formal main.py output only; screenshots never modify its data.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const phase=process.argv.includes('--before')?'before':'after';
const output=path.join(project,'.test_outputs/ui_audit_20261002',phase);
const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
const results={phase,pages:[],errors:[]};
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
 page.on('pageerror',e=>results.errors.push(e.message));
 const ready=()=>page.waitForFunction(()=>window.DASHBOARD_DATA&&document.querySelector('#page')?.getAttribute('aria-busy')==='false');
 async function visit(key,params){
  const url=new URL(base);url.search=new URLSearchParams(params);await page.goto(url.href);await ready();
  const entry={key,params,widths:[]};
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:width===1440?1000:844});
   await page.evaluate(()=>{document.querySelector('#page').scrollTop=0;document.querySelector('.module-bar').scrollTop=0;});
   await page.screenshot({path:path.join(output,key+'-'+width+'.png')});
   entry.widths.push(await page.evaluate(()=>({width:innerWidth,documentWidth:document.documentElement.scrollWidth,
    page:document.querySelector('#page').getBoundingClientRect().toJSON(),
    headerHeight:document.querySelector('.topbar').getBoundingClientRect().height,
    navHeight:document.querySelector('.module-bar').getBoundingClientRect().height,
    controls:[...document.querySelectorAll('button,input,select,summary')].filter(n=>n.checkVisibility()).map(n=>({text:(n.innerText||n.getAttribute('aria-label')||n.name||n.type).slice(0,55),tag:n.tagName,rect:n.getBoundingClientRect().toJSON(),font:getComputedStyle(n).fontSize})).filter(n=>n.rect.top<innerHeight&&n.rect.bottom>0),
    content:document.querySelector('#page').innerText.slice(0,180)
   })));
  }
  if(params.module==='sales_forecast')entry.values=await page.evaluate(()=>{const root=document.querySelector('.forecast-workspace');return {comparison:root._forecastComparison,small:root._smallForecastResult,steady:root._steadyForecastResult};});
  results.pages.push(entry);console.log('AUDIT',key);
 }
 try{
  await page.goto(base.href);await ready();
  const data=await page.evaluate(()=>({subjects:window.DASHBOARD_DATA.subjects,modules:window.DASHBOARD_DATA.config.module_order}));
  const generation=data.subjects.find(s=>s.name==='问界 M9 2026款')||data.subjects.find(s=>s.type==='generation'&&s.modules.includes('sales_forecast'));
  for(const module of data.modules){
   if(module==='sales_forecast')continue;
   const subject=module==='raw'?data.subjects[0]:data.subjects.find(s=>s.type==='generation'&&s.modules.includes(module))||data.subjects.find(s=>s.modules.includes(module));
   if(subject)await visit(module,{module,subject:subject.id});
   else results.pages.push({key:module,skipped:'当前本地数据无可用主体'});
  }
  for(const stage of ['small','launch','steady'])for(const view of ['result','evidence','score'])
   await visit('forecast-'+stage+'-'+view,{module:'sales_forecast',subject:generation.id,forecastStage:stage,forecastView:view});
  if(phase==='after'){
   assert.deepEqual(results.errors,[]);
   const before=JSON.parse(fs.readFileSync(path.join(output,'../before/report.json'),'utf8'));
   for(const entry of results.pages){
    for(const size of entry.widths||[])assert(size.documentWidth<=size.width+1,entry.key+' horizontal overflow');
    // Baseline JSON omits undefined object properties; compare the same serialized shape.
    if(entry.values)assert.deepEqual(JSON.parse(JSON.stringify(entry.values)),before.pages.find(p=>p.key===entry.key).values,entry.key+' prediction values changed');
   }
  }
 }finally{await browser.close();fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(results,null,2));}
 console.log(JSON.stringify({phase,pages:results.pages.length,errors:results.errors}));
})().catch(e=>{console.error(e);process.exitCode=1;});
