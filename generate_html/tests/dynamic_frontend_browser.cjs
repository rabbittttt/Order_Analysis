const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const project=path.resolve(__dirname,'../../..'),root=path.resolve(__dirname,'..');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(project,'.test_runtime/node_modules/playwright'));
const aggregateNames=['问界 M9&M9U 2026款','尊界 V680&V800 2026款','尚界 Z7&Z7T 2026款','享界 S9&S9T 2026款'];
const subjects=[{id:'g',name:'鸿蒙智行',type:'group'},{id:'b',name:'问界',type:'brand',parent:'鸿蒙智行'},{id:'m',name:'问界 M9 2026款',type:'generation',parent:'问界'},{id:'other',name:'智界 R7 2026款',type:'generation',parent:'智界'},...aggregateNames.map((name,index)=>({id:'aggregate'+index,name,type:'generation',parent:name.slice(0,2)}))].map(s=>({...s,has_lock_orders:true,modules:s.id==='m'?['overview','order_mix','raw']:['overview','raw']}));
const generatedTimes={'fixture-v1':'2026-11-10T10:00:00','fixture-v2':'2026-11-10T10:01:00','fixture-v3':'2026-11-10T10:02:00','fixture-v4':'2026-11-10T10:03:00'};
const generationLabel=version=>'生成时间 '+generatedTimes[version].replace('T',' ');
const catalog={dataset_id:'fixture-v1',meta:{generated_at:generatedTimes['fixture-v1']},subjects,config:{module_order:['overview','order_mix','raw'],module_labels:{overview:'订单总览',order_mix:'大定选配',raw:'底表中心'},grain_labels:{day:'日',week:'周',month:'月'}},raw_files:[{name:'fixture.xlsx',workbook_key:'0|xlsx',sheets:[{name:'数据',total_rows:451,total_cols:2}]}]};
const header=['序号','格式值'],allRows=Array.from({length:450},(_,i)=>[i+1,`${i%2?'odd':'even'} 12.30%`]),xlsx=Buffer.from('fixture-original-xlsx');
let currentVersion='fixture-v1',failNewBoard=false,syncPhase='idle';
let notes=[{id:'group',subject:'g',date:'2026-11-10',text:'集团事件',version:1},{id:'brand',subject:'b',date:'2026-11-10',text:'问界事件',version:1}],failSubject='other',requests=[],nextId=1;
const view={periods:['26WK46'],default_period:'26WK46',pages:{'26WK46':{kpis:[{label:'合计',value:123,unit:'辆'}],sections:[{title:'留存大定趋势',kind:'stacked_trend',width:'half',data:{periods:['26WK46'],totals:[123],series:[{name:'增程',values:[1]}]},source:{file:'fixture.xlsx',sheet:'数据'}}]}}};
const batteryPeriods=['26WK42','26WK43','26WK44','26WK45','26WK46'];
const batterySection={
  kind:'mix_combo_trend',title:'电池包度数 · 数量与占比',
  data:{periods:batteryPeriods,series:[
    {name:'80度',shares:[.6,0,.6,0,null],counts:[120,0,740,0,null]},
    {name:'100度',shares:[.4,1,.4,0,null],counts:[80,null,494,0,null]}
  ]}
};
const batteryView={periods:['26WK46'],default_period:'26WK46',pages:{'26WK46':{kpis:[],sections:[batterySection]}}};
let shell=fs.readFileSync(path.join(root,'templates/dashboard.html'),'utf8').replace('<script>window.DASHBOARD_DATA_B64="__DASHBOARD_DATA__";</script>','<script>window.ORDER_DASHBOARD_API_BASE="api/";</script>').replace('__DASHBOARD_RAW__','{}').replace('__DASHBOARD_BLOCKS__','{}').replace('__DASHBOARD_CSS__',()=>fs.readFileSync(path.join(root,'templates/dashboard.css'),'utf8')).replace('__DASHBOARD_JS__',()=>fs.readFileSync(path.join(root,'templates/dashboard.js'),'utf8')).replace('__TREND_ANNOTATIONS_JS__',()=>fs.readFileSync(path.join(root,'templates/trend_annotations.js'),'utf8')).replace('__BRAND_LOGO__','data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7');
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost'),p=url.pathname;requests.push({path:p,query:Object.fromEntries(url.searchParams),method:req.method});
 const send=(value,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value))};
 if(!p.startsWith('/orderiq/api/')){res.setHeader('Content-Type','text/html;charset=utf-8');return res.end(shell)}
 const route=p.slice('/orderiq/api/'.length);
 if(route==='catalog')return send({...catalog,dataset_id:currentVersion,meta:{...catalog.meta,generated_at:generatedTimes[currentVersion]}});
 if(route==='sync')return send({dataset_id:currentVersion,phase:syncPhase,error:null});
 if(!['fixture-v1','fixture-v2','fixture-v3','fixture-v4'].includes(url.searchParams.get('dataset')))return send({detail:'missing dataset'},400);
 if(route==='dashboard'){
   if(failNewBoard&&url.searchParams.get('dataset')!=='fixture-v1')return send({detail:'new batch unavailable'},503);
   if(url.searchParams.get('subject')===failSubject){failSubject=null;return send({detail:'看板读取失败'},503)}
   if(url.searchParams.get('module')==='order_mix')return send({views:{week:batteryView},sources:[]});
   return send({views:{week:view,day:{...view,periods:['2026-11-10'],default_period:'2026-11-10',pages:{'2026-11-10':view.pages['26WK46']}},month:view},sources:[]});
 }
 if(route==='raw'||route==='export/csv'){
   const q=url.searchParams.get('q')||'',matches=allRows.filter(row=>row.some(v=>String(v).toLowerCase().includes(q.toLowerCase()))),offset=Number(url.searchParams.get('offset')||0),limit=Number(url.searchParams.get('limit')||200);
   if(q==='odd')await new Promise(r=>setTimeout(r,600));
   if(route==='export/csv'){res.setHeader('Content-Type','text/csv;charset=utf-8');return res.end('\ufeff'+[header,...matches].map(row=>row.join(',')).join('\r\n'))}
   return send({rows:[header,...matches.slice(offset,offset+limit)],total:matches.length,offset,limit});
 }
 if(route==='workbook'){res.setHeader('Content-Type','application/octet-stream');return res.end(xlsx)}
 if(route==='annotations'&&req.method==='GET')return send({entries:notes});
 const id=decodeURIComponent(route.split('/')[1]||'');let body='';for await(const part of req)body+=part;
 if(route==='annotations'&&req.method==='POST'){const note={...JSON.parse(body),id:'new'+nextId++,version:1};notes.push(note);return send(note)}
 const note=notes.find(n=>n.id===id),params=body?JSON.parse(body):{};
 if(!note)return send({detail:'Not found'},404);
 if(Number(params.version||url.searchParams.get('version'))!==note.version)return send({detail:'conflict'},409);
 if(req.method==='PUT'){Object.assign(note,params,{version:note.version+1});return send(note)}
 if(req.method==='DELETE'){notes=notes.filter(n=>n.id!==id);return send({deleted:id})}
 send({detail:'Not found'},404);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const base=`http://127.0.0.1:${server.address().port}/orderiq/`;
 const browser=await chromium.launch({headless:true,channel:'msedge'}),ctx=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'}),page=await ctx.newPage(),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));const check=(label,v)=>{assert(v,label);checks.push(label);console.log('PASS',label)};
 try{
  await page.addInitScript(()=>localStorage.setItem('order-dashboard.trend-annotations.visible','false'));
  await page.goto(base+'?subject=m');await page.waitForSelector('.kpi');
  check('桌面顶部显示当前批次生成时间',await page.locator('#syncStatus').isVisible()&&await page.locator('#syncStatus').textContent()===generationLabel('fixture-v1'));
  check('首屏仅请求当前看板，未请求底表或Excel',requests.filter(r=>r.path.endsWith('/dashboard')).length===1&&!requests.some(r=>/\/(raw|workbook)$/.test(r.path)));
  const actionsMatchSource=()=>page.locator('.trend-annotation-actions>button').evaluateAll(buttons=>{
    if(buttons.length!==3||buttons.some(button=>!button.classList.contains('panel-source')))return false;
    const styles=buttons.map(button=>{
      const css=getComputedStyle(button);
      return JSON.stringify([css.color,css.backgroundColor,css.border,css.borderRadius,css.fontSize,css.fontWeight,css.minHeight,css.padding]);
    });
    return new Set(styles).size===1;
  });
  check('批注按钮与来源数据使用相同样式',await actionsMatchSource());
  for(const phase of ['building','waiting','idle']){
    syncPhase=phase;
    const expected=generationLabel('fixture-v1')+(phase==='building'?' · 后台数据刷新中':'');
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(text=>document.querySelector('#syncStatus').textContent===text,expected);
    check('顶部按后台状态显示并恢复 '+phase,await page.locator('#syncStatus').isVisible());
  }
  await page.waitForSelector('.trend-annotation');
  const chartHeights=()=>page.locator('[data-trend-chart]').evaluate(chart=>({
    card:chart.closest('.panel').getBoundingClientRect().height,
    bars:[...chart.querySelectorAll('rect[fill]')].map(bar=>bar.getBoundingClientRect().height)
  }));
  const annotated=await chartHeights();
  assert(annotated.bars.some(height=>height>0));
  await page.locator('[data-trend-annotation-toggle]').click();assert.equal(await page.locator('.trend-annotation').count(),0);
  const hidden=await chartHeights();
  assert.deepStrictEqual(hidden.bars,annotated.bars,'显示批注时保持柱高');
  check('切换批注时保持卡片高度',annotated.card===hidden.card);
  await page.locator('[data-trend-annotation-toggle]').click();await page.waitForSelector('.trend-annotation');
  await page.locator('[data-trend-annotation-toggle]').click();
  await page.reload();await page.waitForSelector('.trend-annotation');
  check('刷新后批注默认展开',await page.locator('[data-trend-annotation-toggle]').getAttribute('aria-expanded')==='true');
  check('集团和品牌批注继承到车型',(await page.locator('.trend-annotation').getAttribute('aria-label')).includes('集团事件')&&(await page.locator('.trend-annotation').getAttribute('aria-label')).includes('问界事件'));
  await page.locator('#subjectSelect').selectOption('other');await page.waitForSelector('[data-page-retry]');
  check('失败请求显示重试',await page.locator('#page [role="alert"]').textContent().then(s=>s.includes('看板读取失败')));
  await page.locator('[data-page-retry]').click();await page.waitForSelector('.kpi');
  check('品牌批注不跨品牌',(await page.locator('.trend-annotation').getAttribute('aria-label')).includes('集团事件')&&!(await page.locator('.trend-annotation').getAttribute('aria-label')).includes('问界事件'));
  await page.locator('#subjectSelect').selectOption('m');await page.waitForFunction(()=>new URL(location).searchParams.get('subject')==='m');
  await page.locator('[data-trend-annotation-manage]').click();
  await page.locator('#trendAnnotationForm [name="date"]').fill('2026-11-10');await page.locator('#trendAnnotationForm [name="subject"]').selectOption('g');await page.locator('#trendAnnotationForm [name="text"]').fill('共享新增 <b>');await page.locator('#trendAnnotationForm button[type="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('#trendAnnotationList').textContent.includes('共享新增 <b>'));
  check('共享批注写后台且文本转义',notes.some(n=>n.text==='共享新增 <b>')&&await page.locator('#trendAnnotationList b').count()===0);
  const ctx2=await browser.newContext(),second=await ctx2.newPage();await second.goto(base+'?subject=other');await second.waitForSelector('.kpi');await second.waitForSelector('.trend-annotation');
  check('另一浏览器读取共享修改',(await second.locator('.trend-annotation').getAttribute('aria-label')).includes('共享新增 <b>'));
  const row=page.locator('#trendAnnotationList li').filter({hasText:'共享新增 <b>'});await row.getByRole('button',{name:'编辑',exact:true}).click();notes.find(n=>n.text==='共享新增 <b>').version++;
  await page.locator('#trendAnnotationForm [name="text"]').fill('冲突覆盖');await page.locator('#trendAnnotationForm button[type="submit"]').click();await page.waitForSelector('#trendAnnotationError:not([hidden])');
  check('并发冲突保留别人改动',!notes.some(n=>n.text==='冲突覆盖')&&(await page.locator('#trendAnnotationError').textContent()).includes('他人修改'));
  await page.locator('#trendAnnotationEditor header button').click();
  await page.locator('[data-module="raw"]').click();await page.waitForSelector('#rawNext');
  check('底表首批只显示200条数据',await page.locator('#rawTable tr').count()===201&&(await page.locator('#rawPageInfo').textContent())==='1 / 3');
  await page.locator('#rawNext').click();await page.waitForFunction(()=>document.querySelector('#rawPageInfo').textContent==='2 / 3');
  check('下一页读取正确偏移',await page.locator('#rawTable tr').nth(1).locator('td').first().textContent()==='201');
  await page.locator('#rawSearch').fill('odd');await page.waitForRequest(r=>r.url().includes('q=odd'));await page.locator('#rawSearch').fill('even');await page.waitForFunction(()=>document.querySelector('#rawMatchCount').textContent.includes('225')&&document.querySelector('#rawTable tr:nth-child(2)').textContent.includes('even'));await page.waitForTimeout(700);
  check('搜索竞态不显示旧结果',!(await page.locator('#rawTable').textContent()).includes('odd')&&(await page.locator('#rawPageInfo').textContent())==='1 / 2');
  const d=page.waitForEvent('download');await page.locator('#exportRaw').click();const csv=fs.readFileSync(await(await d).path(),'utf8');
  check('CSV导出所有匹配结果，包含未加载页',csv.split('\r\n').length===226&&csv.includes('449,even'));
  const w=page.waitForEvent('download');await page.locator('#exportRawWorkbook').click();check('Excel按需下载原始字节',fs.readFileSync(await(await w).path()).equals(xlsx));
  await page.setViewportSize({width:390,height:844});check('手机无页面横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  check('API请求都携带同一批次',requests.filter(r=>r.path.includes('/api/')&&!r.path.endsWith('/catalog')).every(r=>r.query.dataset==='fixture-v1'));
  check('手机顶部显示当前批次生成时间',await page.locator('#syncStatus').isVisible()&&await page.locator('#syncStatus').textContent()===generationLabel('fixture-v1'));
  for(const phase of ['building','idle']){
    syncPhase=phase;
    const expected=generationLabel('fixture-v1')+(phase==='building'?' · 后台数据刷新中':'');
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(text=>document.querySelector('#syncStatus').textContent===text,expected);
    check('手机生成时间旁按后台状态显示 '+phase,await page.locator('#syncStatus').isVisible());
  }
  await page.locator('#moduleSelect').selectOption('overview');await page.waitForSelector('.kpi');
  check('手机批注按钮与来源数据使用相同样式',await actionsMatchSource());
  await page.setViewportSize({width:1440,height:1000});
  await page.evaluate(()=>{window.__syncSentinel=42;document.activeElement?.blur()});
  await page.locator('[data-module="overview"]').click();await page.waitForSelector('.kpi');
  failNewBoard=true;currentVersion='fixture-v2';
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>document.querySelector('#syncStatus').textContent.includes('同步暂不可用'));
  check('新批次请求失败保留旧页面',await page.evaluate(()=>window.DASHBOARD_DATA.dataset_id)==='fixture-v1'&&await page.locator('.kpi').count()>0);
  check('新批次请求失败保留旧生成时间',(await page.locator('#syncStatus').textContent()).startsWith(generationLabel('fixture-v1')+' · '));
  failNewBoard=false;
  await page.locator('[data-trend-annotation-manage]').click();
  await page.locator('#trendAnnotationForm [name="text"]').fill('尚未提交的批注');
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForTimeout(150);
  check('批注编辑时暂缓切换',await page.evaluate(()=>window.DASHBOARD_DATA.dataset_id)==='fixture-v1'&&await page.locator('#trendAnnotationForm [name="text"]').inputValue()==='尚未提交的批注');
  check('暂缓切换时保留旧生成时间',await page.locator('#syncStatus').textContent()===generationLabel('fixture-v1'));
  await page.locator('#trendAnnotationEditor header button').click();
  await page.waitForFunction(()=>window.DASHBOARD_DATA.dataset_id==='fixture-v2');await page.waitForSelector('.kpi');
  check('关闭编辑后自动同步且不重载网页',await page.evaluate(()=>window.__syncSentinel===42)&&await page.locator('#subjectSelect').inputValue()==='m');
  check('同步成功显示新批次生成时间',await page.locator('#syncStatus').textContent()===generationLabel('fixture-v2'));
  await page.locator('[data-module="raw"]').click();await page.waitForSelector('#rawNext');
  await page.locator('#rawSearch').fill('even');await page.waitForFunction(()=>document.querySelector('#rawMatchCount').textContent.includes('225'));
  await page.locator('#rawNext').click();await page.waitForFunction(()=>document.querySelector('#rawPageInfo').textContent==='2 / 2');
  await page.evaluate(()=>document.activeElement?.blur());currentVersion='fixture-v3';
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
  await page.waitForFunction(()=>window.DASHBOARD_DATA.dataset_id==='fixture-v3'&&document.querySelector('#page').getAttribute('aria-busy')==='false');
  check('底表同步保留搜索和页码',await page.locator('#rawSearch').inputValue()==='even'&&await page.locator('#rawPageInfo').textContent()==='2 / 2');
  check('底表同步更新生成时间',await page.locator('#syncStatus').textContent()===generationLabel('fixture-v3'));
  const download=page.waitForEvent('download');await page.locator('#exportRawWorkbook').click();await download;
  check('导出使用切换后的批次',requests.filter(r=>r.path.endsWith('/workbook')).at(-1).query.dataset==='fixture-v3');
  currentVersion='fixture-v4';
  await page.waitForFunction(()=>window.DASHBOARD_DATA.dataset_id==='fixture-v4',{},{timeout:22000});
  check('无需点击或刷新即可定期同步',await page.evaluate(()=>window.__syncSentinel===42));
  check('定期同步更新生成时间',await page.locator('#syncStatus').textContent()===generationLabel('fixture-v4'));
  for(let index=0;index<aggregateNames.length;index++){
    const name=aggregateNames[index],option=page.locator('#subjectSelect option').filter({hasText:name});
    check('组合代际完整显示 '+name,await option.textContent()===name);
    const shortcut=page.locator('[data-quick-generation="aggregate'+index+'"]');
    check('组合快捷名称不追加汇总 '+name,(await shortcut.textContent()).includes('&')&&!(await shortcut.textContent()).includes('汇总'));
  }
  await page.locator('[data-module="overview"]').click();await page.waitForSelector('.kpi');
  await page.locator('#subjectSelect').selectOption('aggregate0');await page.waitForFunction(()=>new URL(location).searchParams.get('subject')==='aggregate0');
  check('组合代际可选择并加载',await page.locator('.kpi').count()>0&&await page.locator('#subjectSelect').inputValue()==='aggregate0');
  await page.goto(base+'?subject=m&module=order_mix&grain=week');
  const battery=page.locator('[data-section-kind="mix_combo_trend"]');
  await battery.waitFor();
  const labelText=selector=>battery.locator(selector).evaluateAll(nodes=>nodes.map(node=>
    Array.from(node.childNodes).filter(child=>child.nodeType===Node.TEXT_NODE).map(child=>child.textContent).join('')
  ));
  const shares=await labelText('.stack-segment-label');
  assert.deepStrictEqual(shares.sort(),['60%','0%','60%','0%','40%','100%','40%','0%'].sort());
  check('电池包柱段只标占比，悬停可查看数量',await battery.locator('rect[fill]').count()===shares.length&&(await battery.locator('rect[fill] title').first().textContent()).includes('数量 120'));
  assert.deepStrictEqual(await labelText('.total-label'),['200','1,234','0']);
  const totalLine=battery.locator('svg path');
  check('电池包总量只画一条线，数据缺失时断开',await totalLine.count()===1&&(await totalLine.getAttribute('d')).split('M').length===3&&await battery.locator('circle').count()===3);
  check('电池包占比与总量分别使用左右轴',await battery.locator('.channel-y-axis.left').count()===1&&await battery.locator('.channel-y-axis.right').count()===1);
  check('无浏览器异常',errors.length===0);await ctx2.close();
 }finally{await browser.close();await new Promise(r=>server.close(r));}
 console.log(JSON.stringify({checks:checks.length,errors}));
})().catch(e=>{console.error(e);server.close();process.exitCode=1});
