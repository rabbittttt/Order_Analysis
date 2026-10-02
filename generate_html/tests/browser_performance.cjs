// Benchmark the formal main.py output only. No generated HTML is edited.
const fs=require('fs'),path=require('path'),os=require('os'),crypto=require('crypto');
const {pathToFileURL}=require('url'),{execFileSync}=require('child_process');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const arg=(key,fallback)=>process.argv.find(s=>s.startsWith('--'+key+'='))?.split('=').slice(1).join('=')||fallback;
const label=arg('label','baseline'),runs=Number(arg('runs','5')),profile=process.argv.includes('--profile');
const file=path.join(project,'output_file/鸿蒙智行订单分析汇总.html');
const out=path.join(project,'.test_outputs/performance_20261002');
const report={label,profile,runs,created:new Date().toISOString(),environment:{cpu:os.cpus()[0]?.model,logicalCpus:os.cpus().length,totalMemoryMiB:os.totalmem()/1048576,platform:os.platform(),viewport:'1440x1000',headless:true,reducedMotion:'reduce',htmlBytes:fs.statSync(file).size,htmlSha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')},samples:[],errors:[]};
const url=params=>{const u=pathToFileURL(file);u.search=new URLSearchParams(params);return u.href};
const median=xs=>[...xs].sort((a,b)=>a-b)[Math.floor(xs.length/2)];
function memory(processes){
 const ids=processes.map(p=>p.id).filter(Number.isInteger).join(',');
 const command=`$items=Get-Process -Id ${ids} -ErrorAction SilentlyContinue;[pscustomobject]@{workingSetMiB=($items|Measure-Object WorkingSet64 -Sum).Sum/1MB;privateMiB=($items|Measure-Object PrivateMemorySize64 -Sum).Sum/1MB;processes=$items.Count}|ConvertTo-Json -Compress`;
 return JSON.parse(execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-Command',command],{encoding:'utf8',windowsHide:true}));
}
function profileSummary(data){
 const nodes=new Map(data.nodes.map(n=>[n.id,n])),parents=new Map(),self=new Map(),inclusive=new Map();
 for(const n of data.nodes)for(const id of n.children||[])parents.set(id,n.id);
 (data.samples||[]).forEach((id,i)=>{const ms=(data.timeDeltas[i]||0)/1000;self.set(id,(self.get(id)||0)+ms);for(let n=id;n;n=parents.get(n))inclusive.set(n,(inclusive.get(n)||0)+ms)});
 const ranked=map=>[...map].map(([id,ms])=>({function:nodes.get(id).callFrame.functionName||'(anonymous)',line:nodes.get(id).callFrame.lineNumber+1,ms})).sort((a,b)=>b.ms-a.ms).slice(0,24);
 return {self:ranked(self),inclusive:ranked(inclusive)};
}
(async()=>{
 fs.mkdirSync(out,{recursive:true});
 if(fs.existsSync(path.join(out,label+'.json')))throw Error('Benchmark label already exists; choose a new --label to preserve evidence');
 for(let run=0;run<runs;run++){
  const browser=await chromium.launch({headless:true,channel:'msedge'}),control=await browser.newBrowserCDPSession();
  report.environment.browser=browser.version();
  const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai',reducedMotion:'reduce'});
  page.on('pageerror',e=>report.errors.push(e.message));
  await page.addInitScript(()=>{window.__perfLongTasks=[];new PerformanceObserver(list=>window.__perfLongTasks.push(...list.getEntries().map(e=>({start:e.startTime,duration:e.duration})))).observe({type:'longtask',buffered:true})});
  const cdp=await page.context().newCDPSession(page);await cdp.send('Performance.enable');
  const metrics=async()=>Object.fromEntries((await cdp.send('Performance.getMetrics')).metrics.map(m=>[m.name,m.value]));
  const processes=async()=>(await control.send('SystemInfo.getProcessInfo')).processInfo;
  const ready=()=>page.waitForFunction(()=>window.DASHBOARD_DATA&&document.querySelector('#page')?.getAttribute('aria-busy')==='false');
  const paint=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  async function measure(name,action,options={}){
   const a=await metrics(),pa=await processes();
   const mark=await page.evaluate(()=>performance.now());
   if(profile&&options.profile){await cdp.send('Profiler.enable');await cdp.send('Profiler.start')}
   const start=performance.now();await action();await paint();const wallMs=performance.now()-start;
   const b=await metrics(),pb=await processes();
   const cpuMs=pb.reduce((sum,p)=>sum+Math.max(0,p.cpuTime-(pa.find(q=>q.id===p.id)?.cpuTime||0))*1000,0);
   const tasks=await page.evaluate(mark=>(window.__perfLongTasks||[]).filter(e=>e.start>=mark),options.navigation?0:mark);
   const result={run:run+1,name,wallMs,mainThreadMs:(b.TaskDuration-a.TaskDuration)*1000,scriptMs:(b.ScriptDuration-a.ScriptDuration)*1000,layoutMs:(b.LayoutDuration-a.LayoutDuration)*1000,recalcStyleMs:(b.RecalcStyleDuration-a.RecalcStyleDuration)*1000,browserCpuMs:cpuMs,cpuPercentOneCore:cpuMs/wallMs*100,cpuPercentMachine:cpuMs/wallMs*100/os.cpus().length,jsHeapMiB:b.JSHeapUsedSize/1048576,domNodes:b.Nodes,longTasks:tasks.length,longTaskTotalMs:tasks.reduce((sum,t)=>sum+t.duration,0),maxLongTaskMs:Math.max(0,...tasks.map(t=>t.duration))};
   if(profile&&options.profile){const data=(await cdp.send('Profiler.stop')).profile;fs.writeFileSync(path.join(out,label+'-'+name+'.cpuprofile'),JSON.stringify(data));result.profile=profileSummary(data)}
   if(options.memory)result.memory=memory(pb);
   report.samples.push(result);console.log(JSON.stringify({run:run+1,name,ms:Math.round(wallMs),cpuMs:Math.round(cpuMs),heap:Math.round(result.jsHeapMiB),nodes:result.domNodes,memory:result.memory}));
  }
  try{
   await measure('cold_overview',async()=>{await page.goto(url({module:'overview'}));await ready()},{navigation:true,memory:true});
   const model=await page.evaluate(()=>window.DASHBOARD_DATA.subjects.find(s=>s.name==='问界 M9 2026款')||window.DASHBOARD_DATA.subjects.find(s=>s.type==='generation'&&s.modules.includes('sales_forecast')));
   report.model=model.name;
   await page.selectOption('#subjectSelect',model.id);await ready();
   await measure('enter_forecast',async()=>{await page.locator('[data-module="sales_forecast"]').click();await ready();await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison)},{memory:true,profile:true});
   await page.locator('[data-forecast-stage-switch="launch"]').click();await page.locator('[data-forecast-tab="result"]').click();
   await measure('parameter_change',async()=>{await page.locator('[data-forecast-input="conversion"]').fill('42.7');await page.waitForFunction(()=>document.querySelector('[data-forecast-feedback]')?.dataset.state==='success')},{memory:true,profile:true});
   await measure('evidence_tab',async()=>{await page.locator('[data-forecast-tab="evidence"]').click();await page.waitForFunction(()=>document.querySelector('[data-forecast-tab="evidence"]').getAttribute('aria-selected')==='true')},{profile:true});
   await measure('stage_switch',async()=>{await page.locator('[data-forecast-stage-switch="steady"]').click();await page.waitForFunction(()=>document.querySelector('#periodContext').textContent.includes('平销'))});
   await measure('raw_open',async()=>{await page.locator('[data-module="raw"]').click();await ready();await page.waitForSelector('#rawSearch')},{memory:true});
   await measure('raw_search',async()=>{await page.locator('#rawSearch').fill('NO_MATCH_PERF');await page.waitForSelector('#rawEmpty:not([hidden])')});
   await measure('return_forecast',async()=>{await page.locator('[data-module="sales_forecast"]').click();await ready()},{memory:true});
   await cdp.send('HeapProfiler.collectGarbage');
   const retained=await metrics();report.samples.push({run:run+1,name:'retained_after_gc',jsHeapMiB:retained.JSHeapUsedSize/1048576,domNodes:retained.Nodes,memory:memory(await processes())});
   // Numeric snapshot excludes DOM and functions; identical data/input must yield identical values.
   const values=await page.locator('.forecast-workspace').evaluate(n=>({launch:n._forecastComparison,small:n._smallForecastResult,steady:n._steadyForecastResult}));
   report.samples.push({run:run+1,name:'numeric_snapshot',sha256:crypto.createHash('sha256').update(JSON.stringify(values)).digest('hex')});
   await page.locator('[data-forecast-stage-switch="launch"]').click();
   await measure('score_first_open',async()=>{await page.locator('[data-forecast-tab="score"]').click();await page.waitForSelector('[data-forecast-score-task]')});
   await page.close();
   const cold=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
   const start=performance.now();await cold.goto(url({module:'sales_forecast',subject:model.id,forecastStage:'launch',forecastView:'result'}));await cold.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false');await cold.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
   report.samples.push({run:run+1,name:'fresh_page_forecast',wallMs:performance.now()-start});await cold.close();
  }finally{await browser.close();fs.writeFileSync(path.join(out,label+'.json'),JSON.stringify(report,null,2))}
 }
 if(crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==report.environment.htmlSha256)throw Error('Formal HTML changed during benchmark; discard this run');
 report.summary={};for(const name of [...new Set(report.samples.map(s=>s.name))]){const rows=report.samples.filter(s=>s.name===name);report.summary[name]={};for(const key of Object.keys(rows[0]).filter(k=>typeof rows[0][k]==='number'&&k!=='run'))report.summary[name][key]=median(rows.map(r=>r[key]));if(rows[0].memory)report.summary[name].memory=Object.fromEntries(Object.keys(rows[0].memory).map(k=>[k,median(rows.map(r=>r.memory[k]))]));}
 fs.writeFileSync(path.join(out,label+'.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({summary:report.summary,errors:report.errors},null,2));
 if(report.errors.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
