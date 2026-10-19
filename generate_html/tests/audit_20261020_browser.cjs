// Exercise the formal main output with isolated Python-built conversion facts.
// No alternate HTML page or duplicate JS business calculation is generated.
const path=require('path'),assert=require('assert'),fs=require('fs');
const {pathToFileURL}=require('url'),{execFileSync}=require('child_process');
const root=path.resolve(__dirname,'..'),project=path.resolve(root,'../..');
const {chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const fixture=execFileSync(process.env.PYTHON_EXE||'python',['-c',
  "import json;from tests.test_audit_20261020 import ConversionMissingFactsTests; t=ConversionMissingFactsTests(); result={};\ntry:\n for key,values in [('middle',[100,90,None,80,75,70,60]),('delivery',[100,90,85,80,75,70,None]),('base',[None,90,85,80,75,70,60]),('zero',[100,90,0,0,0,0,0]),('complete',[100,90,85,80,75,70,60])]:\n  page=t.build_page(values,(0,0) if key=='zero' else (3.5,18) if key=='complete' else (None,'#DIV/0!'));result[key]={'periods':['26WK40'],'default_period':'26WK40','pages':{'26WK40':page}}\n print(json.dumps(result,ensure_ascii=False))\nfinally:t.doCleanups()"
 ],{cwd:root,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});
 const scenarios=JSON.parse(fixture),browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];
 const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
 const artifact=process.env.AUDIT_ARTIFACT_DIR;if(artifact)fs.mkdirSync(artifact,{recursive:true});
 let checks=0;const check=(name,passed)=>{assert(passed,name);checks++;console.log('PASS '+name)};
 try{
  for(const [name,view] of Object.entries(scenarios)){
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(({view})=>{
    const parse=JSON.parse;JSON.parse=function(text,...args){
     const result=parse.call(this,text,...args),seen=new WeakSet();
     const visit=value=>{if(!value||typeof value!=='object'||seen.has(value))return;seen.add(value);
      if(value.module_id==='conversion'&&value.views)value.views={week:view};Object.values(value).forEach(visit);
     };visit(result);return result;
    };
   },{view});
   const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
   await page.goto(base.href);await page.waitForFunction(()=>document.querySelector('#subjectSelect option'));
   const subject=await page.evaluate(()=>window.DASHBOARD_DATA.subjects.find(s=>s.modules.includes('conversion')));
   assert(subject,'formal main output needs a conversion subject');
   const url=new URL(base);url.search=new URLSearchParams({subject:subject.id,module:'conversion',grain:'week'});
   await page.goto(url.href);await page.waitForSelector('.funnel-row:not(.head)');
   const rows=await page.locator('.funnel-row:not(.head)').evaluateAll(nodes=>nodes.map(n=>[...n.children].map(c=>c.textContent.trim())));
   const kpis=await page.locator('.kpi').evaluateAll(nodes=>Object.fromEntries(nodes.map(n=>[n.querySelector('span').textContent,n.querySelector('strong').textContent])));
   if(name==='middle'){
    check('missing quantity and loss not displayed as zero: '+JSON.stringify(rows[2]),rows[2].slice(2).every(v=>v==='—'));
    check('following known total rate retained',rows[3][2]==='80'&&rows[3][3]==='80.0%'&&rows[3][4]==='—');
    check('incomplete max loss unavailable',kpis['最大阶段流失']==='—');
    check('independent total conversion retained',kpis['总转化率']==='60');
   }
   if(name==='delivery')check('unknown delivery does not yield 0%',kpis['总转化率']==='—'&&kpis['当前已交付']==='—');
   if(name==='base')check('unknown base leaves all total percentages unknown',rows.every(row=>row[3]==='—'));
   if(name==='zero'){
    check('real zero quantity and total rate remain visible',rows[2][2]==='0'&&rows[2][3]==='0.0%');
    check('zero denominator is not 0% conversion',rows[3][4]==='—');
    check('real stage loss retained',kpis['最大阶段流失']==='90');
   }
   if(name==='complete')check('complete results unchanged',kpis['总转化率']==='60'&&kpis['最大阶段流失']==='10');
   const matrix=await page.locator('.data-table tbody tr').first().locator('td').allTextContents();
   check(name+' durations',name==='zero'?matrix.slice(-2).every(v=>v==='0天'):name==='complete'?matrix.at(-2)==='3.5天'&&matrix.at(-1)==='18天':matrix.slice(-2).every(v=>v==='—'));
   check(name+' no nonfinite output',!/NaN|Infinity/.test(await page.locator('#page').innerText()));
   check(name+' no invented empty funnel bar',await page.locator('.funnel-fill').count()===rows.filter(row=>row[3]!=='—').length);
   if(artifact&&['middle','zero'].includes(name))await page.screenshot({path:path.join(artifact,'conversion-'+name+'.png'),fullPage:true});
   await context.close();
  }
  const context=await browser.newContext(),page=await context.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  const url=new URL(base);url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'overview'});
  const ready=()=>page.waitForFunction(()=>document.querySelector('#page')?.getAttribute('aria-busy')==='false');
  await page.goto(url.href);await ready();
  for(const grain of ['day','week','month']){
   await page.locator(`[data-grain="${grain}"]`).click();await ready();
   const periods=await page.locator('[data-history-body] tbody tr td:first-child').allTextContents();
   const pattern={day:/^\d{4}-\d{2}-\d{2}$/,week:/^\d{2}WK\d{2}$/,month:/^\d{2}-\d{2}$/}[grain];
   check('overview '+grain+' period alignment',periods.length>0&&periods.every(v=>pattern.test(v.trim())));
  }
  await page.locator('[data-module="raw"]').click();await page.waitForSelector('#rawSearch');
  await page.locator('#rawSearch').fill('NO_MATCH_AUDIT_20261020');await page.waitForSelector('#rawEmpty:not([hidden])');
  check('raw search empty feedback',await page.locator('#rawEmpty').isVisible());
  await page.locator('#clearRawSearch').click();
  await page.waitForFunction(()=>document.querySelector('#rawSearch').value===''&&document.querySelector('#rawEmpty').hidden);
  check('raw search reset restores records',!await page.locator('#rawEmpty').isVisible());
  await context.close();
  check('no browser exceptions',errors.length===0);
  console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
