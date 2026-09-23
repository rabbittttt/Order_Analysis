(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ForecastMath = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DEFAULT_COMPLETION_FLOOR = 0.005;

  function protectCompletion(rawValue, floor = DEFAULT_COMPLETION_FLOOR) {
    const raw = Number(rawValue);
    const minimum = Number(floor);
    if (!Number.isFinite(raw) || raw <= 0 || raw > 1) {
      return { raw, applied: NaN, clamped: false, valid: false, reason: '完成率缺失或超出0%~100%' };
    }
    const safeFloor = Number.isFinite(minimum) && minimum > 0 ? Math.min(minimum, 1) : 0;
    const applied = Math.min(Math.max(raw, safeFloor), 1);
    return {
      raw,
      applied,
      clamped: applied !== raw,
      valid: true,
      reason: applied !== raw ? `原始完成率过低，按${(safeFloor * 100).toFixed(1)}%安全下限计算` : '',
    };
  }

  function distributeInteger(total, weights) {
    const integer = Math.max(Math.round(Number(total) || 0), 0);
    if (!weights.length) return [];
    const clean = weights.map(weight => Math.max(Number(weight) || 0, 0));
    const sum = clean.reduce((left, right) => left + right, 0);
    const normalized = sum > 0
      ? clean.map(weight => weight / sum)
      : clean.map(() => 1 / clean.length);
    const quotas = normalized.map(weight => integer * weight);
    const values = quotas.map(Math.floor);
    const remainder = integer - values.reduce((left, right) => left + right, 0);
    const order = quotas
      .map((value, index) => ({ index, fraction: value - values[index] }))
      .sort((left, right) => right.fraction - left.fraction || left.index - right.index);
    for (let index = 0; index < remainder; index += 1) {
      values[order[index % order.length].index] += 1;
    }
    return values;
  }

  function genericDailyShape(index) {
    const dayIndex = Math.max(Math.round(Number(index) || 0), 0);
    return dayIndex === 0 ? 1 : 0.5 / Math.pow(Math.max(dayIndex, 1), 0.72);
  }

  function genericHourlyCompletion(hour) {
    const currentHour = Math.max(Math.min(Math.round(Number(hour) || 0), 23), 0);
    return Math.min((currentHour + 1) / 24, 1);
  }

  function isKnownAttribute(value) {
    const normalized = String(value == null ? '' : value).trim();
    return Boolean(normalized) && !['未维护', '待维护', '未知', '缺失', '—', '-'].includes(normalized);
  }

  function closeness(leftValue, rightValue) {
    const left = Number(leftValue);
    const right = Number(rightValue);
    if (!Number.isFinite(left) || !Number.isFinite(right) || left <= 0 || right <= 0) return NaN;
    return Math.min(left, right) / Math.max(left, right);
  }

  function scoredEvidence(parts, minimumEvidence) {
    const usable = parts.filter(part => Number.isFinite(part.value));
    const score = usable.length
      ? usable.reduce((sum, part) => sum + part.value, 0) / usable.length
      : 0;
    const required = Math.max(Math.round(Number(minimumEvidence) || 0), 1);
    return {
      parts: usable,
      score,
      evidenceCount: usable.length,
      minimumEvidence: required,
      eligible: usable.length >= required,
    };
  }

  function smallReferenceScore(item = {}, target = {}, current = {}, minimumEvidence = 3) {
    current = current || {};
    const parts = [];
    const add = (key, value, evidence) => parts.push({ key, value, evidence });
    const itemTier = String(item.tier || '');
    const targetTier = String(target.tier || '');
    const sameBody = ['SUV', 'MPV', '轿车'].some(word => targetTier.includes(word) && itemTier.includes(word));
    add('tier', isKnownAttribute(targetTier) && isKnownAttribute(itemTier)
      ? (targetTier === itemTier ? 1 : sameBody ? 0.85 : 0.45) : NaN,
    `${targetTier || '未维护'} ↔ ${itemTier || '未维护'}`);
    add('energy', isKnownAttribute(target.energy) && isKnownAttribute(item.energy)
      ? (target.energy === item.energy ? 1 : 0.55) : NaN,
    `${target.energy || '未维护'} ↔ ${item.energy || '未维护'}`);
    add('node', isKnownAttribute(target.node) && isKnownAttribute(item.node)
      ? (target.node === item.node ? 1 : 0.62) : NaN,
    `${target.node || '未维护'} ↔ ${item.node || '未维护'}`);
    const targetDays = Number(target.smallDays);
    const itemDays = Number(item.days);
    add('days', targetDays > 0 && itemDays > 0
      ? Math.max(0, 1 - Math.abs(targetDays - itemDays) / Math.max(targetDays, 36)) : NaN,
    `${targetDays || 0}天 ↔ ${itemDays || 0}天`);
    add('size', closeness(current.total, item.total), `${Number(current.total) || 0} ↔ ${Number(item.total) || 0}`);
    return scoredEvidence(parts, minimumEvidence);
  }

  function steadyReferenceScore(item = {}, target = {}, current = {}, minimumEvidence = 3) {
    const parts = [];
    const add = (key, value, evidence) => parts.push({ key, value, evidence });
    add('tier', isKnownAttribute(target.tier) && isKnownAttribute(item.tier)
      ? (target.tier === item.tier ? 1 : 0.5) : NaN,
    `${target.tier || '未维护'} ↔ ${item.tier || '未维护'}`);
    add('energy', isKnownAttribute(target.energy) && isKnownAttribute(item.energy)
      ? (target.energy === item.energy ? 1 : 0.55) : NaN,
    `${target.energy || '未维护'} ↔ ${item.energy || '未维护'}`);
    add('node', isKnownAttribute(target.node) && isKnownAttribute(item.node)
      ? (target.node === item.node ? 1 : 0.62) : NaN,
    `${target.node || '未维护'} ↔ ${item.node || '未维护'}`);
    const currentLockRate = Number(current.lock_rate);
    const itemLockRate = Number(item.lock_rate);
    add('lock', currentLockRate > 0 && itemLockRate > 0
      ? 1 - Math.min(Math.abs(currentLockRate - itemLockRate), 1) : NaN,
    `${(currentLockRate * 100 || 0).toFixed(1)}% ↔ ${(itemLockRate * 100 || 0).toFixed(1)}%`);
    return scoredEvidence(parts, minimumEvidence);
  }

  function completedSmallOrderDays(start, end, today, primary = [], fallback = []) {
    const parse = value => Date.parse(`${value}T00:00:00Z`);
    const first = parse(start), last = parse(end), now = parse(today);
    if (![first, last, now].every(Number.isFinite) || last < first)
      return {rows: [], missing: [], expected: 0, error: '小订时间窗口缺失或冲突'};
    const expected = Math.max(0, Math.min(Math.round((now-first)/86400000), Math.round((last-first)/86400000)+1));
    const index = source => {
      const result = new Map();
      source.forEach(row => result.set(row.date, result.has(row.date) ? null : row.orders));
      return result;
    };
    const sources = [index(primary), index(fallback)], rows = [], missing = [];
    for (let day = 0; day < expected; day += 1) {
      const date = new Date(first + day*86400000).toISOString().slice(0,10);
      const value = sources.map(source => source.get(date)).find(value =>
        value !== null && value !== undefined && String(value).trim() !== '' && Number.isFinite(Number(value)) && Number(value) >= 0);
      if (value === undefined) missing.push(`D${day+1}`);
      else rows.push({label:`D${day+1}`, date, orders:Number(value), actual:true});
    }
    return {rows, missing, expected, error:''};
  }

  // Bounded transition: protect the first future day, half participation on day 2.
  function defaultBridgeWeights(count) {
    return Array.from({length: Math.max(0, Math.floor(Number(count) || 0))}, (_, index) => index === 0 ? 0 : index === 1 ? .5 : 1);
  }

  // Display only: adjacent-day change, with gaps and zero denominators left unknown.
  function dailySlope(values) {
    return values.map((value, index) => index > 0 && Number.isFinite(value) && value >= 0 && Number.isFinite(values[index - 1]) && values[index - 1] > 0 ? value / values[index - 1] - 1 : NaN);
  }

  function anchoredAllocate({remaining, anchor=null, anchorFactor=1, anchorShape=1, shapes=[], factors=[], weights=[]}) {
    const total = Math.round(Number(remaining));
    const n = shapes.length, warnings = [];
    const fail = error => ({values:[], base:[], weights:[], warnings, error});
    if (!Number.isFinite(total) || total < 0) return fail('剩余量无效');
    if (!n) return total ? fail('没有剩余日期承接剩余量') : {values:[],base:[],weights:[],warnings,error:''};
    if (factors.length!==n || weights.length!==n || !shapes.every(v=>Number.isFinite(v)&&v>=0) || !factors.every(v=>Number.isFinite(v)&&v>0) || !weights.every(v=>Number.isFinite(v)&&v>=0)) return fail('日历系数必须为正数，差额权重必须为非负数且覆盖全部待预测日期');
    const anchored = anchor!==null && Number.isFinite(anchor) && anchor>=0 && anchorFactor>0 && anchorShape>0;
    const shape = shapes.map((value,i)=>value*factors[i]);
    const shapeSum = shape.reduce((a,b)=>a+b,0);
    if (!shapeSum) return fail('参考自然日曲线没有有效量');
    const base = anchored ? shape.map(value=>anchor/anchorFactor*value/anchorShape) : shape.map(value=>total*value/shapeSum);
    if (!anchored) warnings.push('无前一天完整真实值，按日历调整后的参考曲线分配');
    const difference = total-base.reduce((a,b)=>a+b,0);
    const rawWeights = weights.map((weight,i)=>weight*(base[i]>0?base[i]:factors[i]));
    let effective = [...rawWeights], values=[...base];
    if (n===1) {
      if (Math.abs(difference)>.5) warnings.push('仅剩一天，无法渐进分配，末日承接全部剩余量');
      return {values:[total],base,weights:[1],warnings,error:'',difference};
    }
    if (Math.abs(difference)>1e-8 && !effective.some(v=>v>0)) return fail('差额非零但全部调整权重为0，请至少启用一个待预测日期');
    if (difference>=0) {
      const sum=effective.reduce((a,b)=>a+b,0);
      values=base.map((value,i)=>value+(sum?difference*effective[i]/sum:0));
    } else {
      let deficit=-difference;
      for(let round=0;round<=n && deficit>1e-8;round++) {
        let active=values.map((value,i)=>value>1e-8&&effective[i]>0?i:-1).filter(i=>i>=0);
        if(!active.length) {
          active=values.map((value,i)=>value>1e-8?i:-1).filter(i=>i>=0);
          if(!active.length)break;
          warnings.push('剩余量不足以保留衔接基准，已放开零权重日期；请复核终局');
          active.forEach(i=>effective[i]=values[i]);
        }
        const sum=active.reduce((s,i)=>s+effective[i],0),before=deficit;
        active.forEach(i=>{const take=Math.min(values[i],before*effective[i]/sum);values[i]-=take;deficit-=take});
      }
    }
    if(Math.abs(difference)>Math.max(base.reduce((a,b)=>a+b,0)*.3,1))warnings.push('终局剩余量与前日衔接曲线差异超过30%，请复核');
    const sum=effective.reduce((a,b)=>a+b,0);
    return {values:distributeInteger(total,values),base,weights:effective.map(value=>sum?value/sum:0),warnings,error:'',difference};
  }

  // Shared lifecycle baseline helpers live after the stage calculations.
  function recentSteadyBaseline({rows=[],startDate,today,factor=()=>1}) {
    const byDate=new Map();
    for(const row of rows)byDate.set(row.date,byDate.has(row.date)?null:row.lock);
    const values=[];
    for(let i=1;i<=14;i++) {
      const date=new Date(Date.parse(today+'T00:00:00Z')-i*86400000).toISOString().slice(0,10);
      if(date<startDate)break;
      const value=byDate.get(date),weight=factor(date);
      if(typeof value!=='number'||!Number.isFinite(value)||value<0||!Number.isFinite(weight)||weight<=0)break;
      values.unshift(value/weight);
    }
    if(!values.length)return {available:false,level:null,ratio:null};
    const mean=items=>items.reduce((a,b)=>a+b,0)/items.length,level=mean(values.slice(-7)),previous=values.length===14?mean(values.slice(0,7)):null;
    return {available:true,level,ratio:previous>0?level/previous:1,days:values.length,flatTrend:!(previous>0)};
  }

  function launchDirectLockBaseline({rows = [], launchDate, endDate, today, factor = () => 1}) {
    const unavailable = reason => ({available:false, level:null, ratio:null, reason});
    const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    if (!launchDate || !endDate || !today) return unavailable('首销日期缺失');
    if (today <= launchDate) return unavailable('尚无已结束首销日');
    const last = new Date(Math.min(Date.parse(endDate+'T00:00:00Z'), Date.parse(today+'T00:00:00Z')-86400000));
    if (!Number.isFinite(last.getTime())) return unavailable('首销日期无效');
    const count = Math.min(14, Math.floor((last-Date.parse(launchDate+'T00:00:00Z'))/86400000)+1);
    if (count <= 0) return unavailable('首销日期范围无效');
    const byDate = new Map();
    for (const row of rows) byDate.set(row.date, byDate.has(row.date)?null:row);
    const sample = [];
    for (let i=count-1;i>=0;i--) {
      const date = new Date(last.getTime()-i*86400000).toISOString().slice(0,10), row=byDate.get(date);
      if (!row || !valid(row.direct) || !valid(row.gross) || !valid(row.lock) || row.direct>row.gross || row.lock>row.gross) return unavailable(`${date}首销直接大定/大定/锁单缺失或异常`);
      const calendarFactor=factor(date);
      if (!Number.isFinite(calendarFactor) || calendarFactor<=0) return unavailable('日历系数无效');
      sample.push({date,direct:row.direct,gross:row.gross,lock:row.lock,factor:calendarFactor});
    }
    const gross=sample.reduce((sum,row)=>sum+row.gross,0),lock=sample.reduce((sum,row)=>sum+row.lock,0);
    if (gross<=0) return unavailable('首销大定为0，无法计算锁单率');
    const lockRate=lock/gross,values=sample.map(row=>row.direct*lockRate/row.factor);
    const average=items=>items.reduce((sum,value)=>sum+value,0)/items.length;
    const level=average(values.slice(-7)),previous=values.length===14?average(values.slice(0,7)):null;
    return {available:true,level,ratio:previous>0?level/previous:1,lockRate,days:count,first:sample[0].date,last:sample.at(-1).date,flatTrend:!(previous>0),reason:''};
  }

  function applyObservedFloor(values, observed){
    const floor=Number.isFinite(observed)&&observed>=0?Math.ceil(observed):0;
    if(!values.length||values[0]>=floor)return {values:[...values],raised:0};
    const original=values.reduce((a,b)=>a+b,0),total=Math.max(original,floor);
    return {values:[floor,...distributeInteger(total-floor,values.slice(1))],raised:total-original};
  }

  // Missing intraday components are estimates; conserve every observed order.
  function intradayComponents(snapshot, completion, smallShare){
    const count=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value))&&Number(value)>=0?Number(value):null;
    const gross=count(snapshot?.gross),small=count(snapshot?.small_to_big),direct=count(snapshot?.direct);
    const observed=Math.max(gross??0,(small??0)+(direct??0)),share=Math.max(0,Math.min(Number(smallShare)||0,1));
    const estimated=gross===null||small===null||direct===null||Math.abs(small+direct-observed)>.5;
    const observedSmall=!estimated?small:small!==null&&direct===null?Math.min(small,observed):small===null&&direct!==null?Math.max(observed-direct,0):observed*share;
    const observedDirect=observed-observedSmall,rate=Number(completion);
    const total=observed/(Number.isFinite(rate)&&rate>0?Math.min(rate,1):1),remaining=Math.max(total-observed,0);
    const projectedSmall=Math.max(Math.round(observedSmall+remaining*share),Math.ceil(observedSmall));
    const projectedDirect=Math.max(Math.round(total)-projectedSmall,Math.ceil(observedDirect));
    return {gross:projectedSmall+projectedDirect,small:projectedSmall,direct:projectedDirect,observed,observedSmall,observedDirect,estimated};
  }

  function intradayReference({buckets=[],days=[],today,launchDate,dayType=()=>''}){
    const totals=new Map(days.filter(row=>row.date<today).map(row=>[row.date,row.gross])),curves=[];
    for(const bucket of buckets){
      if(bucket.date<=launchDate||bucket.date>=today||!bucket.hours?.length)continue;
      const daily=totals.get(bucket.date),hours=Array(24).fill(0);
      if(!(daily>0))continue;
      let valid=true;
      for(const row of bucket.hours){if(!Number.isInteger(row.hour)||row.hour<0||row.hour>23||typeof row.gross!=='number'||row.gross<0||!Number.isFinite(row.gross)){valid=false;break;}hours[row.hour]+=row.gross;}
      if(!valid||Math.abs(hours.reduce((a,b)=>a+b,0)-daily)>.5)continue;
      let running=0;curves.push({date:bucket.date,values:hours.map(value=>(running+=value)/daily)});
    }
    const sameType=curves.filter(row=>dayType(row.date)===dayType(today)),selected=(sameType.length?sameType:curves).sort((a,b)=>a.date.localeCompare(b.date)).slice(-7);
    return {curve:selected.length?Array.from({length:24},(_,hour)=>selected.reduce((sum,row)=>sum+row.values[hour],0)/selected.length):[],days:selected.length,sameType:!!sameType.length};
  }

  function hourlyComparison(bucket, {today, dailyTotal, forecastTotal, completion}={}){
    const actual=Array(24).fill(null),forecast=Array(24).fill(null),counts=Array(24).fill(0);
    if(!bucket?.date||bucket.date>today||!bucket.hours?.length)return {actual,forecast};
    let last=-1;
    for(const row of bucket.hours){
      const hour=Number(row.hour),value=row.gross;
      if(!Number.isInteger(hour)||hour<0||hour>23||value==null||!Number.isFinite(Number(value))||Number(value)<0)return {actual,forecast};
      counts[hour]+=Number(value);last=Math.max(last,hour);
    }
    const observed=counts.reduce((a,b)=>a+b,0),ongoing=bucket.date===today;
    const terminal=ongoing?Math.max(Number(forecastTotal)||0,observed):dailyTotal!=null&&Number.isFinite(Number(dailyTotal))?Number(dailyTotal):observed;
    if(!(terminal>0)||terminal<observed)return {actual,forecast,date:bucket.date,last,observed,terminal};
    let running=0;
    for(let hour=0;hour<=last;hour++){running+=counts[hour];actual[hour]=running/terminal;}
    if(!ongoing&&terminal===observed)for(let hour=last+1;hour<24;hour++)actual[hour]=1;
    if(ongoing&&last<23&&typeof completion==='function'){
      const cut=actual[last],refCut=completion(last);forecast[last]=cut;
      for(let hour=last+1;hour<24;hour++)forecast[hour]=Math.min(cut+(1-cut)*Math.max(completion(hour)-refCut,0)/Math.max(1-refCut,.0001),1);
      forecast[23]=1;
    }
    return {actual,forecast,date:bucket.date,last,observed,terminal,ongoing};
  }

  return {
    applyObservedFloor,
    intradayReference,
    intradayComponents,
    hourlyComparison,
    launchDirectLockBaseline,
    recentSteadyBaseline,
    defaultBridgeWeights,
    dailySlope,
    anchoredAllocate,
    completedSmallOrderDays,
    DEFAULT_COMPLETION_FLOOR,
    protectCompletion,
    distributeInteger,
    genericDailyShape,
    genericHourlyCompletion,
    isKnownAttribute,
    closeness,
    smallReferenceScore,
    steadyReferenceScore,
  };
});
