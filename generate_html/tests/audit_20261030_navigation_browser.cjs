// Exercise out-of-order decompression on the formal dashboard in isolated memory.
const assert=require('assert'),path=require('path'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  page.on('pageerror',error=>errors.push(error.message));
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search='?module=overview';await page.goto(url.href);
  await page.waitForFunction(()=>window.DASHBOARD_DATA&&document.querySelector('#page').getAttribute('aria-busy')==='false');
  const ids=await page.evaluate(async()=>{
   const subjects=DASHBOARD_DATA.subjects.filter(s=>s.type==='generation'&&s.modules.includes('overview')).slice(0,2);
   for(const [index,subject] of subjects.entries()){
    const grain=index?'week':'day',period=index?'26WK43':'2025-05-01';
    const board={audit_navigation_id:index?'new':'late',subject_id:subject.id,module_id:'overview',views:{
     [grain]:{periods:[period],default_period:period,pages:{[period]:{kpis:[{label:'导航测试',value:index?222:111,unit:'单',note:period}],sections:[]}}}
    }};
    const compressed=new Blob([JSON.stringify(board)]).stream().pipeThrough(new CompressionStream('gzip'));
    const bytes=new Uint8Array(await new Response(compressed).arrayBuffer());
    DASHBOARD_DATA.dashboard_blocks[subject.id+'|overview']=btoa(String.fromCharCode(...bytes));
   }
   const read=Response.prototype.text;
   Response.prototype.text=async function(){const text=await read.call(this);if(text.includes('"audit_navigation_id":"late"')){
    window.auditNavigationPending=true;await new Promise(resolve=>window.auditNavigationRelease=resolve);
   }return text;};
   return subjects.map(s=>s.id);
  });
  await page.locator('#subjectSelect').selectOption(ids[0]);
  await page.waitForFunction(()=>window.auditNavigationPending);
  await page.locator('#subjectSelect').selectOption(ids[1]);
  await page.waitForFunction(()=>document.querySelector('.kpi strong')?.textContent==='222');
  await page.locator('.kpi').evaluate(node=>node.dataset.auditKeep='new page state');
  await page.evaluate(()=>window.auditNavigationRelease());
  // Drain the old async handler, including its render and URL update.
  await page.waitForTimeout(300);
  assert.equal(await page.locator('#subjectSelect').inputValue(),ids[1]);
  assert.equal(await page.locator('#periodSelect').inputValue(),'26WK43');
  assert.equal(await page.locator('.kpi strong').textContent(),'222');
  assert.equal(new URL(page.url()).searchParams.get('grain'),'week');
  assert.equal(new URL(page.url()).searchParams.get('period'),'26WK43');
  assert.equal(await page.locator('.empty-page').count(),0);
  assert.equal(await page.locator('.kpi').getAttribute('data-audit-keep'),'new page state');
  await page.locator('[data-module="raw"]').click();await page.waitForSelector('#rawSearch');
  await page.locator('#rawSearch').fill('AUDIT_NO_MATCH_20261030');
  assert(await page.locator('#rawEmpty').isVisible());
  await page.locator('#clearRawSearch').click();
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({checks:10,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
