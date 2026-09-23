import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
import {chooseGrouping,reportSeries} from './report_grouping.mjs';
const dir=path.dirname(fileURLToPath(import.meta.url));
const evidencePath=process.argv[2] || path.resolve(dir,'..','..','output_file','销量规律','分析证据.json');
const cleanupDefaultEvidence=!process.argv[2];
const outputDir=process.argv[3] || path.resolve(dir,'..','..','output','_file');
const previewDir=process.argv[4] || path.join(dir,'excel_preview');
const payload=JSON.parse(await fs.readFile(evidencePath,'utf8'));
const d=payload.results;
const wb=Workbook.create();
const mean=a=>a.reduce((s,x)=>s+x,0)/a.length;
const median=a=>{a=[...a].sort((x,y)=>x-y);return a.length%2?a[(a.length-1)/2]:(a[a.length/2-1]+a[a.length/2])/2};
const group=(rs,keys)=>{const m=new Map();for(const r of rs){const k=JSON.stringify(keys.map(k=>r[k]));if(!m.has(k))m.set(k,[]);m.get(k).push(r)}return [...m.entries()].map(([k,v])=>[JSON.parse(k),v])};
const col=n=>{let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s};
const previews=[];
function sheet(name,widths){
 const s=wb.worksheets.add(name);s.showGridLines=false;
 for(let i=0;i<widths.length;i++)s.getRange(col(i)+'1:'+col(i)+'350').format.columnWidth=widths[i];
 s.getRange('A1:'+col(widths.length-1)+'350').format.font={name:'Microsoft YaHei',size:10,color:'#243447'};
 s.getRange('A1:'+col(widths.length-1)+'350').format.verticalAlignment='center';
 s.getRange('A2').values=[[name]];s.getRange('A2').format.font={name:'Microsoft YaHei',size:16,bold:true,color:'#18344B'};
 s.getRange('A2:'+col(widths.length-1)+'2').format.rowHeight=30;
 s.getRange('A3').values=[[payload.sample?'样例结果，仅验证分析流程，不代表真实经营规律。':'本次计算结果快照；更新数据后需重新运行分析。']];
 s.getRange('A3').format.font={color:'#945B10',size:10};
 return s;
}
function note(s,row,text,last=8){
 s.getRange('A'+row).values=[[text]];
 s.getRange('A'+row+':'+col(last)+row).format.rowHeight=25;
}
function section(s,row,title,last){
 s.getRange('A'+row+':'+col(last)+row).format.fill='#E7EEF4';
 s.getRange('A'+row).values=[[title]];s.getRange('A'+row).format.font={bold:true,color:'#18344B'};
 s.getRange('A'+row+':'+col(last)+row).format.rowHeight=25;
}
function table(s,start,headers,rows,formats={},filter=false){
 const end=col(headers.length-1);
 s.getRange('A'+start+':'+end+start).values=[headers];
 const h=s.getRange('A'+start+':'+end+start);
 h.format={fill:'#24455F',font:{name:'Microsoft YaHei',size:10,bold:true,color:'#FFFFFF'},rowHeight:34,wrapText:true,horizontalAlignment:'center'};
 if(rows.length){
  s.getRange('A'+(start+1)+':'+end+(start+rows.length)).values=rows;
  s.getRange('A'+(start+1)+':'+end+(start+rows.length)).format.font={name:'Microsoft YaHei',size:10,color:'#243447'};
  s.getRange('A'+(start+1)+':'+end+(start+rows.length)).format.rowHeight=36;
  s.getRange('A'+(start+1)+':'+end+(start+rows.length)).format.wrapText=true;
  for(let i=0;i<rows.length;i++)if(i%2===1)s.getRange('A'+(start+1+i)+':'+end+(start+1+i)).format.fill='#F2F5F8';
  for(const [i,fmt] of Object.entries(formats))s.getRange(col(+i)+(start+1)+':'+col(+i)+(start+rows.length)).setNumberFormat(fmt);
  if(filter){const t=s.tables.add('A'+start+':'+end+(start+rows.length),true,'Data'+wb.worksheets.items.length);t.showFilterButton=true;}
 }
 return start+rows.length+1;
}
const weekly=group(d.weekly,['metric','stage']).map(([k,rs])=>{
 const ms=group(rs,['model']).map(x=>x[1]);
 return [...k,ms.length,rs.length,new Set(rs.map(r=>r.week)).size,
 ...Array.from({length:7},(_,i)=>mean(ms.map(g=>mean(g.map(r=>r.indexes[i]))))),
 mean(ms.map(g=>mean(g.map(r=>r.ratio))))];
});
const monthly=group(d.monthly,['metric','stage']).map(([k,rs])=>{const ms=group(rs,['model']).map(x=>x[1]);return [...k,ms.length,rs.length,new Set(rs.map(r=>r.year+'-'+r.month)).size,mean(ms.map(g=>mean(g.map(r=>r.ratio))))]});
const life=group(d.lifecycle,['metric','stage']).map(([k,rs])=>[...k,rs.length,new Set(rs.map(r=>r.model)).size,median(rs.map(r=>r.d1_ratio)),median(rs.map(r=>r.first2_share))]);

