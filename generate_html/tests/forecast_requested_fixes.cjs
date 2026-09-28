const assert=require('assert'),fs=require('fs'),path=require('path');
const script=fs.readFileSync(path.join(__dirname,'../templates/dashboard.js'),'utf8');
const section=(start,end)=>script.slice(script.indexOf(start),script.indexOf(end,script.indexOf(start)));
const brand=new Function(section('  const referenceBrand=','  function renderLifecycleReferenceCard(')+';return {referenceBrand,lifecycleUnavailable};')();
assert.equal(brand.referenceBrand({model:'RX 2027款',generation:'智界 RX 2027款',brand:'界'}),'智界');
assert.equal(brand.referenceBrand({model:'理想 L9',brand:'理想'}),'理想');
assert.equal(brand.referenceBrand({model:'外部车型',brand:'未维护'}),'其他');
assert.equal(brand.lifecycleUnavailable('hourly',{small_hourly_curve:[]}),true);
assert.equal(brand.lifecycleUnavailable('hourly',{small_hourly_curve:[null,.2,1]}),false);
const root={querySelector:()=>({value:'0'})},data={target:{small_end_date:'2026-10-01'}};
const small=new Function('root','data','todayIso','sameModel',section('    const scoringSmall=','    const targetState=')+';return scoringSmall;')(root,data,()=> '2026-09-28',(a,b)=>a===b);
root._smallForecastResult={name:'智界 RX 2027款',date:'2026-09-28',total:18000,error:null};
assert.deepEqual(small('智界 RX 2027款',{small:0}),{value:18000,estimated:true});
root._smallForecastLinked=true;
assert.equal(small('智界 RX 2027款',{small:0}).value,18000);
root._smallForecastResult.error='缺少分时数据';
assert.equal(small('智界 RX 2027款',{small:0}).value,0);
root._smallForecastResult.error=null;
assert.equal(small('另一车型',{small:0}).value,0);
assert.equal(small('智界 RX 2027款',{small:123,small_end_date:'2026-09-27'}).value,123);
// Exercise the real launch scoring rules before D1, not just the linked-input helper.
const score=new Function('sameModel','actualSignals','calendarProfile','calendarSimilarity','fmt',
  section('    const closeness=','    const updateWeightSummary=')+';return scoreSummary;')(
  (a,b)=>a===b,()=>({days:[]}),()=>({}),()=>NaN,String);
const target={name:'智界 RX 2027款',tier:'中大型SUV',energy:'增程',node:'全新发布',period:'下午',days:35,small:18000,smallEstimated:true};
const reference={model:'历史参考',tier:target.tier,energy:target.energy,node:target.node,launch_period:target.period,days:35,small:20000,conversion:.5,direct_share:.2};
for(const task of ['conversion','direct_share']){
  const result=score(reference,task,target);
  assert(result.coverage>=.45,task+' must have enough evidence before D1');
  assert(result.parts.some(part=>part.key==='size'&&part.label.includes('小订预测')));
  assert(score(reference,task,{...target,small:0,smallEstimated:false}).coverage<.45);
}
const chartCode=section('  function renderForecastEvidenceLines(','  function renderLifecycleScorePage(');
const chart=new Function('esc',chartCode+';return renderLifecycleLineChart;')(v=>String(v??''));
const single=chart({series:[{label:'外部预测',values:[1547],color:'#7C3AED'}],labels:['2026-09-28'],unit:'number',ariaLabel:'导入折线'});
assert(single.includes('<circle')&&single.includes('1,547')&&single.includes('2026-09-28'));
const multiple=chart({series:[{label:'外部预测',values:[1547,0,1600],color:'#7C3AED'}],labels:['2026-09-28','2026-09-29','2026-09-30'],unit:'number',ariaLabel:'导入折线'});
assert(multiple.includes('<polyline')&&multiple.includes('2026-09-29')&&multiple.includes('0单'));
console.log('PASS: predicted-small scoring, brand classification, hourly eligibility and single/multi-point import charts');
