// Verify subject eligibility against the formal main.py output, without test-page data.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),page=await browser.newPage(),errors=[];
 const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 page.on('pageerror',error=>errors.push(error.message));
 try{
  await page.goto(base.href);await page.waitForFunction(()=>document.querySelector('#subjectSelect option'));
  const subjects=await page.evaluate(()=>window.DASHBOARD_DATA.subjects),group=subjects.find(s=>s.type==='group'),brands=subjects.filter(s=>s.type==='brand'),cars=subjects.filter(s=>s.type==='generation');
  const forecast=page.locator('[data-module="sales_forecast"]');
  async function verifyUnavailable(s){
   await page.locator('#subjectSelect').selectOption(s.id);
   await page.waitForFunction(id=>new URL(location.href).searchParams.get('subject')===id&&document.querySelector('#page')?.getAttribute('aria-busy')==='false',s.id);
   await page.waitForFunction(()=>document.querySelector('[data-module="sales_forecast"]')?.disabled);
   assert(await forecast.isDisabled(),s.name+' must not offer vehicle forecasts');
   assert.equal(await page.locator('.forecast-workspace').count(),0,s.name+' displays another vehicle');
  }
  await verifyUnavailable(group);for(const brand of brands)await verifyUnavailable(brand);
  for(const car of cars){
   await page.locator('#subjectSelect').selectOption(car.id);
   await page.waitForFunction(id=>new URL(location.href).searchParams.get('subject')===id&&document.querySelector('#page')?.getAttribute('aria-busy')==='false',car.id);
   await page.waitForFunction(()=>!document.querySelector('[data-module="sales_forecast"]')?.disabled);
   assert(!(await forecast.isDisabled()),car.name+' forecast entry unavailable');
  }
  await forecast.click();await page.waitForSelector('.forecast-workspace');
  await verifyUnavailable(group); // Leaving a vehicle forecast must leave its workspace as well.
  const deepLink=new URL(base);deepLink.search=new URLSearchParams({subject:group.name,module:'sales_forecast'});
  await page.goto(deepLink.href);await page.waitForFunction(()=>document.querySelector('[data-module="sales_forecast"]')?.disabled);
  await page.waitForFunction(id=>new URL(location.href).searchParams.get('subject')===id&&document.querySelector('#page')?.getAttribute('aria-busy')==='false',group.id);
  assert.equal(await page.locator('.forecast-workspace').count(),0,'group deep link leaked a default vehicle');
  assert.equal(new URL(page.url()).searchParams.get('module'),'overview');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({groupDisabled:true,brandsDisabled:brands.length,generationsEnabled:cars.length,vehicleToGroup:true,groupDeepLink:true,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
