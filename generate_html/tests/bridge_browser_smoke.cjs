const fs=require('fs'),path=require('path'),zlib=require('zlib'),assert=require('assert');
const codeRoot=path.resolve(__dirname,'../..');
const root=path.basename(codeRoot).toLowerCase()==='scripts'?path.dirname(codeRoot):codeRoot;
const testOutputRoot=path.join(root,'.test_outputs','forecast_bridge_validation');
const {chromium}=require(path.join(root,'.test_runtime/node_modules/playwright'));
const templates=path.resolve(__dirname,'../templates');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.BRIDGE_TEST_BROWSER||'msedge'});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000},timezoneId:'Asia/Shanghai'});
 await page.clock.install({time:new Date('2026-09-04T12:00:00+08:00')});
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 const data={config:{module_labels:{}},meta:{generated_at:'2026-09-04'},subjects:[]};
 await page.setContent('<main id="page"></main>');
 await page.addStyleTag({content:fs.readFileSync(path.join(templates,'dashboard.css'),'utf8')});
 await page.evaluate(b64=>window.DASHBOARD_DATA_B64=b64,zlib.gzipSync(JSON.stringify(data)).toString('base64'));
 await page.addScriptTag({content:fs.readFileSync(path.join(templates,'forecast-import.js'),'utf8')});
 await page.addScriptTag({content:fs.readFileSync(path.join(templates,'forecast-math.js'),'utf8')});
 let script=fs.readFileSync(path.join(templates,'dashboard.js'),'utf8');
 script=script.replace('  init();','  window.bridgeTest={forecastReferenceCurve,rebasedForecastCompletion,bridgeSettings,renderForecastWorkspaceV2,bindForecastWorkspaceV2,state,captureForecastDraft,restoreForecastDraft,activateForecastStage};');
 await page.addScriptTag({content:script});await page.waitForFunction(()=>window.bridgeTest);
 const tail=await page.evaluate(()=>{
   const partial={days:8,small_progress:[.1,.2,.3,.3,.3,.3,.3,.3],daily_small:[100,100,100,null,null,null,null,null]};
   const a=window.bridgeTest.forecastReferenceCurve(partial,'small_progress'),b=window.bridgeTest.rebasedForecastCompletion(partial,'small_progress',3,8);
   const zero=window.bridgeTest.forecastReferenceCurve({...partial,daily_small:[100,100,100,0,0,0,0,0]},'small_progress');
   return {a,b,zero};
 });
 assert.equal(tail.a.length,3);assert(tail.b.extrapolated);assert(tail.b.value<1);assert.equal(tail.zero.length,8);
 const ref={model:'reference',generation:'reference',brand:'test',tier:'SUV',energy:'增程',node:'年度换代',days:8,launch_date:'2026-08-01',small:1000,gross:1000,conversion:.6,direct_share:.4,lock_rate:.8,net_rate:.9,daily_orders:[100,100,100,100,100,100,100,300],daily_small:[60,60,60,60,60,60,60,180],daily_direct:[40,40,40,40,40,40,40,120],small_progress:[.1,.2,.3,.4,.5,.6,.7,1],direct_progress:[.1,.2,.3,.4,.5,.6,.7,1],hourly_curve:Array.from({length:24},(_,i)=>(i+1)/24),d1_gross:100,d1_small_share:.6};
 const weeks=Array.from({length:4},(_,i)=>({period:'26WK'+(32+i),start_date:new Date(Date.UTC(2026,7,3+i*7)).toISOString().slice(0,10),end_date:new Date(Date.UTC(2026,7,9+i*7)).toISOString().slice(0,10),lock:700,week:i+1}));
 const fixture={target:{name:'current',tier:'SUV',energy:'增程',launch_node:'年度换代',launch_date:'2026-08-31',launch_days:8,total_small:1000,conversion:.6,direct_share:.4,lock_rate:.8,small_start_date:'2026-08-20',small_end_date:'2026-08-30',steady_start_date:'2026-09-08'},targets:[{name:'current',launch_date:'2026-08-31',end_date:'2026-09-07',small_start_date:'2026-08-20',small_end_date:'2026-08-30',steady_start_date:'2026-09-08'}],history:[ref],small_order_history:[{...ref,total:1000,small_start_date:'2026-08-01',event_id:'ref',days:8}],steady_history:[{...ref,weeks,event_id:'steady-ref',steady_start_date:'2026-07-01'}],actuals:[{model:'current',total_small:1000,days:Array.from({length:4},(_,i)=>({day:'D'+(i+1),date:new Date(Date.UTC(2026,7,31+i)).toISOString().slice(0,10),gross:100,small_to_big:60,direct:40,lock:80}))}],tasks:['hourly','small_progress','direct_progress','conversion','direct_share','lock','daily','daily_slope'].map(key=>({key,label:key,purpose:key,recommended:['reference']})),china_calendar:{holidays:{'2026-09-06':'test holiday'},adjusted_workdays:['2026-09-05'],published_years:[2026]}};
 fixture.history.push({...ref,model:'daily-alternate',daily_orders:[100,100,100,100,200,100,50,350]});
 await page.evaluate(f=>{window.fixture=f;const api=window.bridgeTest;api.state.module='sales_forecast';api.state.subject='current';api.state.forecastStage='launch';document.querySelector('#page').innerHTML=api.renderForecastWorkspaceV2(f);api.bindForecastWorkspaceV2()},fixture);
 const read=()=>page.evaluate(()=>{const root=document.querySelector('.forecast-workspace'),c=root._forecastComparison;return {progress:c.progressRows,parameter:c.parameterRows,progressTotal:Math.round(c.scenarios.progress.gross),parameterTotal:Math.round(c.scenarios.parameter.gross),notice:root.querySelector('[data-bridge-stage="launch"] [data-bridge-notice]').textContent}});
 let values=await read();assert(values.progress.length===8,JSON.stringify(values));assert(values.parameter.length===8);
 assert.equal(values.progress.reduce((sum,row)=>sum+row.daily_gross,0),values.progressTotal);assert.equal(values.parameter.reduce((sum,row)=>sum+row.daily_gross,0),values.parameterTotal);
 for(const rows of [values.progress,values.parameter]){assert.deepEqual(rows.slice(0,4).map(r=>r.daily_gross),[100,100,100,100]);assert(rows.every(r=>r.daily_gross>=0))}
 const selectDaily=async name=>page.evaluate(name=>{const root=document.querySelector('.forecast-workspace');const selects=[...root.querySelectorAll('[data-forecast-ref="daily"]')];selects[0].value=name;selects[1].value='';selects[0].dispatchEvent(new Event('change',{bubbles:true}))},name);
 await selectDaily('reference');values=await read();
 for(const stage of ['small','launch','steady'])assert.deepEqual(await page.evaluate(stage=>window.bridgeTest.bridgeSettings(document.querySelector('.forecast-workspace'),stage,8).weights,stage),[0,.5,1,1,1,1,1,1]);
 assert.equal(values.parameter[3].small_conversion,.24);
 assert(values.parameter.slice(4).every(row=>row.cancel_rate===null));
 const rates=await page.locator('[data-forecast-task-chart="conversion"]').evaluate(node=>[...node.querySelectorAll('polyline')].map(line=>({name:line.textContent,dashed:line.hasAttribute('stroke-dasharray'),points:line.getAttribute('points').split(' ').length})));
 assert(rates.some(line=>line.name.includes('current · 真实')&&!line.dashed&&line.points===4));
 assert(rates.some(line=>line.name.includes('current · 方法二预测')&&line.dashed&&line.points===5));
 const beforeImport=await read();
 const importPanel=page.locator('[data-forecast-import="launch"]');
 assert(await importPanel.evaluate(node=>node.closest('[data-forecast-import-anchor="launch"]')?.previousElementSibling?.classList.contains('forecast-decision-grid')));
 await importPanel.locator('[data-forecast-import-file]').setInputFiles({name:'forecast.csv',mimeType:'text/csv',buffer:Buffer.from('车型（代际）,日期,预测数量\ncurrent,2026-09-01,77\ncurrent,2026-09-04,123\ncurrent,2026-09-05,0')});
 await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').textContent.includes('导入成功'));
 assert((await importPanel.textContent()).includes('123'));
 assert((await importPanel.textContent()).includes('1个已过日期未计入'));
 await importPanel.locator('input[value="all"]').check();
 assert((await importPanel.locator('[data-forecast-import-result]').textContent()).includes('200'));
 assert((await importPanel.locator('[data-forecast-import-result]').textContent()).includes('整个阶段'));
 await importPanel.locator('input[value="future"]').check();
 assert.deepEqual(await read(),beforeImport);
 await importPanel.locator('[data-forecast-import-file]').setInputFiles({name:'bad.csv',mimeType:'text/csv',buffer:Buffer.from('车型,日期,预测数量\ncurrent,2026-09-04,-1')});
 await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').textContent.includes('导入失败'));
 assert((await importPanel.locator('[data-forecast-import-result]').textContent()).includes('123'));
 const {execFileSync}=require('child_process');
 const xlsx=execFileSync('python',['-c',"import io,base64,datetime; from openpyxl import Workbook; w=Workbook(); s=w.active; s.append(['车型','日期','预测数量']); s.append(['current',datetime.date(2026,9,4),456]); b=io.BytesIO(); w.save(b); print(base64.b64encode(b.getvalue()).decode())"],{encoding:'utf8'}).trim();
 await importPanel.locator('[data-forecast-import-file]').setInputFiles({name:'forecast.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from(xlsx,'base64')});
 await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').textContent.includes('导入成功'));
 assert((await importPanel.locator('[data-forecast-import-result]').textContent()).includes('456'));
 await importPanel.locator('[data-forecast-import-clear]').evaluate(node=>node.click());
 assert((await importPanel.locator('[data-forecast-import-result]').textContent()).includes('暂无'));
 const original=values;
 await selectDaily('daily-alternate');const alternative=await read();
 for(const method of ['progress','parameter']){
   assert.equal(alternative[method+'Total'],original[method+'Total']);
   assert.deepEqual(alternative[method].slice(0,4),original[method].slice(0,4));
   assert.notDeepEqual(alternative[method].slice(4).map(r=>r.daily_gross),original[method].slice(4).map(r=>r.daily_gross));
   assert.equal(alternative[method].reduce((sum,r)=>sum+r.daily_gross,0),alternative[method+'Total']);
 }
 await selectDaily('reference');values=await read();
 assert.equal(await page.locator('[data-forecast-task="daily_slope"] [data-forecast-ref]').count(),2);
 assert.equal(await page.locator('[data-forecast-task="daily_slope"] [data-forecast-ref-weight]').count(),0);
 assert((await page.locator('[data-forecast-task-chart="daily_slope"]').textContent()).includes('仅展示'));
 const beforeDisplay=await read();
 await page.locator('[data-forecast-task="daily_slope"] [data-forecast-ref][data-ref-slot="0"]').evaluate(node=>{node.value='daily-alternate';node.dispatchEvent(new Event('change',{bubbles:true}))});
 await page.locator('[data-forecast-task="daily_slope"] [data-forecast-ref][data-ref-slot="1"]').evaluate(node=>{node.value='reference';node.dispatchEvent(new Event('change',{bubbles:true}))});
 assert.deepEqual(await read(),beforeDisplay);
 const slopeReason=await page.locator('[data-forecast-task="daily_slope"] [data-forecast-ref-reason]').textContent();
 assert(slopeReason.includes('真实日环比相似度'),slopeReason);
 assert((await page.locator('[data-forecast-task-chart="daily_slope"]').textContent()).includes('主参考 · daily-alternate'));
 assert((await page.locator('[data-forecast-task-chart="daily_slope"]').textContent()).includes('辅助参考 · reference'));

 await page.locator('[data-forecast-chart-ref="daily_slope"]').first().evaluate(node=>{node.checked=!node.checked;node.dispatchEvent(new Event('change',{bubbles:true}))});
 assert.deepEqual(await read(),beforeDisplay);
 await page.locator('[data-forecast-tab="evidence"]').click();
 const slopeCard=page.locator('[data-forecast-task="daily_slope"]');
 await slopeCard.getByText('查看评分对比表',{exact:true}).click();
 assert(await slopeCard.locator('[data-forecast-ref-reason]').isVisible());
 await slopeCard.getByText('查看每日斜率数值',{exact:true}).click();
 assert((await slopeCard.locator('[data-forecast-task-chart] table').textContent()).includes('D8'));
 const screenshotDir=testOutputRoot;fs.mkdirSync(screenshotDir,{recursive:true});
 await slopeCard.screenshot({path:path.join(screenshotDir,'daily-slope.png')});
 await page.setViewportSize({width:390,height:844});
 assert(await slopeCard.evaluate(node=>node.scrollWidth<=node.clientWidth+1));
 await slopeCard.screenshot({path:path.join(screenshotDir,'daily-slope-mobile.png')});
 await page.setViewportSize({width:1440,height:1000});
 await page.locator('[data-forecast-tab="result"]').click();
 const baseline=values.progress.slice(4).map(r=>r.daily_gross);
 await page.locator('[data-bridge-stage="launch"] [data-bridge-control="weights"]').fill('1,0,0,0');await page.locator('[data-bridge-stage="launch"] [data-bridge-control="weights"]').dispatchEvent('change');
 values=await read();assert(values.progress.length===8);assert.deepEqual(values.progress.slice(0,4).map(r=>r.daily_gross),[100,100,100,100]);
 assert.notDeepEqual(values.progress.slice(4).map(r=>r.daily_gross),baseline);
 assert.equal(values.progress.reduce((sum,row)=>sum+row.daily_gross,0),values.progressTotal);assert.equal(values.parameter.reduce((sum,row)=>sum+row.daily_gross,0),values.parameterTotal);
 await page.locator('[data-bridge-stage="launch"] [data-bridge-control="weights"]').fill('1');await page.locator('[data-bridge-stage="launch"] [data-bridge-control="weights"]').dispatchEvent('change');
 assert((await page.locator('[data-forecast-data-error]').textContent()).includes('权重'));
 await page.locator('[data-bridge-stage="launch"] [data-bridge-control="weights"]').fill('');await page.locator('[data-bridge-stage="launch"] [data-bridge-control="weights"]').dispatchEvent('change');
 await page.evaluate(()=>window.bridgeTest.activateForecastStage('small',false));
 await page.locator('[data-bridge-stage="small"] [data-bridge-control="weekend"]').fill('1.8');await page.locator('[data-bridge-stage="small"] [data-bridge-control="weekend"]').dispatchEvent('change');
 await page.evaluate(()=>window.bridgeTest.activateForecastStage('steady',false));
 await page.locator('[data-bridge-stage="steady"] [data-bridge-control="weekend"]').fill('1.6');await page.locator('[data-bridge-stage="steady"] [data-bridge-control="weekend"]').dispatchEvent('change');
 await page.evaluate(()=>{const api=window.bridgeTest;api.captureForecastDraft();document.querySelector('#page').innerHTML=api.renderForecastWorkspaceV2(window.fixture);api.bindForecastWorkspaceV2();api.restoreForecastDraft()});
 assert.equal(await page.locator('[data-bridge-stage="small"] [data-bridge-control="weekend"]').inputValue(),'1.8');
 assert.equal(await page.locator('[data-bridge-stage="steady"] [data-bridge-control="weekend"]').inputValue(),'1.6');
 await page.evaluate(()=>{const f=window.fixture;f.target.small_start_date=f.targets[0].small_start_date='2026-09-01';f.target.small_end_date=f.targets[0].small_end_date='2026-09-08';f.actuals[0].small_daily_days=[{date:'2026-09-01',orders:100},{date:'2026-09-02',orders:120},{date:'2026-09-03',orders:140}];window.bridgeTest.state.forecastStage='small';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2()});
 // Small-order forecast must feed launch method two before D1.
 const savedLaunch=await page.evaluate(()=>{
   const f=window.fixture,saved=JSON.stringify({target:f.target,targets:f.targets,actuals:f.actuals});
   f.target.launch_date=f.targets[0].launch_date='2026-09-09';f.targets[0].end_date='2026-09-16';f.target.steady_start_date=f.targets[0].steady_start_date='2026-09-17';
   f.target.total_small=f.actuals[0].total_small=0;f.targets[0].small=0;
   document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2();
   return saved;
 });
 const linked=await page.evaluate(()=>{const r=document.querySelector('.forecast-workspace');return {small:r._smallForecastResult,input:Number(r.querySelector('[data-forecast-input="small"]').value),scenario:r._forecastComparison.scenarios,readonly:r.querySelector('[data-forecast-input="small"]').readOnly}});
 assert.equal(await page.locator('[data-steady-workspace]').evaluate(w=>w._steadyBasis.source),'launch_forecast');
 assert((await page.locator('[data-steady-workspace]').evaluate(w=>w._steadyDaily.length))>0);
 assert.equal(linked.small.total,1200);assert.equal(linked.input,1200);assert(linked.readonly);
 assert.equal(linked.scenario.progress.available,false);assert(linked.scenario.parameter.available);assert.equal(Math.round(linked.scenario.parameter.gross),1200);
 await page.locator('[data-small-weight]').evaluateAll(nodes=>nodes.forEach(node=>{node.value='0';node.dispatchEvent(new Event('input',{bubbles:true}))}));
 await page.waitForTimeout(250);
 const failed=await page.evaluate(()=>{const r=document.querySelector('.forecast-workspace');return {small:r._smallForecastResult,input:Number(r.querySelector('[data-forecast-input="small"]').value),parameter:r._forecastComparison.scenarios.parameter}});
 assert(failed.small.error);assert.equal(failed.input,0);assert.equal(failed.parameter.available,false);
 await page.evaluate(saved=>{Object.assign(window.fixture,JSON.parse(saved));document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(window.fixture);window.bridgeTest.bindForecastWorkspaceV2()},savedLaunch);
 const smallRead=()=>page.locator('[data-small-chart] .forecast-lifecycle-bars article b').allTextContents();
 const smallBefore=(await smallRead()).map(value=>Number(value.replaceAll(',','')));assert.deepEqual(smallBefore.slice(0,3),[100,120,140]);assert.equal(smallBefore.reduce((a,b)=>a+b,0),1200);
 await page.locator('[data-bridge-stage="small"] [data-bridge-control="holiday"]').fill('2');await page.locator('[data-bridge-stage="small"] [data-bridge-control="holiday"]').dispatchEvent('change');
 const smallAfter=(await smallRead()).map(value=>Number(value.replaceAll(',','')));assert.deepEqual(smallAfter.slice(0,3),[100,120,140]);assert.equal(smallAfter.reduce((a,b)=>a+b,0),1200);assert.notDeepEqual(smallAfter,smallBefore);
 await page.evaluate(()=>{const f=window.fixture;f.target.steady_start_date='2026-07-01';f.targets[0].steady_start_date='2026-07-01';const daily=Array.from({length:61},(_,i)=>({date:new Date(Date.UTC(2026,6,1+i)).toISOString().slice(0,10),lock:90}));daily.push({date:'2026-08-31',lock:100},{date:'2026-09-01',lock:110},{date:'2026-09-02',lock:120},{date:'2026-09-03',lock:130});f.steady_history.push({model:'current',generation:'current',weeks:f.steady_history[0].weeks,daily,steady_start_date:'2026-07-01'});window.bridgeTest.state.forecastStage='steady';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2()});
 const flat=await page.evaluate(()=>{const w=document.querySelector('[data-steady-workspace]');return {daily:w._steadyDaily,error:w.querySelector('[data-steady-error]').textContent}});
 assert.equal(flat.error,'');assert.deepEqual(flat.daily.filter(r=>r.actual).map(r=>r.lock),[100,110,120,130]);assert(flat.daily.every(r=>r.lock>=0));
 const olderGap=await page.evaluate(()=>{const f=window.fixture,item=f.steady_history.at(-1),original=item.daily;item.daily=original.filter(row=>row.date!=='2026-07-15');document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2();const message=document.querySelector('[data-steady-error]').textContent;item.daily=original;document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2();return message});
 assert(olderGap.includes('2026-07-15'));assert(olderGap.includes('共1天'));
 const output=testOutputRoot;fs.mkdirSync(output,{recursive:true});
 await page.locator('[data-bridge-stage="steady"]').screenshot({path:path.join(output,'steady-parameters.png')});
 await page.setViewportSize({width:390,height:844});
 assert(await page.locator('[data-bridge-stage="steady"]').evaluate(node=>node.scrollWidth<=node.clientWidth+1));
 await page.locator('[data-bridge-stage="steady"]').screenshot({path:path.join(output,'steady-parameters-mobile.png')});
 // Final launch day still in progress must carry its own scenario remainder.
 await page.evaluate(()=>{
   const f=window.fixture;f.target.launch_date=f.targets[0].launch_date='2026-08-28';f.targets[0].end_date='2026-09-04';
   f.actuals[0].days=Array.from({length:8},(_,i)=>({day:'D'+(i+1),date:new Date(Date.UTC(2026,7,28+i)).toISOString().slice(0,10),gross:i===7?20:100,small_to_big:i===7?12:60,direct:i===7?8:40,lock:0}));
   window.bridgeTest.state.forecastStage='launch';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2();
 });
 const lastDay=await read();
 assert(await page.locator('[data-forecast-data-error]').evaluate(node=>node.hidden));
 for(const method of ['progress','parameter']){
   assert.equal(lastDay[method].length,8);
   assert(lastDay[method][7].partial&&!lastDay[method][7].actual);
   assert(lastDay[method][7].daily_gross>=20);
   assert.equal(lastDay[method].reduce((s,r)=>s+r.daily_gross,0),lastDay[method+'Total']);
 }
 // Completed launch: freeze actuals even if references/parameters disagree.
 await page.setViewportSize({width:1440,height:1000});
 await page.evaluate(()=>{
   const f=window.fixture;f.target.launch_date=f.targets[0].launch_date='2026-08-27';f.targets[0].end_date='2026-09-03';
   f.actuals[0].days=Array.from({length:8},(_,i)=>({day:'D'+(i+1),date:new Date(Date.UTC(2026,7,27+i)).toISOString().slice(0,10),gross:100,small_to_big:60,direct:40,lock:80}));
   window.renderClosed=()=>{window.bridgeTest.state.forecastStage='launch';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2()};
   window.renderClosed();
 });
 const assertClosed=async(total=800)=>{
   const c=await read();
   for(const method of ['progress','parameter']){
     assert.equal(c[method+'Total'],total);assert.equal(c[method].length,8);
     assert(c[method].every(row=>row.actual));assert.equal(c[method].reduce((s,r)=>s+r.daily_gross,0),total);
   }
   assert(await page.locator('[data-forecast-data-error]').evaluate(node=>node.hidden));
   assert((await page.locator('[data-forecast-method-status="parameter"]').textContent()).includes('按真实结果收口'));
   assert.equal((await page.locator('[data-forecast-value="parameter-lock"]').textContent()).replaceAll(',',''),String(total*.8));
   return c;
 };
 const closed=await assertClosed();
 await page.evaluate(()=>{window.fixture.history.push({...window.fixture.history[0],model:'current',generation:'current',launch_date:'2026-08-27',days:8,gross:800,lock:700});window.renderClosed()});
 assert.equal((await page.locator('[data-forecast-value="parameter-lock"]').textContent()).replaceAll(',',''),'700');
 assert((await page.locator('.forecast-scenario-lock').first().textContent()).includes('整理表同车型同首销窗口终值优先'));
 await page.evaluate(()=>{window.fixture.history.pop();window.renderClosed()});
 await page.evaluate(()=>{
   const root=document.querySelector('.forecast-workspace');
   for(const [selector,value] of [
     ['[data-forecast-input="conversion"]','0'],['[data-forecast-input="direct"]','90'],
     ['[data-forecast-input="lock"]','10'],['[data-forecast-input="progressSmallCompletion"]','20'],
     ['[data-forecast-input="progressDirectCompletion"]','30'],
     ['[data-bridge-stage="launch"] [data-bridge-control="holiday"]','0'],
     ['[data-bridge-stage="launch"] [data-bridge-control="weights"]','bad']
   ]){const input=root.querySelector(selector);input.value=value;input.dispatchEvent(new Event('change',{bubbles:true}));input.dispatchEvent(new Event('input',{bubbles:true}));}
 });
 await page.waitForTimeout(300);
 assert.deepEqual(await assertClosed(),closed);
 await page.evaluate(()=>{window.fixture.history=[];window.renderClosed()});
 await assertClosed();
 await page.evaluate(()=>{window.fixture.actuals[0].days.forEach(row=>{row.gross=row.small_to_big=row.direct=row.lock=0});window.renderClosed()});
 await assertClosed(0);
 await page.evaluate(()=>{window.fixture.actuals[0].days.splice(2,1);window.renderClosed()});
 assert((await page.locator('[data-forecast-data-error]').textContent()).includes('D3'));
 const missing=await read();assert.equal(missing.progress.length,0);assert.equal(missing.parameter.length,0);
 if(process.env.BRIDGE_REAL_DATA){
   const html=fs.readFileSync(process.env.BRIDGE_REAL_DATA,'utf8');
   const data=JSON.parse(zlib.gunzipSync(Buffer.from(html.match(/window\.DASHBOARD_DATA_B64\s*=\s*["']([^"']+)/)[1],'base64')));
   const key=Object.keys(data.dashboard_blocks).find(key=>key.endsWith('|sales_forecast'));
   const block=JSON.parse(zlib.gunzipSync(Buffer.from(data.dashboard_blocks[key],'base64')));
   const f=Object.values(Object.values(block.views)[0].pages)[0].workspace.data;
   for(const t of f.targets.filter(t=>t.name.includes('M9')&&t.stage==='ended')){
     const chosen={...f,target:{...t,launch_days:t.days,total_small:t.small,launch_node:t.node}};
     await page.evaluate(f=>{window.bridgeTest.state.forecastStage='launch';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2()},chosen);
     const c=await read();
     assert(await page.locator('[data-forecast-data-error]').evaluate(node=>node.hidden),t.name);
     const actual=f.actuals.find(a=>a.model===t.actual_model),profile=actual.stage_profiles?.ended||actual;
     const rows=profile.days.filter(r=>r.date>=t.launch_date&&r.date<=t.end_date);
     const gross=rows.reduce((s,r)=>s+Number(r.gross||0),0);
     for(const method of ['progress','parameter']){
       assert.equal(c[method].length,t.days,t.name);assert(c[method].every(r=>r.actual));
       assert.equal(c[method+'Total'],gross,t.name);
       assert.equal(c[method].reduce((s,r)=>s+r.daily_gross,0),gross,t.name);
     }
     console.log('REAL CLOSED PASS:',t.name,t.days,'days',gross,'orders');
   }
 }
 // Priority regression: own flat-sales days > own launch conversion > history.
 const renderPriority=async(mode)=>{
   const f=JSON.parse(JSON.stringify(fixture));
   f.target.launch_date=f.targets[0].launch_date='2026-09-01';
   f.target.launch_days=3;f.targets[0].end_date='2026-09-03';
   f.target.steady_start_date=f.targets[0].steady_start_date='2026-09-04';
   f.actuals[0].days=Array.from({length:3},(_,i)=>({date:`2026-09-0${i+1}`,gross:100,small_to_big:60,direct:40,lock:80}));
   if(mode!=='historical')f.steady_history=[];
   if(mode==='own'){
     f.target.steady_start_date=f.targets[0].steady_start_date='2026-09-01';
     f.steady_history=[{model:'current',weeks:[],daily:[1,2,3].map(i=>({date:`2026-09-0${i}`,lock:100*i}))}];
   }
   if(mode==='historical'){
     f.target.launch_date=f.targets[0].launch_date='2026-09-10';
     f.targets[0].end_date='2026-09-12';
     f.target.steady_start_date=f.targets[0].steady_start_date='2026-09-13';f.actuals=[];
   }
   await page.evaluate(f=>{window.bridgeTest.state.forecastStage='steady';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2()},f);
   return page.evaluate(()=>{const w=document.querySelector('[data-steady-workspace]');return {basis:w._steadyBasis,daily:w._steadyDaily,error:w.querySelector('[data-steady-error]').textContent,source:w.querySelector('[data-steady-source]').textContent}});
 };
 let priority=await renderPriority('launch');assert.equal(priority.error,'');assert.equal(priority.basis.source,'launch_direct');assert.equal(priority.basis.level,32);assert(priority.daily.length>0);
 priority=await renderPriority('own');assert.equal(priority.error,'');assert.equal(priority.basis.source,'own_steady');assert.equal(priority.basis.level,200);assert.deepEqual(priority.daily.slice(0,3).map(row=>row.lock),[100,200,300]);
 await page.locator('[data-bridge-stage="steady"] [data-bridge-control="workday"]').fill('0');
 await page.locator('[data-bridge-stage="steady"] [data-bridge-control="workday"]').dispatchEvent('change');
 await page.waitForTimeout(300);
 assert.equal(await page.locator('[data-steady-workspace]').evaluate(w=>w._steadyDaily.length),0);
 priority=await renderPriority('historical');assert.equal(priority.error,'');assert.equal(priority.basis.source,'launch_forecast');assert(priority.daily.length>0);
 const chartText=await page.locator('[data-steady-reference-chart]').textContent();assert(chartText.includes('单'));assert(!chartText.includes('100%基准'));
 // Intraday totals without components must not lose already observed orders.
 const partialFixture=JSON.parse(JSON.stringify(fixture));
 partialFixture.actuals[0].hourly_days=[{date:'2026-09-04',last_hour:11,gross:100,small_to_big:null,direct:null,hours:[{hour:10,gross:40},{hour:11,gross:60}]}];
 await page.evaluate(f=>{window.bridgeTest.state.forecastStage='launch';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2()},partialFixture);
 values=await read();
 for(const rows of [values.progress,values.parameter]){
   const current=rows.find(row=>row.partial);assert(current);assert.equal(current.daily_gross,200);assert.equal(current.small_to_big+current.direct,200);
 }
 assert.equal((await page.locator('[data-forecast-progress-actual-small]').textContent()).replaceAll(',',''),'240单');
 assert((await page.locator('[data-forecast-progress-intraday]').textContent()).includes('全天估算'));
 assert(!(await page.locator('[data-forecast-decision-chart="parameter"]').textContent()).includes('退订率'));
 assert((await page.locator('[data-forecast-task-chart="hourly"]').textContent()).includes('D5 · 2026-09-04'));
 for(const [field,value] of [['conversion','37.1'],['direct','33.3']])await page.locator(`[data-forecast-input="${field}"]`).evaluate((node,value)=>{node.value=value;node.dispatchEvent(new Event('input',{bubbles:true}))},value);
 await page.waitForTimeout(300);values=await read();
 assert.equal(values.parameter.reduce((sum,row)=>sum+row.daily_gross,0),values.parameterTotal);
 const smallKpi=Number((await page.locator('[data-forecast-value="parameter-small"]').textContent()).replaceAll(',',''));
 assert.equal(values.parameter.reduce((sum,row)=>sum+row.small_to_big,0),smallKpi);
 const nowSteady=JSON.parse(JSON.stringify(fixture));
 nowSteady.target.steady_start_date=nowSteady.targets[0].steady_start_date='2026-09-01';
 nowSteady.steady_history=[{model:'current',weeks:[],daily:[1,2,3,4].map(i=>({date:`2026-09-0${i}`,lock:i===4?900:100}))}];
 await page.evaluate(f=>{window.bridgeTest.state.forecastStage='steady';document.querySelector('#page').innerHTML=window.bridgeTest.renderForecastWorkspaceV2(f);window.bridgeTest.bindForecastWorkspaceV2()},nowSteady);
 const steadyToday=await page.locator('[data-steady-workspace]').evaluate(w=>w._steadyDaily.find(row=>row.date==='2026-09-04'));
 assert(steadyToday.lock>=900);assert.equal(steadyToday.actual,false);
 assert.deepEqual(errors,[]);
 console.log('PASS: shared daily curve affects both methods, capped weights across stages, display-only slope isolation and responsive layout, conservation and calendar integration');
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
