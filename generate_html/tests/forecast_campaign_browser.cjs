// Uses the real main output; never creates a second HTML or rewrites its data.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const parent='问界 M7 2024款',ultra=parent+' Ultra版',pro=parent+' Pro版';
const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
url.search=new URLSearchParams({module:'sales_forecast',subject:parent,forecastStage:'launch',forecastView:'result',forecastCampaign:ultra});
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const check=(name,ok)=>{assert(ok,name);checks++;console.log('PASS '+name)};
 page.on('pageerror',e=>errors.push(e.stack));
 const waitTarget=name=>page.waitForFunction(name=>{
  const root=document.querySelector('.forecast-workspace');return root&&JSON.parse(root.dataset.forecastConfig||'{}').target?.name===name;
 },name);
 try{
  await page.goto(url.href);await waitTarget(ultra);
  check('顶部主体只有一级代际',!(await page.locator('#subjectSelect option').allTextContents()).some(s=>s.includes('Ultra版')||s.includes('Pro版')));
  const labels=await page.locator('#periodSelect option').allTextContents();
  check('右上角版本与时间范围',labels.length===2&&labels.some(s=>s.startsWith('Ultra版 · 2024-05-31'))&&labels.some(s=>s.startsWith('Pro版 · 2024-08-26')));
  check('事件选择可操作',await page.locator('#periodSelect').isEnabled());
  const conversion=page.locator('[data-forecast-input="conversion"]');
  await conversion.fill('89.7');await conversion.dispatchEvent('change');
  await page.locator('#periodSelect').selectOption(pro);await waitTarget(pro);
  check('不同版本不继承人工参数',await conversion.inputValue()!=='89.7');
  await page.locator('#periodSelect').selectOption(ultra);await waitTarget(ultra);
  check('切回版本恢复自己的参数',await conversion.inputValue()==='89.7');
  await page.locator('[data-forecast-stage-switch="steady"]').click();await waitTarget(parent);
  check('平销合并为一级代际',await page.locator('#periodSelect').isDisabled()&&(await page.locator('#periodSelect').textContent()).includes('一级代际合并'));
  await page.locator('[data-forecast-stage-switch="launch"]').click();await waitTarget(ultra);
  check('平销切回首销保留版本草稿',await conversion.inputValue()==='89.7');
  await page.locator('#periodSelect').selectOption(pro);await waitTarget(pro);
  check('网址保存二级事件',new URL(page.url()).searchParams.get('forecastCampaign')===pro);
  await page.reload();await waitTarget(pro);
  check('刷新恢复二级事件',await page.locator('#periodSelect').inputValue()===pro);
  await page.locator('#periodSelect').selectOption(ultra);await waitTarget(ultra);
  check('刷新后各版本人工参数仍隔离',await conversion.inputValue()==='89.7');
  check('无浏览器运行错误',errors.length===0);
  console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exit(1)});
