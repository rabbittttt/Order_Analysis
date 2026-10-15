// Production main.py HTML only; test records live in isolated browser memory.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.addInitScript(()=>{
   const parse=JSON.parse,same=name=>String(name||'').replace(/\s/g,'')==='问界M92026款';
   JSON.parse=function(text,...args){
    const value=parse.call(this,text,...args),seen=new WeakSet();
    const visit=data=>{
     if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
     if(data.config&&data.subjects)data.config.forecast_as_of_date='2026-09-02';
     if(data.target&&Array.isArray(data.history)&&Array.isArray(data.actuals)){
      for(const target of [data.target,...data.targets||[]])if(same(target.name))Object.assign(target,{
       has_small:false,launch_date:'2026-09-01',end_date:'2026-09-10',days:10,
       steady_start_date:'2026-09-11',small:0,small_start_date:'',small_end_date:'',
       hard_errors:[],validation_issues:[],data_error:false
      });
      for(const item of data.history)Object.assign(item,{
       launch_date:'2026-08-01',end_date:'2026-08-10',days:10,gross:100,direct:100,small_to_big:0,
       daily_orders:[100,...Array(9).fill(0)],daily_direct:[100,...Array(9).fill(0)],daily_small:Array(10).fill(0),
       direct_progress:Array(10).fill(1),small_progress:Array(10).fill(0),
       d1_direct:100,d1_gross:100,d1_direct_ratio:1,d1_direct_completion:1,d1_valid:true,
       d2_direct:0,d2_gross:0,d2_valid:true,lock_rate:.8,quality_issues:''
      });
      for(const profile of data.actuals)if(same(profile.model))for(const candidate of [profile,...Object.values(profile.stage_profiles||{})])Object.assign(candidate,{
       days:[{date:'2026-09-01',day:'D1',gross:100,direct:100,small_to_big:0,lock:80}],
       total_small:0,hourly_days:[],hard_errors:[],validation_issues:[],data_error:false,has_small:false
      });
     }
     Object.values(data).forEach(visit);
    };visit(value);return value;
   };
  });
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({module:'sales_forecast',subject:'问界 M9 2026款',forecastStage:'launch',forecastView:'result'});
  await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
  const result=await page.locator('.forecast-workspace').evaluate(root=>root._forecastComparison);
  assert(result.scenarios.progress.available,'100%已实现且未来曲线为0，不应停止方法一');
  assert.equal(result.scenarios.progress.gross,100,'不抬高终局以制造正数尾量');
  const rows=result.scenarios.progress.rows;
  assert.equal(rows.length,10);assert.equal(rows[0].gross,100);assert(rows[0].actual);
  assert(rows.slice(1).every(row=>!row.actual&&row.gross===0&&row.direct===0));
  assert(!result.scenarios.progress.bridgeError);
  const notice=await page.locator('[data-forecast-data-error]').innerText();
  assert(!notice.includes('参考自然日曲线没有有效量'));
  assert.equal(errors.length,0,errors.join('\n'));
  console.log(JSON.stringify({checks:9,errors,terminal:result.scenarios.progress.gross,future:rows.slice(1).map(row=>row.gross)}));
  await context.close();
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
