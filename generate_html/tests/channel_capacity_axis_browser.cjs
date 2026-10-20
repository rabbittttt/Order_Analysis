// Exercise the actual channel component with isolated display-only fixtures.
// Pass --html <generated.html> to verify the code embedded in a rebuilt report.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const project=path.resolve(__dirname,'../../..'),root=path.resolve(__dirname,'..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const htmlIndex=process.argv.indexOf('--html'),html=htmlIndex<0?'':fs.readFileSync(process.argv[htmlIndex+1],'utf8');
const script=html||fs.readFileSync(path.join(root,'templates/dashboard.js'),'utf8');
const css=html?html.match(/<style>([\s\S]*?)<\/style>/)[1]:fs.readFileSync(path.join(root,'templates/dashboard.css'),'utf8');
const formatter=script.slice(script.indexOf('  const displayText ='),script.indexOf('  const colors ='));
const component=script.slice(script.indexOf('  const channelPanelData='),script.indexOf('  function renderStackedTrend('));
assert(formatter&&component,'Real channel template must be available');
const artifacts=process.env.AUDIT_ARTIFACT_DIR||path.join(project,'.test_runtime/channel_capacity_axis_20261020');
fs.mkdirSync(artifacts,{recursive:true});
const channels=['华为授权体验店','鸿蒙智行用户中心'];
function fixture(mode='normal',grain='week',end=39){
 const history=Array.from({length:40},(_,index)=>{
  const period=grain==='day'?new Date(Date.UTC(2026,0,index+1)).toISOString().slice(0,10):grain==='month'?`${2023+Math.floor(index/12)}-${String(index%12+1).padStart(2,'0')}`:`26WK${String(index+1).padStart(2,'0')}`;
  const rows=channels.map((channel,series)=>{
   const productivity=mode==='missing'||mode==='missing-tail'&&index>10?null:mode==='zero'?0:index===0&&series===0?100:index===12?null:(index+series)%7;
   return {channel,productivity,count:productivity==null?null:productivity*100,share:series?.4:.6,store_count:100,active_count:30+series*20,active_rate:.3+series*.2};
  });
  return {period,rows,totals:{count:rows.every(row=>row.count!=null)?rows.reduce((sum,row)=>sum+row.count,0):null,active_rate:.4,productivity:rows[0].productivity}};
 });
 return ['sales','stores','capacity'].map(metric=>({metric,period:history[end].period,rows:history[end].rows,totals:history[end].totals,history}));
}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'msedge'});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 let checks=0;
 const check=(value,label)=>{assert(value,label);checks++};
 try{
  await page.setContent('<!doctype html><meta charset="utf-8"><main id="fixture" style="padding:20px;max-width:1600px;margin:auto"></main>');
  await page.addStyleTag({content:css+'\nhtml,body{height:auto;min-height:100%;overflow:auto}'});
  await page.addScriptTag({content:formatter+'\n'+component+`
   window.renderFixture=panels=>{
    channelPanelData.clear();window.fixtureSource=JSON.stringify(panels);
    document.querySelector('#fixture').innerHTML=panels.map(data=>'<article class="panel full" data-section-kind="channel_panel"><div class="panel-body">'+renderChannelPanel(data)+'</div></article>').join('');
    bindChannelPanels();
   };`});
  const capacity='[data-channel-metric="capacity"]',plot=capacity+' .channel-plot-scroll';
  const settle=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  const render=async(data)=>{await page.evaluate(data=>window.renderFixture(data),data);await settle()};
  const snapshot=()=>page.locator(capacity).evaluate(panel=>{
   const chart=panel.querySelector('[data-channel-chart]'),scroll=panel.querySelector('.channel-plot-scroll'),svg=scroll?.querySelector('svg');
   return {maximum:Number(chart.dataset.channelAxisMax),labels:[...chart.querySelectorAll('.channel-y-axis.left span')].map(item=>item.textContent),
    left:scroll?.scrollLeft,width:scroll?.clientWidth,scrollWidth:scroll?.scrollWidth,svgWidth:svg?.viewBox.baseVal.width,
    points:[...chart.querySelectorAll('.channel-series-point')].map(point=>({channel:point.dataset.channel,period:point.dataset.period,value:point.dataset.value,x:Number(point.getAttribute('cx')),y:Number(point.getAttribute('cy'))})),
    paths:[...chart.querySelectorAll('.channel-series-line')].map(item=>item.getAttribute('d')),
    values:[...panel.querySelectorAll('td[data-value]')].map(item=>item.dataset.value),
    clip:chart.querySelector('clipPath rect')?.outerHTML,empty:chart.classList.contains('channel-chart-empty')};
  });
  const otherGraphs=()=>page.locator('.channel-panel:not([data-channel-metric="capacity"]) [data-channel-chart]').evaluateAll(charts=>charts.map(chart=>chart.innerHTML));
  const scrollTo=async(where)=>{
   await page.locator(plot).evaluate((scroll,where)=>{scroll.scrollLeft=where==='end'?scroll.scrollWidth:where},where);
   await settle();
  };
  const sameData=(a,b,label)=>{assert.deepEqual(b.points.map(({y,...point})=>point),a.points.map(({y,...point})=>point),label+' all history points unchanged');assert.deepEqual(b.values,a.values,label+' table values unchanged');checks+=2};
  const visibleFits=(state,label)=>{
   const visible=state.points.filter(point=>point.x>=state.left&&point.x<=state.left+state.width);
   check(visible.length>0,label+' has visible points');
   check(visible.every(point=>point.y>=26&&point.y<=284),label+' visible points remain within plot');
   check(state.labels[0]==='0.00',label+' zero baseline');
   check(state.paths.every(value=>!/(NaN|Infinity)/.test(value)),label+' finite paths');
   check(!!state.clip,label+' plot clipping is present');
  };
  await render(fixture());
  const initial=await snapshot(),others=await otherGraphs();
  check(initial.maximum>=6&&initial.maximum<=10,'Tail ignores offscreen 100 and uses a readable scale');
  check(Math.abs(initial.left+initial.width-initial.scrollWidth)<=2,'Initial view remains at latest period');
  visibleFits(initial,'tail');
  const initialSource=await page.evaluate(()=>window.fixtureSource);
  await page.locator(capacity).screenshot({path:path.join(artifacts,'capacity-tail-1440.png')});

  await scrollTo(0);
  await page.waitForFunction(selector=>Number(document.querySelector(selector+' [data-channel-chart]').dataset.channelAxisMax)>100,capacity);
  const early=await snapshot();
  check(early.maximum<=130,'Early high value has modest headroom');
  check(early.paths.some((value,index)=>value!==initial.paths[index]),'Existing paths are rescaled');
  visibleFits(early,'early');sameData(initial,early,'left scroll');
  await page.locator(capacity).screenshot({path:path.join(artifacts,'capacity-early-1440.png')});
  await scrollTo(25);
  check((await snapshot()).maximum>100,'High point still scales the axis while its center is visible at the edge');
  await scrollTo(27);
  const edge=await snapshot();
  check(edge.maximum<=10,'Offscreen high point stops compressing visible points at the edge');
  check(edge.points.find(point=>Number(point.value)===100).y<26&&/height="258"/.test(edge.clip),'Offscreen high geometry is retained and clipped to the plot');
  visibleFits(edge,'partial boundary period');
  await scrollTo('end');visibleFits(await snapshot(),'returned tail');
  assert.deepEqual(await otherGraphs(),others,'Sales and contributing-store chart markup stays unchanged');checks++;

  for(const width of [1920,390,1440]){
   await page.setViewportSize({width,height:1100});await settle();
   const state=await snapshot();
   check(state.maximum<=10,'Resize '+width+' retains local scale');
   check(Math.abs(state.left+state.width-state.scrollWidth)<=2,'Resize '+width+' preserves tail position');
   sameData(initial,state,'resize '+width);visibleFits(state,'resize '+width);
   if(width===390)await page.locator(capacity).screenshot({path:path.join(artifacts,'capacity-tail-390.png')});
  }
  await scrollTo(650);
  await page.setViewportSize({width:1920,height:1100});await settle();
  check(Math.abs((await snapshot()).left-650)<=2,'Resize preserves user-selected historical position');
  visibleFits(await snapshot(),'historical resize');
  await page.setViewportSize({width:1440,height:1100});await settle();
  await scrollTo('end');
  await page.locator(capacity+' [data-channel-point]').last().focus();
  await page.keyboard.press('Home');await settle();
  check((await snapshot()).maximum>100,'Keyboard Home exposes high-value scale');
  check((await page.locator(capacity+' [data-channel-tooltip]').innerText()).includes('100.00'),'Tooltip retains real high value');
  await page.keyboard.press('End');await settle();
  check((await snapshot()).maximum<=10,'Keyboard End restores local scale');
  await page.keyboard.press('Escape');
  check(await page.locator(capacity+' [data-channel-tooltip]').isHidden(),'Tooltip Escape still works');
  assert.equal(await page.evaluate(()=>window.fixtureSource),initialSource,'Component never mutates fixture source');checks++;

  for(const grain of ['day','month','week']){
   const panels=fixture('normal',grain,29);
   await render(panels);
   const state=await snapshot();
   check(state.maximum<=10,grain+' period switch ignores offscreen high');
   check(state.points.at(-1).period===panels[0].period&&state.points.length===58,grain+' selection excludes future periods');
   visibleFits(state,grain);
  }
  await render(fixture('zero'));
  const zero=await snapshot();
  check(zero.maximum===1&&zero.points.every(point=>point.y===284),'All-zero range uses stable finite baseline');
  await scrollTo(0);check((await snapshot()).maximum===1,'Zero range scroll remains stable');
  await render(fixture('missing-tail'));
  const missingTail=await snapshot();
  check(missingTail.maximum===1,'Missing visible range uses stable fallback instead of offscreen high');
  check(missingTail.paths.every(value=>!/(NaN|Infinity)/.test(value)),'Missing range keeps finite paths and original gaps');
  await scrollTo(0);check((await snapshot()).maximum>100,'Known earlier values remain available from missing range');
  await render(fixture('missing'));
  check((await snapshot()).empty,'All-missing data retains existing empty state');
  await page.setViewportSize({width:390,height:900});await settle();
  check((await snapshot()).empty,'All-missing data remains stable after resize');
  assert.deepEqual(errors,[]);checks++;
  console.log(JSON.stringify({checks,errors,template:html?'rebuilt HTML':'source template',artifacts}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
