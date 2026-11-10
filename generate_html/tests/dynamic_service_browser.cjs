// Real HTTP service + isolated persistent state. Never writes production annotations.
const fs=require('fs'),path=require('path'),net=require('net'),assert=require('assert'),{spawn}=require('child_process');
const project=path.resolve(__dirname,'../../..'),root=path.resolve(__dirname,'..');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(project,'.test_runtime/node_modules/playwright'));
const python=process.env.ORDER_PYTHON||path.resolve(project,'../.venv/Scripts/python.exe');
(async()=>{
 const output=path.join(project,'.test_outputs');fs.mkdirSync(output,{recursive:true});const state=fs.mkdtempSync(path.join(output,'shared-browser-'));
 const portServer=net.createServer();await new Promise(r=>portServer.listen(0,'127.0.0.1',r));const port=portServer.address().port;await new Promise(r=>portServer.close(r));
 const base=`http://127.0.0.1:${port}/`;let child,log='',browser;
 const start=async()=>{
  child=spawn(python,['server.py','--port',String(port),'--state-dir',state],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});child.stdout.on('data',b=>log+=b);child.stderr.on('data',b=>log+=b);
  for(let i=0;i<80;i++){if(child.exitCode!==null)throw new Error(log);try{if((await fetch(base+'health')).ok)return;}catch{}await new Promise(r=>setTimeout(r,200));}throw new Error('Service start timed out: '+log);
 };
 const stop=async()=>{if(child&&child.exitCode===null){const exited=new Promise(r=>child.once('exit',r));child.kill();await exited;}};
 try{
  await start();browser=await chromium.launch({headless:true,channel:'msedge'});
  const a=await browser.newContext(),b=await browser.newContext(),page=await a.newPage(),other=await b.newPage(),errors=[];
  for(const p of [page,other])p.on('pageerror',e=>errors.push(e.message));
  const catalog=await(await fetch(base+'api/catalog')).json(),group=catalog.subjects.find(s=>s.type==='group'),model=catalog.subjects.find(s=>s.type==='generation'&&s.modules.includes('overview'));
  assert(group&&model,'真实数据需包含集团及车型总览');
  await page.goto(base+'?subject='+group.id);await page.waitForSelector('[data-trend-annotation-manage]');await page.locator('[data-trend-annotation-manage]').first().click();
  await page.locator('#trendAnnotationForm [name="date"]').fill('2026-11-10');await page.locator('#trendAnnotationForm [name="text"]').fill('动态共享批注测试');await page.locator('#trendAnnotationForm button[type="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('#trendAnnotationList').textContent.includes('动态共享批注测试'));
  await other.goto(base+'?subject='+model.id);await other.waitForSelector('[data-trend-annotation-manage]');await other.locator('[data-trend-annotation-manage]').first().click();await other.waitForFunction(()=>document.querySelector('#trendAnnotationList').textContent.includes('动态共享批注测试'));
  console.log('PASS 真实服务写入且另一个浏览器在车型上读取集团批注');
  await other.locator('#trendAnnotationList li').filter({hasText:'动态共享批注测试'}).getByRole('button',{name:'编辑',exact:true}).click();await other.locator('#trendAnnotationForm [name="text"]').fill('第二浏览器更新');await other.locator('#trendAnnotationForm button[type="submit"]').click();await other.waitForFunction(()=>document.querySelector('#trendAnnotationList').textContent.includes('第二浏览器更新'));
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForFunction(()=>document.querySelector('#trendAnnotationList').textContent.includes('第二浏览器更新'));
  console.log('PASS 跨浏览器更新同步');
  await stop();await start();await page.reload();await page.waitForSelector('[data-trend-annotation-manage]');await page.locator('[data-trend-annotation-manage]').first().click();await page.waitForFunction(()=>document.querySelector('#trendAnnotationList').textContent.includes('第二浏览器更新'));
  console.log('PASS 服务重启后批注保留');
  page.once('dialog',d=>d.accept());await page.locator('#trendAnnotationList li').filter({hasText:'第二浏览器更新'}).getByRole('button',{name:'删除',exact:true}).click();await page.waitForFunction(()=>!document.querySelector('#trendAnnotationList').textContent.includes('第二浏览器更新'));
  await other.evaluate(()=>window.dispatchEvent(new Event('focus')));await other.waitForFunction(()=>!document.querySelector('#trendAnnotationList').textContent.includes('第二浏览器更新'));
  console.log('PASS 共享删除同步');assert.deepStrictEqual(errors,[]);console.log(JSON.stringify({checks:4,errors,state}));
 }finally{if(browser)await browser.close();await stop();}
})().catch(e=>{console.error(e);process.exitCode=1});