const config=JSON.parse(await fs.readFile(process.argv[5] || path.join(dir,'report_config.json'),'utf8'));
const grouping=chooseGrouping(d.model_classes,config);
const modelMap=new Map(grouping.entries.map(r=>[r.model,r]));
const categories=grouping.categories;
const series=reportSeries(d.period_comparisons,categories,modelMap);
const within=(rows,field)=>rows.length?median(group(rows,['model']).map(([,rs])=>median(rs.map(r=>r[field])))):null;
const pick=(rows,category,metric,stage)=>rows.filter(r=>(category==='全部车型'||modelMap.get(r.model)?.category===category)&&r.metric===metric&&r.stage===stage);
const monthRows=d.period_comparisons.filter(r=>r.kind==='月');
const monthlyProfiles=[];
for(const {category,metric,stage} of series){
 const scoped=pick(monthRows,category,metric,stage);
 for(let month=1;month<=12;month++){
  const rows=scoped.filter(r=>Number(r.start.slice(5,7))===month);
  const complete=rows.filter(r=>r.current_observed===r.current_days&&r.current>=0).map(r=>({...r,daymean:r.current/r.current_days}));
  const paired=rows.filter(r=>r.status==='有效');
  const years=[...new Set(paired.map(r=>r.start.slice(0,4)))].sort();
  const annual=years.map(y=>[y,within(paired.filter(r=>r.start.startsWith(y)),'daily_ratio')]);
  monthlyProfiles.push({category,metric,stage,month,daymean:within(complete,'daymean'),ratio:within(paired,'ratio'),daily:within(paired,'daily_ratio'),
   models:new Set(complete.map(r=>r.model)).size,complete:complete.length,pairs:paired.length,pairmodels:new Set(paired.map(r=>r.model)).size,
   years:years.length,periods:new Set(paired.map(r=>r.start)).size,
   above:paired.length?mean(group(paired,['model']).map(([,rs])=>mean(rs.map(r=>r.daily_ratio>1?1:0)))):null,
   yearly:annual.map(([y,v])=>y+'：'+(100*v).toFixed(1)+'%').join('；'),
   conclusion:!paired.length?'缺少完整相邻月':years.length<2?'单年样本，不能认定季节性':annual.every(([,v])=>v>1)?'各年中位数均上升，待控制活动':annual.every(([,v])=>v<1)?'各年中位数均下降，待控制活动':'跨年方向不一致'});
 }
}
if(monthlyProfiles.length!==(series.length*12))throw Error('月份矩阵缺行');
const overview=sheet('分析总览',[22,12,24,24,24,24,24,15]);
overview.tabColor='#18344B';
section(overview,5,'车型分组｜'+grouping.reason,7);
table(overview,6,['车型组','车型数','车型成员（代际）'],categories.map(c=>[c,[...modelMap.values()].filter(r=>r.category===c).length,[...modelMap.values()].filter(r=>r.category===c).map(r=>r.model).join('、')]));
overview.getRange('C6:H6').merge();
for(let i=0;i<categories.length;i++){
 const r=7+i;
 overview.getRange('C'+r+':H'+r).merge();
 overview.getRange('C'+r).format.wrapText=true;
 overview.getRange('A'+r+':H'+r).format.rowHeight=Math.min(400,Math.max(44,Math.ceil(String(overview.getRange('C'+r).values[0][0]).length/80)*20+12));
}
const groupNoteRow=8+categories.length, summaryRowStart=groupNoteRow+3;
note(overview,groupNoteRow,'类别及车型自动读取；不合并原始类别、不凑固定组数。分组维度可在report_config.json中指定。',7);
section(overview,summaryRowStart-1,'分组读数｜小订、大定、锁单独立；比例100%＝持平',7);
const overviewRows=[];
for(const {category,metric,stage} of series.filter(r=>r.category!=='全部车型')){
 const w=pick(d.weekly,category,metric,stage),m=monthlyProfiles.filter(r=>r.category===category&&r.metric===metric&&r.stage===stage);
 const pm=pick(monthRows,category,metric,stage).filter(r=>r.status==='有效');
 overviewRows.push([category,metric,stage,within(w,'ratio'),new Set(w.map(r=>r.week)).size,m.filter(r=>r.pairs>0).length,pm.length,pm.length?'见全年月份':'暂无相邻月']);
}
table(overview,summaryRowStart,['车型组','指标','阶段','周末/工作日日均','完整普通周数','可比月份/12','相邻月比较对数','月份结论'],overviewRows,{3:'0.0%'});
const overviewEnd=summaryRowStart+1+overviewRows.length;
note(overview,overviewEnd+1,'全年月份页：逐月看日均比、月度日均量及覆盖；月份证据页：看总量比、年份、跨年方向。',7);
note(overview,overviewEnd+2,'周末比例先车型内取中位数，再车型等权；空白＝无合格样本，0%才表示真实为零。',7);
note(overview,overviewEnd+3,'首销及小订受上市节奏影响；常年季节性应优先检验平销，并控制上市、促销和节假日。',7);
overview.freezePanes.freezeRows(6);
previews.push([overview,'A1:H'+(groupNoteRow+1),'首页分类'],[overview,'A'+(summaryRowStart-1)+':H'+Math.min(overviewEnd,summaryRowStart+25),'首页分组读数']);

