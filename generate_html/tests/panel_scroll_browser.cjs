// Run after main.py. PANEL_USE_TEMPLATE_CSS=1 checks pending CSS on the formal page.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),{pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'..'),{chromium}=require(process.env.PLAYWRIGHT_MODULE||path.resolve(root,'../../.test_runtime/node_modules/playwright'));
const html=process.argv[2]||path.resolve(root,'../../output_file/鸿蒙智行订单分析汇总.html');
const css=fs.readFileSync(path.join(root,'templates/dashboard.css'),'utf8');
const output=process.env.PANEL_ARTIFACT_DIR||path.join(process.env.TEMP||'/tmp','order-panel-scroll');
const ready=page=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false');
async function verifyPanel(panel){
 await panel.scrollIntoViewIfNeeded();
 // Center the header below the mobile sticky module picker before hit-testing.
 await panel.locator(':scope>.panel-head').evaluate(n=>n.scrollIntoView({block:'center',behavior:'instant'}));
 return panel.evaluate(n=>{
  const body=n.querySelector(':scope>.panel-body'),head=n.querySelector(':scope>.panel-head'),unlimited=getComputedStyle(n).maxHeight==='none';
  const before=head.getBoundingClientRect(),text=body.textContent,contentHeight=body.scrollHeight;
  body.scrollTop=150;
  const after=head.getBoundingClientRect(),box=n.getBoundingClientRect(),viewport=body.getBoundingClientRect();
  const leaked=[];
  for(let y=Math.ceil(box.top)+2;y<Math.floor(viewport.top);y+=3)for(const x of [box.left+24,box.left+box.width/2,box.right-24]){
   if(y<0||y>=innerHeight||x<0||x>=innerWidth)continue;
   const hit=document.elementFromPoint(x,y);if(hit&&body.contains(hit))leaked.push({x,y,tag:hit.tagName});
  }
  const source=head.querySelector('[data-panel-source]');let sourceHit=true,sourceDetail=null;
  if(source){const b=source.getBoundingClientRect(),hit=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);sourceHit=source.contains(hit);if(!sourceHit)sourceDetail={width:innerWidth,button:{left:b.left,top:b.top,right:b.right,bottom:b.bottom},hit:hit?.outerHTML.slice(0,250)};}
  const middle=body.scrollTop;body.scrollTop=body.scrollHeight;
  const last=body.lastElementChild?.getBoundingClientRect(),end=body.getBoundingClientRect();
  return {kind:n.dataset.sectionKind,unlimited,height:box.height,headShift:after.top-before.top,leaked,sourceHit,sourceDetail,middle,panelScroll:n.scrollTop,bodyHeight:body.clientHeight,contentHeight,atEnd:Math.abs(body.scrollTop-(body.scrollHeight-body.clientHeight))<=1,lastReached:!last||last.bottom<=end.bottom+2,textPreserved:text===body.textContent,overflow:getComputedStyle(body).overflowY};
 });
}
function checkPanel(m){
 assert.equal(m.headShift,0,m.kind+' title moved with content');assert.equal(m.leaked.length,0,m.kind+' content entered title/padding');assert(m.sourceHit,m.kind+' source button obscured '+JSON.stringify(m.sourceDetail));assert.equal(m.panelScroll,0,m.kind+' outer card still scrolls');assert(m.textPreserved,m.kind+' content changed');
 if(m.unlimited){assert.equal(m.overflow,'visible');assert.equal(m.middle,0,m.kind+' page-scroll exception gained an inner scroller');}
 else {assert(m.height<=500.1,m.kind+' lost height limit');assert.equal(m.overflow,'auto');assert(m.atEnd&&m.lastReached,m.kind+' last content is unreachable');if(m.contentHeight>m.bodyHeight+1)assert(m.middle>0,m.kind+' vertical scrolling stopped');}
}
(async()=>{
 fs.mkdirSync(output,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'}),report=[],errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});page.on('pageerror',e=>errors.push(e.message));
  // A genuinely long ordinary table detects the old 54px header gap and proves
  // the final row remains reachable. This fixture changes no dashboard payload.
  for(const width of [1440,390]){
   await page.setViewportSize({width,height:1000});
   await page.setContent('<!doctype html><meta charset="utf-8"><style>'+css+'</style><main style="padding:20px"><article class="panel full" data-section-kind="table"><div class="panel-head"><div><h2>普通长表的标题与来源按钮保持可见</h2><span>滚动内容不得进入标题或上方留白</span></div><button class="panel-source" data-panel-source="0">来源数据</button></div><div class="panel-body"><div class="table-wrap"><table class="data-table"><thead><tr><th>周期</th><th>数量</th></tr></thead><tbody>'+Array.from({length:60},(_,i)=>'<tr><td>D'+(i+1)+'</td><td>'+i+'</td></tr>').join('')+'</tbody></table></div></div></article></main>');
   const panel=page.locator('.panel'),m=await verifyPanel(panel);checkPanel(m);
   const header=await panel.evaluate(n=>{const body=n.querySelector('.panel-body'),th=n.querySelector('th');return {offset:th.getBoundingClientRect().top-body.getBoundingClientRect().top,last:n.querySelector('tbody tr:last-child').getBoundingClientRect().bottom-body.getBoundingClientRect().bottom};});
   assert(Math.abs(header.offset)<1,'table header retains the old card-title offset');assert(header.last<=1,'last table row is clipped');
   await panel.screenshot({path:path.join(output,'long-table-'+width+'.png')});report.push({width,fixture:true,...m});
  }
  const base=pathToFileURL(html);await page.goto(base.href);await ready(page);
  if(process.env.PANEL_USE_TEMPLATE_CSS==='1')await page.addStyleTag({content:css});
  const subjects=await page.evaluate(()=>window.DASHBOARD_DATA.subjects),modules=['sku','overview','order_mix','channel_analysis','cancellation','launch_rhythm'];
  let sourceChecked=false;
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1000});
   for(const module of modules){
    const subject=subjects.find(s=>s.modules.includes(module));if(!subject)continue;
    if(await page.locator('#subjectSelect').inputValue()!==subject.id){await page.locator('#subjectSelect').selectOption(subject.id);await page.waitForFunction(id=>document.querySelector('#page')?.dataset.viewKey?.startsWith(id+'|')&&document.querySelector('#page').getAttribute('aria-busy')==='false',subject.id);}
    if(await page.locator('#page').getAttribute('data-view-key')!==subject.id+'|'+module){const button=page.locator(`[data-module="${module}"]`);if(await button.isVisible())await button.click();else await page.locator('#moduleSelect').selectOption(module);}
    await page.waitForFunction(key=>document.querySelector('#page')?.dataset.viewKey===key&&document.querySelector('#page').getAttribute('aria-busy')==='false',subject.id+'|'+module);
    for(const panel of await page.locator('#page .panel').all()){
     const m=await verifyPanel(panel);checkPanel(m);report.push({width,module,...m});
     if(m.kind==='sku_heatmap')await panel.screenshot({path:path.join(output,'sku-scrolled-'+width+'.png')});
    }
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),module+' page overflows');
    if(module==='sku'&&!sourceChecked){
     const source=page.locator('.panel[data-section-kind="sku_heatmap"]>.panel-head [data-panel-source]');
     await source.click();await page.waitForSelector('#rawSearch');await ready(page);sourceChecked=true;
    }
   }
  }
  assert(sourceChecked,'no source action checked');assert.deepEqual(errors,[]);
  for(const kind of ['sku_heatmap','channel_panel','structure_cards'])assert(report.some(m=>m.kind===kind),'missing representative '+kind);
  fs.writeFileSync(path.join(output,'report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({panels:report.length,scrollable:report.filter(m=>m.middle>0).length,unlimited:report.filter(m=>m.unlimited).length,kinds:[...new Set(report.map(m=>m.kind))],sourceChecked,errors,output}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
