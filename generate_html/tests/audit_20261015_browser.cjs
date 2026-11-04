// Formal main.py output only; synthetic records stay in isolated browser memory.
const fs=require('fs'),path=require('path'),assert=require('assert'),zlib=require('zlib'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(project,'.test_runtime/node_modules/playwright'));
const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],checks=[];
 try{
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