const months=sheet('全年月份',[22,16,14,...Array(12).fill(12)]);
months.tabColor='#197A83';
note(months,5,'1月对比上年12月；每格按车型等权中位数。空白表示缺样本，不能用零替代。',14);
let mr=7;
for(const [field,title,format] of [
 ['daily','① 本月日均 / 上月日均｜排除自然月天数不同的影响','0.0%'],
 ['daymean','② 完整月日均量｜单车型日均的中位数，单位：单/天','#,##0.0'],
 ['pairs','③ 完整相邻月比较对数｜与①逐格对应','0']]){
 section(months,mr,title,14);
 const rows=[];
 for(const {category,metric,stage} of series){
  const p=monthlyProfiles.filter(r=>r.category===category&&r.metric===metric&&r.stage===stage);
  rows.push([category,metric,stage,...p.map(r=>r[field])]);
 }
 table(months,mr+1,['车型组','指标','阶段',...Array.from({length:12},(_,i)=>(i+1)+'月')],rows,Object.fromEntries(Array.from({length:12},(_,i)=>[i+3,format])));
 if(field==='daily')for(let i=0;i<rows.length;i++)for(let j=3;j<15;j++){
  const v=rows[i][j];if(v!==null)months.getRange(col(j)+(mr+2+i)).format.fill=v>1.02?'#DCEFE8':v<0.98?'#FBE7DD':'#EDF0F3';
 }
 previews.push([months,'A'+mr+':O'+Math.min(mr+1+rows.length,mr+26),'全年月份_'+field]);
 mr+=rows.length+4;
}
note(months,mr,'不同月份的车型构成可能不同，②不可直接据此排名淡旺季；季节性以同车型相邻月与分年复核为主。',14);
months.freezePanes.freezeRows(8);months.freezePanes.freezeColumns(3);
featureSheet('月份证据',
 ['车型组','指标','阶段','月份','单车型日均中位数','完整月车型数','完整车型月数','相邻月车型数','相邻月比较对数','不同年月数','年份数','总量占上月','日均占上月','上升占比','分年日均比','证据判断'],
 monthlyProfiles.map(r=>[r.category,r.metric,r.stage,r.month,r.daymean,r.models,r.complete,r.pairmodels,r.pairs,r.periods,r.years,r.ratio,r.daily,r.above,r.yearly,r.conclusion]),
 [22,16,14,9,20,16,16,16,18,16,12,17,17,15,48,38],{4:'#,##0.0',11:'0.0%',12:'0.0%',13:'0.0%'},
 '每个组×指标×阶段均保留1—12月。先车型内中位数，再车型等权；比较对限定同车型/阶段/批次/来源。');
