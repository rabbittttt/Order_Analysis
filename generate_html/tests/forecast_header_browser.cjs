// Exercise only the formal main.py output, without injecting forecast data.
const path=require('path'),assert=require('assert'),fs=require('fs'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const parent='问界 M7 2024款',campaign=parent+' Ultra版';
const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror',e=>errors.push(e.message));
 const check=(name,ok)=>{assert(ok,name);checks++;console.log('PASS '+name)};
 const open=async(module,stage='launch')=>{
  const url=new URL(base);url.search=new URLSearchParams({module,subject:parent,forecastStage:stage,forecastCampaign:campaign});
  await page.goto(url.href);await page.waitForFunction(()=>document.querySelector('#subjectSelect option'));
  await page.waitForTimeout(400);
 };
 const change=async(key,value)=>{
  const control=page.locator('[data-forecast-target="'+key+'"]');
  await control.fill(value);await control.dispatchEvent('change');
  await page.waitForTimeout(300);
 };
 try{
  await open('overview');const defaultList=await page.locator('#subjectSelect option').evaluateAll(nodes=>nodes.map(n=>n.value));
  await open('sales_forecast');await page.waitForSelector('.forecast-workspace');
  check('预测和普通模块共用主体名单',JSON.stringify(defaultList)===JSON.stringify(await page.locator('#subjectSelect option').evaluateAll(nodes=>nodes.map(n=>n.value))));
  const groups=await page.locator('#subjectSelect optgroup').evaluateAll(nodes=>nodes.map(n=>n.label));
  check('主体列表含集团品牌代际',['集团','品牌','代际'].every(g=>groups.includes(g)));
  check('九个参数及阶段时段分别可见',await page.locator('.forecast-target-form [data-forecast-target]').count()===9);
  const smallPeriod=page.locator('[data-forecast-target="smallPeriod"]'),launchPeriod=page.locator('[data-forecast-target="period"]');
  await smallPeriod.selectOption('下午');await launchPeriod.selectOption('晚上');
  check('两个发布时段独立修改',await smallPeriod.inputValue()==='下午'&&await launchPeriod.inputValue()==='晚上');
  const raw=await page.locator('.forecast-workspace').getAttribute('data-forecast-config');
  const configured=JSON.parse(raw),start=configured.target.launch_date;
  const end=new Date(Date.parse(start+'T00:00:00Z')+4*86400000).toISOString().slice(0,10);
  await change('days','5');
  check('首销天数修改进入时间口径计算',(await page.locator('[data-forecast-time-summary]').textContent()).includes(end+'，共5天'));
  const steady=new Date(Date.parse(end+'T00:00:00Z')+86400000).toISOString().slice(0,10);
  check('平销起点同步首销新结束日',(await page.locator('[data-forecast-time-summary]').textContent()).includes('平销自 '+steady+' 起'));
  const smallStart=configured.target.small_start_date;
  const smallEnd=new Date(Date.parse(smallStart+'T00:00:00Z')+2*86400000).toISOString().slice(0,10);
  await change('smallDays','3');
  check('小订天数修改进入窗口计算',(await page.locator('[data-forecast-time-summary]').textContent()).includes(smallStart+' ~ '+smallEnd));
  check('窗口编辑未改写绝对日期真实订单',await page.locator('.forecast-workspace').getAttribute('data-forecast-config')===raw);
  await change('days','');
  check('清空天数不伪造一天预测',(await page.locator('[data-forecast-data-error]').textContent()).includes('首销天数未维护或不是正整数'));
  await change('days',String(configured.target.launch_days));
  await page.locator('[data-forecast-tab="evidence"]').click();
  const ref=page.locator('[data-forecast-task="daily"] [data-forecast-ref]').first();
  const choice=await ref.locator('option:not(:disabled)').evaluateAll(nodes=>nodes.find(n=>n.value)?.value);
  if(choice){
   await ref.selectOption(choice);await launchPeriod.selectOption('下午');await page.waitForTimeout(350);
   check('参数刷新保留人工主参考',await ref.inputValue()===choice);
  }
  const output=path.join(project,'.test_outputs/forecast_header');fs.mkdirSync(output,{recursive:true});
  for(const width of [1920,1440,1024,768,390]){
   await page.setViewportSize({width,height:1000});await page.waitForTimeout(100);
   const boxes=await page.evaluate(()=>[...document.querySelectorAll('.module-nav button')].map(n=>{const r=n.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,w:r.width,h:r.height};}).filter(r=>r.w&&r.h));
   const overlap=boxes.some((a,i)=>boxes.slice(i+1).some(b=>Math.min(a.right,b.right)-Math.max(a.x,b.x)>1&&Math.min(a.bottom,b.bottom)-Math.max(a.y,b.y)>1));
   check(width+'px 导航框不重叠',!overlap);
   const controls=await page.locator('.forecast-target-form [data-forecast-target]').evaluateAll(nodes=>nodes.map(n=>{const r=n.getBoundingClientRect();return {x:r.x,right:r.right};}));
   check(width+'px 参数控件不越出窗口',controls.every(r=>r.x>=0&&r.right<=width+1));
   if(width===1440||width===390)await page.screenshot({path:path.join(output,'header-'+width+'.png')});
  }
  await open('cancellation');
  const periods=await page.locator('#periodSelect option').allTextContents();
  if(periods.some(s=>s==='全部阶段')){
   check('小订节奏多版本含全部阶段',true);
   await page.locator('#periodSelect').selectOption({label:'全部阶段'});
   await page.waitForTimeout(200);
   check('全部阶段展示阶段对比',(await page.locator('body').textContent()).includes('小订阶段对比'));
  }else{
   console.log('SKIP: 本机未维护匹配的M7二级小订原表；新命名读取与全部阶段数量由Python集成测试验证');
  }
  check('无浏览器运行错误',errors.length===0);
  console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
