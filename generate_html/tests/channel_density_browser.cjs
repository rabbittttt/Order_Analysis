// Display-only fixtures exercise the real channel component and all history cells.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const project=path.resolve(__dirname,'../../..'),root=path.resolve(__dirname,'..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const htmlIndex=process.argv.indexOf('--html'),html=htmlIndex<0?'':fs.readFileSync(process.argv[htmlIndex+1],'utf8');
const script=html||fs.readFileSync(path.join(root,'templates/dashboard.js'),'utf8');
const css=html?html.match(/<style>([\s\S]*?)<\/style>/)[1]:fs.readFileSync(path.join(root,'templates/dashboard.css'),'utf8');
const oldCss=process.env.CHANNEL_DENSITY_BASELINE_CSS?fs.readFileSync(process.env.CHANNEL_DENSITY_BASELINE_CSS,'utf8'):null;
const formatter=script.slice(script.indexOf('  const displayText ='),script.indexOf('  const colors ='));
const component=script.slice(script.indexOf('  const channelPanelData='),script.indexOf('  function renderStackedTrend('));
const artifacts=process.env.AUDIT_ARTIFACT_DIR||path.join(project,'.test_runtime/channel_density_20261021');
fs.mkdirSync(artifacts,{recursive:true});
const channels=['华为授权体验店','华为智能生活馆','华为旗舰店','鸿蒙智行用户中心','问界用户中心','智界用户中心','享界用户中心','尊界用户中心','尚界用户中心','未知门店类型'];
function fixture(size){
 const names=channels.slice(0,size),history=Array.from({length:16},(_,index)=>{
  const rows=names.map((channel,slot)=>({channel,count:100+index*10+slot,share:1/size,store_count:1800-slot*100,active_count:100+index+slot,active_rate:(100+index+slot)/(1800-slot*100),productivity:(100+index*10+slot)/(1800-slot*100)}));
  return {period:`26WK${String(index+27).padStart(2,'0')}`,rows,totals:{count:rows.reduce((sum,row)=>sum+row.count,0),active_count:rows.reduce((sum,row)=>sum+row.active_count,0),active_rate:.12,productivity:.5}};
 });
 return ['sales','stores','capacity'].map(metric=>({metric,period:history.at(-1).period,rows:history.at(-1).rows,totals:history.at(-1).totals,history}));
}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'msedge'}),errors=[],report=[];
 let checks=0;
 const check=(value,label)=>{assert(value,label);checks++};
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100},reducedMotion:'reduce'});
  page.on('pageerror',error=>errors.push(error.message));
  await page.setContent('<!doctype html><meta charset="utf-8"><main id="fixture" style="padding:20px;max-width:1600px;margin:auto"></main>');
  const style=await page.addStyleTag({content:css+'\nhtml,body{height:auto;min-height:100%;overflow:auto}'});
  await page.addScriptTag({content:formatter+'\n'+component+`
   window.renderFixture=panels=>{
    channelPanelData.clear();window.fixtureSource=JSON.stringify(panels);
    document.querySelector('#fixture').innerHTML=panels.map(data=>'<article class="panel full" data-section-kind="channel_panel"><div class="panel-body">'+renderChannelPanel(data)+'</div></article>').join('');
    bindChannelPanels();
   };`});
  const settle=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const measure=()=>page.locator('.channel-panel').evaluateAll(panels=>panels.map(panel=>({
   metric:panel.dataset.channelMetric,leftHeight:panel.querySelector('.channel-history-tables').getBoundingClientRect().height,chartHeight:panel.querySelector('.channel-chart-block').getBoundingClientRect().height,
   svgHeight:panel.querySelector('.channel-plot-scroll svg')?.getBoundingClientRect().height,
   tables:[...panel.querySelectorAll('[data-channel-table]')].map(table=>({
    key:table.dataset.channelTable,channels:[...table.querySelectorAll('tbody tr')].map(row=>row.dataset.channel),periods:table.querySelectorAll('thead [data-period]').length,
    rowHeights:[...table.querySelectorAll('tbody tr')].map(row=>row.getBoundingClientRect().height),fontSize:parseFloat(getComputedStyle(table).fontSize),
    values:[...table.querySelectorAll('td[data-value]')].map(cell=>[cell.dataset.value,cell.textContent]),
    fullHeight:table.parentElement.clientHeight>=table.getBoundingClientRect().height-1,
    nameWidth:table.querySelector('tbody th').getBoundingClientRect().width,
    labelsFit:[...table.querySelectorAll('tbody th')].every(cell=>cell.scrollWidth<=cell.clientWidth+1),
    configCount:table.querySelectorAll('small').length
   }))
  })));
  for(const size of [10,5])for(const width of [1920,1440,768,390]){
   await page.setViewportSize({width,height:1100});
   const data=fixture(size);await page.evaluate(panels=>window.renderFixture(panels),data);await settle();
   const current=await measure(),label=`${size} channels / ${width}px`;
   check(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)),label+' no page overflow');
   for(const panel of current){
    const wanted=panel.metric==='sales'?['count','share']:panel.metric==='stores'?['active_count','active_rate']:['productivity'];
    assert.deepEqual(panel.tables.map(table=>table.key),wanted,label+' metric tables');checks++;
    if(size===10&&width>=1440&&panel.metric!=='capacity')check(Math.abs(panel.leftHeight-panel.chartHeight)<=60,label+' dual tables and chart have similar heights');
    for(const table of panel.tables){
     assert.deepEqual(table.channels,channels.slice(0,size),label+' all channel names retained');checks++;
     check(table.periods===16,label+' all history periods retained');
     check(table.fontSize>=11,label+' readable numeric type size');
     check(table.fullHeight&&table.labelsFit,label+' complete rows without clipping');
     check(Math.max(...table.rowHeights)<=24,label+' compact single-line rows');
     if(table.key==='active_count')check(table.configCount===0,label+' counts do not repeat configured-store sublabels');
    }
   }
   const beforeValues=JSON.stringify(current.map(panel=>panel.tables.map(table=>table.values)));
   const scrolls=await page.locator('.channel-matrix-scroll').evaluateAll(nodes=>nodes.map(scroll=>{
    const table=scroll.querySelector('table'),heading=table.querySelector('tbody th'),left=heading.getBoundingClientRect().left;
    const overflow=scroll.scrollWidth>scroll.clientWidth+2;scroll.scrollLeft=0;
    const pinned=Math.abs(heading.getBoundingClientRect().left-left)<1;
    scroll.scrollLeft=scroll.scrollWidth;
    return {pinned,moved:scroll.scrollLeft>0,overflow,focusable:scroll.tabIndex===0};
   }));
   check(scrolls.every(item=>item.pinned&&item.focusable&&(!item.overflow||item.moved)),label+' sticky channel column and horizontal scroll preserved');
   check(JSON.stringify((await measure()).map(panel=>panel.tables.map(table=>table.values)))===beforeValues,label+' scrolling does not alter any table value');
   if(oldCss&&width===1440){
    await style.evaluate((element,value)=>{element.textContent=value+'\nhtml,body{height:auto;min-height:100%;overflow:auto}'},oldCss);await settle();
    const before=await measure();
    await style.evaluate((element,value)=>{element.textContent=value+'\nhtml,body{height:auto;min-height:100%;overflow:auto}'},css);await settle();
    for(const panel of current){
     const prior=before.find(item=>item.metric===panel.metric);
     assert.deepEqual(panel.tables.map(table=>table.values),prior.tables.map(table=>table.values),label+' CSS preserves displayed source values');checks++;
     check(panel.svgHeight===prior.svgHeight,label+' CSS preserves chart geometry');
     if(panel.metric!=='capacity')check(panel.leftHeight<=prior.leftHeight*.8,label+' dual tables reduced at least 20%');
    }
    report.push({size,width,current,before});
   }else report.push({size,width,current});
   if(width===1440||width===390)for(const metric of ['sales','stores'])await page.locator(`[data-channel-metric="${metric}"]`).screenshot({path:path.join(artifacts,`density-${size}-${metric}-${width}.png`)});
   const point=page.locator('[data-channel-metric="stores"] [data-channel-point]').last();await point.focus();
   await page.keyboard.press('Home');await settle();
   check((await page.locator('[data-channel-metric="stores"] [data-channel-tooltip]').innerText()).includes('26WK27'),label+' keyboard historical tooltip preserved');
   await page.keyboard.press('End');await page.keyboard.press('Escape');
   check(await page.locator('[data-channel-metric="stores"] [data-channel-tooltip]').isHidden(),label+' keyboard tooltip dismissal preserved');
  }
  assert.deepEqual(errors,[]);checks++;
  fs.writeFileSync(path.join(artifacts,'density-report.json'),JSON.stringify({checks,errors,report},null,2));
  console.log(JSON.stringify({checks,views:report.length,errors,template:html?'rebuilt HTML':'source template',artifacts}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
