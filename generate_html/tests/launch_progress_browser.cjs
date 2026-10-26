// Check the formal main.py output against the source progress, without calculating shares.
const path=require('path'),assert=require('assert'),{gunzipSync}=require('zlib'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const metric='累计直接大定占比';
function decode(block){
 const value=JSON.parse(gunzipSync(Buffer.from(block,'base64')).toString('utf8'));
 function restore(item){
  if(!item||typeof item!=='object')return item;
  if(Array.isArray(item))return item.map(restore);
  if(Object.hasOwn(item,'$shared'))return restore(value.pool[item.$shared]);
  return Object.fromEntries((Object.hasOwn(item,'$literal')?item.$literal:Object.entries(item)).map(([key,child])=>[key,restore(child)]));
 }
 return value.format==='shared-v1'?restore(value.root):value;
}
const known=value=>typeof value==='number'&&Number.isFinite(value);
const latest=values=>[...(values||[])].reverse().find(known)??null;
const display=value=>value===null?'—':value.toLocaleString('zh-CN',{maximumFractionDigits:1});

const quantity=value=>known(value)&&value>=0?value:null;
const divide=(direct,gross)=>quantity(direct)!==null&&quantity(gross)!==null&&gross>0?direct/gross:null;
function sourceRatios(part){
 const metrics=part.data.metrics,periods=part.data.periods;
 const daily=periods.map((_,i)=>divide(metrics['当日直接大定数量']?.[i],metrics['当日大定数量']?.[i]));
 const bases=periods.map((_,i)=>{
  const direct=quantity(metrics['累计直接大定数量']?.[i]);
  let gross=quantity(metrics['累计总大定数量']?.[i])??quantity(metrics['累计大定数量']?.[i]);
  if(gross===null){
   const small=quantity((metrics['累计小订转大定数量']||metrics['累计小订转大数量'])?.[i]);
   gross=small!==null&&direct!==null?small+direct:null;
  }
  return {direct,gross,share:divide(direct,gross)};
 });
 const cumulative=bases.map(row=>row.share),lastBasis=[...bases].reverse().find(row=>known(row.share))??[...bases].reverse().find(row=>row.direct===0&&row.gross===0)??null;
 return {daily,cumulative,lastBasis};
}

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 let pages=0,series=0,multiPhase=0;
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  page.on('pageerror',error=>errors.push(error.message));
  const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  const ready=()=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false');
  await page.goto(base.href);await ready();
  const blocks=await page.evaluate(()=>window.DASHBOARD_BLOCKS_B64);
  const boards=Object.entries(blocks).filter(([key])=>key.endsWith('|launch_rhythm'));
  assert(boards.length,'no launch dashboards in formal output');
  for(const [key,block] of boards){
   const board=decode(block),subject=key.split('|')[0];
   for(const [grain,view] of Object.entries(board.views)){
    const url=new URL(base);url.search=new URLSearchParams({subject,module:'launch_rhythm',grain});
    await page.goto(url.href);await ready();
    for(const period of view.periods){
     await page.locator('#periodSelect').selectOption(period);await ready();
     const data=view.pages[period],parts=data.sections.filter(section=>section.kind==='launch_composite');
     const source=parts.map(sourceRatios);
     parts.forEach((part,i)=>{
      assert.deepEqual(part.data.metrics[metric],source[i].cumulative,key+' cumulative share is not cumulative direct / cumulative gross');
      assert.deepEqual(part.data.metrics['每日直接大定占比'],source[i].daily,key+' period share is not period direct / period gross');
     });
     const sourceValues=source.map(item=>latest(item.cumulative)),bases=source.map(item=>item.lastBasis);
     const direct=bases.every(Boolean)?bases.reduce((sum,row)=>sum+row.direct,0):null,gross=bases.every(Boolean)?bases.reduce((sum,row)=>sum+row.gross,0):null;
     const combined=divide(direct,gross),expected=combined===null?null:combined*100;
     assert.equal(data.kpis[3].label,metric,key+' card metric changed');
     assert.equal(data.kpis[3].value,expected,key+' card is not the quantity-based cumulative share');
     const card=page.locator('.kpi').nth(3);
     assert.equal(await card.locator(':scope>span').textContent(),metric);
     assert.equal(await card.locator('strong').textContent(),display(expected));
     assert.equal(await card.locator('em').first().textContent(),'%');
     assert(!data.kpis.some(item=>item.label.includes('直接大定进度')));
     const charts=page.locator('.panel').filter({has:page.locator('[data-rhythm-kind="launch-day"]')});
     assert.equal(await charts.count(),parts.length);
     for(let i=0;i<parts.length;i++){
      const values=parts[i].data.metrics[metric]||[],chart=charts.nth(i);
      if(!values.length){assert.equal(await chart.locator('[data-launch-rate="bigRate"]').count(),0);continue;}
      assert.equal(await chart.locator('[data-launch-rate-summary],.launch-rate-summaries,.launch-rate-heading').count(),0);
      const legend=chart.locator('[data-launch-rate-legend="bigRate"]');
      assert.equal(await legend.textContent(),metric);
      assert.equal(await legend.getAttribute('title'),metric);
      const actual=await chart.locator('[data-launch-rate="bigRate"] [data-launch-rate-point]').evaluateAll(points=>points.map(point=>({index:Number(point.dataset.index),value:Number(point.dataset.value)})));
      assert.deepEqual(actual,values.map((value,index)=>({index,value})).filter(point=>known(point.value)),key+' chart differs from quantity-based cumulative share');
      assert.equal(await chart.locator('[data-launch-rate-label="bigRate"]').count(),actual.length);series++;
     }
     if(parts.length>1){
      multiPhase++;
      const table=data.sections.find(section=>section.title==='阶段概览').data,index=table.columns.indexOf(metric);
      assert(index>=0);assert.equal(table.formats[index],'percent');
      assert.deepEqual(table.rows.map(row=>row[index]),sourceValues);
      const cells=page.locator('[data-section-kind="table"]').first().locator('tbody tr');
      for(let i=0;i<sourceValues.length;i++)assert.equal(await cells.nth(i).locator('td').nth(index).textContent(),sourceValues[i]===null?'—':(sourceValues[i]*100).toFixed(1)+'%');
     }
     pages++;
    }
   }
  }
  assert(pages&&series&&multiPhase);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({boards:boards.length,pages,series,multiPhase,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
