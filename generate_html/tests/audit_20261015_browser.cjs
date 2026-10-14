// Formal main.py output only; synthetic records stay in isolated browser memory.
const fs=require('fs'),path=require('path'),assert=require('assert'),zlib=require('zlib'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],checks=[];
 try{
  for(const today of ['2026-05-05','2026-05-03']){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({today})=>{
    const parse=JSON.parse,same=name=>String(name||'').replace(/\s/g,'')==='问界M92026款';
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date=today;
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       for(const target of [data.target,...data.targets||[],...data.steady_targets||[]])if(same(target.name))Object.assign(target,{
        has_small:false,launch_date:'2026-05-01',end_date:'2026-05-03',days:3,steady_start_date:'2026-05-04',
        hard_errors:[],validation_issues:[],data_error:false
       });
       for(const item of [...data.history,...data.steady_launch_history||[]])if(same(item.model)||same(item.generation))Object.assign(item,{
        launch_date:'2026-05-01',end_date:'2026-05-03',days:3,lock_rate:.5,
        daily_orders:[100,null,200],daily_direct:[100,null,200],daily_small:[0,null,0]
       });
       for(const profile of data.actuals)if(same(profile.model))for(const item of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(item,{
        days:[{date:'2026-05-01',gross:100,direct:100,small_to_big:0,lock:50},{date:'2026-05-03',gross:200,direct:200,small_to_big:0,lock:100}],
        hard_errors:[],validation_issues:[],data_error:false
       });
       data.steady_history=(data.steady_history||[]).filter(item=>!same(item.model)&&!same(item.generation));
       data.steady_history.push({model:'问界 M9 2026款',generation:'问界 M9 2026款',event_id:'audit15-own',weeks:[],
        daily:[{date:'2026-05-04',lock:30,gross:60,complete:true}]});
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{today});
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   const url=new URL(base);url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'steady',forecastView:'evidence'});
   await page.goto(url.href);await page.waitForSelector('[data-steady-reference-chart] svg');
   await page.evaluate(()=>document.querySelectorAll('[data-bridge-stage="launch"] [data-bridge-control]').forEach(input=>{
    if(input.dataset.bridgeControl!=='weights'){input.value='1';input.dispatchEvent(new Event('change',{bubbles:true}));}
   }));
   const cells=await page.locator('[data-steady-reference-chart] tbody tr').filter({hasText:'问界 M9 2026款 · 首销直接大定实际'}).first().locator('td').allTextContents();
   assert.deepEqual(cells,today==='2026-05-05'?['100%','—','200%']:['100%','—']);
   const labels=await page.locator('[data-steady-reference-chart] circle[aria-label]').evaluateAll(nodes=>nodes.map(node=>node.getAttribute('aria-label')).filter(label=>label.includes('问界 M9 2026款 · 首销直接大定实际')));
   assert(!labels.some(label=>label.includes('D2')));
   assert.equal(labels.some(label=>label.includes('D3')&&label.includes('200%')),today==='2026-05-05');
   checks.push('steady calendar gap and cutoff '+today);await context.close();
  }
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  await context.addInitScript(()=>{
   const text=Response.prototype.text;
   Response.prototype.text=async function(...args){
    const value=await text.apply(this,args);
    if(value.includes('AUDIT_OLD'))await new Promise(resolve=>setTimeout(()=>{window.__auditOldReadFinished=true;resolve();},500));
    return value;
   };
  });
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base.href);await page.waitForFunction(()=>window.DASHBOARD_DATA&&document.querySelector('#page')?.getAttribute('aria-busy')==='false');
  const pack=marker=>zlib.gzipSync(JSON.stringify({rows:[['标记'],[marker]]})).toString('base64');
  const indices=await page.evaluate(({old,current})=>{
   const files=window.DASHBOARD_DATA.raw_files,index=files.length;
   files.push(...['旧读取','当前读取'].map(name=>({name:name+'.xlsx',sheets:[{name:'by天',total_rows:2,total_cols:1}]})));
   window.DASHBOARD_RAW_B64[index+'|0']=old;window.DASHBOARD_RAW_B64[(index+1)+'|0']=current;
   return [index,index+1];
  },{old:pack('AUDIT_OLD'),current:pack('AUDIT_NEW')});
  await page.locator('[data-module="raw"]').click();await page.waitForSelector('#rawTable');
  await page.locator(`[data-file="${indices[0]}"]`).click();
  await page.locator(`[data-file="${indices[1]}"]`).click();
  await page.waitForFunction(()=>document.querySelector('#rawTable')?.textContent.includes('AUDIT_NEW'));
  await page.waitForFunction(()=>window.__auditOldReadFinished);
  assert.equal(await page.locator('#rawFile').inputValue(),String(indices[1]));
  assert((await page.locator('#rawTable').innerText()).includes('AUDIT_NEW'));
  const event=page.waitForEvent('download');await page.locator('#exportRaw').click();const download=await event;
  const csv=fs.readFileSync(await download.path(),'utf8');assert(csv.includes('AUDIT_NEW'));assert(!csv.includes('AUDIT_OLD'));
  assert.equal(download.suggestedFilename(),'当前读取_by天.csv');
  checks.push('late old decompression cannot alter visible sheet or exported CSV');
  await page.locator('#rawSearch').fill('NOT_FOUND');assert(await page.locator('#rawEmpty').isVisible());
  await page.locator('#clearRawSearch').click();assert((await page.locator('#rawTable').innerText()).includes('AUDIT_NEW'));
  checks.push('raw search and clear still use current sheet');
  await context.close();assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
