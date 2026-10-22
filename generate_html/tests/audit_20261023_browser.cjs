// Exercise the formal generated page with isolated in-memory source scenarios.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const check=(label,ok)=>{assert(ok,label);checks++;console.log('PASS '+label)};
 try{
  for(const mode of ['priority','missing','derived','zero']){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({mode})=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-03';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const name='问界 M9 2026款',same=v=>String(v||'').replace(/\s/g,'')===name.replace(/\s/g,'');
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:true,small_start_date:'2026-09-01',small_end_date:'2026-09-02',small_days:2,
        launch_date:'2026-09-03',end_date:'2026-09-04',days:2,steady_start_date:'2026-09-05',
        small:100,lock_rate:0,hard_errors:[],validation_issues:[],data_error:false
       });
       data.small_order_history=(data.small_order_history||[]).filter(item=>!same(item.model)&&!same(item.generation));
       data.small_order_history.unshift({model:name,generation:name,event_id:'audit-current',total:100,total_complete:true,
        days:2,small_start_date:'2026-09-01',dates:['2026-09-01','2026-09-02'],daily_actual:mode!=='derived',
        daily_orders:mode==='missing'?[null,100]:mode==='zero'?[99,1]:[20,80]});
       for(const history of data.history)Object.assign(history,{lock:0,lock_rate:0,quality_issues:''});
       const daily=mode==='priority'?[{date:'2026-09-01',orders:50},{date:'2026-09-02',orders:50}]:
        mode==='zero'?[{date:'2026-09-01',orders:0},{date:'2026-09-02',orders:100}]:[{date:'2026-09-02',orders:100}];
       for(const profile of data.actuals)if(same(profile.model))for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
        small_daily_days:daily,small_hourly_days:[],total_small:100,hard_errors:[],validation_issues:[],data_error:false
       });
      }
      if(data.module_id==='order_mix'&&data.views)data.views={week:{periods:['26WK01'],default_period:'26WK01',pages:{'26WK01':{kpis:[],sections:[{
       kind:'table',title:'审计未知数量',data:{columns:['选配项','数量','占比','变化'],formats:['text','number','percent','signed_percent'],
        rows:[['unknown',null,null,null],['zero',0,0,0]]}
      }]}}}};
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{mode});
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   const url=new URL(base);url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'sales_forecast',forecastStage:'small',forecastView:'result'});
   await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._smallForecastResult);
   const d1=await page.locator('[data-small-kpi="d1"]').textContent(),result=await page.locator('.forecast-workspace').evaluate(r=>r._smallForecastResult);
   check(mode+' D1 uses only resolved real D1',d1===({priority:'50',missing:'—',derived:'—',zero:'0'})[mode]);
   check(mode+' terminal total remains independent',result.total===100&&!result.error);
   if(mode==='priority'){
    check('system-derived zero rate is present',Number(await page.locator('[data-forecast-input="lock"]').inputValue())===0);
    await page.locator('[data-forecast-stage-switch="steady"]').click();
    const panel=page.locator('[data-forecast-import="steady"]');
    await panel.locator('[data-forecast-import-file]').setInputFiles({name:'audit-zero-rate.csv',mimeType:'text/csv',buffer:Buffer.from('车型,日期,预测大定\n问界 M9 2026款,2026-09-05,100')});
    await page.waitForFunction(()=>document.querySelector('[data-forecast-import="steady"] [data-forecast-import-status]').textContent.includes('导入成功'));
    const prediction=()=>panel.locator('[data-forecast-import-result] tbody tr').filter({hasText:'2026-09-05'}).first().locator('td').allTextContents();
    const imported=await prediction();
    check('untouched automatic 0% gives zero imported lock',imported[2]==='0');
    const rate=page.locator('[data-forecast-input="lock"]'),setRate=value=>rate.evaluate((input,value)=>{input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}))},value);
    await setRate('');
    await page.waitForFunction(()=>document.querySelector('[data-forecast-import="steady"] [data-forecast-import-result]').textContent.includes('外部预测合计：—'));
    check('blank rate does not convert orders to zero',(await prediction())[2]!=='0'&&(await panel.locator('[data-forecast-import-result]').textContent()).includes('外部预测合计：—'));
    await setRate('0');
    await page.waitForFunction(()=>[...document.querySelectorAll('[data-forecast-import="steady"] tbody tr')].some(row=>row.children[0]?.textContent==='2026-09-05'&&row.children[2]?.textContent==='0'));
    check('explicit zero remains valid',(await prediction())[2]==='0');
    const mix=new URL(base);mix.search=new URLSearchParams({subject:'问界 M9 2026款',module:'order_mix',grain:'week'});
    await page.goto(mix.href);const table=page.locator('.panel').filter({has:page.getByRole('heading',{name:'审计未知数量',exact:true})});await table.waitFor();
    const unknown=await table.locator('tbody tr').nth(0).locator('td').allTextContents(),zero=await table.locator('tbody tr').nth(1).locator('td').allTextContents();
    check('unknown quantity/share/change stay unknown',unknown.slice(1).every(value=>value==='—'));
    check('real zero formats remain valid',JSON.stringify(zero.slice(1))===JSON.stringify(['0','0.0%','+0.0%']));
   }
   await context.close();
  }
  check('no browser exceptions',errors.length===0);console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
