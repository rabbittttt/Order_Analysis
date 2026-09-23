// No vehicle names or category values belong in these rules.
const dimensions=[['segment','产品档位'],['brand','品牌'],['energy','能源类型']];
const text=x=>x==null?'':String(x).trim();
const usable=x=>!!text(x)&&!['未提供','映射冲突'].includes(text(x));
export function chooseGrouping(models,config={}){
 const {groupBy='auto',minGroups=3,maxGroups=8}=config;
 if(!Number.isInteger(minGroups)||!Number.isInteger(maxGroups)||minGroups<1||maxGroups<minGroups)throw Error('分组数量范围无效');
 if(groupBy!=='auto'&&!dimensions.some(([k])=>k===groupBy))throw Error('groupBy须为auto、segment、brand或energy');
 const candidates=dimensions.map(([key,label],priority)=>{
  const valid=models.filter(r=>usable(r[key]));
  const count=new Set(valid.map(r=>text(r[key]))).size;
  return {key,label,priority,count,coverage:models.length?valid.length/models.length:0,fit:count>=minGroups&&count<=maxGroups};
 });
 // Prefer sufficiently complete dimensions; never manufacture categories to meet a target.
 const complete=candidates.filter(r=>r.coverage>=0.8&&r.count>1);
 const pool=complete.length?complete:candidates;
 const selected=groupBy==='auto'?[...pool].sort((a,b)=>Number(b.fit)-Number(a.fit)||b.coverage-a.coverage||a.priority-b.priority)[0]:candidates.find(r=>r.key===groupBy);
 const entries=models.map(r=>{
  const value=text(r[selected.key])||'未提供';
  return {...r,category:selected.label+'：'+value};
 });
 const categories=[...new Set(entries.map(r=>r.category))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
 return {entries,categories,dimension:selected.key,label:selected.label,candidates,
  reason:(groupBy==='auto'?'自动选择':'配置指定')+' '+selected.label+'；有效属性覆盖 '+(selected.coverage*100).toFixed(1)+'%；原始类别 '+selected.count+' 个；缺失/冲突独立展示'};
}
export function reportSeries(comparisons,categories,modelMap){
 const main=new Set(['小订数量','大定','交车锁单']);
 const hasMain=comparisons.some(r=>main.has(r.metric));
 const result=[];
 for(const category of ['全部车型',...categories]){
  const seen=new Set();
  for(const r of comparisons){
   if(hasMain&&!main.has(r.metric))continue;
   if(category!=='全部车型'&&modelMap.get(r.model)?.category!==category)continue;
   const key=JSON.stringify([r.metric,r.stage]);
   if(!seen.has(key)){seen.add(key);result.push({category,metric:r.metric,stage:r.stage});}
  }
 }
 return result;
}