function details(name,widths,headers,rows,formats,method,range){
 const s=sheet(name,widths);note(s,5,method,widths.length-1);table(s,7,headers,rows,formats,true);
 if(rows.length)s.getRange(col(widths.length-1)+'8:'+col(widths.length-1)+(7+rows.length)).format.wrapText=true;
 for(let i=0;i<rows.length;i++)if(String(rows[i].at(-1)).length>30)s.getRange('A'+(8+i)+':'+col(widths.length-1)+(8+i)).format.rowHeight=42;
 s.freezePanes.freezeRows(7);previews.push([s,range,name]);return s;
}
details('周内明细',[29,15,14,15,15,10,10,10,10,10,10,10,14,55],
 ['车型','指标','阶段','批次','周一日期','周一','周二','周三','周四','周五','周六','周日','周末倍率','数据来源'],
 d.weekly.map(r=>[r.model,r.metric,r.stage,r.cycle,new Date(r.week+'T00:00:00Z'),...r.indexes,r.ratio,r.source]),
 {4:'yyyy-mm-dd',...Object.fromEntries(Array.from({length:7},(_,i)=>[i+5,'0.0'])),12:'0.000"倍"'},
 '同车型/阶段/批次/来源的完整普通周；节假日与调休所在周排除。','A1:M15');
details('月内明细',[29,15,14,15,10,10,17,55],
 ['车型','指标','阶段','批次','年份','月份','月末7天倍率','数据来源'],
 d.monthly.map(r=>[r.model,r.metric,r.stage,r.cycle,r.year,r.month,r.ratio,r.source]),{6:'0.000"倍"'},
 '完整自然月；最后7天日均/其余日期日均。不补齐缺失日期。','A1:H15');
details('生命周期明细',[29,15,14,15,18,19,55],
 ['车型','指标','阶段','批次','首日相对D3—D7','前两天占首周','数据来源'],
 d.lifecycle.map(r=>[r.model,r.metric,r.stage,r.cycle,r.d1_ratio,r.first2_share,r.source]),{4:'0.000"倍"',5:'0.0%'},
 '要求D1—D7完整；小转大与直接大定分别分析，避免混淆集中转化和新增需求。','A1:G15');
const methods=sheet('数据覆盖与方法',[20,18,14,16,16,17,17,18]);
table(methods,6,['指标','阶段','车型数','车型日数','不同日期数','开始日期','结束日期'],
d.coverage.map(r=>[r.metric,r.stage,r.models,r.observations,r.dates,new Date(r.start+'T00:00:00Z'),new Date(r.end+'T00:00:00Z')]),{5:'yyyy-mm-dd',6:'yyyy-mm-dd'});
const sourceRow=8+d.coverage.length;
section(methods,sourceRow,'数据来源与检查',7);
note(methods,sourceRow+1,'业务来源：鸿蒙智行销量数据汇总.xlsx / 小订及退订逐日、当前订单逐日',7);
note(methods,sourceRow+2,'结果模式：'+(payload.sample?'本地样例':'实际数据')+'；所有数值为本次分析快照，原业务工作簿未修改。',7);
note(methods,sourceRow+3,'SHA-256：'+payload.sha256,7);
const auditRow=sourceRow+5;
table(methods,auditRow,['检查项','记录数'],Object.entries(payload.audit));
methods.getRange('A1:A350').format.columnWidth=30;
const notes=[
 ['周','完整普通周；指数每日/该周日均×100；先车型内平均再车型等权。'],
 ['月','完整自然月；月末最后7天与其余日期日均比较，未调整星期与节日。'],
 ['年','同车型同来源至少两个完整平销年份；年款不自动合并，避免混入产品变化。'],
 ['节假日','平销节前7天、节中、节后7天均须完整；同星期匹配前后对照。'],
 ['节日对照','取节前8—35天及节后8—35天；每目标日至少4个对照且前后都有。'],
 ['生命周期','同批次同来源D1—D7完整；首日倍率与前两天占首周分别计算。'],
 ['缺失与来源','缺失不补零；预测/合成/模拟/缺失来源排除；小订要求真实逐日标记。'],
 ['统计边界','当前未做回归、置信区间或时间留出验证；结果不是因果系数或预测参数。'],
 ['内网验证','日期范围随输入扩展；分车型分年份复核，并控制上市及权益活动。'],
 ['指标边界','锁单不能替代交付销量；累计退订不当日退订；不以当日大定/小订代造转化率。'],
 ['日历','已配置年份：'+(payload.calendar_years||[]).join('、')+'；未配置年份不判断普通周与节日，需补充日历。'],
 ['首页分类',grouping.reason],
 ['分类候选',grouping.candidates.map(r=>r.label+'：'+r.count+'类，覆盖'+(r.coverage*100).toFixed(1)+'%').join('；')],
 ['更新','重新运行分析脚本，再执行本导出脚本；Excel中的快照不会自行读取源文件。']
];
const methodRow=auditRow+Object.keys(payload.audit).length+3;
section(methods,methodRow,'分析方法与适用边界',7);
for(let i=0;i<notes.length;i++){methods.getRange('A'+(methodRow+2+i)).values=[[notes[i][0]]];methods.getRange('B'+(methodRow+2+i)).values=[[notes[i][1]]];methods.getRange('A'+(methodRow+2+i)+':H'+(methodRow+2+i)).format.rowHeight=27;}
previews.push([methods,'A1:H'+(sourceRow+3),'覆盖']);

