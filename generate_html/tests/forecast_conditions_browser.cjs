// Real main output only; scenarios are injected in memory, never extra HTML.
const fs=require('fs'),path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'result'});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const check=(label,ok)=>{assert(ok,label);checks++;console.log('PASS '+label)};
 try{
  for(const scenario of ['no_small','missing_total','ended_components','unknown_window','missing_direct','invalid_rows','unknown_issue','conflicting_window']){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({scenario})=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-30';
      if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
       const name='问界 M9 2026款',same=value=>String(value||'').replace(/\s/g,'')===name.replace(/\s/g,'');
       const hasSmall=scenario!=='no_small',end=scenario==='conflicting_window'?'2026-09-27':scenario==='ended_components'?'2026-09-29':'2026-10-07';
       for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
        has_small:hasSmall,launch_date:scenario==='unknown_window'?'':'2026-09-28',end_date:end,days:scenario==='ended_components'?2:10,
        launch_days_maintained:true,steady_start_date:end==='2026-09-29'?'2026-09-30':'2026-10-08',
        small:0,small_start_date:'2026-09-01',small_end_date:hasSmall?'2026-09-27':'',
        hard_errors:[],validation_issues:[],data_error:false
       });
       for(const item of data.history)Object.assign(item,{
        launch_date:'2026-08-01',end_date:'2026-08-10',
        days:10,daily_orders:Array(10).fill(10),daily_small:Array(10).fill(4),daily_direct:Array(10).fill(6),
        direct_progress:Array.from({length:10},(_,i)=>(i+1)/10),small_progress:Array.from({length:10},(_,i)=>(i+1)/10)
       });
       const rows=[100,80].map((gross,index)=>({date:'2026-09-'+(28+index),day:'D'+(index+1),gross,lock:gross*.8,
        small_to_big:scenario==='ended_components'||scenario==='no_small'?null:gross*.4,
        direct:['ended_components','no_small','missing_direct'].includes(scenario)?null:gross*.6}));
       if(scenario==='invalid_rows')rows[1].gross=null;
       const issues=scenario==='invalid_rows'?[{code:'COMPLETED_DAYS_INVALID',message:'来源旧窗口中有异常记录'}]:
        scenario==='unknown_issue'?[{code:'CUSTOM_SOURCE_BLOCKER',message:'不可忽略的来源异常'}]:[];
       for(const profile of data.actuals)if(same(profile.model)){
        for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
         days:rows.map(row=>({...row})),total_small:0,hourly_days:[],hard_errors:issues.map(issue=>issue.message),validation_issues:issues,data_error:!!issues.length,has_small:hasSmall});
       }
      }
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   },{scenario});
   const page=await context.newPage();page.on('pageerror',e=>{errors.push(e.message);console.error(scenario+': '+e.stack);});
   await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
   const result=await page.locator('.forecast-workspace').evaluate(root=>root._forecastComparison);
   const notice=await page.locator('[data-forecast-data-error]').innerText();
   if(scenario==='no_small'){
    check('无小订车型方法一可预测',result.scenarios.progress.available&&result.scenarios.progress.gross>180);
    check('无小订车型方法二使用D1直接大定基准',result.scenarios.parameter.available&&Math.abs(result.scenarios.parameter.gross-1000)<1);
    check('无小订不伪造小转大',result.rows.every(row=>row.small_to_big===0));
    await page.locator('[data-forecast-tab="evidence"]').click();
    check('无小订相关输入不参与界面',!(await page.locator('[data-forecast-input="small"]').isVisible()));
    const completion=page.locator('[data-forecast-input="progressDirectCompletion"]');
    await completion.fill('120');await completion.dispatchEvent('change');
    await page.waitForFunction(()=>!document.querySelector('.forecast-workspace')._forecastComparison.scenarios.progress.available);
    check('人工完成率超过100%时明确指出字段',(await page.locator('[data-forecast-data-error]').innerText()).includes('直接大定人工完成率必须大于0%且不超过100%'));
    check('无效方法一参数不影响方法二',await page.locator('.forecast-workspace').evaluate(root=>root._forecastComparison.scenarios.parameter.available));
    await completion.fill('0');await completion.dispatchEvent('change');
    check('人工零完成率不偷偷回退',!(await page.locator('.forecast-workspace').evaluate(root=>root._forecastComparison.scenarios.progress.available)));
    await completion.fill('');await completion.dispatchEvent('change');
    await page.waitForFunction(()=>document.querySelector('.forecast-workspace')._forecastComparison.scenarios.progress.available);
    check('清空人工完成率恢复原有结果',await page.locator('.forecast-workspace').evaluate((root,original)=>root._forecastComparison.scenarios.progress.gross===original,result.scenarios.progress.gross));
    await page.locator('[data-forecast-stage-switch="small"]').click();
    check('小订明确不适用而非原始数据错误',(await page.locator('[data-small-error]').innerText()).includes('不适用'));
    await page.locator('[data-forecast-stage-switch="steady"]').click();
    check('无小订仍可从首销预测接入平销',await page.locator('[data-steady-error]').isHidden());
   }else if(scenario==='missing_total'){
    check('缺总小订不阻断方法一',result.scenarios.progress.available);
    check('缺总小订只限制方法二',!result.scenarios.parameter.available&&notice.includes('方法二')&&!notice.includes('方法一：'));
    check('无总小订的小转大率保持未知',result.rows.every(row=>row.small_conversion===null));
    check('无总小订的转化率KPI不显示伪造0',await page.locator('[data-forecast-value="progress-conversion"]').innerText()==='—');
    await page.locator('[data-forecast-tab="evidence"]').click();
    const completion=page.locator('[data-forecast-input="progressSmallCompletion"]');
    await completion.fill('120');await completion.dispatchEvent('change');
    await page.waitForFunction(()=>!document.querySelector('.forecast-workspace')._forecastComparison.scenarios.progress.available);
    check('小转大人工完成率无效也准确提示',(await page.locator('[data-forecast-data-error]').innerText()).includes('小转大人工完成率必须大于0%且不超过100%'));
   }else if(scenario==='ended_components'){
    check('首销结束后保留真实总大定',result.scenarios.progress.gross===180&&result.scenarios.progress.available);
    check('缺失实际分项没有伪造0',await page.locator('[data-forecast-value="progress-small"]').innerText()==='—');
    check('分项不完整提示明确保留总大定',notice.includes('实际分项不完整')&&notice.includes('真实总大定正常展示'));
   }else if(scenario==='unknown_window'){
    check('预测窗口缺失说明原因及影响',notice.includes('首销开始日期未维护')&&notice.includes('影响：'));
   }else if(scenario==='missing_direct'){
    check('历史分项缺失按具体字段与日期提示',notice.includes('直接大定缺失或无效')&&notice.includes('2026-09-28～2026-09-29'));
    check('预测不可用时仍显示已知真实大定',result.rows.length===2&&result.rows.every(row=>row.actual));
   }else if(scenario==='conflicting_window'){
    check('冲突结束日期不按天数偷偷回退',notice.includes('首销窗口冲突')&&!result.scenarios.progress.available&&!result.scenarios.parameter.available);
   }else{
    const unknown=scenario==='unknown_issue';
    check(unknown?'未知错误代码保守拦截':'已结束日无效总量重新校验',notice.includes(unknown?'不可忽略的来源异常':'大定缺失或无效')&&!result.scenarios.progress.available);
    const changeDays=async value=>{
     await page.locator('[data-forecast-target="days"]').fill(value);
     await page.locator('[data-forecast-target="days"]').dispatchEvent('change');
     await page.waitForFunction(()=>document.querySelector('[data-forecast-feedback]').dataset.state==='success');
     return page.locator('.forecast-workspace').evaluate(root=>root._forecastComparison);
    };
    const stillInvalid=await changeDays('9');
    check('修改窗口后仍拦截窗口内无效数据：'+scenario,!stillInvalid.scenarios.progress.available);
    const narrowed=await changeDays('1'),currentNotice=await page.locator('[data-forecast-data-error]').innerText();
    check(unknown?'调整窗口不能绕过未知来源错误':'缩短窗口清除范围外旧错误并保留真实值',unknown?
     !narrowed.scenarios.progress.available&&currentNotice.includes('不可忽略的来源异常'):
     narrowed.scenarios.progress.available&&narrowed.scenarios.progress.gross===100&&!currentNotice.includes('来源旧窗口'));
   }
   await context.close();
  }
  check('场景切换没有运行时异常',errors.length===0);
 }finally{await browser.close();}
 console.log(JSON.stringify({checks,errors}));
})().catch(error=>{console.error(error);process.exitCode=1});
