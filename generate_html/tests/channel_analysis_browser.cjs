// Compare the formal dashboard with the formal source Excel, without changing business data.
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {pathToFileURL}=require('node:url'),{execFileSync}=require('node:child_process');
const project=path.resolve(__dirname,'../../..'),root=path.resolve(__dirname,'..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));

// Independent acceptance fixture: user-provided denominators, never backend-derived.
const configuredStores={
 '问界':{'问界用户中心':374,'鸿蒙智行用户中心':28,'华为旗舰店':11,'华为授权体验店':131,'华为智能生活馆':425},
 '智界':{'智界用户中心':48,'鸿蒙智行用户中心':334,'华为旗舰店':11,'华为授权体验店':129,'华为智能生活馆':388},
 '尊界':{'鸿蒙智行用户中心':157,'华为旗舰店':7,'华为授权体验店':3,'华为智能生活馆':35,'尊界用户中心':9,'智界用户中心':1,'问界用户中心':2},
 '尚界':{'尚界用户中心':221,'鸿蒙智行用户中心':259,'华为旗舰店':13,'华为授权体验店':153,'华为智能生活馆':450},
 '享界':{'享界用户中心':14,'鸿蒙智行用户中心':344,'华为旗舰店':11,'华为授权体验店':100,'华为智能生活馆':387},
};
const expected=JSON.parse(execFileSync(process.env.PYTHON_EXE||'python',['-B','-c',String.raw`
import json,math,re,sys
from datetime import date,datetime
from pathlib import Path
from openpyxl import load_workbook

configured=json.loads(sys.argv[1])
w=load_workbook(Path('..','..','output_file','鸿蒙智行大定选配比例分析.xlsx'),read_only=True,data_only=True)
brands=['问界','智界','享界','尊界','尚界']
group_config={}
for brand in brands:
 for channel,total in configured[brand].items():
  group_config[channel]=group_config.get(channel,0)+total
names=['鸿蒙智行',*brands]
for brand in brands:
 names.append(next(n[:-3] for n in w.sheetnames if n.startswith(brand) and '款' in n and n.endswith('by天')))

def period(value):
 if isinstance(value,(date,datetime)):
  return value.strftime('%Y-%m-%d')
 text=str(value or '').strip()
 match=re.fullmatch(r'(\d{2}|\d{4})WK(\d{1,2})',text,re.I)
 if match:
  return f'{int(match[1])%100:02d}WK{int(match[2]):02d}'
 return text

def number(cell,rate=False):
 value=cell.value
 if value is None or isinstance(value,bool):return None
 percent=isinstance(value,str) and value.strip().endswith(('%','％'))
 try:
  value=float(str(value).replace(',','').replace('，','').rstrip('%％').strip())
 except (ValueError,TypeError):return None
 if not math.isfinite(value) or value<0:return None
 if rate and (percent or ('%' not in cell.number_format and '％' not in cell.number_format and value>1.5)):value/=100
 return value if not rate or value<=1 else None

def complete_sum(values):
 return sum(values) if values and all(value is not None for value in values) else None

result=[]
for name in names:
 brand=next((brand for brand in brands if name.startswith(brand)),None)
 config=group_config if name=='鸿蒙智行' else configured.get(brand,{})
 for grain,suffix in [('day','天'),('week','周'),('month','月')]:
  sheet=w[name+'by'+suffix]
  cells=list(sheet.iter_rows())
  indexes={period(c.value):i for i,c in enumerate(cells[0]) if i>=3 and period(c.value) and not re.search(r'总计|合计|汇总|累计|近\s*\d+\s*(?:天|日|周|月)',period(c.value))}
  periods=sorted(indexes)
  channels=[];values={p:{} for p in periods};priorities={};metric=stat=''
  for row in cells[1:]:
   metric=str(row[0].value or metric).strip();stat=str(row[1].value or stat).strip();channel=str(row[2].value or '').strip()
   field={('门店类型','数量'):'count',('门店类型','占比'):'share',('门店类型','贡献门店数'):'active_count',('贡献订单门店数','数量'):'active_count'}.get((metric,stat))
   if not field or not channel or channel in ('数量','总计','合计','汇总'):continue
   if channel not in channels:channels.append(channel)
   priority=2 if stat=='贡献门店数' else 1
   for p,index in indexes.items():
    key=(p,channel,field)
    if priority<priorities.get(key,0):continue
    priorities[key]=priority
    values[p].setdefault(channel,{})[field]=number(row[index],rate=field=='share')
  history=[]
  for p in periods:
   rows={}
   for channel in channels:
    raw=values[p].get(channel,{})
    count,share,active=(raw.get(key) for key in ('count','share','active_count'))
    total=config.get(channel)
    rows[channel]={'count':count,'share':share,'active_count':active,'store_count':total,
      'active_rate':active/total if total and active is not None and active<=total else None,
      'productivity':count/total if total and count is not None else None}
   count=complete_sum([r['count'] for r in rows.values()])
   active=complete_sum([r['active_count'] for r in rows.values()])
   # Group denominators sum the five brands, including shared stores in each brand.
   coverage_known=bool(config) and all(r['store_count'] is not None or (r['count']==0 and r['active_count']==0) for r in rows.values())
   total=sum(config.values()) if coverage_known else None
   valid_active=all(r['active_count'] is None or r['store_count'] is None or r['active_count']<=r['store_count'] for r in rows.values())
   totals={'count':count,'active_count':active,'active_rate':active/total if total and active is not None and valid_active else None,'productivity':count/total if total and count is not None else None}
   history.append({'period':p,'rows':rows,'totals':totals})
  result.append({'subject':name,'brand':brand,'grain':grain,'period':periods[-1],'periods':periods,'channels':channels,'history':history})
print(json.dumps(result,ensure_ascii=False,allow_nan=False))
w.close()
`,JSON.stringify(configuredStores)],{cwd:root,encoding:'utf8',maxBuffer:32*1024*1024,env:{...process.env,PYTHONIOENCODING:'utf-8',PYTHONUTF8:'1'}}));

const known=value=>typeof value==='number'&&Number.isFinite(value);
const formatted=(value,kind='number')=>!known(value)?'—':kind==='percent'?(value*100).toFixed(1)+'%':value.toLocaleString('zh-CN',{minimumFractionDigits:kind==='capacity'?2:0,maximumFractionDigits:kind==='capacity'?2:1});
const keyFor=(channel,period)=>JSON.stringify([channel,period]);

(async()=>{
 const browser=await chromium.launch({headless:true,channel:process.env.BROWSER_CHANNEL||'msedge'}),errors=[];
 let checks=0,tableCells=0,chartPoints=0;
 const check=(name,value)=>{assert(value,name);checks++};
 const equal=(name,actual,wanted)=>{assert.deepEqual(actual,wanted,name);checks++};
 const near=(name,actual,wanted)=>{
  if(!known(wanted))equal(name,actual,'');
  else check(name,actual!==''&&Number.isFinite(Number(actual))&&Math.abs(Number(actual)-wanted)<=1e-10*Math.max(1,Math.abs(wanted)));
 };
 const artifacts=process.env.AUDIT_ARTIFACT_DIR||path.join(project,'.test_runtime','channel_history_audit');
 fs.mkdirSync(artifacts,{recursive:true});
 const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage();
 page.on('pageerror',error=>errors.push(error.message));
 const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 const urlFor=sample=>{const url=new URL(base);url.search=new URLSearchParams({subject:sample.subject,module:'channel_analysis',grain:sample.grain,period:sample.period});return url.href;};
 const waitForTail=async label=>{
  await page.waitForFunction(()=>{
   const nodes=[...document.querySelectorAll('[data-channel-scroll]')];
   return nodes.length>0&&nodes.every(node=>{const end=Math.max(0,node.scrollWidth-node.clientWidth);return end<=2||Math.abs(node.scrollLeft-end)<=2});
  },null,{timeout:10000});
  check(label+' horizontal histories remain at latest period',true);
 };
 const settleResize=async()=>{
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 };
 const snapshot=()=>page.locator('.channel-panel').evaluateAll(panels=>Object.fromEntries(panels.map(panel=>[panel.dataset.channelMetric,{
  controls:panel.querySelectorAll('select,details').length,
  tables:Object.fromEntries([...panel.querySelectorAll('[data-channel-table]')].map(table=>[table.dataset.channelTable,{
   periods:[...table.querySelectorAll('thead th[data-period]')].map(cell=>cell.dataset.period),
   rows:[...table.querySelectorAll('tr[data-channel]')].map(row=>({channel:row.dataset.channel,heading:row.querySelector('th')?.textContent.trim(),cells:[...row.querySelectorAll('td[data-period]')].map(cell=>({period:cell.dataset.period,value:cell.dataset.value,text:cell.textContent.trim()}))}))
  }])),
  charts:[...panel.querySelectorAll('[data-channel-chart]')].map(chart=>({
   emptyText:chart.textContent.trim(),
   points:[...chart.querySelectorAll('[data-channel][data-period][data-value]')].map(point=>({channel:point.dataset.channel,period:point.dataset.period,value:point.dataset.value,tag:point.tagName.toLowerCase()})),
   stacks:chart.querySelectorAll('rect[data-channel]').length,
   totalLines:[...chart.querySelectorAll('.channel-total-line')].map(line=>line.getAttribute('d')),
   overlays:[...chart.querySelectorAll('[data-channel-point]')].map(point=>({period:point.dataset.period,description:point.getAttribute('aria-label')}))
  }))
 }])));

 function verify(sample,actual){
  const label=sample.subject+'/'+sample.grain;
  equal(label+' three panels',Object.keys(actual),['sales','stores','capacity']);
  for(const [panelName,keys] of [['sales',['count','share']],['stores',['active_count','active_rate']],['capacity',['productivity']]]){
   const panel=actual[panelName];
   equal(label+'/'+panelName+' no channel selector or details',panel.controls,0);
   equal(label+'/'+panelName+' table set',Object.keys(panel.tables),keys);
   for(const key of keys){
    const table=panel.tables[key],total=key!=='share',kind=['share','active_rate'].includes(key)?'percent':key==='productivity'?'capacity':'number';
    equal(label+'/'+key+' all history columns',table.periods,sample.periods);
    equal(label+'/'+key+' channel rows',table.rows.map(row=>row.channel),[...sample.channels,...(total?['__total__']:[])]);
    for(const row of table.rows){
     equal(label+'/'+key+'/'+row.channel+' history length',row.cells.length,sample.history.length);
     if(key==='active_rate'&&row.channel!=='__total__'){
      const denominator=sample.history.at(-1).rows[row.channel].store_count;
      check(label+'/'+row.channel+' configured denominator',row.heading.includes('配置 '+formatted(denominator)+' 家'));
     }
     for(let i=0;i<sample.history.length;i++){
      const entry=sample.history[i],cell=row.cells[i],wanted=row.channel==='__total__'?entry.totals[key]:entry.rows[row.channel][key],prefix=label+'/'+key+'/'+row.channel+'/'+entry.period;
      equal(prefix+' period',cell.period,entry.period);
      equal(prefix+' rendered value',cell.text,formatted(wanted,kind));
      near(prefix+' exact value',cell.value,wanted);tableCells++;
     }
    }
   }
   equal(label+'/'+panelName+' one chart',panel.charts.length,1);
   const chart=panel.charts[0],wantedPoints=new Map();
   for(const entry of sample.history){
    if(panelName==='sales'){
     if(sample.channels.every(channel=>known(entry.rows[channel].share)))for(const channel of sample.channels)wantedPoints.set(keyFor(channel,entry.period),{value:entry.rows[channel].share,tag:'rect'});
     if(known(entry.totals.count))wantedPoints.set(keyFor('__total__',entry.period),{value:entry.totals.count,tag:'circle'});
    }else{
     const field=panelName==='stores'?'active_rate':'productivity';
     for(const channel of sample.channels)if(known(entry.rows[channel][field]))wantedPoints.set(keyFor(channel,entry.period),{value:entry.rows[channel][field],tag:'circle'});
    }
   }
   equal(label+'/'+panelName+' chart value count',chart.points.length,wantedPoints.size);
   const seen=new Set();
   for(const point of chart.points){
    const key=keyFor(point.channel,point.period),wanted=wantedPoints.get(key),prefix=label+'/'+panelName+'/'+key;
    check(prefix+' unique chart datum',!seen.has(key));seen.add(key);
    check(prefix+' expected chart datum',Boolean(wanted));
    near(prefix+' chart value',point.value,wanted.value);
    equal(prefix+' chart shape',point.tag,wanted.tag);chartPoints++;
   }
   if(panelName==='sales'){
    equal(label+' total order line exists',chart.totalLines.length,1);
    if(sample.history.some(entry=>known(entry.totals.count)))check(label+' total order line has path',Boolean(chart.totalLines[0]));
   }else equal(label+'/'+panelName+' ratios and capacity are not stacked',chart.stacks,0);
   const emptyChart=panelName!=='sales'&&wantedPoints.size===0;
   if(emptyChart){
    equal(label+'/'+panelName+' empty chart has no period overlays',chart.overlays,[]);
    const unconfigured=!Object.values(sample.history.at(-1).rows).some(row=>known(row.store_count));
    check(label+'/'+panelName+' explicit missing data state',chart.emptyText.includes(unconfigured?'未配置该主体的门店总数':'暂无可用的'));
   }else equal(label+'/'+panelName+' chart periods',chart.overlays.map(point=>point.period),sample.periods);
   if(panelName==='stores'&&!emptyChart)for(let i=0;i<chart.overlays.length;i++)for(const channel of sample.channels){
    const row=sample.history[i].rows[channel];
    check(label+'/'+channel+'/'+sample.periods[i]+' source active count in chart description',chart.overlays[i].description.includes(channel+' 出单率 '+formatted(row.active_rate,'percent')+'，'+formatted(row.active_count)+' / '+formatted(row.store_count)+' 家'));
   }
  }
 }

 try{
  equal('eleven subjects',new Set(expected.map(sample=>sample.subject)).size,11);
  equal('thirty-three subject/grain views',expected.length,33);
  for(const sample of expected){
   await page.goto(urlFor(sample));await page.waitForSelector('[data-channel-table="productivity"]');
   await waitForTail(sample.subject+'/'+sample.grain+' first navigation');
   const nav=await page.locator('#moduleNav button').evaluateAll(nodes=>nodes.map(node=>node.dataset.module));
   equal(sample.subject+' navigation follows overview',nav.indexOf('channel_analysis'),nav.indexOf('overview')+1);
   equal(sample.subject+'/'+sample.grain+' selected period',await page.locator('#periodSelect').inputValue(),sample.period);
   verify(sample,await snapshot());
  }

  const sample=expected.find(item=>item.subject==='问界'&&item.grain==='week');
  await page.goto(urlFor(sample));await page.waitForSelector('[data-channel-table="productivity"]');
  const earlierIndex=Math.min(1,sample.periods.length-2),earlier=sample.periods[Math.max(0,earlierIndex)];
  await page.locator('#periodSelect').selectOption(earlier);
  await page.waitForFunction(period=>document.querySelector('.channel-panel-intro')?.textContent.includes('截至 '+period),earlier);
  verify({...sample,period:earlier,periods:sample.periods.slice(0,earlierIndex+1),history:sample.history.slice(0,earlierIndex+1)},await snapshot());
  equal('period selection updates URL',new URL(page.url()).searchParams.get('period'),earlier);
  await page.locator('#grainSelect [data-grain="day"]').click();
  await page.waitForFunction(()=>new URL(location.href).searchParams.get('grain')==='day');
  await page.reload();await page.waitForSelector('[data-channel-table="productivity"]');
  check('grain persists after reload',(await page.locator('#grainSelect [data-grain="day"]').getAttribute('class')).includes('active'));

  // Use the full daily history for keyboard and narrow-screen checks.
  const daily=expected.find(item=>item.subject==='问界'&&item.grain==='day');
  await page.goto(urlFor(daily));await page.waitForSelector('[data-channel-table="productivity"]');
  const sales=page.locator('[data-channel-metric="sales"]'),points=sales.locator('[data-channel-point]');
  await points.last().focus();await page.keyboard.press('Home');
  equal('keyboard Home focuses earliest period',await page.evaluate(()=>document.activeElement?.dataset.period),daily.periods[0]);
  check('focused period exposes tooltip',(await sales.locator('[data-channel-tooltip]').innerText()).includes(daily.periods[0]));
  await page.keyboard.press('End');
  equal('keyboard End focuses latest period',await page.evaluate(()=>document.activeElement?.dataset.period),daily.period);
  await page.keyboard.press('Escape');
  check('Escape hides tooltip',await sales.locator('[data-channel-tooltip]').isHidden());

  // A deliberate history scroll must survive resize; only a reader already
  // following the latest period should continue following the trailing edge.
  await waitForTail('daily page before manual scroll');
  const manualScroller=page.locator('[data-channel-table="count"]').locator('..');
  const manualState=await manualScroller.evaluate(node=>new Promise(resolve=>{
   const end=node.scrollWidth-node.clientWidth;
   if(end<=10){resolve({end,left:node.scrollLeft,event:false});return}
   node.addEventListener('scroll',()=>requestAnimationFrame(()=>resolve({end,left:node.scrollLeft,event:true})),{once:true});
   node.scrollLeft=0;
  }));
  check('manual history scroll emits an actual scroll event',manualState.event&&manualState.end>10&&manualState.left<=2);
  await page.setViewportSize({width:1920,height:1050});
  await page.waitForFunction(()=>innerWidth===1920);
  await settleResize();
  await page.waitForFunction(()=>{
   const node=document.querySelector('[data-channel-table="count"]')?.parentElement;
   return node&&node.scrollWidth-node.clientWidth>10&&node.scrollLeft<node.scrollWidth-node.clientWidth-2;
  },null,{timeout:10000});
  check('resize preserves manual history position instead of forcing latest',await manualScroller.evaluate(node=>node.scrollLeft<node.scrollWidth-node.clientWidth-2));

  // Navigation deliberately resets the reading position before screenshots.
  await page.setViewportSize({width:1440,height:1050});
  await page.goto(urlFor(daily));await page.waitForSelector('[data-channel-table="productivity"]');
  await waitForTail('fresh navigation restores latest after manual scroll');
  for(const width of [1920,1440,768,390]){
   await page.setViewportSize({width,height:1050});
   await page.waitForFunction(width=>innerWidth===width,width);
   await settleResize();
   await waitForTail('resize to '+width);
   check('no document overflow '+width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   check('panel boundaries fit viewport '+width,await page.locator('.channel-panel').evaluateAll(nodes=>nodes.every(node=>{const r=node.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1})));
   check('history containers fit viewport '+width,await page.locator('.channel-history-tables,[data-channel-chart]').evaluateAll(nodes=>nodes.every(node=>node.getBoundingClientRect().right<=innerWidth+1)));
   check('tables retain internal horizontal scrolling '+width,await page.locator('[data-channel-table]').evaluateAll(nodes=>nodes.every(table=>{const box=table.parentElement;return box.scrollWidth>=box.clientWidth&&['auto','scroll'].includes(getComputedStyle(box).overflowX)})));
   await page.locator('#page').screenshot({path:path.join(artifacts,'channel-'+width+'.png')});
   if(width===1440||width===390)for(const metric of ['sales','stores','capacity'])await page.locator('[data-channel-metric="'+metric+'"]').screenshot({path:path.join(artifacts,'channel-'+metric+'-'+width+'.png')});
  }

  await page.setViewportSize({width:1440,height:1050});
  await page.locator('[data-panel-source="0"]').click();await page.waitForSelector('#rawTable');
  equal('source opens raw module',new URL(page.url()).searchParams.get('module'),'raw');
  const rawSearch=page.locator('#rawSearch');
  equal('raw source search exists',await rawSearch.count(),1);
  await rawSearch.fill('华为授权体验店');
  equal('raw search accepts channel',await rawSearch.inputValue(),'华为授权体验店');
  await page.waitForFunction(()=>document.querySelector('#rawTable')?.textContent.includes('华为授权体验店'));
  await page.goBack();await page.waitForSelector('[data-channel-table="productivity"]');
  equal('source back restores channel page',new URL(page.url()).searchParams.get('module'),'channel_analysis');
  equal('no browser runtime errors',errors,[]);
  console.log(JSON.stringify({checks,tableCells,chartPoints,subjects:new Set(expected.map(s=>s.subject)).size,views:expected.length,errors,artifacts}));
 }catch(error){
  await page.screenshot({path:path.join(artifacts,'failure.png'),fullPage:true}).catch(()=>{});
  throw error;
 }finally{await context.close();await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
