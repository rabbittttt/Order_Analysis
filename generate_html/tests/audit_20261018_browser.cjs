// Exercise the formal main output with isolated in-memory lifecycle scenarios.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const check=(name,condition)=>{assert(condition,name);checks++;console.log('PASS '+name)};
 try{
  for(const mode of ['before','no_small','ended']){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({mode})=>{
    const original=JSON.parse;
    JSON.parse=function(text,...args){
     const value=original.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-30';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const name='问界 M9 2026款',same=value=>String(value||'').replace(/\s/g,'')===name.replace(/\s/g,''),ended=mode==='ended';
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:mode!=='no_small',launch_date:ended?'2026-09-28':'2026-10-02',
        end_date:ended?'2026-09-29':'2026-10-11',days:ended?2:10,launch_days_maintained:true,
        steady_start_date:ended?'2026-09-30':'2026-10-12',small:10000,
        small_start_date:'2026-09-01',small_end_date:'2026-09-27',small_days:27,
        hard_errors:[],validation_issues:[],data_error:false
       });
       for(const item of data.history)Object.assign(item,{
        launch_date:'2026-08-01',end_date:'2026-08-10',days:10,small:10000,
        gross:1000,small_to_big:400,direct:600,lock:800,conversion:.4,direct_share:.5,lock_rate:.8,
        daily_orders:Array(10).fill(100),daily_small:Array(10).fill(40),daily_direct:Array(10).fill(60),
        small_progress:Array.from({length:10},(_,i)=>(i+1)/10),
        direct_progress:Array.from({length:10},(_,i)=>(i+1)/10),
        quality_issues:'',d1_valid:true,d2_valid:true,d12_valid:true
       });
       for(const profile of data.actuals)if(same(profile.model))
        for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
         days:ended?[28,29].map((day,i)=>({date:'2026-09-'+day,day:'D'+(i+1),gross:100,small_to_big:40,direct:60,lock:80})):[],
         hourly_days:[],total_small:10000,hard_errors:[],validation_issues:[],data_error:false
        });
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{mode});
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
   url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'evidence'});
   await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
   const input=page.locator('[data-forecast-input="d1Gross"]'),root=page.locator('.forecast-workspace');
   // Inputs recalculate after 120ms and persist after 220ms. Observe the public
   // applied state instead of reading the previous scenario or adding a sleep.
   const settled=()=>page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison&&document.querySelector('.forecast-workspace').getAttribute('aria-busy')!=='true');
   const edit=async value=>{await input.fill(value);await input.dispatchEvent('change');await settled()};
   const scenario=()=>root.evaluate(root=>root._forecastComparison.scenarios.parameter);
   if(mode==='ended'){
    const initial=await scenario();
    await input.evaluate(node=>{node.value='-1';node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}))});
    await settled();
    check('已结束首销真实值不受旧D1人工输入影响',JSON.stringify(await scenario())===JSON.stringify(initial));
    check('真实D1仍是100单',(await page.locator('[data-forecast-d1-value]').textContent()).trim()==='100');
    check('真实值优先时不误报人工参数错误',await input.getAttribute('aria-invalid')==='false');
   }else if(mode==='no_small'){
    await edit('200');const valid=await scenario();
    check('无小订车型仍可用有效D1推算方法二',valid.available&&valid.gross>200&&valid.rows[0].gross===200);
    await edit('-1');
    check('无小订车型拒绝负D1而不回退估算',!(await scenario()).available&&(await page.locator('[data-forecast-data-error]').innerText()).includes('D1预测大定须为非负整数'));
    await edit('200');
    check('修正D1后恢复同一预测',JSON.stringify(await scenario())===JSON.stringify(valid));
   }else{
    for(const [field,value] of [['small','10000'],['conversion','40'],['direct','50'],['lock','80']]){
     const control=page.locator('[data-forecast-input="'+field+'"]');
     await control.fill(value);await control.dispatchEvent('change');
    }
    await edit('');const original=await scenario(),systemD1=original.rows[0]?.gross;
    check('首销前空白采用系统D1且方法二可用',original.available&&systemD1>0);
    await edit('0');const zero=await scenario();
    check('人工D1零值不再被系统值覆盖',zero.available&&zero.rows[0].gross===0);
    check('人工D1零值不改变终局或数量守恒',zero.gross===original.gross&&zero.rows.reduce((sum,row)=>sum+row.gross,0)===zero.gross);
    check('人工D1零值来源标记正确',(await page.locator('[data-forecast-d1-note]').textContent()).includes('采用人工输入值'));
    await page.reload();await settled();
    check('刷新后仍保留人工D1零值',JSON.stringify(await scenario())===JSON.stringify(zero));
    await edit('125');
    check('有效D1人工值进入逐日曲线',(await scenario()).rows[0].gross===125);
    for(const value of ['-1','3.5','9007199254740992']){
     await edit(value);
     check('拒绝非法D1 '+value,!(await scenario()).available&&await input.getAttribute('aria-invalid')==='true');
     check('非法D1原因准确 '+value,(await page.locator('[data-forecast-data-error]').innerText()).includes('D1预测大定须为非负整数'));
     check('非法D1不显示NaN '+value,!/\bNaN\b|\bInfinity\b/.test(await page.locator('[data-forecast-d1-card]').innerText()));
    }
    await edit('');
    check('清空后恢复系统推荐及原终局',JSON.stringify(await scenario())===JSON.stringify(original));
    check('恢复后清除参数无效状态',await input.getAttribute('aria-invalid')==='false');
    await page.reload();await settled();
    check('清空并刷新后仍使用系统推荐',JSON.stringify(await scenario())===JSON.stringify(original));
   }
   await context.close();
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
