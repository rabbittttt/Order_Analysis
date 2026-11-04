// Exercise the formal generated page with isolated in-memory source scenarios.
const path=require('path'),assert=require('assert'),{pathToFileURL}=require('url');
const project=path.resolve(__dirname,'../../..');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(project,'.test_runtime/node_modules/playwright'));
const base=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'}),errors=[];let checks=0;
 const check=(label,ok)=>{assert(ok,label);checks++;console.log('PASS '+label)};
 try{
   const context=await browser.newContext({viewport:{width:1440,height:1000}});
   await context.addInitScript(()=>{
    const parse=JSON.parse;
    JSON.parse=function(text,...args){
     const value=parse.call(this,text,...args),seen=new WeakSet();
     const visit=data=>{
      if(!data||typeof data!=='object'||seen.has(data))return;seen.add(data);
      if(data.module_id==='order_mix'&&data.views)data.views={week:{periods:['26WK01'],default_period:'26WK01',pages:{'26WK01':{kpis:[],sections:[{
       kind:'table',title:'审计未知数量',data:{columns:['选配项','数量','占比','变化'],formats:['text','number','percent','signed_percent'],
        rows:[['unknown',null,null,null],['zero',0,0,0]]}
      }]}}}};
      Object.values(data).forEach(visit);
     };visit(value);return value;
    };
   });
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
    const mix=new URL(base);mix.search=new URLSearchParams({subject:'问界 M9 2026款',module:'order_mix',grain:'week'});
    await page.goto(mix.href);const table=page.locator('.panel').filter({has:page.getByRole('heading',{name:'审计未知数量',exact:true})});await table.waitFor();
    const unknown=await table.locator('tbody tr').nth(0).locator('td').allTextContents(),zero=await table.locator('tbody tr').nth(1).locator('td').allTextContents();
    check('unknown quantity/share/change stay unknown',unknown.slice(1).every(value=>value==='—'));
    check('real zero formats remain valid',JSON.stringify(zero.slice(1))===JSON.stringify(['0','0.0%','+0.0%']));
   await context.close();
  check('no browser exceptions',errors.length===0);console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
