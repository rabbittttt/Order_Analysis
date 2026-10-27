// Run after main.py: node tests/sku_raw_export_browser.cjs [dashboard.html]
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url'),{createHash}=require('node:crypto');
const root=path.resolve(__dirname,'..');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.resolve(root,'../../.test_runtime/node_modules/playwright'));
const html=process.argv[2]||path.resolve(root,'../../output_file/鸿蒙智行订单分析汇总.html');
const source=fs.readFileSync(path.join(root,'templates/dashboard.js'),'utf8');
const css=fs.readFileSync(path.join(root,'templates/dashboard.css'),'utf8');
const runtime=source.slice(source.indexOf('  const displayText ='),source.indexOf('  const colors ='))+
 source.slice(source.indexOf('  function bindSkuHeatmaps('),source.indexOf('  function renderTailDistribution('));
const switchStart=source.indexOf('    document.querySelectorAll("[data-combo-switch]")');
const switches=source.slice(switchStart,source.indexOf('    document.querySelectorAll("[data-hourly-select]")',switchStart));
const periods=Array.from({length:24},(_,i)=>'26WK'+(20+i));
const heat={periods,rows:Array.from({length:15},(_,i)=>({label:'TOP'+(i+1),values:periods.map((_,j)=>(i+j)/40)}))};
const combo={groups:[24,16].map((length,i)=>({name:['外饰 × 内饰 × 轮毂','版本 × 外饰'][i],periods:periods.slice(-length),
 rows:[{rank:'TOP1',label:'Ultra版 × 曜石黑 × 琥珀棕 × 20英寸轮毂',values:periods.slice(-length).map((_,j)=>(j+1)/length)}]}))};
