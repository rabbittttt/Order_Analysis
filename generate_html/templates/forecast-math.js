(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ForecastMath = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const DEFAULT_COMPLETION_FLOOR = 0.005;

  // Preserve the distinction between a real zero and unavailable evidence.
  function observedQuantity(value) {
    if (value === null || value === undefined || typeof value === 'boolean' ||
        (typeof value === 'string' && !value.trim())) return NaN;
    const number = Number(value);
    return Number.isFinite(number) && number >= 0 ? number : NaN;
  }

  function observedRatio(numerator, denominator) {
    const top = observedQuantity(numerator), bottom = observedQuantity(denominator);
    return bottom > 0 ? top / bottom : NaN;
  }

  // A missing ratio is not a zero observation. Normalize only usable weights.
  function weightedObserved(rows, fallback = NaN) {
    const usable = (rows || []).filter(row => row.value !== null && row.value !== undefined &&
      !(typeof row.value === 'string' && !row.value.trim()) && typeof row.value !== 'boolean' && Number.isFinite(Number(row.value)) && Number(row.weight) > 0);
    const weight = usable.reduce((sum, row) => sum + Number(row.weight), 0);
    if (weight) return usable.reduce((sum, row) => sum + Number(row.value) * Number(row.weight), 0) / weight;
    return fallback === null || fallback === undefined || fallback === '' ? NaN : Number(fallback);
  }

  function referenceParameter(rows, field, fallback = NaN) {
    const labels = {conversion:'小订转化率', direct_share:'直接大定占比', lock_rate:'大定到锁单率', net_rate:'留存大定率', cancel_rate:'退订率'};
    const used = [], excluded = [];
    for (const row of rows || []) {
      if (!row.item || !(Number(row.weight) > 0)) continue;
      const raw = row.item[field], value = weightedObserved([{value:raw, weight:1}]);
      const invalid = !Number.isFinite(value) || value < 0 || value > 1 ||
        (field === 'direct_share' && value === 1) ||
        String(row.item.quality_issues || '').includes(labels[field] || field);
      (invalid ? excluded : used).push({...row, value});
    }
    const weight = used.reduce((sum, row) => sum + Number(row.weight), 0);
    return {value:weightedObserved(used, excluded.length ? NaN : fallback),
      used:used.map(row => ({...row, effectiveWeight:Number(row.weight)/weight})), excluded};
  }

  // Editable windows change date alignment, never the dates of actual orders.
  function dateNumber(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return NaN;
    const stamp = Date.parse(value+'T00:00:00Z');
    return Number.isFinite(stamp) && new Date(stamp).toISOString().slice(0,10) === value ? stamp : NaN;
  }

  function positiveDays(value) {
    const count = Number(value);
    return typeof value !== 'boolean' && Number.isInteger(count) && count > 0 ? count : 0;
  }

  // UTC date-only arithmetic: the contract matches Python's calendar dates,
  // independently of browser timezone/DST. Explicit conflicting ends never fall back.
  function launchStage({launchDate='', endDate='', days=0} = {}, today) {
    const start = dateNumber(launchDate), current = dateNumber(today), count = positiveDays(days);
    const unknown = label => ({key:'unknown',label,day:0,days:0,start:Number.isFinite(start)?launchDate:'',end:''});
    if (!Number.isFinite(start)) return unknown('时间缺失');
    if (endDate && !Number.isFinite(dateNumber(endDate))) return unknown('首销结束日期无效');
    const end = endDate ? dateNumber(endDate) : count ? start+(count-1)*86400000 : NaN;
    if (end < start) return {...unknown('首销窗口冲突'),end:endDate};
    if (!Number.isFinite(end)) return unknown('首销截止日期与天数缺失');
    if (!Number.isFinite(current)) return unknown('判定日期无效');
    const span = (end-start)/86400000+1, finish = new Date(end).toISOString().slice(0,10);
    const key = current < start ? 'before' : current > end ? 'ended' : 'active';
    return {key,label:{before:'首销期未开始',active:'首销期进行中',ended:'首销期已结束'}[key],
      day:key==='before'?0:key==='ended'?span:(current-start)/86400000+1,days:span,start:launchDate,end:finish};
  }

  function smallStage({smallStartDate='', smallEndDate=''} = {}, today) {
    const start = dateNumber(smallStartDate), end = dateNumber(smallEndDate), current = dateNumber(today);
    const unknown = label => ({key:'unknown',label,day:0,days:0});
    if (!Number.isFinite(start)) return unknown('小订时间缺失');
    if (!Number.isFinite(end)) return unknown('小订结束日期缺失');
    if (end < start) return unknown('小订窗口冲突');
    if (!Number.isFinite(current)) return unknown('判定日期无效');
    const days=(end-start)/86400000+1,key=current<start?'before':current===start?'d1':current>end?'ended':'active';
    return {key,label:{before:'小订D1未到',d1:'小订D1进行中',active:'小订D1已过',ended:'小订期已结束'}[key],
      day:key==='before'?0:key==='ended'?days:(current-start)/86400000+1,days};
  }

  // Known date/row checks are reevaluated against editable windows below.
  // Unknown codes and legacy unstructured errors fail closed, without parsing prose.
  function sourceBlockingIssues(issues, legacyErrors = [], windowChanged = false) {
    if (!Array.isArray(issues)) return legacyErrors.map(message=>({code:'LEGACY_SOURCE_ERROR',message}));
    const live = new Set(['COMPLETED_DAYS_MISSING','COMPLETED_DAYS_INVALID','TOTAL_SMALL_REQUIRED']);
    const windowCodes = new Set(['LAUNCH_START_INVALID','LAUNCH_DAYS_INVALID','LAUNCH_WINDOW_UNMAINTAINED','LAUNCH_STAGE_UNKNOWN','ACTUAL_START_MISMATCH']);
    return issues.filter(issue=>!live.has(issue.code)&&!(windowChanged&&windowCodes.has(issue.code)));
  }

  function launchRowIssues(rows, ended = false) {
    const valid = value => value!==null&&value!==undefined&&String(value).trim()!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value))&&Number(value)>=0;
    const issues=[];
    for (const row of rows || []) {
      if (!valid(row.gross)) {issues.push({code:'GROSS_INVALID',date:row.date,fields:['gross']});continue;}
      const present = value => value!==null&&value!==undefined&&String(value).trim()!=='';
      if (!ended && present(row.small_to_big) && present(row.direct) &&
          (!valid(row.small_to_big)||!valid(row.direct)||Math.abs(Number(row.small_to_big)+Number(row.direct)-Number(row.gross))>Math.max(1,Math.abs(Number(row.gross))*.005)))
        issues.push({code:'COMPONENTS_INCONSISTENT',date:row.date,fields:['gross','small_to_big','direct']});
    }
    return issues;
  }

  // Launch terminal arithmetic has one owner; no DOM or source-reading dependencies.
  function launchParameterTerminal({rawDataError,endedComplete,componentsReady,hasSmall,small,baseConversion,baseShare,directD1,d1Ratio,actualSmall,actualDirect,actualGross,anchorSmall,anchorDirect}) {
    const available=!rawDataError&&(endedComplete||(componentsReady&&(hasSmall?(small>0&&baseConversion>0&&baseConversion<=1&&baseShare>=0&&baseShare<1):(directD1>0&&d1Ratio>0))));
    const rawSmall=available&&hasSmall?small*baseConversion:0,rawDirect=available?(hasSmall?rawSmall*baseShare/(1-baseShare):directD1/d1Ratio):0;
    const totalSmall=endedComplete?actualSmall:available?Math.max(rawSmall,anchorSmall):0,totalDirect=endedComplete?actualDirect:available?Math.max(rawDirect,anchorDirect):0;
    return {available,rawSmall,rawDirect,small:totalSmall,direct:totalDirect,gross:endedComplete?actualGross:totalSmall+totalDirect,
      adjusted:!endedComplete&&available&&(totalSmall>rawSmall+.5||totalDirect>rawDirect+.5)};
  }

  function launchProgressTerminal({rawDataError,historyComplete,endedComplete,d1Unavailable,componentsReady,effectiveDays,hasSmall,smallCompletion,directCompletion,actualSmall,actualDirect,actualGross,anchorSmall,anchorDirect}) {
    const validCompletion = value => Number.isFinite(value) && value > 0 && value <= 1;
    const available=!rawDataError&&historyComplete&&(endedComplete||(!d1Unavailable&&componentsReady&&effectiveDays>0&&anchorSmall+anchorDirect>0&&(!hasSmall||validCompletion(smallCompletion))&&validCompletion(directCompletion)));
    const small=endedComplete?actualSmall:!hasSmall?0:available?Math.max(anchorSmall,anchorSmall/smallCompletion):0,direct=endedComplete?actualDirect:available?Math.max(anchorDirect,anchorDirect/directCompletion):0;
    return {available,small,direct,gross:endedComplete?actualGross:small+direct};
  }

  // Empty overrides restore the reference; invalid nonempty overrides must not
  // silently fall back or be used as divisors. Manual values retain their precision.
  function launchCompletion(reference, manual, overridden = false) {
    const supplied = overridden && manual !== null && manual !== undefined && String(manual).trim() !== '';
    const value = supplied ? observedQuantity(manual) / 100 : observedQuantity(reference);
    return value > 0 && value <= 1 ? value : NaN;
  }

  function forecastWindows(configured = {}, values = {}) {
    const parse = dateNumber;
    const shift = (start, count) => Number.isFinite(parse(start)) && count > 0
      ? new Date(parse(start)+(count-1)*86400000).toISOString().slice(0,10) : '';
    const launchDate = values.launchDate ?? configured.launch_date ?? '';
    const days = positiveDays(values.days ?? configured.days ?? configured.launch_days);
    const smallStartDate = values.smallStartDate ?? configured.small_start_date ?? '';
    const smallDays = positiveDays(values.smallDays ?? configured.small_days);
    const launchChanged = launchDate !== (configured.launch_date || '') || days !== Number(configured.days ?? configured.launch_days ?? 0);
    const smallChanged = smallStartDate !== (configured.small_start_date || '') || smallDays !== Number(configured.small_days || 0);
    const endDate = launchChanged ? shift(launchDate, days) : configured.end_date || shift(launchDate, days);
    const smallEndDate = smallChanged ? shift(smallStartDate, smallDays) : configured.small_end_date || '';
    return {launchDate, days, endDate, smallStartDate, smallDays, smallEndDate,
      steadyStartDate: launchChanged ? shift(endDate, 2) : configured.steady_start_date || shift(endDate, 2),
      launchChanged, smallChanged};
  }

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

  function smallHourlyStart(item = {}) {
    const explicit = item.small_start_hour;
    if (Number.isInteger(explicit) && explicit >= 0 && explicit < 24) return explicit;
    return (item.small_hourly_curve || []).findIndex(value => Number.isFinite(value) && value > 0);
  }

  function smallHourlyCurve(item = {}, targetStart = smallHourlyStart(item)) {
    const start = smallHourlyStart(item), source = item.small_hourly_curve || [];
    if (start < 0 || targetStart < 0 || targetStart > 23) return [];
    const end = Math.min(23, start + 23 - targetStart), terminal = source[end];
    if (!(terminal > 0)) return [];
    return Array.from({length:24}, (_, hour) => {
      if (hour < targetStart) return null;
      const value = source[Math.min(start + hour - targetStart, 23)];
      return Number.isFinite(value) ? Math.min(Math.max(value / terminal, 0), 1) : null;
    });
  }

  function smallHourlyReferenceScore(item = {}, current = {}, minimumEvidence = 1) {
    const hours = (current.hours || []).filter(row => Number.isInteger(row.hour) && Number.isFinite(row.orders) && row.orders >= 0);
    const positive = hours.filter(row => row.orders > 0), inferred = positive.length ? Math.min(...positive.map(row => row.hour)) : -1;
    const start = Number.isInteger(current.startHour) && current.startHour >= 0 ? current.startHour : inferred;
    const refStart = smallHourlyStart(item), parts = [];
    if (start >= 0 && refStart >= 0) parts.push({key:'release_hour',value:Math.max(0,1-Math.abs(start-refStart)/12),weight:.2,evidence:`${start}时 ↔ ${refStart}时`});
    const curve = smallHourlyCurve(item,start), last = hours.length ? Math.max(...hours.map(row=>row.hour)) : -1;
    const counts = Array(24).fill(0);hours.forEach(row=>counts[row.hour]+=row.orders);
    const observed = counts.reduce((a,b)=>a+b,0), cut = curve[last];
    if (last>start && observed>0 && cut>0) {
      let actual=0,previous=0,slopeGap=0,cumulativeGap=0;
      for(let hour=start;hour<=last;hour++) {
        const value=curve[hour];if(!Number.isFinite(value))return scoredEvidence(parts,minimumEvidence);
        actual+=counts[hour];slopeGap+=Math.abs(counts[hour]/observed-(value-previous)/cut);
        cumulativeGap+=Math.abs(actual/observed-value/cut);previous=value;
      }
      parts.push({key:'hour_slope',value:Math.max(0,1-slopeGap/2),weight:.5,evidence:`发布后${last-start+1}小时新增量归一化比较`});
      parts.push({key:'hour_progress',value:Math.max(0,1-cumulativeGap/(last-start+1)),weight:.3,evidence:`截至${last}时的各小时累计占比比较`});
    }
    const result=scoredEvidence(parts,minimumEvidence),weight=parts.reduce((sum,part)=>sum+part.weight,0);
    result.score=weight?parts.reduce((sum,part)=>sum+part.value*part.weight,0)/weight:0;
    return result;
  }

  function smallHourlyForecast({hours=[],references=[],startHour}={}) {
    const invalid=hours.some(row=>!Number.isInteger(row.hour)||row.hour<0||row.hour>23||!Number.isFinite(row.orders)||row.orders<0);
    if(invalid)return {error:'D1分时存在无效小时或数量',total:null};
    const counts=Array(24).fill(0);hours.forEach(row=>counts[row.hour]+=row.orders);
    const observed=counts.reduce((a,b)=>a+b,0),first=counts.findIndex(value=>value>0),start=Number.isInteger(startHour)&&startHour>=0?Math.min(startHour,first>=0?first:startHour):first,last=hours.length?Math.max(...hours.map(row=>row.hour)):-1;
    if(start<0||last<start||observed<=0)return {error:'等待发布后的有效分时小订',total:null};
    const refs=references.map(row=>({...row,curve:smallHourlyCurve(row.item,start)})).filter(row=>row.weight>0&&row.curve[last]>0&&row.curve.slice(start).every(Number.isFinite));
    if(!refs.length)return {error:'所选参考车型缺少有效D1分时曲线',total:null};
    const weight=refs.reduce((sum,row)=>sum+row.weight,0),curve=Array.from({length:24},(_,hour)=>hour<start?null:refs.reduce((sum,row)=>sum+row.curve[hour]*row.weight,0)/weight);
    const cut=curve[last],recentStart=Math.max(start,last-2),prior=recentStart>start?curve[recentStart-1]:0;
    const recent=counts.slice(recentStart,last+1).reduce((a,b)=>a+b,0),recentShare=cut-prior;
    // Fit scale from both accumulated demand and the latest three observed
    // hourly increments. Historical D1 absolute volume never enters this fit.
    const cumulativeScale=observed/cut,scale=recentShare>0?(cumulativeScale+recent/recentShare)/2:cumulativeScale;
    const remaining=Math.max(0,Math.round(scale*(1-cut))),future=distributeInteger(remaining,curve.slice(last+1).map((value,i)=>Math.max(value-curve[last+i],0)));
    const total=observed+remaining,actual=Array(24).fill(null),forecast=Array(24).fill(null),predictedHours=Array(24).fill(null);let running=0;
    for(let hour=start;hour<=last;hour++){running+=counts[hour];actual[hour]=running/total;}
    if(last<23){forecast[last]=running/total;future.forEach((value,index)=>{const hour=last+index+1;predictedHours[hour]=value;running+=value;forecast[hour]=running/total;});}
    return {error:'',observed,total,remaining,start,last,actual,forecast,predictedHours,curve};
  }


  // Preserve launch and closing impulses; resample only the cumulative middle.
  function stretchCompletion(curve, length) {
    const n=curve.length, m=Math.round(length);
    if(!n||m<1||!curve.every((v,i)=>Number.isFinite(v)&&v>=0&&(!i||v>=curve[i-1]))||!(curve[n-1]>0))return [];
    const normalized=curve.map(v=>v/curve[n-1]);
    if(n===m)return normalized;
    if(n<5||m<5)return [];
    const at=x=>{const lo=Math.floor(x),fraction=x-lo;return normalized[lo]+fraction*(normalized[Math.min(lo+1,n-1)]-normalized[lo]);};
    return Array.from({length:m},(_,i)=>i<2?normalized[i]:i>=m-2?normalized[n-m+i]:at(1+(i-1)*(n-4)/(m-4)));
  }

  function launchDailyReference(item = {}, today) {
    const parse = value => {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return NaN;
      const time = Date.parse(value + 'T00:00:00Z');
      return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value ? time : NaN;
    };
    const days = Number(item.days), start = parse(item.launch_date), end = parse(item.end_date), now = parse(today);
    const source = item.daily_orders || [], observed = [];
    const completed = Number.isInteger(days) && days > 0 && Number.isFinite(start) && Number.isFinite(now)
      ? Math.max(0, Math.min(days, Math.floor((now - start) / 86400000))) : 0;
    for (let i = 0; i < Math.min(completed, source.length); i++) {
      const value = weightedObserved([{value:source[i], weight:1}]);
      if (!Number.isFinite(value) || value < 0) break;
      observed.push(value);
    }
    const fail = reason => ({available:false, reason, orders:[], observed});
    if (!Number.isInteger(days) || days < 1 || ![start, end, now].every(Number.isFinite))
      return fail('首销完整时间窗口未维护');
    if (end - start !== (days - 1) * 86400000) return fail('首销日期与天数不一致');
    if (end >= now) return fail('首销期尚未结束');
    if (observed.length !== days) return fail('首销逐日大定未收齐或存在无效数量');
    if (!(observed[0] > 0)) return fail('D1大定不大于0，无法构建相对D1基础曲线');
    return {available:true, reason:'', orders:observed, observed};
  }

  function adaptLaunchDailyOrders(item, targetDays, today) {
    const reference = launchDailyReference(item, today);
    if (!reference.available) return [];
    let total = 0;
    const curve = reference.orders.map(value => (total += value));
    const adapted = stretchCompletion(curve, targetDays);
    return adapted.map((value, index) => Math.max((value - (index ? adapted[index-1] : 0)) * total, 0));
  }

  function normalizedShapeSimilarity(current, reference) {
    if(current.length<3||reference.length<3)return NaN;
    if(!current.every(v=>Number.isFinite(v)&&v>=0)||!reference.every(v=>Number.isFinite(v)&&v>=0))return NaN;
    const mass=(values,n)=>{let sum=0;const c=[0,...values.map(v=>(sum+=v))];if(!sum)return [];
      const at=x=>{const i=Math.floor(x);return (c[i]+(x-i)*((c[i+1]??c[i])-c[i]))/sum;};
      return Array.from({length:n},(_,i)=>at((i+1)*values.length/n)-at(i*values.length/n));};
    const a=mass(current,Math.max(current.length,reference.length)),b=mass(reference,a.length);
    return a.length&&b.length?Math.max(0,1-a.reduce((sum,v,i)=>sum+Math.abs(v-b[i]),0)/2):NaN;
  }

  function launchHourlyItem(item={}) {
    return {small_hourly_curve:item.hourly_curve||[],small_start_hour:item.launch_start_hour};
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
    const source=item.direct_curve||[],horizon=current.launch_days||source.length;
    const adapted=source.length&&(!item.launch_days||source.length===Number(item.launch_days))?stretchCompletion(source.reduce((out,v)=>{out.push((out.at(-1)||0)+v);return out;},[]),horizon):[];
    const reference=adapted.map((v,i)=>v-(i?adapted[i-1]:0)).slice(0,(current.direct_curve||[]).length);
    add('launch_shape',normalizedShapeSimilarity(current.direct_curve||[],reference),'全首销已观测段直接大定归一化形状；不比较绝对量');
    add('steady_shape',normalizedShapeSimilarity(current.steady_curve||[],(item.steady_curve||[]).slice(0,(current.steady_curve||[]).length)),'相同平销进度窗口的日历还原趋势');
    const result=scoredEvidence(parts,minimumEvidence),weights={tier:.05,energy:.05,node:.05,lock:.1,launch_shape:.55,steady_shape:.2};
    result.parts=result.parts.map(part=>({...part,weight:weights[part.key]}));
    const total=result.parts.reduce((sum,part)=>sum+part.weight,0);
    result.score=total?result.parts.reduce((sum,part)=>sum+part.value*part.weight,0)/total:0;
    result.eligible=result.eligible&&result.parts.some(part=>part.key==='launch_shape');
    return result;
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

  // Keep absolute calendar positions: a missing/duplicate date is unknown,
  // never a reason to shift a later order into an earlier Dn or calendar factor.
  function launchDirectObservations({rows = [], launchDate, endDate, days, today, factor = () => 1}) {
    const stage = launchStage({launchDate,endDate,days},today);
    const count = stage.key === 'ended' ? stage.days : stage.key === 'active' ? stage.day-1 : 0;
    const byDate = new Map();
    for (const row of rows) byDate.set(row.date,byDate.has(row.date)?null:row);
    const first = dateNumber(launchDate);
    return Array.from({length:count}, (_,index) => {
      const day = new Date(first+index*86400000).toISOString().slice(0,10);
      const value = observedQuantity(byDate.get(day)?.direct), multiplier = factor(day,index);
      return Number.isFinite(multiplier) && multiplier > 0 ? value/multiplier : NaN;
    });
  }

  function launchDirectLockBaseline({rows = [], launchDate, endDate, today, factor = () => 1}) {
    const unavailable = reason => ({available:false, level:null, ratio:null, reason});
    const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
    if (!launchDate || !endDate || !today) return unavailable('首销日期缺失');
    if (today <= launchDate) return unavailable('尚无已结束首销日');
    const last = new Date(Math.min(Date.parse(endDate+'T00:00:00Z'), Date.parse(today+'T00:00:00Z')-86400000));
    if (!Number.isFinite(last.getTime())) return unavailable('首销日期无效');
    const count = Math.floor((last-Date.parse(launchDate+'T00:00:00Z'))/86400000)+1;
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
    const level=average(values),xMean=(values.length-1)/2,y=values.map(v=>Math.log1p(v)),yMean=average(y);
    const denominator=values.reduce((sum,_,i)=>sum+(i-xMean)**2,0);
    const slope=denominator?y.reduce((sum,v,i)=>sum+(i-xMean)*(v-yMean),0)/denominator:0;
    return {available:true,level,ratio:count>=3?Math.exp(Math.max(-.7,Math.min(.7,slope*7))):1,lockRate,days:count,first:sample[0].date,last:sample.at(-1).date,flatTrend:count<3,curve:sample.map(row=>row.direct/row.factor),reason:''};
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
    // Known components are lower bounds, not proportions to overwrite. Only
    // the unclassified part of a gross snapshot may use the reference share.
    const unclassified=Math.max(observed-(small??0)-(direct??0),0);
    const observedSmall=small!==null&&direct!==null?small+unclassified*share:
      small!==null?small:direct!==null?observed-direct:observed*share;
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
    weightedObserved,
    observedQuantity,
    observedRatio,
    launchCompletion,
    referenceParameter,
    forecastWindows,
    launchStage,
    smallStage,
    sourceBlockingIssues,
    launchRowIssues,
    launchParameterTerminal,
    launchProgressTerminal,
    stretchCompletion,
    launchDailyReference,
    adaptLaunchDailyOrders,
    normalizedShapeSimilarity,
    launchHourlyItem,
    applyObservedFloor,
    intradayReference,
    intradayComponents,
    hourlyComparison,
    launchDirectLockBaseline,
    launchDirectObservations,
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
    smallHourlyStart,
    smallHourlyCurve,
    smallHourlyReferenceScore,
    smallHourlyForecast,
    steadyReferenceScore,
  };
});
