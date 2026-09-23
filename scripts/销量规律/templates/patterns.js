(() => {
"use strict";
const data = window.PATTERNS_DATA || JSON.parse(document.getElementById("patterns-data").textContent);
const rows = Array.isArray(data.series) ? data.series : [];
const result = data.results || {};
const meta = data.meta || {};
const metrics = Array.isArray(data.metrics) ? data.metrics : [];
const entries = (data.grouping && data.grouping.entries) || [];
const entryByModel = new Map(entries.map(x => [String(x.model), x]));
const metricByKey = new Map(metrics.map(x => [x.key, x]));
const allCategories = (data.grouping && data.grouping.categories) || [];
const rules = Array.isArray(data.rules) ? data.rules : [];
const profiles = (data.forecast && data.forecast.profiles) || [];
const backtests = (data.forecast && data.forecast.backtests) || [];
const events = meta.calendar_events || [];
const PAGE_SIZE = 100;
const cache = new Map();
const numberFmt = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 1});
const integerFmt = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 0});
const pctFmt = new Intl.NumberFormat("zh-CN", {style:"percent", maximumFractionDigits:1});
const state = {
  page:"overview", pattern:"months", evidence:"daily", metric:"",
  category:"__ALL__", model:"__ALL__", stage:"",
  start:"", end:"", grain:"月", compare:false, search:"", pageNo:0,
  forecastModel:"", forecastGrain:"月", profileKey:""
};
const $ = id => document.getElementById(id);
const el = (tag, cls, text, parent) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  if (parent) parent.appendChild(n);
  return n;
};
const clear = n => { if (n) n.replaceChildren(); };
const dateOnly = v => v == null ? "" : String(v).slice(0, 10);
const num = v => typeof v === "number" && Number.isFinite(v) ? v : null;
const fmtNum = v => num(v) === null ? "—" : numberFmt.format(v);
const fmtInt = v => num(v) === null ? "—" : integerFmt.format(v);
const fmtPct = v => num(v) === null ? "—" : pctFmt.format(v);
const median = values => {
  const a = values.filter(v => num(v) !== null).sort((x,y) => x-y);
  if (!a.length) return null;
  const m = Math.floor(a.length / 2);
  return a.length % 2 ? a[m] : (a[m-1] + a[m]) / 2;
};
const quantile = (values, p) => {
  const a = values.filter(v => num(v) !== null).sort((x,y) => x-y);
  if (!a.length) return null;
  const k = (a.length - 1) * p, lo = Math.floor(k), hi = Math.min(lo+1, a.length-1);
  return a[lo] + (a[hi]-a[lo]) * (k-lo);
};
const unique = values => [...new Set(values.filter(v => v !== undefined && v !== null && String(v) !== ""))];
const safeArray = v => Array.isArray(v) ? v.map(String) : v == null ? [] : String(v).split(/[、,，;；]/).map(x => x.trim()).filter(Boolean);
const metricName = key => (metricByKey.get(key) || {}).label || (key === "交车锁单" ? "锁单" : "净大定");
const metricSource = key => (metricByKey.get(key) || {}).source_label || key;
const categoryOf = model => {
  const x = entryByModel.get(String(model));
  return x && x.category ? String(x.category) : "未提供分类";
};
const isoAdd = (s, days) => {
  const d = dateOnly(s);
  if (!d) return "";
  const p = d.split("-").map(Number);
  const x = new Date(Date.UTC(p[0], p[1]-1, p[2] + days));
  return x.toISOString().slice(0,10);
};
const monthDays = (y,m) => new Date(Date.UTC(Number(y), Number(m), 0)).getUTCDate();
const isoWeekStart = d => {
  const wd = new Date(Date.UTC(Number(d.slice(0,4)), Number(d.slice(5,7))-1, Number(d.slice(8,10)))).getUTCDay();
  return isoAdd(d, -(wd === 0 ? 6 : wd-1));
};
const yearBounds = y => [String(y)+"-01-01", String(y)+"-12-31"];
const dateRangeDays = (a,b) => {
  if (!a || !b) return 0;
  return Math.max(0, Math.floor((Date.parse(b+"T00:00:00Z")-Date.parse(a+"T00:00:00Z"))/86400000)+1);
};
function setOptions(select, options, selected) {
  clear(select);
  for (const item of options) {
    const o = el("option", "", item.label, select);
    o.value = String(item.value);
  }
  if (options.some(x => String(x.value) === String(selected))) select.value = String(selected);
  else if (options.length) select.value = String(options[0].value);
}
function makeTable(container, headers, bodyRows, emptyText) {
  clear(container);
  const wrap = el("table", "data-table", null, container);
  const thead = el("thead", "", null, wrap), trh = el("tr", "", null, thead);
  headers.forEach(h => el("th", "", h, trh));
  const tbody = el("tbody", "", null, wrap);
  if (!bodyRows.length) {
    const tr = el("tr", "", null, tbody), td = el("td", "table-empty", emptyText || "当前筛选没有可展示的合格样本。", tr);
    td.colSpan = headers.length;
    return;
  }
  for (const sourceRow of bodyRows) {
    const tr = el("tr", "", null, tbody);
    sourceRow.forEach((v, i) => {
      const cls = v && typeof v === "object" && "text" in v ? (v.cls || "") : "";
      const value = v && typeof v === "object" && "text" in v ? v.text : v;
      const td = el("td", cls, value == null ? "—" : value, tr);
      if (cls.includes("number")) td.title = String(value == null ? "" : value);
    });
  }
}
function emptyBox(container, title, detail) {
  clear(container);
  const box = el("div", "empty-state", null, container);
  el("strong", "", title, box);
  el("span", "", detail || "", box);
}
function optionRows(metric) {
  return rows.filter(r => r.metric === metric);
}
const metricBounds = new Map(metrics.map(m => {
  const dates = optionRows(m.key).map(r => dateOnly(r.date)).filter(Boolean).sort();
  return [m.key, dates.length ? [dates[0], dates[dates.length-1]] : ["",""]];
}));
const defaultMetric = metrics.find(m => m.key === "留存大定" && m.available) ||
                      metrics.find(m => m.available) || metrics.find(m => m.key === "留存大定") ||
                      metrics[0] || {key:"留存大定"};