// Extended analysis: metrics and sales stages remain separate in every grouping.
function featureSheet(name,headers,rows,widths,formats,method){
 const s=sheet(name,widths);
 note(s,5,method,widths.length-1);
 const last=col(headers.length-1),end=7+Math.max(1,rows.length);
 s.getRange('A7:'+last+'7').values=[headers];
 s.getRange('A7:'+last+'7').format={fill:'#24455F',font:{name:'Microsoft YaHei',size:10,bold:true,color:'#FFFFFF'},rowHeight:38,wrapText:true,horizontalAlignment:'center'};
 if(rows.length){
  s.getRange('A8:'+last+(7+rows.length)).values=rows;
  s.getRange('A8:'+last+(7+rows.length)).format.font={name:'Microsoft YaHei',size:10,color:'#243447'};
  s.getRange('A8:'+last+(7+rows.length)).format.rowHeight=27;
  for(const [i,f] of Object.entries(formats))s.getRange(col(+i)+'8:'+col(+i)+(7+rows.length)).setNumberFormat(f);
  const t=s.tables.add('A7:'+last+(7+rows.length),true,'Extended'+wb.worksheets.items.length);
  t.showFilterButton=true;
 } else {s.getRange('A8').values=[['当前没有满足条件的可比样本。']];}
 s.freezePanes.freezeRows(7);s.freezePanes.freezeColumns(2);
 previews.push([s,'A1:'+col(Math.min(headers.length-1,10))+'14',name]);
 if(headers.length>11)previews.push([s,'L7:'+last+'14',name+'_数值']);
 return s;
}
const sortedSummaries=[...d.period_summary].sort((a,b)=>{
 const rank=(x,list)=>{const i=list.indexOf(x);return i<0?99:i};
 return rank(a.metric,['小订数量','大定','交车锁单','留存大定','小转大','直接大定'])-rank(b.metric,['小订数量','大定','交车锁单','留存大定','小转大','直接大定'])
 ||rank(a.stage,['平销','首销','小订阶段'])-rank(b.stage,['平销','首销','小订阶段'])
 ||rank(a.kind,['周','月','季','年','日'])-rank(b.kind,['周','月','季','年','日'])
 ||rank(a.dimension,['整体','品牌','产品档位','能源类型'])-rank(b.dimension,['整体','品牌','产品档位','能源类型'])
 ||((parseInt(a.transition)||0)-(parseInt(b.transition)||0))
 ||a.category.localeCompare(b.category,'zh-CN');
});
const summaryHeaders=['环节','指标','销售阶段','周期','周期转换','分类维度','类别','车型数','比较对数','不同周期','年份数','总量比中位数','日均比中位数','周期P25','周期P75','高于100%占比','分年日均比','证据说明'];
const summaryRow=r=>[r.role,r.metric,r.stage,r.kind,r.transition,r.dimension,r.category,r.models,r.pairs,r.periods,r.years,r.ratio,r.daily_ratio,r.p25,r.p75,r.above100,r.yearly,r.evidence+'；'+r.status];
const sw=[10,15,13,9,16,14,25,10,12,12,10,17,17,14,14,19,45,48];
const sf={11:'0.0%',12:'0.0%',13:'0.0%',14:'0.0%',15:'0.0%'};
featureSheet('下订周期规律',summaryHeaders,sortedSummaries.filter(r=>r.role!=='锁单').map(summaryRow),sw,sf,
 '小订、大定各指标分别统计；100%＝持平，120%＝增长20%。车型内取中位数，再车型等权取中位数。');
