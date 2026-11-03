// Run after main.py. Exercise the actual two-page output over HTTP and file://.
// The baseline reuses this build's data with the pre-split UI, never recalculates it.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const http=require('node:http'),zlib=require('node:zlib');
const {execFileSync}=require('node:child_process'),{pathToFileURL}=require('node:url');
const project=path.resolve(__dirname,'../../..'),code=path.join(project,'scripts');
const output=process.env.FORECAST_OUTPUT_DIR||path.join(project,'output_file');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(project,'.test_runtime/node_modules/playwright'));
const orderName=process.env.FORECAST_ORDER_NAME||'鸿蒙智行订单分析汇总.html',forecastName='鸿蒙智行销量预测.html';
const target='问界 M9 2026款',report={checks:[],errors:[],layout:[]};
const check=(name,value)=>{assert(value,name);report.checks.push(name);console.log('PASS',name);};
const gzip=value=>zlib.gzipSync(Buffer.from(JSON.stringify(value))).toString('base64');
const manifest=html=>JSON.parse(zlib.gunzipSync(Buffer.from(html.match(/window\.DASHBOARD_DATA_B64="([^"]+)"/)[1],'base64')));
const boards=html=>JSON.parse(html.match(/window\.DASHBOARD_BLOCKS_B64=([^\n]+);<\/script>/)[1]);
function baselineHtml(){
  let html=fs.readFileSync(path.join(output,orderName),'utf8');
  const data=manifest(html),forecast=fs.readFileSync(path.join(output,forecastName),'utf8');
  for(const key of ['app_mode','forecast_page','order_page','forecast_legacy_page','raw_block_urls','forecast_disabled'])delete data[key];
  const blocks={...boards(html),...boards(forecast)};
  html=html.replace(/window\.DASHBOARD_DATA_B64="[^"]+"/,'window.DASHBOARD_DATA_B64="'+gzip(data)+'"');
  html=html.replace(/window\.DASHBOARD_BLOCKS_B64=[^\n]+;<\/script>/,'window.DASHBOARD_BLOCKS_B64='+JSON.stringify(blocks)+';</script>');
  const oldJs=execFileSync('git',['show','HEAD:generate_html/templates/dashboard.js'],{cwd:code,encoding:'utf8',maxBuffer:16*1024*1024});
  const oldCss=execFileSync('git',['show','HEAD:generate_html/templates/dashboard.css'],{cwd:code,encoding:'utf8',maxBuffer:16*1024*1024});
  // Once this feature is committed, HEAD itself is a valid shared-engine baseline.
  html=html.replace(/<style>[\s\S]*?<\/style>/,()=>'<style>'+oldCss+'</style>');
  const runtime=/\(async \(\) => \{\r?\n  async function decompressJson/.exec(html);
  assert(runtime,'dashboard runtime marker missing');
  html=html.slice(0,runtime.index)+oldJs+html.slice(html.lastIndexOf('</script>'));
  return html;
}
const ready=page=>page.waitForFunction(()=>document.querySelector('.forecast-workspace')?._forecastComparison);
const settled=page=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false');
async function values(page){return page.locator('.forecast-workspace').evaluate(root=>{
  const c=root._forecastComparison,s=root._smallForecastResult;
  return JSON.parse(JSON.stringify({rows:c.rows,progressRows:c.progressRows,parameterRows:c.parameterRows,
    actualRates:c.actualRates,forecastRates:c.forecastRates,small:s,
    steady:root.querySelector('[data-steady-chart]')?.textContent}));
});}
async function run(){
  const legacy=baselineHtml(),requests=[];
  const server=http.createServer((req,res)=>{
    const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    if(pathname==='/_forecast_baseline.html'){res.setHeader('Content-Type','text/html;charset=utf-8');res.end(legacy);return;}
    const file=path.resolve(output,'.'+pathname);
    if(!file.startsWith(path.resolve(output)+path.sep)){res.writeHead(403);res.end();return;}
    fs.readFile(file,(error,body)=>{if(error){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript;charset=utf-8':'text/html;charset=utf-8');res.end(body);});
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port;
  const url=(name,params={})=>{const value=new URL(encodeURIComponent(name),origin+'/');value.search=new URLSearchParams(params);return value.href;};
  const forecastParams={subject:target,module:'sales_forecast',forecastStage:'launch',forecastView:'result'};
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const context=await browser.newContext({viewport:{width:1366,height:1000},reducedMotion:'reduce'});
    const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>requests.push(r.url()));
    await page.goto(url('_forecast_baseline.html',forecastParams));await ready(page);await settled(page);
    const baseline=await values(page);
    await page.goto(url(forecastName,forecastParams));await ready(page);await settled(page);
    check('独立入口只提供代际车型',await page.locator('#subjectSelect').evaluate(select=>[...select.options].length>0&&[...select.options].every(option=>window.DASHBOARD_DATA.subjects.find(s=>s.id===option.value)?.type==='generation')));
    check('正式预测数量及三阶段结果与原界面相同',JSON.stringify(await values(page))===JSON.stringify(baseline));
    check('独立页面只含预测业务块',await page.evaluate(()=>window.DASHBOARD_DATA.app_mode==='forecast'&&Object.keys(window.DASHBOARD_BLOCKS_B64).every(key=>key.endsWith('|sales_forecast'))));
    check('首次进入不加载底表行或整本Excel',!requests.some(value=>value.includes('/forecast_assets/'))&&await page.evaluate(()=>Object.keys(window.DASHBOARD_RAW_B64).length===0));
    for(const stage of ['small','steady','launch']){
      await page.locator('[data-forecast-nav="'+stage+'"]').click();
      await page.waitForSelector('[data-forecast-stage-pane="'+stage+'"].active');
      for(const view of ['params','evidence','score','result']){
        await page.locator('[data-forecast-tab="'+view+'"]').click();
        const selector=stage==='launch'?'[data-forecast-pane="'+view+'"].active':'[data-lifecycle-subpane="'+stage+'-'+view+'"].active';
        check(stage+' / '+view+'可见',await page.locator(selector).isVisible());
      }
    }
    // Edit real controls after they have been relocated to the dedicated params pane.
    await page.locator('[data-forecast-tab="params"]').click();
    const conversion=page.locator('[data-forecast-input="conversion"]');
    await conversion.fill('41.2');await conversion.dispatchEvent('change');
    await page.waitForFunction(()=>document.querySelector('[data-forecast-feedback]').dataset.state==='success');
    await page.locator('[data-forecast-tab="result"]').click();await page.locator('[data-forecast-tab="params"]').click();
    check('切换视图保留人工参数',await conversion.inputValue()==='41.2');
    await page.reload();await ready(page);
    check('刷新恢复独立看板人工参数',await conversion.inputValue()==='41.2');
    await page.locator('[data-forecast-tab="result"]').click();
    const importPanel=page.locator('[data-forecast-import="launch"]');
    if(!await importPanel.locator('.forecast-import-manager').evaluate(node=>node.open))await importPanel.locator('.forecast-import-manager > summary').click();
    const launchDate=await page.locator('.forecast-workspace').evaluate(n=>JSON.parse(n.dataset.forecastConfig).target.launch_date);
    await importPanel.locator('[data-forecast-import-file]').setInputFiles({name:'standalone.csv',mimeType:'text/csv',buffer:Buffer.from('车型（代际）,日期,预测大定\n'+target+','+launchDate+',100\n')});
    await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]').textContent.includes('导入成功'));
    check('独立入口支持原外部预测导入',await page.evaluate(()=>JSON.parse(localStorage.getItem('harmony-forecast-v1:'+location.pathname)).imports.some(([,entry])=>entry.rows.some(row=>row.quantity===100&&row.source==='standalone.csv'))));
    // Reuse a validated production draft as the old-page storage record.
    const migration=await page.evaluate(()=>{
      const key='harmony-forecast-v1:'+location.pathname,legacy='harmony-forecast-v1:'+new URL(window.DASHBOARD_DATA.forecast_legacy_page,location.href).pathname;
      const raw=localStorage.getItem(key);localStorage.setItem(legacy,raw);
      // Simulate arriving from the old URL, not a dirty new page recreating its key on unload.
      document.querySelector('.forecast-workspace').dataset.forecastDirty='false';
      localStorage.removeItem(key);return {key,legacy,raw};
    });
    await page.reload();await ready(page);
    check('旧地址草稿迁移到新地址',await conversion.inputValue()==='41.2'&&await page.evaluate(({key,legacy,raw})=>localStorage.getItem(key)===raw&&localStorage.getItem(legacy)===raw,migration));
    check('旧地址外部预测同时迁移',await page.evaluate(()=>JSON.parse(localStorage.getItem('harmony-forecast-v1:'+location.pathname)).imports.some(([,entry])=>entry.rows.some(row=>row.quantity===100&&row.source==='standalone.csv'))));
    // Source buttons must retain physical-file/Sheet positioning after the split.
    await page.locator('[data-workspace-source]').click();await page.waitForSelector('#rawTable');await settled(page);
    check('来源跳转只加载所选Sheet',await page.evaluate(()=>Object.keys(window.DASHBOARD_RAW_B64).length===1&&Object.keys(window.DASHBOARD_RAW_B64).every(key=>!key.endsWith('|xlsx'))));
    const selected=await page.evaluate(()=>({file:document.querySelector('#rawFile').value,sheet:document.querySelector('#rawSheet').value,key:window.DASHBOARD_DATA.raw_files[Number(document.querySelector('#rawFile').value)].workbook_key}));
    check('底表默认锁定首列且来源定位写入网址',await page.locator('#rawFreezeFirstColumn').isChecked()&&new URL(page.url()).searchParams.get('rawSheet')===await page.locator('#rawSheet').evaluate(n=>n.selectedOptions[0].textContent));
    const firstText=await page.locator('#rawTable tr').nth(1).locator('td').first().textContent();
    await page.locator('#rawSearch').fill(firstText||'2026');
    const csvDownload=page.waitForEvent('download');await page.locator('#exportRaw').click();const csv=await csvDownload;
    check('当前筛选数据可导出CSV',csv.suggestedFilename().endsWith('.csv')&&fs.statSync(await csv.path()).size>3);
    const xlsxDownload=page.waitForEvent('download');await page.locator('#exportRawWorkbook').click();const xlsx=await xlsxDownload;
    const workbook=fs.readFileSync(await xlsx.path());
    const expectedHash=await page.evaluate(key=>{
      const text=window.DASHBOARD_RAW_B64[key];return text;
    },selected.key);
    check('整个Excel按需下载且字节与快照一致',xlsx.suggestedFilename().endsWith('.xlsx')&&workbook.equals(Buffer.from(expectedHash,'base64'))&&workbook[0]===0x50&&workbook[1]===0x4b);
    // Return through browser history, keeping model/phase and its saved draft.
    await page.goBack();await ready(page);
    check('来源页后退恢复预测车型和人工参数',await page.locator('#subjectSelect').evaluate(n=>n.selectedOptions[0].textContent)===target&&await conversion.inputValue()==='41.2');
    // A fresh document has no cached row blocks; block only its requested asset once.
    let failOnce=true;await page.route('**/forecast_assets/*.js',route=>{if(failOnce){failOnce=false;route.abort();}else route.continue();});
    await page.reload();await ready(page);await page.locator('[data-workspace-source]').click();
    await page.waitForSelector('[data-raw-retry]');check('缺少配套底表时明确失败并允许重试',await page.locator('[data-raw-retry]').isVisible());
    await page.locator('[data-raw-retry]').click();await page.waitForSelector('#rawTable');await settled(page);
    check('底表重试后恢复且未缓存失败Promise',await page.locator('#rawTable tr').count()>1);
    await page.unroute('**/forecast_assets/*.js');
    let corruptOnce=true;await page.route('**/forecast_assets/*.js',route=>{
      if(corruptOnce){corruptOnce=false;route.fulfill({contentType:'application/javascript',body:'window.DASHBOARD_RAW_B64['+JSON.stringify(selected.file+'|'+selected.sheet)+']="bm90LWd6aXA=";'});}
      else route.continue();
    });
    await page.goto(url(forecastName,forecastParams));await ready(page);await page.locator('[data-workspace-source]').click();
    await page.waitForSelector('[data-raw-retry]');check('底表损坏时不误报为空表',await page.locator('[data-raw-retry]').isVisible());
    await page.locator('[data-raw-retry]').click();await page.waitForSelector('#rawTable');await settled(page);
    check('解压失败后重试可重新读取正确资源',await page.locator('#rawTable tr').count()>1);
    await page.unroute('**/forecast_assets/*.js');
    // Each app has its own navigation; old prediction URL deep links remain compatible.
    await page.goto(url(orderName,{subject:target,module:'overview'}));await settled(page);
    for(const width of [1366,390]){
      await page.setViewportSize({width,height:1000});
      check(width+'px订单导航不展示销量预测按钮或选项',await page.locator('[data-module="sales_forecast"],#moduleSelect option[value="sales_forecast"]').count()===0);
      check(width+'px订单导航保留订单总览和底表',await page.locator('[data-module="overview"]').count()===1&&await page.locator('[data-module="raw"]').count()===1);
    }
    await page.goto(url(forecastName,forecastParams));await ready(page);
    check('直接打开独立看板保留车型',await page.locator('#subjectSelect').evaluate(n=>n.selectedOptions[0].textContent)===target);
    await page.goto(url(orderName,forecastParams));await ready(page);
    check('旧预测深链接自动跳转且保留阶段',decodeURIComponent(new URL(page.url()).pathname).endsWith('/'+forecastName)&&new URL(page.url()).searchParams.get('forecastStage')==='launch');
    for(const width of [1366,1920,390]){
      await page.setViewportSize({width,height:1000});
      check(width+'px预测导航无返回订单分析入口',await page.locator('.forecast-order-link').count()===0&&await page.getByRole('link',{name:'返回订单分析'}).count()===0);
      check(width+'px预测导航仅含三阶段和底表',JSON.stringify(await page.locator('[data-forecast-nav]').evaluateAll(nodes=>nodes.map(node=>node.dataset.forecastNav)))===JSON.stringify(['small','launch','steady','raw'])&&JSON.stringify(await page.locator('#moduleSelect option').evaluateAll(nodes=>nodes.map(node=>node.value)))===JSON.stringify(['small','launch','steady','raw']));
      await page.locator('[data-forecast-tab="params"]').click();
      const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,fields:[...document.querySelectorAll('.forecast-general-settings [data-forecast-target]')].map(n=>{const b=n.getBoundingClientRect();return {left:b.left,right:b.right,width:b.width,height:b.height};})}));
      report.layout.push(layout);check(width+'px参数区域与页面无横向裁切',layout.scroll<=width+1&&layout.fields.length===9&&layout.fields.every(b=>b.left>=0&&b.right<=width+1&&b.width>0&&b.height>0));
      await page.locator('[data-forecast-tab="result"]').click();
      check(width+'px结果区域无整页横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
    const filePage=await context.newPage();filePage.on('pageerror',e=>report.errors.push(e.message));
    const fileUrl=pathToFileURL(path.join(output,forecastName));fileUrl.search=new URLSearchParams(forecastParams);
    await filePage.goto(fileUrl.href);await ready(filePage);await filePage.locator('[data-workspace-source]').click();await filePage.waitForSelector('#rawTable');
    check('file协议独立入口与配套底表也可打开',await filePage.locator('#rawTable tr').count()>1);
    assert.deepEqual(report.errors,[]);check('浏览器无脚本异常',true);
    console.log(JSON.stringify({passed:true,checks:report.checks.length,layout:report.layout,pageErrors:report.errors},null,2));
    await context.close();
  }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
}
run().catch(error=>{console.error(error.stack||error);process.exitCode=1;});