state.metric = defaultMetric.key;
function scopeEntries(metric) {
  return entries.filter(x => safeArray(x.metrics).includes(metric) || optionRows(metric).some(r => String(r.model) === String(x.model)));
}
function matchingRows(baseRows, metric, useDate) {
  const from = state.start, to = state.end;
  return baseRows.filter(r => {
    if (r.metric !== metric || r.stage !== state.stage) return false;
    const model = String(r.model || "");
    if (state.model !== "__ALL__" && model !== state.model) return false;
    if (state.model === "__ALL__" && state.category !== "__ALL__" && categoryOf(model) !== state.category) return false;
    if (useDate) {
      const d = dateOnly(r.date);
      if (d && ((from && d < from) || (to && d > to))) return false;
    }
    return true;
  });
}
function currentSeries(metric) {
  const key = [metric,state.category,state.model,state.stage,state.start,state.end].join("|");
  if (!cache.has("s:"+key)) cache.set("s:"+key, matchingRows(rows,metric,true));
  return cache.get("s:"+key);
}
function resultBase(name, metric) {
  const key = "r:"+name+"|"+metric+"|"+state.category+"|"+state.model+"|"+state.stage;
  if (!cache.has(key)) cache.set(key, matchingRows(result[name] || [], metric, false));
  return cache.get(key);
}
function setMetricSwitch() {
  document.querySelectorAll("[data-metric]").forEach(btn => {
    const m = metricByKey.get(btn.dataset.metric);
    const available = Boolean(m && m.available);
    btn.disabled = !available;
    btn.classList.toggle("is-selected", btn.dataset.metric === state.metric);
    btn.setAttribute("aria-pressed", btn.dataset.metric === state.metric ? "true" : "false");
    btn.title = available ? metricSource(btn.dataset.metric) : "原始数据未提供该指标";
  });
  $("metricSourceLabel").textContent = metricName(state.metric) + " · 源字段 " + metricSource(state.metric);
}
function updateFilters(resetDate) {
  const eligible = scopeEntries(state.metric);
  const categories = unique(eligible.map(x => x.category).filter(Boolean)).sort((a,b)=>a.localeCompare(b,"zh-CN"));
  const categoryOptions = [{value:"__ALL__",label:"全部分类"}].concat(categories.map(x=>({value:x,label:x})));
  if (!categoryOptions.some(o=>o.value===state.category)) state.category="__ALL__";
  setOptions($("categoryFilter"),categoryOptions,state.category);

  let models = eligible;
  if (state.category !== "__ALL__") models = models.filter(x=>String(x.category)===state.category);
  const modelOptions = [{value:"__ALL__",label:"全部车型"}].concat(unique(models.map(x=>String(x.model))).sort((a,b)=>a.localeCompare(b,"zh-CN")).map(x=>({value:x,label:x})));
  if (!modelOptions.some(o=>o.value===state.model)) state.model="__ALL__";
  setOptions($("modelFilter"),modelOptions,state.model);

  let candidates = optionRows(state.metric).filter(r => {
    const model = String(r.model || "");
    if (state.model !== "__ALL__" && model !== state.model) return false;
    if (state.model === "__ALL__" && state.category !== "__ALL__" && categoryOf(model) !== state.category) return false;
    return true;
  });
  const stages = unique(candidates.map(r=>String(r.stage || "")).filter(Boolean)).sort((a,b)=>a.localeCompare(b,"zh-CN"));
  const stagePref = stages.includes(state.stage) ? state.stage : stages.includes("平销") ? "平销" : stages.includes("首销") ? "首销" : stages[0] || "";
  state.stage = stagePref;
  setOptions($("stageFilter"),stages.map(x=>({value:x,label:x})),stagePref);

  const bounds = metricBounds.get(state.metric) || ["",""];
  if (resetDate || !state.start || !state.end) {
    state.start = bounds[0]; state.end = bounds[1];
  } else {
    if (bounds[0] && state.start < bounds[0]) state.start=bounds[0];
    if (bounds[1] && state.end > bounds[1]) state.end=bounds[1];
    if (bounds[0] && state.end < bounds[0]) {state.start=bounds[0];state.end=bounds[1];}
    if (state.start > state.end) {state.start=bounds[0];state.end=bounds[1];}
  }
  $("dateStart").min = bounds[0]; $("dateStart").max = bounds[1];
  $("dateEnd").min = bounds[0]; $("dateEnd").max = bounds[1];
  $("dateStart").value = state.start; $("dateEnd").value = state.end;
  setMetricSwitch();
}
function inScope(row, metric) {
  if (row.metric !== metric || row.stage !== state.stage) return false;
  const model=String(row.model||"");
  if (state.model!=="__ALL__" && model!==state.model) return false;
  if (state.model==="__ALL__" && state.category!=="__ALL__" && categoryOf(model)!==state.category) return false;
  return true;
}
function fullComparedPeriod(row, kind) {
  const s=dateOnly(row.start), e=dateOnly(row.end), ps=dateOnly(row.previous_start), pe=dateOnly(row.previous_end);
  if (!s || !e || !ps || !pe || !state.start || !state.end) return false;
  if (ps < state.start || pe > state.end || s < state.start || e > state.end) return false;
  if (kind==="周") return e===isoAdd(s,6) && ps===isoAdd(s,-7) && pe===isoAdd(ps,6);
  if (kind==="月") {
    const [y,m]=s.split("-").map(Number), prev=new Date(Date.UTC(y,m-2,1)).toISOString().slice(0,10);
    return s===y+"-"+String(m).padStart(2,"0")+"-01" && e===y+"-"+String(m).padStart(2,"0")+"-"+String(monthDays(y,m)).padStart(2,"0") &&
           ps===prev && pe===isoAdd(s,-1);
  }
  if (kind==="年") {
    const y=Number(s.slice(0,4));
    return s===String(y)+"-01-01" && e===String(y)+"-12-31" && ps===String(y-1)+"-01-01" && pe===String(y-1)+"-12-31";
  }
  return true;
}
function comparisons(kind, metric) {
  return resultBase("period_comparisons",metric).filter(r =>
    r.kind===kind && r.status==="有效" &&
    !(Number(r.current_negative_days||0)>0 || Number(r.previous_negative_days||0)>0) &&
    num(r.daily_ratio)!==null && fullComparedPeriod(r,kind)
  );
}
function summary(rowsIn, field) {
  const byModel=new Map(),byPeriod=new Map();
  const periodKey=r=>{
    let p=dateOnly(r.start)||dateOnly(r.week);
    if(!p&&r.period!=null)p=String(r.period);
    if(!p&&r.cycle!=null)p=String(r.cycle);
    if(!p&&r.year!=null){
      if(r.month!=null)p=String(r.year)+"-"+String(r.month).padStart(2,"0");
      else if(r.holiday)p=String(r.year)+"|"+String(r.holiday);
      else p=String(r.year);
    }
    return p||"__all__";
  };
  let samples=0;
  for(const r of rowsIn){
    const value=num(r[field]);if(value===null)continue;
    const model=String(r.model||"");
    if(!byModel.has(model))byModel.set(model,[]);
    byModel.get(model).push(value);
    const p=periodKey(r);
    if(!byPeriod.has(p))byPeriod.set(p,new Map());
    const models=byPeriod.get(p);
    if(!models.has(model))models.set(model,[]);
    models.get(model).push(value);
    samples++;
  }
  const modelMedians=[...byModel.values()].map(median).filter(v=>v!==null);
  const periodMedians=[...byPeriod.values()].map(models=>median([...models.values()].map(median))).filter(v=>v!==null);
  return {typical:median(modelMedians),p25:quantile(periodMedians,.25),p75:quantile(periodMedians,.75),
          models:byModel.size,periods:byPeriod.size,samples};
}
function rangeCompleteRows(name,metric,kind) {
  const base=resultBase(name,metric);
  if (name==="weekly") return base.filter(r=>{
    const s=dateOnly(r.week), e=isoAdd(s,6);
    return s && s>=state.start && e<=state.end && Array.isArray(r.indexes) && r.indexes.length===7;
  });
  if (name==="monthly") return base.filter(r=>{
    const y=Number(r.year),m=Number(r.month),s=String(y)+"-"+String(m).padStart(2,"0")+"-01",e=String(y)+"-"+String(m).padStart(2,"0")+"-"+String(monthDays(y,m)).padStart(2,"0");
    return s>=state.start && e<=state.end;
  });
  if (name==="annual") return base.filter(r=>{
    const y=Number(r.year),[s,e]=yearBounds(y);
    return s>=state.start && e<=state.end && Array.isArray(r.indexes) && r.indexes.length===12 && r.status==="有效";
  });
  if (name==="lifecycle") return base.filter(r=>{
    const cyc=dateOnly(r.cycle), last=isoAdd(cyc,6);
    return cyc && cyc>=state.start && last<=state.end;
  });
  return base;
}
function currentEvents() {
  return events.filter(e=>{
    const s=isoAdd(e.start,-7),z=isoAdd(e.end,7);
    return s>=state.start && z<=state.end;
  });
}
function holidayRows(metric) {
  const valid=new Set(currentEvents().map(e=>String(e.year)+"|"+String(e.holiday)));
  return resultBase("holidays",metric).filter(r=>valid.has(String(r.year)+"|"+String(r.holiday)));
}
function activeComparisons(kind,metric) { return comparisons(kind,metric); }
function addKpi(grid,label,value,foot) {
  const card=el("article","kpi-card",null,grid),top=el("div","kpi-top",null,card);
  el("span","",label,top);el("i","kpi-bullet","",top);
  el("strong","kpi-value",value,card);el("small","kpi-foot",foot||"",card);
}
function sEl(tag,attrs,text) {
  const n=document.createElementNS("http://www.w3.org/2000/svg",tag);
  Object.keys(attrs||{}).forEach(k=>n.setAttribute(k,String(attrs[k])));
  if(text!==undefined)n.textContent=String(text);
  return n;
}
function chartEmpty(container,message) { clear(container);el("div","chart-empty",message,container); }
function makeTrendPoints(series, grain) {
  const buckets=new Map();
  for(const r of series){
    const d=dateOnly(r.date);if(!d)continue;
    let key=d;
    if(grain==="周")key=isoWeekStart(d);
    if(grain==="月")key=d.slice(0,7);
    if(grain==="年")key=d.slice(0,4);
    if(!buckets.has(key))buckets.set(key,{key,value:0,dates:new Set(),models:new Set(),negative:0});
    const b=buckets.get(key),v=num(r.value);
    if(v===null)continue;
    b.value+=v;b.dates.add(d);b.models.add(String(r.model));
    if(v<0)b.negative++;
  }
  return [...buckets.values()].sort((a,b)=>a.key.localeCompare(b.key)).map(b=>{
    let expected=1;
    if(grain==="周")expected=7;
    else if(grain==="月"){const p=b.key.split("-").map(Number);expected=monthDays(p[0],p[1]);}
    else if(grain==="年")expected=new Date(Date.UTC(Number(b.key)+1,0,0)).getUTCDate();
    return {...b,observed:b.dates.size,expected};
  });
}
function renderLine(container,points,title,color,grain) {
  clear(container);el("div","chart-box-title",title,container);
  if(!points.length){chartEmpty(container,"当前车型、阶段和日期范围内没有观测。");return;}
  const w=850,h=235,left=58,right=18,top=12,bottom=43,pw=w-left-right,ph=h-top-bottom;
  const svg=sEl("svg",{viewBox:"0 0 "+w+" "+h,class:"chart-svg",role:"img","aria-label":title+"趋势图"});
  const values=points.map(p=>p.value),lo=Math.min(0,...values),hi=Math.max(0,...values);
  const span=(hi-lo)||1,pad=span*.08,min=lo<0?lo-pad:0,max=hi+pad;
  const y=v=>top+(max-v)/(max-min)*ph;
  for(let i=0;i<=4;i++){
    const val=max-(max-min)*i/4,yy=top+ph*i/4;
    svg.appendChild(sEl("line",{x1:left,y1:yy,x2:w-right,y2:yy,class:"chart-gridline"}));
    svg.appendChild(sEl("text",{x:left-8,y:yy+3,"text-anchor":"end",class:"chart-label"},integerFmt.format(val)));
  }
  svg.appendChild(sEl("line",{x1:left,y1:top+ph,x2:w-right,y2:top+ph,class:"chart-axis"}));
  const x=i=>points.length===1?left+pw/2:left+i*pw/(points.length-1);
  const d=points.map((p,i)=>(i?"L":"M")+x(i).toFixed(1)+" "+y(p.value).toFixed(1)).join(" ");
  const line=sEl("path",{d,class:"chart-series"});line.style.stroke=color;svg.appendChild(line);
  if(points.length<=32)points.forEach((p,i)=>svg.appendChild(sEl("circle",{cx:x(i),cy:y(p.value),r:3.3,class:"chart-point",stroke:color})));
  const ticks=points.length<=8?points.map((_,i)=>i):[0,Math.round((points.length-1)/3),Math.round((points.length-1)*2/3),points.length-1];
  unique(ticks).forEach(i=>{
    const p=points[i],label=String(p.key).length>7?String(p.key).slice(0,7):String(p.key);
    svg.appendChild(sEl("text",{x:x(i),y:h-16,"text-anchor":"middle",class:"chart-label"},label));
  });
  container.appendChild(svg);
  const coverage=points.map(p=>p.observed+"/"+p.expected).filter(x=>x!=="1/1");
  const caption=el("div","chart-caption","");caption.textContent="观测周期 "+points.length+" 个；每点合计所选车型在该口径、阶段下的观测值。未观测日期不补零。"+(coverage.length?" 周/月/年内有效日期覆盖可能不完整。":"");
}
function chartTrend(series,grain){
  const pts=makeTrendPoints(series,grain);
  return pts;
}
function renderTrend(){
  const primary=currentSeries(state.metric),other=state.compare?currentSeries(state.metric==="留存大定"?"交车锁单":"留存大定"):[];
  const grid=$("trendCharts");clear(grid);
  grid.classList.toggle("is-comparison",state.compare);
  const legend=$("trendLegend");clear(legend);
  const colorPrimary="#2563eb",colorOther="#0f766e";
  const a=el("span","legend-item",null,legend);el("i","legend-swatch","",a).style.background=colorPrimary;el("span","",metricName(state.metric)+"（"+metricSource(state.metric)+"）",a);
  if(state.compare){const key=state.metric==="留存大定"?"交车锁单":"留存大定";const b=el("span","legend-item",null,legend);el("i","legend-swatch","",b).style.background=colorOther;el("span","",metricName(key)+"（"+metricSource(key)+"）",b);}
  const one=el("div","chart-box","",grid);renderLine(one,chartTrend(primary,state.grain),metricName(state.metric)+" · "+state.stage,colorPrimary,state.grain);
  if(state.compare){const key=state.metric==="留存大定"?"交车锁单":"留存大定";const two=el("div","chart-box","",grid);renderLine(two,chartTrend(other,state.grain),metricName(key)+" · 同阶段 "+state.stage,colorOther,state.grain);}
  $("trendCaption").textContent="两个口径若同时对照，会分别使用各自纵轴，数值不会相加。分类汇总会受到不同日期车型覆盖变化影响。";
}
function groupedStats(rowsIn,field,keyFn,periodFn){
  const groups=new Map();
  for(const r of rowsIn){
    const key=keyFn(r),value=num(r[field]);if(value===null)continue;
    if(!groups.has(key))groups.set(key,[]);
    groups.get(key).push(r);
  }
  return [...groups].map(([key,items])=>{
    const samples=items.map(r=>{
      const x={model:r.model,start:r.start,week:r.week,year:r.year,month:r.month,holiday:r.holiday,period:r.period,cycle:r.cycle};
      if(periodFn)x.start=periodFn(r);
      x[field]=r[field];
      return x;
    });
    const stats=summary(samples,field);
    return {key,median:stats.typical,p25:stats.p25,p75:stats.p75,n:stats.samples,models:stats.models,periods:stats.periods};
  }).sort((a,b)=>{
    const ma=String(a.key).match(/^(\d+)月$/),mb=String(b.key).match(/^(\d+)月$/);
    if(ma&&mb)return Number(ma[1])-Number(mb[1]);
    return String(a.key).localeCompare(String(b.key),"zh-CN");
  });
}
function renderRatio(){
  const rowsC=comparisons(state.grain,state.metric),stats=summary(rowsC,"daily_ratio");
  $("ratioSubtitle").textContent=state.grain+"周期日均倍率；只保留上期和本期完整落在所选日期窗内的有效比较。";
  const box=$("ratioSummary");clear(box);
  [["P25",stats.p25,"周期中较低的一侧"],["中位数",stats.typical,"车型等权后典型值"],["P75",stats.p75,"周期中较高的一侧"]].forEach(x=>{
    const item=el("div","ratio-item",null,box);el("span","",x[0],item);el("strong","",fmtPct(x[1]),item);el("small","",x[2],item);
  });
  $("ratioDescription").textContent=stats.samples?stats.periods+" 个完整周期、"+stats.models+" 个车型、"+stats.samples+" 条车型周期记录。日均倍率便于比较不同长度周期；样本分布不能当作预测置信区间。":
    "没有满足口径与完整窗口要求的周期比较。可扩大日期范围，或检查该车型阶段是否覆盖完整的相邻周期。";
}
function drawBars(container,items,labelKey,valueKey,formatValue,kind){
  clear(container);
  const usable=items.filter(x=>num(x[valueKey])!==null);
  if(!usable.length){el("div","chart-empty","没有满足条件的可用样本。",container);return;}
  if(kind==="horizontal"){
    const max=Math.max(1,...usable.map(x=>Math.abs(x[valueKey])));
    usable.forEach(x=>{
      const row=el("div","bar-row",null,container);el("span","bar-label",x[labelKey],row);
      const track=el("div","bar-track","",row),fill=el("div","bar-fill","",track);fill.style.width=(Math.max(1,Math.abs(x[valueKey])/max*100))+"%";
      el("strong","bar-value",formatValue(x[valueKey]),row);
    });
    return;
  }
  const w=760,h=210,left=34,right=8,top=12,bottom=42,pw=w-left-right,ph=h-top-bottom,max=Math.max(1,...usable.map(x=>x[valueKey]));
  const svg=sEl("svg",{viewBox:"0 0 "+w+" "+h,role:"img","aria-label":"规律对比柱状图"});
  for(let i=0;i<=3;i++){const yy=top+ph*i/3;svg.appendChild(sEl("line",{x1:left,y1:yy,x2:w-right,y2:yy,class:"chart-gridline"}));}
  const step=pw/usable.length,bw=Math.min(36,step*.62);
  usable.forEach((x,i)=>{
    const bh=Math.max(1,x[valueKey]/max*ph),bx=left+i*step+(step-bw)/2,by=top+ph-bh;
    const rect=sEl("rect",{x:bx,y:by,width:bw,height:bh,rx:3,class:i%2?"chart-bar is-teal":"chart-bar"});
    const title=sEl("title",{},String(x[labelKey])+": "+formatValue(x[valueKey])+(x.n?" · n="+x.n:""));rect.appendChild(title);svg.appendChild(rect);
    svg.appendChild(sEl("text",{x:bx+bw/2,y:h-17,"text-anchor":"middle",class:"chart-label"},String(x[labelKey])));
  });
  container.appendChild(svg);
}
function card(container,title,subtitle){
  const c=el("section","pattern-card",null,container);el("h3","",title,c);if(subtitle)el("p","",subtitle,c);return c;
}
function miniKpis(container,items){
  clear(container);items.forEach(x=>{const c=el("div","kpi-card",null,container),t=el("div","kpi-top","",c);el("span","",x.label,t);el("i","kpi-bullet","",t);el("strong","kpi-value",x.value,c);el("small","kpi-foot",x.foot||"",c);});
}
function monthSeasonRows(metric){
  const annual=state.stage==="平销"?rangeCompleteRows("annual",metric):[];
  const buckets=Array.from({length:12},()=>[]);
  annual.forEach(r=>r.indexes.forEach((v,i)=>{
    if(num(v)!==null)buckets[i].push({model:String(r.model),year:Number(r.year),start:String(r.year)+"-"+String(i+1).padStart(2,"0")+"-01",value:v});
  }));
  return buckets.map((items,i)=>{
    const stats=summary(items,"value");
    return {month:(i+1)+"月",monthNo:i+1,median:stats.typical,p25:stats.p25,p75:stats.p75,
      models:stats.models,years:stats.periods,n:stats.samples};
  });
}
function lifecycleRows(metric){
  return rangeCompleteRows("lifecycle",metric).filter(r=>num(r.d1_ratio)!==null&&num(r.first2_share)!==null);
}
function weeklyStats(metric){
  const valid=rangeCompleteRows("weekly",metric);
  const labels=["周一","周二","周三","周四","周五","周六","周日"];
  const weekday=labels.map((label,i)=>{
    const samples=valid.map(r=>({model:r.model,start:r.week,value:num(r.indexes[i])})).filter(r=>r.value!==null);
    const stats=summary(samples,"value");
    return {label,value:stats.typical,p25:stats.p25,p75:stats.p75,n:stats.samples,models:stats.models,periods:stats.periods};
  });
  return {valid,weekday};
}
function monthEndRows(metric){
  return rangeCompleteRows("monthly",metric).filter(r=>num(r.ratio)!==null);
}
function holidayPhaseRows(metric){
  const groups=new Map();
  for(const r of holidayRows(metric)){
    const key=String(r.year)+"|"+String(r.holiday)+"|"+String(r.model);
    if(!groups.has(key))groups.set(key,{year:r.year,holiday:r.holiday,model:r.model,rows:[]});
    groups.get(key).rows.push(r);
  }
  return [...groups.values()].map(g=>({
    event:String(g.year)+"年"+String(g.holiday),period:String(g.year)+"|"+String(g.holiday),
    holiday:g.holiday,year:g.year,model:g.model,
    before:median(g.rows.map(r=>num(r.before)).filter(v=>v!==null)),
    during:median(g.rows.map(r=>num(r.during)).filter(v=>v!==null)),
    after:median(g.rows.map(r=>num(r.after)).filter(v=>v!==null)),
    control_days:median(g.rows.map(r=>num(r.control_days)).filter(v=>v!==null)),
    n:g.rows.length
  }));
}
function renderPatternTabs(){
  document.querySelectorAll("[data-pattern]").forEach(b=>{b.classList.toggle("is-active",b.dataset.pattern===state.pattern);b.setAttribute("aria-selected",b.dataset.pattern===state.pattern?"true":"false");});
  const container=$("patternPanels");clear(container);
  const metric=state.metric;
  const intro=$("patternIntro");
  if(state.pattern==="months"){
    intro.textContent="月份规律拆成三个问题：完整年度的12月季节性、相邻自然月日均变化、月内末7天相对前段。只有完整年度参与季节指数；首销与平销按当前阶段单独筛选。";
    const annual=monthSeasonRows(metric),mcomp=comparisons("月",metric),monthStats=groupedStats(mcomp,"daily_ratio",r=>Number(dateOnly(r.start).slice(5,7))+"月"),me=monthEndRows(metric),life=lifecycleRows(metric);
    miniKpis($("patternKpis"),[
      {label:"完整年度季节性样本",value:fmtInt(unique(rangeCompleteRows("annual",metric).map(r=>r.year)).length),foot:"完整年度，不含部分年度"},
      {label:"相邻完整月比较",value:fmtInt(mcomp.length),foot:"车型周期记录"},
      {label:"月内末7天样本",value:fmtInt(me.length),foot:"完整自然月"},
      {label:"生命周期批次",value:fmtInt(life.length),foot:"当前阶段且批次起始日落窗"}
    ]);
    const dual=el("div","pattern-dual","",container);
    let c=card(dual,"完整年度12月季节性指数","全年月均 = 100；只使用完整年度记录，不用环比替代季节性。");
    let chart=el("div","pattern-chart","",c);drawBars(chart,annual.filter(x=>x.median!==null),"month","median",v=>fmtNum(v), "vertical");
    let annualTable=el("div","table-wrap","",c);makeTable(annualTable,["月份","P25 指数","中位指数","P75 指数","车型数","年度数","车型年度记录数"],annual.filter(x=>x.n>0).map(x=>[x.month,fmtNum(x.p25),fmtNum(x.median),fmtNum(x.p75),fmtInt(x.models),fmtInt(x.years),fmtInt(x.n)]),"暂无完整年度季节性样本；需要车型、阶段和指标均覆盖完整自然年。");
    c=card(dual,"相邻月日均变化","本月日均 / 上月日均；只纳入两个自然月都完整落在日期范围内的比较。");
    chart=el("div","pattern-chart","",c);drawBars(chart,monthStats.filter(x=>x.median!==null),"key","median",fmtPct,"vertical");
    let monthTable=el("div","table-wrap","",c);makeTable(monthTable,["当前月份","P25","日均倍率中位数","P75","车型周期记录数","车型数"],monthStats.map(x=>[x.key,fmtPct(x.p25),fmtPct(x.median),fmtPct(x.p75),fmtInt(x.n),fmtInt(unique(mcomp.filter(r=>(Number(dateOnly(r.start).slice(5,7))+"月")===x.key).map(r=>r.model)).length)]),"日期窗内没有完整的相邻自然月比较。");
    c=card(container,"月内末7天与前段日均","来自完整月证据；倍率 >100% 表示月末7天日均较高。");
    let endTable=el("div","table-wrap","",c);makeTable(endTable,["车型","年份","月份","月末 / 前段日均","状态","来源批次"],me.map(r=>[r.model,r.year,String(r.month)+"月",fmtPct(r.ratio),r.status,r.source+" · "+r.cycle]),"当前阶段没有满足完整自然月的月末证据。");
    c=card(container,"首销生命周期","D1 相对 D3–D7 日均；前2天占首7天量比。批次必须是同一车型、来源与阶段。");
    let lifeTable=el("div","table-wrap","",c);makeTable(lifeTable,["车型","批次","D1 / D3–D7 日均","首2天占首7天","阶段","样本来源"],life.map(r=>[r.model,r.cycle,fmtPct(r.d1_ratio),fmtPct(r.first2_share),r.stage,r.source]),"当前阶段与日期窗内没有完整 D1–D7 生命周期记录。");
  }else if(state.pattern==="week"){
    intro.textContent="按同车型、同指标、同阶段、同周期/来源的完整自然周读取周一至周日指数；周末比较使用周六、周日对工作日日均。月末只纳入完整自然月。";
    const w=weeklyStats(metric),ends=monthEndRows(metric),wkSummary=summary(w.valid.map(r=>({...r,start:r.week})),"ratio");
    const wkRatio=wkSummary.typical;
    miniKpis($("patternKpis"),[
      {label:"完整自然周",value:fmtInt(w.valid.length),foot:"车型周期样本"},
      {label:"周末 / 工作日日均",value:fmtPct(wkRatio),foot:fmtInt(wkSummary.samples)+"条车型周记录 · "+fmtInt(wkSummary.periods)+"周"},
      {label:"月末样本",value:fmtInt(ends.length),foot:"完整自然月"},
      {label:"适用阶段",value:state.stage,foot:"阶段分开，不做跨阶段混合"}
    ]);
    const dual=el("div","pattern-dual","",container);
    let c=card(dual,"周一至周日指数","整周日均 = 100；中位数按车型/完整周样本计算。");
    let chart=el("div","pattern-chart","",c);drawBars(chart,w.weekday.filter(x=>x.value!==null),"label","value",v=>fmtNum(v),"vertical");
    const tbl=el("div","table-wrap","",c);makeTable(tbl,["星期","P25 指数","中位指数","P75 指数","车型周记录数"],w.weekday.map(x=>[x.label,fmtNum(x.p25),fmtNum(x.value),fmtNum(x.p75),fmtInt(x.n)]),"所选日期窗没有完整周。");
    c=card(dual,"月内末7天变化","末7天日均 / 前段日均，按月展示。");
    const mStats=groupedStats(ends,"ratio",r=>String(r.month)+"月");
    chart=el("div","pattern-chart","",c);drawBars(chart,mStats.filter(x=>x.median!==null),"key","median",fmtPct,"vertical");
    const endTbl=el("div","table-wrap","",c);makeTable(endTbl,["月份","P25","倍率中位数","P75","车型月记录数"],mStats.map(x=>[x.key,fmtPct(x.p25),fmtPct(x.median),fmtPct(x.p75),fmtInt(x.n)]),"暂无完整月份。");
    c=card(container,"首销生命周期补充","生命周期规律按完整首7日批次计算，不并入平销。");
    const lif=lifecycleRows(metric);const lt=el("div","table-wrap","",c);makeTable(lt,["车型","首销批次","D1 / D3–D7 日均","首2天占首7天","有效批次数"],lif.map(r=>[r.model,r.cycle,fmtPct(r.d1_ratio),fmtPct(r.first2_share),fmtInt(lif.length)]),"该阶段没有完整生命周期样本。");
  }else if(state.pattern==="holiday"){
    intro.textContent="节假日只提供历史解释：与同星期节前/节后对照计算，不视为可直接外推的预测系数。当前日期窗需覆盖节前7日至节后7日；主分析限定平销阶段。";
    const hs=holidayPhaseRows(metric);
    miniKpis($("patternKpis"),[
      {label:"完整节假日记录",value:fmtInt(holidayRows(metric).length),foot:"同阶段车型周期"},
      {label:"节日事件",value:fmtInt(unique(hs.map(r=>r.event)).length),foot:"日期窗口完整落入筛选"},
      {label:"控制日期",value:fmtInt(summary(holidayRows(metric),"control_days").typical),foot:"中位控制日期数"},
      {label:"适用阶段",value:"平销",foot:state.stage==="平销"?"当前选择为平销":"当前阶段无节日对照"}
    ]);
    const c=card(container,"节前、节中、节后日均指数","100% 为匹配星期的控制日水平；只显示有效的历史对照。");
    if(state.stage!=="平销")el("div","pattern-intro","节假日对照仅基于平销数据。当前筛选阶段为 "+state.stage+"，不会用其他阶段填补。",c);
    const chart=el("div","pattern-chart","",c);
    const pRows=[];
    [["before","节前"],["during","节中"],["after","节后"]].forEach(([phase,label])=>groupedStats(hs,phase,r=>r.holiday,r=>r.period).forEach(x=>pRows.push({label:x.key+label,value:x.median,n:x.periods})));
    drawBars(chart,pRows.filter(x=>num(x.value)!==null),"label","value",fmtPct,"vertical");
    const table=el("div","table-wrap","",c);makeTable(table,["节日","年份","车型","节前日均","节中日均","节后日均","控制日期数","车型批次/来源记录"],hs.map(r=>[r.holiday,r.year,r.model,fmtPct(r.before),fmtPct(r.during),fmtPct(r.after),fmtInt(r.control_days),fmtInt(r.n)]),"当前日期窗没有完整节假日对照；需覆盖节日前后各7日，且该年份节假日日历可用。");
    const detail=card(container,"节假日原始对照明细","逐条保留车型、阶段、批次和来源，可追溯上方车型等权汇总。");
    const detailTable=el("div","table-wrap","",detail);
    makeTable(detailTable,["节日","年份","车型","阶段","批次 / 周期","来源","节前日均指数","节中日均指数","节后日均指数","控制日期数"],holidayRows(metric).map(r=>[r.holiday,r.year,r.model,r.stage,r.cycle,r.source,fmtPct(r.before),fmtPct(r.during),fmtPct(r.after),fmtInt(r.control_days)]),"当前筛选没有完整的节假日原始对照记录。");
  }else{
    intro.textContent="周期变化率以当前周期与紧邻前一完整周期比较。百分比中位数按车型等权；P25/P75描述历史周期波动，不能直接解释为预测区间。";
    const kinds=["日","周","月","年"];
    const summaries=kinds.map(k=>({kind:k,rows:comparisons(k,metric),stats:summary(comparisons(k,metric),"daily_ratio")}));
    miniKpis($("patternKpis"),summaries.map(x=>({label:x.kind+"周期典型日均倍率",value:fmtPct(x.stats.typical),foot:fmtInt(x.stats.periods)+"个周期 · "+fmtInt(x.stats.models)+"车型"})));
    const c=card(container,"按比较类型查看 P25 / 中位数 / P75","完整窗口条件：前一期与本期都须全部处于当前筛选日期内；倍率按日均标准化。");
    const table=el("div","table-wrap","",c);makeTable(table,["比较周期","P25","车型等权中位数","P75","车型数","完整日历周期","车型周期记录"],summaries.map(x=>[x.kind,fmtPct(x.stats.p25),fmtPct(x.stats.typical),fmtPct(x.stats.p75),fmtInt(x.stats.models),fmtInt(x.stats.periods),fmtInt(x.stats.samples)]),"没有符合日期范围要求的相邻周期。");
    const trans=groupedStats(comparisons(state.grain,metric),"daily_ratio",r=>r.transition||"前期→本期");
    const c2=card(container,"当前周期的变化分布","当前趋势周期："+state.grain+"；显示实际样本可辨识的转换类别。");
    const bars=el("div","pattern-chart","",c2);drawBars(bars,trans.filter(x=>x.median!==null),"key","median",fmtPct,"vertical");
    const t2=el("div","table-wrap","",c2);makeTable(t2,["周期转换","P25","日均倍率中位数","P75","有效记录数"],trans.map(x=>[x.key,fmtPct(x.p25),fmtPct(x.median),fmtPct(x.p75),fmtInt(x.n)]),"没有足够的完整周期比较。");
  }
}
function renderSignals(){
  const c=$("overviewSignals");clear(c);
  const kinds=comparisons(state.grain,state.metric),s=summary(kinds,"daily_ratio");
  let cardEl=el("article","signal-card",null,c);
  el("div","signal-card-title",state.grain+"日均变化倍率",cardEl);
  el("strong","signal-value",fmtPct(s.typical),cardEl);
  el("div","signal-detail","P25 "+fmtPct(s.p25)+" · P75 "+fmtPct(s.p75)+" · "+s.periods+"完整周期",cardEl);
  const months=monthSeasonRows(state.metric).filter(x=>x.median!==null).sort((a,b)=>b.median-a.median);
  cardEl=el("article","signal-card",null,c);el("div","signal-card-title","全年月份季节性",cardEl);
  el("strong","signal-value",months.length?months[0].month+" · "+fmtNum(months[0].median):"暂无",cardEl);
  el("div","signal-detail",months.length?"相对完整年度月均为100；样本 "+months[0].n:"缺少覆盖完整自然年的平销样本",cardEl);
  const wk=weeklyStats(state.metric),wkSummary=summary(wk.valid.map(r=>({...r,start:r.week})),"ratio");
  cardEl=el("article","signal-card",null,c);el("div","signal-card-title","周末 / 工作日日均",cardEl);
  el("strong","signal-value",fmtPct(wkSummary.typical),cardEl);
  el("div","signal-detail","来自每个完整周结果中的周末日均/工作日均ratio；"+wkSummary.samples+"条车型周记录、"+wkSummary.periods+"周",cardEl);
  const life=lifecycleRows(state.metric),lifeSummary=summary(life.map(r=>({...r,start:r.cycle})),"first2_share");
  cardEl=el("article","signal-card",null,c);el("div","signal-card-title","首销首2天占比",cardEl);
  el("strong","signal-value",fmtPct(lifeSummary.typical),cardEl);
  el("div","signal-detail","完整D1–D7车型批次记录 "+lifeSummary.samples+" 条；当前阶段 "+state.stage,cardEl);
  const end=monthEndRows(state.metric),endSummary=summary(end,"ratio");
  cardEl=el("article","signal-card",null,c);el("div","signal-card-title","月末7天 / 月内前段",cardEl);
  el("strong","signal-value",fmtPct(endSummary.typical),cardEl);
  el("div","signal-detail","完整自然月车型周期记录 "+endSummary.samples+" 条；覆盖 "+endSummary.periods+" 个自然月",cardEl);
  const h=holidayPhaseRows(state.metric),holidaySummary=summary(h,"during");
  cardEl=el("article","signal-card",null,c);el("div","signal-card-title","节中 / 平常星期对照",cardEl);
  el("strong","signal-value",fmtPct(holidaySummary.typical),cardEl);
  el("div","signal-detail",state.stage==="平销"?"完整节日车型事件 "+holidaySummary.samples+" 条；覆盖 "+holidaySummary.periods+"个事件":"仅平销有节日样本；当前为"+state.stage,cardEl);
}
function renderModelCompare(){
  const container=$("modelCompare");clear(container);
  const s=currentSeries(state.metric);
  const agg=new Map();
  for(const r of s){const k=state.category==="__ALL__"&&state.model==="__ALL__"?categoryOf(r.model):String(r.model);
    agg.set(k,(agg.get(k)||0)+(num(r.value)||0));}
  const arr=[...agg].map(([label,value])=>({label,value})).sort((a,b)=>b.value-a.value).slice(0,12);
  $("groupCompareTitle").textContent=state.category==="__ALL__"&&state.model==="__ALL__"?"车型分类观测对比":"所选车型观测量";
  drawBars(container,arr,"label","value",fmtNum,"horizontal");
}
function renderCoverage(){
  const c=$("overviewCoverage");clear(c);
  const s=currentSeries(state.metric),dates=unique(s.map(r=>dateOnly(r.date))),models=unique(s.map(r=>r.model)),sources=unique(s.map(r=>r.source)),cycles=unique(s.map(r=>r.cycle));
  const facts=[
    ["来源工作簿",meta.source_name||"未提供"],
    ["指标源口径",metricSource(state.metric)],
    ["源数据日期",dateOnly(meta.date_start)+" 至 "+dateOnly(meta.date_end)],
    ["筛选后记录",fmtInt(s.length)],
    ["来源数",fmtInt(sources.length)],
    ["批次/周期数",fmtInt(cycles.length)],
    ["分类依据",(data.grouping&&data.grouping.reason)||"来自源工作簿车型属性"]
  ];
  facts.forEach(x=>{const span=el("span","coverage-item",null,c);el("strong","",x[0]+"：",span);el("span","",x[1],span);});
  const notes=(meta.notes||[]).slice(0,3);
  notes.forEach(n=>{const span=el("span","coverage-item",null,c);el("strong","","方法提示：",span);el("span","",n,span);});
}
function renderKpis(){
  const c=$("overviewKpis");clear(c);
  const s=currentSeries(state.metric),total=s.reduce((a,r)=>a+(num(r.value)||0),0);
  const dates=unique(s.map(r=>dateOnly(r.date))),models=unique(s.map(r=>r.model));
  const days=dateRangeDays(state.start,state.end),sum=summary(comparisons(state.grain,state.metric),"daily_ratio");
  addKpi(c,"筛选内观测量",fmtNum(total),"保留源数据正负值；按当前单一阶段合计");
  addKpi(c,"车型覆盖",fmtInt(models.length),state.category==="__ALL__"?"当前动态车型分组":"分类："+state.category);
  addKpi(c,"有观测日期",fmtInt(dates.length)+" / "+fmtInt(days),"观察日期，不推断缺失日为零");
  addKpi(c,"完整"+state.grain+"比较周期",fmtInt(sum.periods),sum.models+"个车型 · "+sum.samples+"条车型周期样本");
}
function renderRangeNotice(){
  const s=currentSeries(state.metric),models=unique(s.map(r=>r.model)),dts=unique(s.map(r=>dateOnly(r.date)));
  const node=$("rangeNotice");
  node.classList.toggle("is-warning",!s.length);
  node.textContent=metricName(state.metric)+"（源："+metricSource(state.metric)+"） · "+state.stage+" · "+(state.category==="__ALL__"?"全部分类":state.category)+" · "+(state.model==="__ALL__"?"全部车型":state.model)+" · "+state.start+" 至 "+state.end+" · "+models.length+"车型 / "+s.length+"条日观测"+(!s.length?"；该范围没有可用观测。":"");
}
function renderOverview(){
  renderRangeNotice();renderKpis();renderTrend();renderRatio();renderModelCompare();renderSignals();renderCoverage();
}
function renderPatterns(){
  renderPatternTabs();
}
function forecastEligibleModels(){
  const base=optionRows(state.metric).filter(r=>r.stage===state.stage).map(r=>String(r.model));
  return unique(base).sort((a,b)=>a.localeCompare(b,"zh-CN"));
}
function profileId(p){return [p.model,p.metric,p.stage,p.cycle,p.source,p.grain,p.cutoff||p.as_of,p.target_start,p.target_end].join("|");}
function fillForecastControls(){
  const candidates=forecastEligibleModels();
  if(!candidates.includes(state.forecastModel))state.forecastModel=candidates.includes(state.model)?state.model:(candidates[0]||"");
  setOptions($("forecastModel"),candidates.map(x=>({value:x,label:x})),state.forecastModel);
  const list=profiles.filter(p=>String(p.model)===state.forecastModel&&p.metric===state.metric&&p.stage===state.stage&&p.grain===state.forecastGrain);
  const opts=list.map(p=>({value:profileId(p),label:(p.cycle||"未分批")+" · "+(p.source||"未标来源")+" · "+(dateOnly(p.target_start)||"待定")+"～"+(dateOnly(p.target_end)||"待定")+" · 截止 "+(dateOnly(p.cutoff||p.as_of)||"未知")}));
  state.profileKey=opts.some(x=>x.value===state.profileKey)?state.profileKey:(opts[0]?opts[0].value:"");
  setOptions($("forecastProfile"),opts,state.profileKey);
  return list.find(p=>profileId(p)===state.profileKey)||null;
}
function profileStatus(status){
  return ({ok:"可用",insufficient_history:"历史训练样本不足",insufficient_backtest:"回测样本不足",no_complete_target_period:"目标周期尚未完整"}[status]||status||"未提供状态");
}
function scoreBacktests(profile) {
  if (!profile) return {windowRows:[], scored:[], samples:0, wape:null, baselineWape:null, bias:null, improvement:null, denominator:0, note:""};
  const sameSeries = backtests.filter(r =>
    String(r.model)===String(profile.model) && r.metric===profile.metric &&
    r.stage===profile.stage && r.grain===profile.grain &&
    r.cycle===profile.cycle && r.source===profile.source
  );
  const completeTarget = r => {
    const start=dateOnly(r.target_start), end=dateOnly(r.target_end);
    if (!start || !end || start>end) return false;
    if (profile.grain==="日") return start===end;
    if (profile.grain==="周") return isoWeekStart(start)===start && isoAdd(start,6)===end;
    if (profile.grain==="月") {
      const y=Number(start.slice(0,4)),m=Number(start.slice(5,7));
      return start===String(y)+"-"+String(m).padStart(2,"0")+"-01" &&
        end===String(y)+"-"+String(m).padStart(2,"0")+"-"+String(monthDays(y,m)).padStart(2,"0");
    }
    return true;
  };
  const windowRows=sameSeries.filter(r => {
    const start=dateOnly(r.target_start), end=dateOnly(r.target_end);
    return completeTarget(r) && start>=state.start && end<=state.end;
  });
  const scored=windowRows.filter(r =>
    r.status==="ok" && num(r.actual)!==null && num(r.predicted)!==null && num(r.baseline)!==null
  );
  const denominator=scored.reduce((sum,r)=>sum+Math.abs(r.actual),0);
  const modelError=scored.reduce((sum,r)=>sum+Math.abs(r.predicted-r.actual),0);
  const baselineError=scored.reduce((sum,r)=>sum+Math.abs(r.baseline-r.actual),0);
  const signedError=scored.reduce((sum,r)=>sum+(r.predicted-r.actual),0);
  const wape=denominator>0?modelError/denominator:null;
  const baselineWape=denominator>0?baselineError/denominator:null;
  const bias=denominator>0?signedError/denominator:null;
  const improvement=baselineWape>0?(baselineWape-wape)/baselineWape:null;
  let note="";
  if (!windowRows.length) note="所选日期范围内没有完整落窗的同序列回测目标期。";
  else if (!scored.length) note="完整目标期中没有同时满足 status=ok 且实际、规则预测、基准均为有限数值的评分样本。";
  else if (denominator===0) note="评分样本的实际绝对值之和为0，WAPE、偏差及相对改善率不可计算。";
  else if (baselineWape===0) note="所选窗口基准WAPE为0，相对改善率不可定义。";
  return {windowRows,scored,samples:scored.length,wape,baselineWape,bias,improvement,denominator,note};
}
function renderBacktest(profile, evaluation) {
  const chart=$("backtestChart"),table=$("backtestTableWrap");
  if(!profile){
    chartEmpty(chart,"没有与当前选择完全匹配的预测画像。");
    makeTable(table,["目标期","实际","规则预测","基准预测","状态"],[],"当前没有可展示的同口径回测样本。");
    return;
  }
  const scored=evaluation.scored;
  const displayRows=scored.slice(-24);
  if(!scored.length){
    chartEmpty(chart,"当前日期范围内没有可评分的完整回测窗口。");
  }else{
    clear(chart);
    const legend=el("div","backtest-legend","",chart);
    [["实际","var(--teal)"],["规则预测","var(--blue2)"],["基准预测","var(--amber)"]].forEach(x=>{
      const z=el("span","",null,legend),i=el("i","", "",z);i.style.background=x[1];el("span","",x[0],z);
    });
    const w=780,h=190,L=48,R=12,T=12,B=30,pw=w-L-R,ph=h-T-B;
    const vals=scored.flatMap(r=>[num(r.actual),num(r.predicted),num(r.baseline)]).filter(v=>v!==null);
    const max=Math.max(1,...vals),min=Math.min(0,...vals),svg=sEl("svg",{viewBox:"0 0 "+w+" "+h,class:"backtest-svg",role:"img","aria-label":"所选日期窗口内历史回测实际与预测"});
    for(let i=0;i<4;i++){const yy=T+ph*i/3;svg.appendChild(sEl("line",{x1:L,y1:yy,x2:w-R,y2:yy,class:"chart-gridline"}));}
    const x=i=>scored.length===1?L+pw/2:L+i*pw/(scored.length-1),y=v=>T+(max-v)/(max-min||1)*ph;
    [["actual","backtest-actual"],["predicted","backtest-pred"],["baseline","backtest-base"]].forEach(([key,cl])=>{
      const points=scored.map((r,i)=>[x(i),y(r[key])]);
      if(points.length)svg.appendChild(sEl("path",{d:points.map((p,i)=>(i?"L":"M")+p[0]+","+p[1]).join(" "),class:cl}));
    });
    scored.forEach((r,i)=>{
      if(i===0||i===scored.length-1||scored.length<=10){
        const d=dateOnly(r.target_start),label=profile.grain==="月"?d.slice(0,7):d;
        svg.appendChild(sEl("text",{x:x(i),y:h-8,"text-anchor":"middle",class:"chart-label"},label));
      }
    });
    chart.appendChild(svg);
  }
  makeTable(table,["目标期","起点","实际","规则预测","基准预测","训练样本","状态"],
    displayRows.slice().reverse().map(r=>[
      dateOnly(r.target_start)+"～"+dateOnly(r.target_end),dateOnly(r.origin),
      fmtNum(r.actual),fmtNum(r.predicted),fmtNum(r.baseline),fmtInt(r.train_samples),profileStatus(r.status)
    ]),
    "当前没有同车型、同口径、同阶段、同批次/来源和同周期的有效回测记录。");
  const shown=Math.min(24,scored.length);
  const info=el("div","table-meta","评分窗口 "+fmtInt(evaluation.windowRows.length)+" 条；有效评分样本 "+fmtInt(evaluation.samples)+" 条；图表与表格使用同一有效样本集，表格展示最新 "+fmtInt(shown)+" 条。",table);
  table.insertBefore(info,table.firstChild);
}
function renderForecast() {
  const profile=fillForecastControls();
  const evaluation=profile?scoreBacktests(profile):null;
  const kpis=$("forecastKpis");clear(kpis);
  const empty=$("forecastEmpty");empty.hidden=true;
  if(profile){
    const cutoff=dateOnly(profile.cutoff||profile.as_of||profile.last_observation);
    const latestOutside=Boolean(cutoff&&state.end&&cutoff>state.end);
    const target=latestOutside?"超出当前历史范围":dateOnly(profile.target_start)+"～"+dateOnly(profile.target_end);
    [
      ["目标周期",target],
      ["基准",latestOutside?"—":fmtNum(profile.baseline)],
      ["规则估计",latestOutside||profile.status==="no_complete_target_period"?"—":fmtNum(profile.estimate)],
      ["所选窗 WAPE / 基准",fmtPct(evaluation.wape)+" / "+fmtPct(evaluation.baselineWape)]
    ].forEach(x=>{const c=el("div","forecast-kpi",null,kpis);el("span","",x[0],c);el("strong","",x[1],c);});
    const note=$("forecastProfileNote");
    if(latestOutside){
      note.textContent="当前日期范围不含最新预测时点（"+cutoff+"），预测数值留空，以下仅显示所选历史回测。日期筛选控制历史展示和评分窗口；每个回测训练期仍可使用所选开始日期以前、且早于目标期的历史。"+(evaluation.note?" "+evaluation.note:"");
    }else{
      const imp=evaluation.improvement;
      note.textContent="状态："+profileStatus(profile.status)+" · "+(profile.method||"方法未提供")+
        " · 训练样本 "+fmtInt(profile.train_samples)+" · 所选窗口评分样本 "+fmtInt(evaluation.samples)+
        " · 窗口偏差 "+fmtPct(evaluation.bias)+
        (imp!==null?" · 相对基准WAPE改善 "+fmtPct(imp):"")+
        " · 日期筛选控制历史回测展示与评分；训练可使用开始日期以前、且早于各目标期的历史。"+
        (evaluation.note?" "+evaluation.note:"");
      if(profile.tail_note)note.textContent+=" "+profile.tail_note;
      if(profile.status==="no_complete_target_period")note.textContent+=" 当前截止点所在周期未完整，不将半周期冒称为下一个完整预测期。";
      if(profile.p25!==undefined||profile.p75!==undefined)note.textContent+=" 历史倍率P25～P75："+fmtPct(profile.p25)+"～"+fmtPct(profile.p75)+"，仅为历史波动。";
    }
  }else{
    ["目标周期","基准","规则估计","所选窗 WAPE / 基准"].forEach(x=>{const c=el("div","forecast-kpi",null,kpis);el("span","",x,c);el("strong","","—",c);});
    $("forecastProfileNote").textContent=state.forecastModel?"当前车型、口径、阶段与周期没有完全匹配的预测画像；不借用其他车型或阶段。":"该口径与阶段没有可用于回测的车型。";
    emptyBox(empty,"暂无可匹配的历史预测画像","可用右侧试算输入自己的可比日均或上期量，再选择一个倍率。");
    empty.hidden=false;
  }
  renderBacktest(profile,evaluation);
  updateTrial();
}
function updateTrial(){
  const mode=document.querySelector('input[name="trialMode"]:checked').value;
  const daysField=$("trialDaysField"),label=$("trialBaseLabel"),factorLabel=$("trialFactorLabel");
  if(mode==="daily"){daysField.hidden=false;label.textContent="参考日均（辆 / 日）";if(factorLabel)factorLabel.textContent="日均倍率";}
  else{daysField.hidden=true;label.textContent="上期总量（辆）";if(factorLabel)factorLabel.textContent="总量倍率";}
  const base=Number($("trialBase").value),factor=Number($("trialFactor").value),days=Number($("trialDays").value);
  const out=$("trialResult");clear(out);el("span","","单一倍率试算",out);
  if(!Number.isFinite(base)||base<0||!Number.isFinite(factor)||factor<0||(mode==="daily"&&(!Number.isFinite(days)||days<=0))){el("strong","","—",out);el("small","","请输入非负基准、倍率和有效天数。",out);return;}
  const total=mode==="daily"?base*factor*days:base*factor;
  el("strong","",fmtNum(total)+" 辆",out);
  el("small","",mode==="daily"?fmtNum(base)+" × "+fmtNum(factor)+" × "+fmtNum(days)+"天":"上期总量 "+fmtNum(base)+" × 总量倍率 "+fmtNum(factor),out);
}
function evidenceRows(){
  if(state.evidence==="daily")return currentSeries(state.metric);
  return (result.lock_lags||[]).filter(r=>r.metric==="留存大定"&&r.stage===state.stage&&
    (state.model==="__ALL__"||String(r.model)===state.model)&&
    (state.model!=="__ALL__"&&state.category!=="__ALL__"?true:state.category==="__ALL__"||categoryOf(r.model)===state.category)&&
    dateOnly(r.start)>=state.start&&dateOnly(r.end)<=state.end);
}
function searchEvidence(list){
  const q=state.search.trim().toLocaleLowerCase();if(!q)return list;
  return list.filter(r=>Object.values(r).some(v=>String(v==null?"":v).toLocaleLowerCase().includes(q))||categoryOf(r.model).toLocaleLowerCase().includes(q));
}
function renderEvidence(){
  const list=searchEvidence(evidenceRows());const wrap=$("evidenceTableWrap"),offset=state.pageNo*PAGE_SIZE,page=list.slice(offset,offset+PAGE_SIZE);
  $("evidenceMeta").textContent=state.evidence==="daily"?"净大定和锁单分别显示当前口径；表内保留原始阶段、批次、来源和负值。筛选命中 "+fmtInt(list.length)+" 条记录。":"净大定→交车锁单的0–3日共同日期相关性；不代表逐单转化率，也不作为锁单数量预测系数。筛选命中 "+fmtInt(list.length)+" 条记录。";
  if(state.evidence==="daily"){
    makeTable(wrap,["日期","车型","车型分类","指标口径","阶段","观测值","批次 / 周期","来源","生命周期"],
      page.map(r=>[{text:dateOnly(r.date)},{text:r.model},{text:categoryOf(r.model)},{text:metricName(r.metric)+" · "+metricSource(r.metric)},{text:r.stage},{text:fmtNum(r.value),cls:"number"+(num(r.value)<0?" negative":"")},{text:r.cycle},{text:r.source},{text:r.life==null?"—":"D"+r.life}]),
      "当前口径、车型、阶段和日期范围内没有逐日观测。");
  }else{
    makeTable(wrap,["车型","分类","阶段","大定来源","锁单来源","滞后日","共同日期数","日期范围","水平相关","日变化相关","说明"],
      page.map(r=>[{text:r.model},{text:categoryOf(r.model)},{text:r.stage},{text:r.deposit_source},{text:r.lock_source},{text:fmtInt(r.lag),cls:"number"},{text:fmtInt(r.pairs),cls:"number"},{text:dateOnly(r.start)+"～"+dateOnly(r.end)},{text:fmtNum(r.level_corr),cls:"number"},{text:fmtNum(r.change_corr),cls:"number"},{text:r.status}]),
      "当前选择没有满足完整日期范围的净大定与锁单配对样本。");
  }
  const pages=Math.max(1,Math.ceil(list.length/PAGE_SIZE));
  $("evidencePageInfo").textContent="第 "+(state.pageNo+1)+" / "+pages+" 页 · 共 "+fmtInt(list.length)+" 条";
  $("prevPage").disabled=state.pageNo<=0;$("nextPage").disabled=state.pageNo+1>=pages;
}
function csvEscape(v){
  let x=v==null?"":String(v);
  if(typeof v==="string"&&/^[\s\uFEFF]*[=+\-@\t\r]/.test(x))x="'"+x;
  return '"'+x.replace(/"/g,'""')+'"';
}
function exportCsv(){
  const list=searchEvidence(evidenceRows());let headers,items;
  if(state.evidence==="daily"){
    headers=["日期","车型","车型分类","指标源口径","阶段","观测值","批次周期","来源","生命周期"];
    items=list.map(r=>[dateOnly(r.date),r.model,categoryOf(r.model),metricSource(r.metric),r.stage,r.value,r.cycle,r.source,r.life==null?"":"D"+r.life]);
  }else{
    headers=["车型","车型分类","阶段","净大定来源","锁单来源","滞后日","共同日期数","开始日期","结束日期","水平相关","日变化相关","状态"];
    items=list.map(r=>[r.model,categoryOf(r.model),r.stage,r.deposit_source,r.lock_source,r.lag,r.pairs,dateOnly(r.start),dateOnly(r.end),r.level_corr,r.change_corr,r.status]);
  }
  const content="\uFEFF"+[headers,...items].map(row=>row.map(csvEscape).join(",")).join("\r\n");
  const blob=new Blob([content],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob),a=el("a");
  a.href=url;a.download="销量规律_"+metricName(state.metric)+"_"+state.stage+"_"+(state.evidence==="daily"?"逐日明细":"净大定锁单相关")+".csv";a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function updatePage(page){
  state.page=page;
  const info={
    overview:["销量规律概览","先确认口径与样本范围，再查看可用于预测的历史信号。"],
    patterns:["规律探索","用同口径、同阶段的完整周期，检验规律是否稳定。"],
    forecast:["预测试算与回测","先看同车型留出回测，再用单一倍率构造可复核情景。"],
    evidence:["证据明细","从汇总指标追溯到每日观测和净大定→锁单共同日期相关性。"]
  }[page];
  $("pageTitle").textContent=info[0];$("pageDescription").textContent=info[1];
  document.querySelectorAll("[data-panel]").forEach(b=>{const on=b.dataset.panel===page;b.classList.toggle("is-active",on);b.setAttribute("aria-selected",on?"true":"false");});
  document.querySelectorAll(".page-panel").forEach(p=>p.hidden=p.id!=="panel-"+page);
  if(page==="patterns")renderPatterns();if(page==="forecast")renderForecast();if(page==="evidence")renderEvidence();
}
function refresh(){
  cache.clear();
  renderOverview();
  if(state.page==="patterns")renderPatterns();
  if(state.page==="forecast")renderForecast();
  if(state.page==="evidence")renderEvidence();
}
function setExcelLink(){
  const link=$("excelLink"),topLink=$("excelTopLink");
  [link,topLink].forEach(a=>{if(a){a.href=meta.excel_name||"鸿蒙智行销量规律分析.xlsx";a.download=meta.excel_name||"";}});
  $("generatedAt").textContent=meta.generated_at?("生成于 "+String(meta.generated_at).replace("T"," ").slice(0,16)):"";
  $("sourceBadge").textContent="数据源 · "+(meta.source_name||"未提供");
  $("footerSource").textContent="源文件："+(meta.source_name||"未提供")+" · "+dateOnly(meta.date_start)+" 至 "+dateOnly(meta.date_end)+" · SHA-256 "+(meta.sha256||"未提供");
}
document.querySelectorAll("[data-panel]").forEach(b=>b.addEventListener("click",()=>updatePage(b.dataset.panel)));
document.querySelectorAll("[data-go]").forEach(b=>b.addEventListener("click",()=>updatePage(b.dataset.go)));
document.querySelectorAll("[data-metric]").forEach(b=>b.addEventListener("click",()=>{
  if(b.disabled||state.metric===b.dataset.metric)return;
  state.metric=b.dataset.metric;state.category="__ALL__";state.model="__ALL__";state.stage="";
  updateFilters(true);refresh();
}));
$("categoryFilter").addEventListener("change",e=>{state.category=e.target.value;state.model="__ALL__";state.stage="";updateFilters(false);refresh();});
$("modelFilter").addEventListener("change",e=>{state.model=e.target.value;state.stage="";updateFilters(false);refresh();});
$("stageFilter").addEventListener("change",e=>{state.stage=e.target.value;refresh();});
$("dateStart").addEventListener("change",e=>{state.start=e.target.value;if(state.start>state.end)state.end=state.start;$("dateEnd").value=state.end;refresh();});
$("dateEnd").addEventListener("change",e=>{state.end=e.target.value;if(state.end<state.start)state.start=state.end;$("dateStart").value=state.start;refresh();});
$("resetFilters").addEventListener("click",()=>{state.metric=defaultMetric.key;state.category="__ALL__";state.model="__ALL__";state.stage="";state.start="";state.end="";state.grain="月";state.compare=false;$("trendGrain").value="月";$("compareMetrics").checked=false;$("evidenceSearch").value="";state.search="";state.pageNo=0;updateFilters(true);refresh();});
$("trendGrain").addEventListener("change",e=>{state.grain=e.target.value;refresh();});
$("compareMetrics").addEventListener("change",e=>{state.compare=e.target.checked;refresh();});
document.querySelectorAll("[data-pattern]").forEach(b=>b.addEventListener("click",()=>{state.pattern=b.dataset.pattern;renderPatterns();}));
$("forecastModel").addEventListener("change",e=>{state.forecastModel=e.target.value;state.profileKey="";renderForecast();});
$("forecastGrain").addEventListener("change",e=>{state.forecastGrain=e.target.value;state.profileKey="";renderForecast();});
$("forecastProfile").addEventListener("change",e=>{state.profileKey=e.target.value;renderForecast();});
document.querySelectorAll('input[name="trialMode"]').forEach(x=>x.addEventListener("change",updateTrial));
["trialBase","trialDays","trialFactor"].forEach(id=>$(id).addEventListener("input",updateTrial));
document.querySelectorAll("[data-evidence]").forEach(b=>b.addEventListener("click",()=>{
  state.evidence=b.dataset.evidence;state.pageNo=0;
  document.querySelectorAll("[data-evidence]").forEach(x=>{const on=x===b;x.classList.toggle("is-active",on);x.setAttribute("aria-pressed",on?"true":"false");});
  renderEvidence();
}));
$("evidenceSearch").addEventListener("input",e=>{state.search=e.target.value;state.pageNo=0;renderEvidence();});
$("prevPage").addEventListener("click",()=>{state.pageNo=Math.max(0,state.pageNo-1);renderEvidence();});
$("nextPage").addEventListener("click",()=>{state.pageNo+=1;renderEvidence();});
$("exportCsv").addEventListener("click",exportCsv);
setExcelLink();updateFilters(true);
document.querySelectorAll("[data-metric]").forEach(b=>{if(b.dataset.metric==="交车锁单"&&!metrics.some(x=>x.key==="交车锁单"&&x.available))b.disabled=true;});
document.querySelectorAll("[data-pattern]").forEach(b=>{const on=b.dataset.pattern===state.pattern;b.classList.toggle("is-active",on);b.setAttribute("aria-selected",on?"true":"false");});
renderOverview();renderForecast();renderEvidence();
})();