// Verify the formal output against the source workbook, without writing business data.
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {pathToFileURL}=require('node:url'),{execFileSync}=require('node:child_process');
const project=path.resolve(__dirname,'../../..'),root=path.resolve(__dirname,'..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
const expected=JSON.parse(execFileSync(process.env.PYTHON_EXE||'python',['-c',String.raw`
import json,re
from pathlib import Path
from openpyxl import load_workbook
from core.excel import _daily_period,display_period
from modules.channel_analysis import CHANNEL_STORE_COUNTS
w=load_workbook(Path('..','..','output_file','鸿蒙智行大定选配比例分析.xlsx'),read_only=True,data_only=True)
brands=['问界','智界','享界','尊界','尚界']
names=['鸿蒙智行',*brands]
for brand in brands:
 names.append(next(n[:-3] for n in w.sheetnames if n.startswith(brand) and '款' in n and n.endswith('by天')))
result=[]
for name in names:
 for grain,suffix in [('day','天'),('week','周'),('month','月')]:
  s=w[name+'by'+suffix]; cells=list(s.iter_rows()); labels=[(_daily_period if grain=='day' else display_period)(c.value,c.number_format) for c in cells[0]]
  indexes=[i for i,label in enumerate(labels) if i>=3 and label and not re.fullmatch(r'(?:总计|合计|汇总|累计|近\d+(?:天|日|周|月))',label)]
  c=indexes[-1]; rows={}; metric=stat=''
  for row in cells[1:]:
   metric=str(row[0].value or metric);stat=str(row[1].value or stat);channel=row[2].value
   if metric not in ('门店类型','贡献订单门店数') or not channel:continue
   item=rows.setdefault(channel,{'channel':channel,'store_count':CHANNEL_STORE_COUNTS.get(channel)})
   if metric=='门店类型' and stat in ('数量','占比'):item['count' if stat=='数量' else 'share']=row[c].value
   elif metric=='贡献订单门店数' and stat=='数量':item['active_count']=row[c].value
  result.append({'subject':name,'grain':grain,'period':labels[c],'rows':list(rows.values())})
print(json.dumps(result,ensure_ascii=False));w.close()
`],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONIOENCODING:'utf-8',PYTHONUTF8:'1'}}));

(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const check=(name,value)=>{assert(value,name);checks++};
 const artifacts=process.env.AUDIT_ARTIFACT_DIR;if(artifacts)fs.mkdirSync(artifacts,{recursive:true});
 const context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage();
 page.on('pageerror',error=>errors.push(error.message));
 const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 const formatted=(value,kind='number')=>kind==='percent'?(value*100).toFixed(1)+'%':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:kind==='capacity'?2:0,maximumFractionDigits:kind==='capacity'?2:1});
 try{
  for(const sample of expected){
   const url=new URL(base);url.search=new URLSearchParams({subject:sample.subject,module:'channel_analysis',grain:sample.grain,period:sample.period});
   await page.goto(url.href);await page.waitForSelector('.channel-panel[data-channel-metric="sales"]');
   check('three sections',await page.locator('.channel-panel').count()===3);
   const nav=await page.locator('#moduleNav button').evaluateAll(nodes=>nodes.map(node=>node.dataset.module));
   check('navigation follows overview',nav.indexOf('channel_analysis')===nav.indexOf('overview')+1);
   check('selected period matches source',await page.locator('#periodSelect').inputValue()===sample.period);
   check('all channels visible',await page.locator('[data-channel-metric="sales"] [data-channel-choose]').count()===sample.rows.length);
   const tables=await page.locator('.channel-panel').evaluateAll(panels=>Object.fromEntries(panels.map(panel=>[panel.dataset.channelMetric,[...panel.querySelectorAll('.channel-current-details tbody tr')].map(tr=>[...tr.children].map(cell=>cell.textContent.trim()))])));
   for(const row of sample.rows){
    const sales=tables.sales.find(r=>r[0]===row.channel),stores=tables.stores.find(r=>r[0]===row.channel),capacity=tables.capacity.find(r=>r[0]===row.channel);
    check('raw channel count',sales?.[1]===formatted(row.count));
    check('raw channel share',sales?.[2]===formatted(row.share,'percent'));
    check('active store numerator',stores?.[1]===formatted(row.active_count));
    check('store denominator',stores?.[2]===formatted(row.store_count));
    check('active store ratio',stores?.[3]===formatted(row.active_count/row.store_count,'percent'));
    check('productivity denominator',capacity?.[3]===formatted(row.count/row.store_count,'capacity'));
   }
  }
  const brand=new URL(base);brand.search=new URLSearchParams({subject:'问界',module:'channel_analysis',grain:'week'});
  await page.goto(brand.href);await page.waitForSelector('.channel-panel');
  const sales=page.locator('[data-channel-metric="sales"]');
  await sales.locator('[data-channel-select]').selectOption('鸿蒙智行用户中心');
  check('channel select updates history',(await sales.locator('.channel-trend-summary').innerText()).includes('鸿蒙智行用户中心'));
  await sales.locator('[data-channel-measure]').selectOption('count');
  check('quantity trend selectable',(await sales.locator('[data-channel-chart] svg').getAttribute('aria-label')).includes('留存大定'));
  await sales.locator('[data-channel-choose="未知门店类型"]').click();
  check('bar click selects channel',await sales.locator('[data-channel-select]').inputValue()==='未知门店类型');
  const periods=await page.locator('#periodSelect option').evaluateAll(nodes=>nodes.map(node=>node.value));
  await page.locator('#periodSelect').selectOption(periods[0]);
  await page.waitForFunction(period=>document.querySelector('.channel-subhead span')?.textContent.includes(period),periods[0]);
  check('history stops at selected period',await sales.locator('.channel-history tbody tr').count()===1);
  await page.locator('#grainSelect [data-grain="day"]').click();
  await page.waitForFunction(()=>new URL(location.href).searchParams.get('grain')==='day');
  await page.reload();await page.waitForSelector('.channel-panel');
  check('grain persists after reload',await page.locator('#grainSelect [data-grain="day"]').getAttribute('class').then(c=>c.includes('active')));
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1050});
   check('no page overflow '+width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
   check('all section bodies constrained '+width,await page.locator('.channel-panel').evaluateAll(nodes=>nodes.every(node=>node.getBoundingClientRect().right<=innerWidth+1)));
   if(artifacts)await page.locator('#page').screenshot({path:path.join(artifacts,`channel-${width}.png`)});
  }
  await page.setViewportSize({width:1440,height:1050});
  await page.locator('[data-panel-source="0"]').click();
  await page.waitForSelector('#rawTable');
  check('source opens raw module',new URL(page.url()).searchParams.get('module')==='raw');
  const rawSearch=page.locator('#rawSearch');
  if(await rawSearch.count()){await rawSearch.fill('华为授权体验店');check('raw search usable',await rawSearch.inputValue()==='华为授权体验店');}
  await page.goBack();await page.waitForSelector('.channel-panel');
  check('source back restores channel page',new URL(page.url()).searchParams.get('module')==='channel_analysis');
  await context.close();
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({checks,subjects:new Set(expected.map(s=>s.subject)).size,views:expected.length,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