const scrollState=locator=>locator.evaluate(n=>({left:n.scrollLeft,max:n.scrollWidth-n.clientWidth}));
async function atRight(locator){const s=await scrollState(locator);assert(s.max>0);assert(Math.abs(s.left-s.max)<1,JSON.stringify(s))}

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.setContent('<!doctype html><meta charset="utf-8"><main id="fixture" style="padding:20px;max-width:1400px;margin:auto"></main>');
  await page.addStyleTag({content:css+'\nhtml,body{height:auto;min-height:100%;overflow:auto}'});
  await page.addScriptTag({content:runtime+`
   const state={period:'26WK34'};
   window.fixture=(data)=>{document.querySelector('#fixture').innerHTML='<div class="sections"><article class="panel full"><div class="panel-body">'+
    renderSkuHeatmap(data.heat)+'</div></article><article class="panel full"><div class="panel-body">'+renderComboMatrix(data.combo)+'</div></article></div>';
    bindSkuHeatmaps();${switches}};window.rebind=bindSkuHeatmaps;`});
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1000});
   await page.evaluate(data=>window.fixture(data),{heat,combo});
   const weekly=page.locator('.sku-heatmap-scroll').first(),first=page.locator('[data-combo-panel="0"]'),second=page.locator('[data-combo-panel="1"]');
   for(const region of [weekly,first]){
    await atRight(region);
    assert.equal(await region.locator('[data-sku-period]').count(),24);
    await region.focus();await page.keyboard.press('Home');assert.equal((await scrollState(region)).left,0);
    const earliest=await region.locator('[data-sku-period]').first().boundingBox(),frame=await region.boundingBox();
    assert(earliest.x>=frame.x&&earliest.x+earliest.width<=frame.x+frame.width+1);
    await page.keyboard.press('End');await atRight(region);
    const before=await scrollState(region),box=await region.boundingBox();
    await page.mouse.move(box.x+150,box.y+25);await page.mouse.down();
    await page.mouse.move(box.x+240,box.y+25,{steps:5});await page.mouse.up();
    assert(Math.abs((await scrollState(region)).left-(before.max-90))<2);
    const touch=await region.evaluate(n=>n.dispatchEvent(new PointerEvent('pointerdown',{pointerType:'touch',button:0,pointerId:9,bubbles:true,cancelable:true})));
    assert(touch);
   }
   assert.equal(await second.evaluate(n=>Boolean(n._skuHeatmapBound)),false);
   await first.evaluate(n=>n.scrollLeft=37);
   await page.locator('[data-combo-switch="1"]').click();await atRight(second);
   assert.equal(await second.locator('[data-sku-period]').count(),16);
   await second.focus();await page.keyboard.press('Home');assert.equal((await scrollState(second)).left,0);
   await page.locator('[data-combo-switch="0"]').click();assert.equal((await scrollState(first)).left,37);
   await page.evaluate(()=>window.rebind());assert.equal((await scrollState(first)).left,37);
   const text=await weekly.locator('.heatmap-row').nth(1).locator('div').allTextContents();
   assert.deepEqual(text.slice(1),heat.rows[0].values.map(v=>(v*100).toFixed(1)+'%'));
   console.log(JSON.stringify({width,fullHistory:true,defaultLatest:true,drag:true,keyboard:true,hiddenComboInitializes:true,userScrollPreserved:true}));
  }

  await page.setViewportSize({width:1440,height:1000});
  const base=pathToFileURL(html),ready=()=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false');
  await page.goto(base.href);await ready();
  const subjects=await page.evaluate(()=>window.DASHBOARD_DATA.subjects);
  const sku=subjects.find(s=>s.name.includes('V9')&&s.modules.includes('sku'))||subjects.find(s=>s.modules.includes('sku'));
  const url=new URL(base);url.search=new URLSearchParams({subject:sku.id,module:'sku',grain:'week'});
  await page.goto(url.href);await ready();
  const ranking=page.locator('.panel').filter({has:page.getByRole('heading',{name:'主销SKU排行',exact:true})});
  assert.deepEqual(await ranking.locator('th').allTextContents(),['排名','SKU','版本中文名称','外饰','内饰','轮毂套件','占比']);
  assert((await ranking.locator('tbody tr').count())>0);
  await ranking.screenshot({path:path.join(process.env.TEMP||'/tmp','order-sku-ranking-20261027.png')});
  await page.setViewportSize({width:390,height:900});
  await ranking.scrollIntoViewIfNeeded();
  const tableBox=await ranking.locator('.table-wrap').evaluate(n=>({client:n.clientWidth,scroll:n.scrollWidth}));
  assert(tableBox.scroll>tableBox.client);
  await page.setViewportSize({width:1440,height:1000});

  await page.locator('[data-module="raw"]').click();await page.waitForSelector('#rawSearch');
  const files=await page.evaluate(()=>window.DASHBOARD_DATA.raw_files);
  const indexes=[...new Set([0,files.findIndex(f=>f.name.includes('SKU')),files.length-1])].filter(i=>i>=0);
  for(const index of indexes){
   await page.locator(`[data-file="${index}"]`).click();
   await page.waitForFunction(name=>document.querySelector('.raw-title strong')?.textContent===name,files[index].name);
   await page.locator('#rawSearch').fill('NO_MATCH_WHOLE_WORKBOOK_EXPORT');
   await page.waitForSelector('#rawEmpty:not([hidden])');
   const pending=page.waitForEvent('download');await page.locator('#exportRawWorkbook').click();const download=await pending;
   assert.equal(download.suggestedFilename(),files[index].name);
   const actual=fs.readFileSync(await download.path()),original=fs.readFileSync(path.join(path.dirname(html),files[index].name));
   const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
   assert.equal(hash(actual),hash(original));
   const csvPending=page.waitForEvent('download');await page.locator('#exportRaw').click();const csv=fs.readFileSync(await (await csvPending).path(),'utf8');
   assert(!csv.includes('\r\n'),'filtered CSV must contain only the header for no results');
  }
  await page.locator('#clearRawSearch').click();assert((await page.locator('#rawTable tr').count())>1);
  let disabled=0;
  for(const subject of subjects.filter(s=>s.modules.includes('overview')).slice(0,2)){
   await page.locator('#subjectSelect').selectOption(subject.id);await ready();
   disabled+=await page.locator('[data-module][disabled]').count();
   await page.locator('[data-module="overview"]').click();await ready();
   for(const grain of ['day','week','month']){await page.locator(`[data-grain="${grain}"]`).click();await ready();assert.equal(new URL(page.url()).searchParams.get('grain'),grain)}
  }
  assert(disabled>0);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({sku:sku.name,rankingFields:7,wholeWorkbookByteExact:indexes.length,filteredCsv:true,subjectSwitch:true,grains:3,disabled,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