featureSheet('锁单周期规律',summaryHeaders,sortedSummaries.filter(r=>r.role==='锁单').map(summaryRow),sw,sf,
 '按实际锁单日期独立分析；不与小订/大定加总，不将锁单统一提前3天。滞后另页核验。');
featureSheet('周期比例明细',
 ['车型','品牌','产品档位','能源类型','环节','指标','销售阶段','周期','周期转换','本期开始','本期结束','前期开始','前期结束','本期观测合计','前期观测合计','本期天数','本期有效日','前期天数','前期有效日','本期占前期','日均占前期','假期调休日','状态','数据来源'],
 d.period_comparisons.map(r=>[r.model,r.brand,r.segment,r.energy,r.role,r.metric,r.stage,r.kind,r.transition,new Date(r.start+'T00:00:00Z'),new Date(r.end+'T00:00:00Z'),new Date(r.previous_start+'T00:00:00Z'),new Date(r.previous_end+'T00:00:00Z'),r.current,r.previous,r.current_days,r.current_observed,r.previous_days,r.previous_observed,r.ratio,r.daily_ratio,r.holiday_adjusted_days,r.status,r.source]),
 [30,12,22,18,10,15,13,9,16,16,16,16,16,19,19,12,13,12,13,17,17,14,28,55],
 {9:'yyyy-mm-dd',10:'yyyy-mm-dd',11:'yyyy-mm-dd',12:'yyyy-mm-dd',13:'#,##0',14:'#,##0',19:'0.0%',20:'0.0%'},
 '分母仅取紧邻前一自然周期；缺日、缺前期或前期为零时比例留空。两期观测合计不完整时不代表周期总量。');
featureSheet('锁单滞后',
 ['车型','销售阶段','周期批次','大定指标','品牌','产品档位','能源类型','滞后天数','共同日期数','对齐开始','对齐结束','数量相关系数','日变动相关系数','变动对数','解释','大定来源','锁单来源'],
 d.lock_lags.map(r=>[r.model,r.stage,r.cycle,r.metric,r.brand,r.segment,r.energy,r.lag,r.pairs,r.start?new Date(r.start+'T00:00:00Z'):null,r.end?new Date(r.end+'T00:00:00Z'):null,r.level_corr,r.change_corr,r.change_pairs,r.status,r.deposit_source,r.lock_source]),
 [30,13,16,15,12,22,18,13,15,16,16,18,20,13,48,35,55],
 {9:'yyyy-mm-dd',10:'yyyy-mm-dd',11:'0.000',12:'0.000'},
 '比较大定(t)与锁单(t+0/1/2/3)。四个滞后共用同一批日期；至少14对才计算。非逐单锁单时长或转化率。');
featureSheet('车型分组',
 ['车型代际','首页车型组','品牌','产品档位','能源类型','销售阶段','可用指标'],
 d.model_classes.map(r=>[r.model,modelMap.get(r.model).category,r.brand,r.segment,r.energy,r.stages,r.metrics]),
 [32,22,14,26,22,28,60],{},
 '仅使用同一汇总文件的车型基本信息。增程/纯电作为混合组；映射冲突保留提示，不强行归类。');
