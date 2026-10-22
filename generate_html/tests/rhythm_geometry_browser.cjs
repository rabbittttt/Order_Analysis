// Checks the formal main.py output; never creates or substitutes a test page.
const path=require('path'),fs=require('fs'),crypto=require('crypto'),assert=require('assert'),{gunzipSync}=require('zlib'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const out=process.env.RHYTHM_ARTIFACT_DIR||path.join(project,'.test_outputs/rhythm_geometry');
// Baseline comparison is opt-in: never compare new business data with a stale run.
const baselinePath=process.env.RHYTHM_BASELINE,baseline=baselinePath?JSON.parse(fs.readFileSync(baselinePath,'utf8')):null;
function readBoard(block){
 const value=JSON.parse(gunzipSync(Buffer.from(block,'base64')).toString('utf8'));
 const restore=item=>{
  if(!item||typeof item!=='object')return item;
  if(Array.isArray(item))return item.map(restore);
  if(Object.hasOwn(item,'$shared'))return restore(value.pool[item.$shared]);
  return Object.fromEntries((Object.hasOwn(item,'$literal')?item.$literal:Object.entries(item)).map(([key,child])=>[key,restore(child)]));
 };
 return value.format==='shared-v1'?restore(value.root):value;
}
(async()=>{
 fs.mkdirSync(out,{recursive:true});const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[],report=[];
 let boards=0,charts=0,snapshots=0,selections=0,rankings=0,toolbars=0;
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000},reducedMotion:'reduce'});page.on('pageerror',error=>errors.push(error.message));
  const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  const ready=()=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false'&&[...document.querySelectorAll('[data-rhythm-config]')].every(n=>n._rhythmWidth===Math.floor(n.clientWidth)));
  await page.goto(base.href);await ready();
  const blocks=await page.evaluate(()=>window.DASHBOARD_BLOCKS_B64),keys=Object.keys(blocks).filter(key=>/\|(cancellation|launch_rhythm)$/.test(key));
  const boardData=Object.fromEntries(keys.map(key=>[key,readBoard(blocks[key])]));
  assert(keys.length,'no rhythm dashboards in formal output');
  if(baseline)assert.deepEqual([...keys].sort(),Object.keys(baseline.boards).sort(),'rhythm dashboard availability changed');
  const rankingKey=keys.find(key=>key.endsWith('|cancellation')&&Object.values(boardData[key].views.day.pages).some(item=>item.sections.some(section=>section.kind==='bars'&&section.title==='选配退订率排行')));
  const representative=process.env.RHYTHM_SCREENSHOT_SUBJECT||(rankingKey||keys[0]).split('|')[0];
  assert(keys.some(key=>key.startsWith(representative+'|')),'screenshot subject has no rhythm dashboards');
  for(const key of keys){if(baseline?.boards[key])assert.equal(crypto.createHash('sha256').update(blocks[key]).digest('hex'),baseline.boards[key],key+' business payload changed');boards++;}
  for(const width of [1920,1440,768,390]){
   await page.setViewportSize({width,height:1000});
   for(const key of keys){
    const [subject,module]=key.split('|'),url=new URL(base);url.search=new URLSearchParams({subject,module,grain:'day'});
    await page.goto(url.href);await ready();
    const actual=await page.evaluate(()=>{
     const frames=[...document.querySelectorAll('[data-rhythm-config]')],daily=[],hourly=[];
     const measurements=frames.map(frame=>{
      const svg=frame.querySelector('svg'),box=frame.getBoundingClientRect(),kind=frame.dataset.rhythmKind;
      const panel=frame.closest('.panel'),panelBox=panel.getBoundingClientRect(),gridBox=panel.parentElement.getBoundingClientRect(),bodyBox=panel.querySelector('.panel-body').getBoundingClientRect();
      const texts=[...svg.querySelectorAll('text')].map(n=>({text:n.textContent,box:n.getBoundingClientRect()}));let overlaps=0;
      for(let i=0;i<texts.length;i++)for(let j=i+1;j<texts.length;j++){const a=texts[i].box,b=texts[j].box;if(Math.min(a.right,b.right)-Math.max(a.left,b.left)>2&&Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>2)overlaps++;}
      const rows=[...svg.querySelectorAll('[data-rhythm-row]')];
      if(kind.endsWith('-day'))daily.push(rows.map(n=>n.querySelector(':scope>title')?.textContent));
      else hourly.push(...[...svg.querySelectorAll('[data-rhythm-bar]>title')].map(n=>n.textContent));
      const totalLabels=[...svg.querySelectorAll('[data-rhythm-label="total"]')].map(n=>({index:Number(n.dataset.index),text:n.textContent})),spec=JSON.parse(frame.dataset.rhythmConfig);
      const columnPositions=rows.map((row,index)=>{const bar=row.querySelector('[data-rhythm-bar]');return bar?{index,x:bar.getBoundingClientRect().x,width:bar.getBoundingClientRect().width}:null}).filter(Boolean);
      const columnGaps=columnPositions.slice(1).map((bar,index)=>(bar.x-columnPositions[index].x)/(bar.index-columnPositions[index].index)-bar.width);
      const labelWeights=[...svg.querySelectorAll('.rhythm-value-label')].map(n=>Number(getComputedStyle(n).fontWeight));
      const barColors=[...new Set([...svg.querySelectorAll('[data-rhythm-bar]')].map(n=>getComputedStyle(n).fill))];
      const lineColors=[...svg.querySelectorAll('[data-rhythm-series]')].map((line,index)=>({key:line.dataset.rhythmSeries,color:getComputedStyle(line).stroke,points:[...svg.querySelectorAll(`[data-rhythm-point="${line.dataset.rhythmSeries}"]`)].map(n=>getComputedStyle(n).stroke),labels:[...svg.querySelectorAll(`[data-series="${line.dataset.rhythmSeries}"]`)].map(n=>getComputedStyle(n).fill),legend:getComputedStyle(frame.nextElementSibling.querySelectorAll('.line-key')[index]).backgroundColor}));
      return {kind,height:box.height,left:box.left,right:box.right,panelLeft:panelBox.left,panelRight:panelBox.right,gridLeft:gridBox.left,gridRight:gridBox.right,bodyLeft:bodyBox.left,bodyRight:bodyBox.right,viewportWidth:frame.clientWidth,scrollWidth:frame.scrollWidth,overflowX:getComputedStyle(frame).overflowX,svgHeight:svg.getBoundingClientRect().height,scale:svg.getScreenCTM().a,barWidths:[...new Set([...svg.querySelectorAll('[data-rhythm-bar]')].map(n=>n.getBoundingClientRect().width))],plotHeight:Number(svg.dataset.plotHeight),plotLeft:Number(svg.dataset.plotLeft),plotRight:Number(svg.dataset.plotRight),rows:rows.length,overlaps,expectedGap:Math.max(40,...spec.rows.map(row=>typeof row.total==='number'?row.total.toLocaleString('zh-CN',{maximumFractionDigits:1}).length*9*.62+8:17))-28,columnGaps,labelWeights,totalLabels,expectedTotals:spec.rows.map(row=>typeof row.total==='number'?row.total.toLocaleString('zh-CN',{maximumFractionDigits:1}):'—'),decorations:svg.querySelectorAll('.rhythm-grid-line,.rhythm-label-background').length,labelOffsets:[...svg.querySelectorAll('[data-rhythm-label="line"]')].map(n=>Math.abs(Number(n.getAttribute('y'))-Number(n.dataset.pointY))),labelStrokes:[...new Set([...svg.querySelectorAll('.rhythm-line-label')].map(n=>parseFloat(getComputedStyle(n).strokeWidth)))],barColors,lineColors};
     });
     const toolbarChecks=[...document.querySelectorAll('.hourly-toolbar')].map(toolbar=>{
      const select=toolbar.querySelector('select'),box=select.getBoundingClientRect(),wrap=toolbar.parentElement.getBoundingClientRect(),head=toolbar.closest('.panel').querySelector('.panel-head').getBoundingClientRect();
      return {right:box.right,wrapRight:wrap.right,left:box.left,wrapLeft:wrap.left,top:box.top,headBottom:head.bottom,flexWrap:getComputedStyle(toolbar).flexWrap,label:select.getAttribute('aria-label')};
     });
     const ranking=document.querySelector('.cancel-ranking'),rankingCheck=ranking?{kind:ranking.closest('.panel').dataset.sectionKind,sourceIndex:Number(ranking.querySelector('[data-panel-source]')?.dataset.panelSource),rows:[...ranking.querySelectorAll('.bar-row')].map(row=>({label:row.querySelector('label').textContent,value:row.querySelector('b').textContent})),columns:getComputedStyle(ranking.querySelector('.bars')).gridTemplateColumns.split(' ').length,clipped:[...ranking.querySelectorAll('.bar-row label')].some(node=>node.scrollHeight>node.clientHeight+1),standalone:[...document.querySelectorAll('.panel-head h2')].some(n=>n.textContent==='选配退订率排行')}:null;
     return {daily,hourly,measurements,toolbarChecks,rankingCheck,period:document.querySelector('#periodSelect').value,pageOverflow:document.documentElement.scrollWidth>innerWidth+2};
    });
    assert(!actual.pageOverflow,key+' page overflow at '+width);
    assert(actual.measurements.length,key+' missing charts');
    for(const m of actual.measurements){
     assert(Math.abs(m.height-240)<.05,key+' inconsistent frame height');assert(Math.abs(m.svgHeight-224)<.05);
     assert(Math.abs(m.panelLeft-m.gridLeft)<1&&Math.abs(m.panelRight-m.gridRight)<1,key+' outer rhythm card does not fill the content width');
     assert(Math.abs((m.left+m.right)-(m.bodyLeft+m.bodyRight))<1,key+' rhythm chart is not centered within its card');
     assert(m.left>=m.bodyLeft-1&&m.right<=m.bodyRight+1,key+' rhythm viewport escapes its card');
     assert.equal(m.overflowX,'auto',key+' horizontal scrolling is not available');
     assert(Math.abs(m.scale-1)<.001,key+' SVG scaling changes actual bar width');
     assert(m.barWidths.every(w=>Math.abs(w-28)<.05),key+' unequal actual bar widths: '+m.barWidths);
     assert.equal(m.plotHeight,160);assert.equal(m.plotLeft,30);assert.equal(m.plotRight,30);
     assert.equal(m.decorations,0,key+' background stripes');
     assert(m.columnGaps.every(gap=>Math.abs(gap-m.expectedGap)<.05),key+' gaps stretched with viewport: '+m.columnGaps);
     assert(m.labelWeights.every(weight=>weight===400),key+' data labels still bold');
     assert.deepEqual(m.totalLabels.map(n=>n.index),m.expectedTotals.map((_,i)=>i),key+' dropped total labels');
     assert.deepEqual(m.totalLabels.map(n=>n.text),m.expectedTotals,key+' total labels no longer match values');
     assert.equal(m.overlaps,0,key+' text overlaps at '+width+' '+m.kind);
     assert(m.labelOffsets.every(offset=>offset<=24.01),key+' labels drift away from their points');
     assert(m.labelStrokes.every(stroke=>stroke<=1.5),key+' heavy label halo');
     for(const line of m.lineColors){
      assert(!m.barColors.includes(line.color),key+' line shares a column color: '+line.key);
      assert(line.points.every(color=>color===line.color)&&line.labels.every(color=>color===line.color)&&line.legend===line.color,key+' line, points, labels and legend disagree: '+line.key);
     }
     assert.equal(new Set(m.lineColors.map(line=>line.color)).size,m.lineColors.length,key+' line colors collide');
     if(m.kind.endsWith('-hour'))assert.equal(m.rows,24,key+' lost clock hours');charts++;
    }
    for(const toolbar of actual.toolbarChecks){
     assert(Math.abs(toolbar.right-toolbar.wrapRight)<1,key+' hourly selector is not right aligned');
     assert(toolbar.left>=toolbar.wrapLeft-1&&toolbar.top>=toolbar.headBottom-1,key+' hourly selector escapes card or overlaps source');
     assert.equal(toolbar.flexWrap,'wrap');assert.equal(toolbar.label,'分时口径');toolbars++;
    }
    const sections=boardData[key].views.day.pages[actual.period].sections,rankingIndex=sections.findIndex(item=>item.kind==='bars'&&item.title==='选配退订率排行');
    if(rankingIndex>=0&&sections.some(item=>item.kind==='daily_cancel')){
     const ranking=actual.rankingCheck;assert(ranking,key+' missing integrated option ranking');
     assert.equal(ranking.kind,'daily_cancel');assert.equal(ranking.sourceIndex,rankingIndex);assert(!ranking.standalone&&!ranking.clipped,key+' ranking is standalone or truncates labels');
     const fmt=value=>typeof value==='number'?value.toLocaleString('zh-CN',{maximumFractionDigits:1}):String(value),expected=sections[rankingIndex].data.rows.map(row=>{const value=Number(row.share??row.value??0),percent=Math.abs(value)<=1.5?value*100:value;return {label:String(row.label).replaceAll('净大定','留存大定'),value:percent.toFixed(1)+'%'+(row.count!=null?' ('+fmt(row.count)+')':'')};});
     assert.deepEqual(ranking.rows,expected,key+' option ranking values/order changed');
     if(width>=1440)assert(ranking.columns>=2,key+' option ranking is not compact');
     if(width===390)assert.equal(ranking.columns,1,key+' narrow ranking columns overflow');rankings++;
    }
    if(baseline?.snapshots[key]){assert.deepEqual({daily:actual.daily,hourly:actual.hourly},baseline.snapshots[key],key+' historical quantities/tooltips changed');snapshots++;}
    if(width===390){
     const scrolling=await page.locator('[data-rhythm-config]').evaluateAll(frames=>frames.map(frame=>{
      const before=frame.innerHTML,overflow=frame.scrollWidth>frame.clientWidth+2;
      frame.scrollLeft=frame.scrollWidth;
      const moved=frame.scrollLeft>0,unchanged=frame.innerHTML===before;frame.scrollLeft=0;
      return {overflow,moved,unchanged};
     }));
     assert(scrolling.every(item=>item.unchanged&&(!item.overflow||item.moved)),key+' narrow-screen scroll lost content or cannot move');
    }
    if(width===1440){
     const selects=page.locator('[data-hourly-select],[data-launch-hourly-select]');
     for(let i=0;i<await selects.count();i++){
      const control=selects.nth(i),options=await control.locator('option').evaluateAll(nodes=>nodes.map(n=>n.value));
      if(options.length<2)continue;await control.selectOption(options[1]);await ready();
      const check=await control.evaluate(select=>{
       const launch=select.hasAttribute('data-launch-hourly-select'),source=JSON.parse(select.dataset[launch?'launchHourlyRows':'hourlyRows']);
       const totals=Array(24).fill(0);source.filter(row=>String(row.period||'')===select.value).forEach(row=>{if(Number.isInteger(Number(row.hour))&&Number(row.hour)>=0&&Number(row.hour)<24)totals[Number(row.hour)]+=Number((launch?row.orders:row.count)||0)});
       return {expected:totals,actual:[...select.closest('.hourly-wrap').querySelectorAll('[data-rhythm-row]')].map(n=>Number(n.dataset.total))};
      });assert.deepEqual(check.actual,check.expected,key+' hourly date selection changed values');selections++;
      await control.selectOption(options[0]);await ready();
     }
    }
    if(subject===representative){
     const panels=page.locator('.panel').filter({has:page.locator('[data-rhythm-config]')});
     for(let i=0;i<await panels.count();i++)await panels.nth(i).screenshot({path:path.join(out,`after-${module}-${width}-${i+1}.png`)});
    }
    report.push({width,key,measurements:actual.measurements,toolbars:actual.toolbarChecks,ranking:actual.rankingCheck});
   }
  }
  // Exercise ResizeObserver on an already mounted chart, without a navigation.
  for(const width of [1440,390,768]){await page.setViewportSize({width,height:1000});await ready();assert(await page.locator('[data-rhythm-bar]').evaluateAll(nodes=>nodes.every(n=>Math.abs(n.getBoundingClientRect().width-28)<.05)));}
  let weekChecks=0,sourceClicks=0;
  const weeklyKey=keys.find(key=>key.endsWith('|launch_rhythm')&&boardData[key].views.week);
  if(weeklyKey){
   const url=new URL(base);url.search=new URLSearchParams({subject:weeklyKey.split('|')[0],module:'launch_rhythm',grain:'week'});
   await page.setViewportSize({width:1440,height:1000});await page.goto(url.href);await ready();
   const colors=await page.locator('[data-rhythm-config]').evaluateAll(frames=>frames.map(frame=>({bars:[...frame.querySelectorAll('[data-rhythm-bar]')].map(n=>getComputedStyle(n).fill),lines:[...frame.querySelectorAll('[data-rhythm-series]')].map(n=>getComputedStyle(n).stroke)})));
   assert(colors.some(item=>item.lines.length),'weekly launch chart has no rate lines');
   assert(colors.every(item=>item.lines.every(color=>!item.bars.includes(color))),weeklyKey+' weekly line shares a column color');weekChecks++;
   await page.locator('.panel').filter({has:page.locator('[data-rhythm-series]')}).first().screenshot({path:path.join(out,'after-launch-week-1440.png')});
  }
  if(rankingKey){
   const url=new URL(base);url.search=new URLSearchParams({subject:rankingKey.split('|')[0],module:'cancellation',grain:'day'});
   await page.goto(url.href);await ready();
   const period=await page.locator('#periodSelect').inputValue(),source=boardData[rankingKey].views.day.pages[period].sections.find(item=>item.kind==='bars'&&item.title==='选配退订率排行').source;
   await page.locator('.cancel-ranking [data-panel-source]').click();await page.locator('#rawSheet').waitFor();
   const selected=await page.evaluate(()=>{const file=window.DASHBOARD_DATA.raw_files[Number(document.querySelector('#rawFile').value)];return {file:file.name,sheet:file.sheets[Number(document.querySelector('#rawSheet').value)]};});
   assert.equal(selected.file,source.file);assert(selected.sheet.name===source.sheet||selected.sheet.source_sheet===source.sheet,'ranking source opened the wrong sheet');sourceClicks++;
  }
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'geometry-report.json'),JSON.stringify({boards,checks:report.length,charts,snapshots,selections,rankings,toolbars,weekChecks,sourceClicks,representative,errors,report},null,2));
  console.log(JSON.stringify({boards,checks:report.length,charts,snapshots,selections,rankings,toolbars,weekChecks,sourceClicks,representative,resizes:3,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