const auditEnd=auditRow+Object.keys(payload.audit).length;
methods.getRange('A'+(auditEnd+1)).values=[['扩展指标见新增工作表；业务输入增加同文件“车型基本信息”，未读取其他业务文件。']];
const extraRow=methodRow+notes.length+4;
section(methods,extraRow,'新增周期与滞后口径',7);
const extraNotes=[
 '周期：日、周、月、季、年，分母必须是紧邻前一周期，不跨缺失周期跳算。',
 '总量比：本期总量/前期总量；日均比：(本期总量/天数)/(前期总量/天数)。',
 '分类统计：先取每车型有效比较的中位数，再对车型中位数取中位数。',
 'P25/P75：先对每个日历周期取车型间日均比中位数，再统计时间序列四分位数；不是置信区间。',
 '高于100%占比：先每车型统计上升周期占比，再车型等权平均，不是预测概率。',
 '完整相邻月即可参与1—12月比较，不要求同车型有完整两年；跨年证据单独报告。',
 '假期调休日：前期和本期放假/调休日期的并集天数；周期环比尚未剔除这些影响。',
 '滞后：大定日t与锁单日t+k匹配；k取0—3，四组使用完全相同的大定日期。',
 '数量相关易受首销共同趋势影响；同时给日变动相关。只作诊断，不选最大值作为真实锁单时长。',
 '前期零/负、任何一期缺日均不输出比例；真实本期零保留为0%。',
 '源字段有增程/纯电时保持混合类；属性映射冲突保持独立，不拆分订单数量。',
 '至少8个不同周期仅为样本量提示，不构成统计显著或规律成立；跨年还需控制活动与趋势。'
];
for(let i=0;i<extraNotes.length;i++){note(methods,extraRow+2+i,extraNotes[i],7);}

previews.push([methods,'A'+methodRow+':H'+(methodRow+notes.length+1),'方法']);


const periodRow=extraRow+extraNotes.length+4;
section(methods,periodRow,'各周期覆盖：无有效比较也保留提示',7);
const coverageMap=new Map();
for(const r of d.period_comparisons){
 const key=JSON.stringify([r.role,r.metric,r.stage,r.kind]);
 if(!coverageMap.has(key))coverageMap.set(key,{keys:JSON.parse(key),valid:0,current:0,previous:0,denominator:0});
 const x=coverageMap.get(key);
 if(r.status==='有效')x.valid++;else if(r.status==='本期不完整')x.current++;else if(r.status==='前期缺失或不完整')x.previous++;else x.denominator++;
}
const cr=[...coverageMap.values()].map(x=>[...x.keys,x.valid,x.current,x.previous,x.denominator]);
table(methods,periodRow+2,['环节','指标','阶段','周期','有效比较','本期不完整','前期不完整','前期零/负'],cr);
previews.push([methods,'A'+periodRow+':H'+(periodRow+15),'周期覆盖']);

wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'分析总览!A'+summaryRowStart+':H'+(summaryRowStart+7),tableMaxRows:8,tableMaxCols:13,maxChars:1800})).ndjson);
const errors=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!',options:{useRegex:true,maxResults:20},maxChars:500});
console.log(errors.ndjson);
const out=await SpreadsheetFile.exportXlsx(wb);
await fs.mkdir(outputDir,{recursive:true});
await fs.mkdir(previewDir,{recursive:true});
await out.save(path.join(previewDir,'workbook.xlsx'));
await fs.copyFile(path.join(previewDir,'workbook.xlsx'),path.join(outputDir,'鸿蒙智行销量规律分析.xlsx'));
await fs.mkdir(previewDir,{recursive:true});
for(const [s,range,name] of previews.filter(x=>['首页分类','首页分组读数','全年月份_daily','全年月份_daymean','全年月份_pairs','月份证据','月份证据_数值','车型分组','覆盖','方法'].includes(x[2]))){
 const blob=await wb.render({sheetName:s.name,range,scale:1,format:'png'});
 await fs.writeFile(path.join(previewDir,name+'.png'),new Uint8Array(await blob.arrayBuffer()));
}
if(cleanupDefaultEvidence){
 await fs.rm(evidencePath,{force:true});
 await fs.rm(path.join(path.dirname(evidencePath),'分析报告.md'),{force:true});
 try{await fs.rmdir(path.dirname(evidencePath));}catch(error){if(!['ENOENT','ENOTEMPTY'].includes(error.code))throw error;}
}
console.log(JSON.stringify({output:path.join(outputDir,'鸿蒙智行销量规律分析.xlsx'),grouping:grouping.reason,groups:categories.length,monthlyRows:monthlyProfiles.length,sheets:wb.worksheets.items.map(s=>s.name)}));



