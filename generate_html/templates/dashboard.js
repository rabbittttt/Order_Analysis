(async () => {
  async function decompressJson(b64){
    const bin=atob(b64||""),bytes=new Uint8Array(bin.length);
    for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);
    const stream=new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    return JSON.parse(await new Response(stream).text());
  }
  function unpackDashboard(value){
    if(value?.format!=='shared-v1')return value;
    const memo=new Map();
    function restore(item){
      if(!item||typeof item!=='object')return item;
      if(Array.isArray(item))return item.map(restore);
      if(Object.hasOwn(item,'$shared')){
        const index=item.$shared;
        if(!Number.isInteger(index)||index<0||index>=value.pool.length)throw new Error('Invalid shared dashboard reference');
        if(!memo.has(index))memo.set(index,restore(value.pool[index]));
        return memo.get(index);
      }
      const entries=Object.hasOwn(item,'$literal')?item.$literal:Object.entries(item);
      return Object.fromEntries(entries.map(([key,child])=>[key,restore(child)]));
    }
    return restore(value.root);
  }
  const DATA = await decompressJson(window.DASHBOARD_DATA_B64);
  DATA.dashboard_blocks=window.DASHBOARD_BLOCKS_B64||DATA.dashboard_blocks||{};
  window.DASHBOARD_DATA = DATA;
  const {protectCompletion,distributeInteger,genericDailyShape,genericHourlyCompletion,isKnownAttribute,smallReferenceScore,steadyReferenceScore,completedSmallOrderDays}=window.ForecastMath;
  const RAW_BLOCKS = window.DASHBOARD_RAW_B64 || {};
  window.CHART_RENDER_MODE = DATA.config.chart_render_mode || "generated";
  const $ = selector => document.querySelector(selector);
  const displayText = value => String(value ?? "").replaceAll("净大定", "留存大定");
  const esc = value => displayText(value).replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const fmt = value => typeof value === "number" ? value.toLocaleString("zh-CN", {maximumFractionDigits: 1}) : esc(value);
  const colors = {blue:"#1677FF",green:"#00B578",orange:"#FF8A00",purple:"#7C3AED",coral:"#FF4D6D"};
  const LABEL_SCALE_HEADROOM=1.18;
  const chartMax=values=>Math.max(...values.map(value=>Number(value||0)),1)*LABEL_SCALE_HEADROOM;
  const stackedBarWidth=step=>Math.min(42,step*.58);
  function avoidLabelY(baseY,occupied=[],minY=12,maxY=280,gap=14){
    let y=Math.min(Math.max(baseY,minY),maxY);
    for(let attempt=0;attempt<occupied.length*2+2;attempt++){
      const conflict=occupied.find(value=>Math.abs(value-y)<gap);
      if(conflict==null)break;
      const above=conflict-gap,below=conflict+gap;
      y=above>=minY?above:Math.min(below,maxY);
    }
    return Math.min(Math.max(y,minY),maxY);
  }
  // 通用浅色图表色板。
  const chartPalette = {blue:"#BDD7EE",cyan:"#B5DDE5",green:"#C6E0B4",yellow:"#FFE699",orange:"#F8CBAD",rose:"#F0CCCC",violet:"#CCC0DA"};
  // 留存大定/锁单堆叠趋势图按系列出现顺序取色，不按能源类型固定颜色。
  const stackedTrendPalette=["#FFF2CC","#E2F0D9","#C8E8E8","#A8D8EA","#A0C1E8","#DCC5ED","#F0C8C8","#F8D8B0"];
  const moduleLabels = DATA.config.module_labels;
  const forecastStages=[{id:"small",label:"小订预测"},{id:"launch",label:"首销预测"},{id:"steady",label:"平销预测"}];
  const forecastViews=["result","evidence","score"];
  const state = {subject:null,module:"overview",forecastStage:null,forecastStageAuto:true,forecastView:"result",forecastCampaign:null,grain:"week",period:null,rawFile:0,rawSheet:0,rawQuery:"",rawFreezeRow:true,rawFreezeColumn:true};
  const forecastDrafts=new Map();
  const forecastDraftSelector='[data-forecast-target],[data-forecast-input],[data-forecast-allocation],[data-forecast-ref],[data-forecast-ref-weight],[data-forecast-chart-ref],[data-small-ref],[data-small-weight],[data-small-input],[data-steady-ref],[data-steady-weight],[data-bridge-control],[data-lifecycle-ref],[data-lifecycle-weight],[data-lifecycle-chart-ref]';
  const forecastImportScopes=new Map();
  let forecastStorageWarning='';
  const forecastStorageKey='harmony-forecast-v1:'+location.pathname;
  const forecastDraftControlKey=control=>`${control.closest('[data-bridge-stage]')?.dataset.bridgeStage||''}|${control.tagName}|${[...control.attributes].filter(attr=>attr.name.startsWith('data-')||attr.name==='type'||(attr.name==='value'&&['checkbox','radio'].includes(control.type))).map(attr=>`${attr.name}=${attr.value}`).sort().join('|')}`;
  function captureForecastDraft(){
    const root=document.querySelector('.forecast-workspace.forecast-v2');
    if(state.module!=="sales_forecast"||!root||root.dataset.forecastDirty!=="true")return;
    const meta=root._forecastDraftState?.()||{};
    forecastDrafts.set(root._forecastSubjectId||state.subject,{generatedAt:DATA.meta?.generated_at,meta,controls:[...root.querySelectorAll(forecastDraftSelector)].filter(control=>root._forecastTouched?.has(forecastDraftControlKey(control))||(meta.manualOverride&&['conversion','direct','lock'].includes(control.dataset.forecastInput))).map(control=>({key:forecastDraftControlKey(control),value:control.value,checked:control.type==='checkbox'?control.checked:null}))});
    return persistForecastState();
  }
  function restoreForecastDraft(){
    const root=document.querySelector('.forecast-workspace.forecast-v2'),draft=forecastDrafts.get(root?._forecastSubjectId||state.subject);
    if(!root||!draft)return;
    const controls=new Map([...root.querySelectorAll(forecastDraftSelector)].map(control=>[forecastDraftControlKey(control),control]));
    root._forecastTouched=new Set();
    draft.controls.forEach(saved=>{const control=controls.get(saved.key);if(!control||control.disabled)return;if(control.tagName==='SELECT'&&![...control.options].some(option=>option.value===saved.value&&!option.disabled))return;control.value=saved.value;if(saved.checked!==null)control.checked=saved.checked;root._forecastTouched.add(saved.key)});
    root.dataset.forecastDirty="true";root._forecastRestoreDraft?.(draft.meta||{});
    const feedback=root.querySelector('[data-forecast-feedback]');if(feedback){feedback.dataset.state=forecastStorageWarning?'loading':'success';feedback.querySelector('span').textContent=forecastStorageWarning?'仅当前页保存':'已恢复本机草稿';feedback.title=forecastStorageWarning||(draft.generatedAt!==DATA.meta?.generated_at?'数据版本已更新：只恢复人工修改项，真实订单和未修改参数采用本次生成数据。':'已恢复当前浏览器保存的人工参数。');}
  }

  const importedForecastRows = new Map();
  // Per-page local storage: no uploads, and never store actual-order payloads.
  function persistForecastState(){
    try{
      localStorage.setItem(forecastStorageKey,JSON.stringify({version:1,drafts:[...forecastDrafts],imports:[...importedForecastRows],scopes:[...forecastImportScopes]}));
      forecastStorageWarning='';return true;
    }catch(error){
      forecastStorageWarning='本机保存失败（浏览器限制或空间不足）；当前页仍可使用，刷新可能恢复到上次成功保存的状态。';
      return false;
    }
  }
  function loadForecastState(){
    try{
      const raw=localStorage.getItem(forecastStorageKey);if(!raw)return;
      if(raw.length>8*1024*1024)throw Error('保存的数据过大');
      const saved=JSON.parse(raw);
      if(saved?.version!==1||!['drafts','imports','scopes'].every(key=>Array.isArray(saved[key])&&saved[key].length<=500))throw Error('保存格式不兼容');
      const drafts=[],imports=[],scopes=[];
      for(const entry of saved.drafts){
        if(!Array.isArray(entry)||entry.length!==2)throw Error('参数草稿损坏');
        const [key,draft]=entry;
        if(typeof key!=='string'||!Array.isArray(draft?.controls)||draft.controls.length>3000||!draft.controls.every(item=>typeof item?.key==='string'&&typeof item.value==='string'&&[null,true,false].includes(item.checked)))throw Error('参数草稿损坏');
        drafts.push([key,draft]);
      }
      for(const entry of saved.imports){
        if(!Array.isArray(entry)||entry.length!==2)throw Error('外部预测保存记录损坏');
        const [key,item]=entry,seen=new Set();
        if(typeof key!=='string'||!Array.isArray(item?.rows)||item.rows.length>20000)throw Error('外部预测保存记录损坏');
        for(const row of item.rows){
          const identity=(row.metric||row.stage)+'|'+row.date,validDate=typeof row.date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(row.date)&&Number.isFinite(Date.parse(row.date+'T00:00:00Z'))&&new Date(row.date+'T00:00:00Z').toISOString().slice(0,10)===row.date;
          if(!validDate||typeof row.model!=='string'||!forecastStages.some(stage=>stage.id===row.stage)||(row.metric&&!['small','gross','lock'].includes(row.metric))||!Number.isSafeInteger(row.quantity)||row.quantity<0||seen.has(identity))throw Error('外部预测保存记录损坏');
          seen.add(identity);
        }
        imports.push([key,item]);
      }
      for(const [key,value] of saved.scopes){
        if(typeof key!=='string'||!value||!Object.values(value).every(scope=>['future','all'].includes(scope)))throw Error('导入范围保存记录损坏');
        scopes.push([key,value]);
      }
      for(const [key,value] of drafts)forecastDrafts.set(key,value);
      for(const [key,value] of imports)importedForecastRows.set(key,value);
      for(const [key,value] of scopes)forecastImportScopes.set(key,value);
    }catch(error){forecastStorageWarning='本机保存内容不可读取，已使用系统默认值；原保存内容未删除。'}
  }
  loadForecastState();
  window.addEventListener('pagehide',()=>captureForecastDraft());
  window.addEventListener('beforeunload',()=>captureForecastDraft());
  function bindForecastImport(root, context) {
    const stages={small:['小订','小订量'],launch:['首销','总大定'],steady:['平销','交车锁单']};
    const stageFor=(date,target,preferred)=>{
      const windows={small:!!target.smallStartDate&&date>=target.smallStartDate&&date<=target.smallEndDate,launch:!!target.launchDate&&date>=target.launchDate&&date<=context.stageInfo(target).end,steady:!!target.steadyStartDate&&date>=target.steadyStartDate};
      return windows[preferred]?preferred:Object.keys(windows).find(key=>windows[key])||'';
    };
    const metricOf=row=>row.metric||(row.stage==='small'?'small':row.stage==='steady'?'lock':'gross');
    const cards=[];
    for(const [stage,[label,unit]] of Object.entries(stages)){
      const anchor=root.querySelector(`[data-forecast-import-anchor="${stage}"]`);if(!anchor)continue;
      const card=document.createElement('section');card.className='forecast-import';card.dataset.forecastImport=stage;
      card.innerHTML='<div class="forecast-import-head"><div><small>预测曲线外部对照</small><h4>外部逐日预测 · '+label+'</h4></div><p>三个阶段共用导入：小订量、总大定分列；平销总大定按大定到锁单率换算。导入值独立展示，不覆盖真实订单或算法结果。</p></div><div class="forecast-import-actions"><label>导入方式<select data-forecast-import-mode aria-label="外部预测导入方式"><option value="merge">合并（同指标同日更新）</option><option value="replace">替换该车型全部外部预测</option></select></label><label>选择Excel/CSV<input type="file" accept=".xlsx,.csv" data-forecast-import-file aria-label="导入'+label+'逐日预测"></label><button type="button" data-forecast-import-template>下载CSV模板</button><button type="button" data-forecast-import-clear>清除该车型全部导入</button></div><p class="forecast-import-help">字段：车型（代际）、日期、预测小订、预测大定（总大定，不是留存大定）；数量为非负整数，可只填其中一列。一次导入供三个阶段使用；按各阶段日期展示，保留已过日期预测。</p><p role="status" aria-live="polite" data-forecast-import-status>尚未导入；成功后自动保存到当前浏览器，不上传。</p><div data-forecast-import-result></div>';
      anchor.append(card);cards.push({stage,unit,card});
      const status=card.querySelector('[data-forecast-import-status]'),input=card.querySelector('[data-forecast-import-file]');
      input.onchange=async()=>{
        const file=input.files?.[0];if(!file)return;
        const mode=card.querySelector('[data-forecast-import-mode]').value;
        for(const {card:other} of cards)other.querySelectorAll('[data-forecast-import-file],[data-forecast-import-mode],[data-forecast-import-clear]').forEach(control=>control.disabled=true);
        card.setAttribute('aria-busy','true');status.dataset.state='loading';status.textContent='正在读取并校验…';
        try{
          const target=context.targetState(),all=await window.ForecastImport.read(file),rows=all.filter(row=>context.sameModel(row.model,target.name)).flatMap(row=>{
            const entries=row.quantity!==undefined?[[stage==='small'?'small':'gross',row.quantity]]:[['small',row.small],['gross',row.gross]];
            return entries.filter(([,quantity])=>quantity!==undefined).map(([metric,quantity])=>({model:row.model,date:row.date,metric,quantity,stage:metric==='small'?'small':stageFor(row.date,target,'launch')||'launch',source:file.name}));
          });
          if(!rows.length)throw Error('没有匹配当前车型“'+target.name+'”的记录，请使用当前代际名或已映射的历史传播名');
          const seen=new Set();
          for(const row of rows){const key=row.metric+'|'+row.date;if(seen.has(key))throw Error(row.date+'同指标重复（含别名映射后的重复）');seen.add(key);}
          if(!root.isConnected)return;
          const previous=importedForecastRows.get(target.name);
          if(mode==='replace'&&previous?.rows.length&&!window.confirm('替换当前车型全部阶段的外部预测？原有'+previous.rows.length+'条记录将被本文件替换。真实订单和算法结果不受影响。')){status.dataset.state='';status.textContent='已取消替换，原导入数据保持不变。';return;}
          const merged=new Map((mode==='merge'?previous?.rows||[]:[]).map(row=>[metricOf(row)+'|'+row.date,row]));
          let updated=0;for(const row of rows){const key=metricOf(row)+'|'+row.date;if(merged.has(key))updated++;merged.set(key,row);}
          if(merged.size>20000)throw Error('合并后超过20000条记录，请清理旧外部预测或选择替换');
          importedForecastRows.set(target.name,{filename:file.name,rows:[...merged.values()].sort((a,b)=>a.date.localeCompare(b.date)||a.stage.localeCompare(b.stage))});
          const saved=persistForecastState();
          status.dataset.state=saved?'success':'loading';status.textContent='导入成功：'+rows.length+'条；'+(mode==='merge'?'合并后共'+merged.size+'条，同指标同日更新'+updated+'条':'已替换当前车型全部外部预测')+(all.some(row=>!context.sameModel(row.model,target.name))?'；其他车型记录未导入':'')+'。'+(saved?'已保存本机，刷新可恢复。':forecastStorageWarning);
          render();
        }catch(error){status.dataset.state='error';status.textContent='导入失败：'+error.message+'；原导入数据保持不变。';}
        finally{for(const {card:other} of cards)other.querySelectorAll('[data-forecast-import-file],[data-forecast-import-mode],[data-forecast-import-clear]').forEach(control=>control.disabled=false);input.value='';card.setAttribute('aria-busy','false');}
      };
      card.querySelector('[data-forecast-import-clear]').onclick=()=>{importedForecastRows.delete(context.targetState().name);const saved=persistForecastState();for(const {card:other} of cards){const notice=other.querySelector('[data-forecast-import-status]');notice.dataset.state=saved?'success':'loading';notice.textContent='已清除当前车型全部阶段的导入数据。'+(saved?'本机保存已同步。':forecastStorageWarning);}render();};
      card.querySelector('[data-forecast-import-template]').onclick=()=>{
        const target=context.targetState(),date=stage==='small'?target.smallStartDate:stage==='launch'?target.launchDate:target.steadyStartDate;
        const text='\uFEFF车型（代际）,日期,预测小订,预测大定\r\n'+[target.name,date||context.todayIso(),'',0].map(csvCell).join(',')+'\r\n';
        const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download='逐日预测导入模板.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      };
    }
    function render(){
      const target=context.targetState(),imported=importedForecastRows.get(target.name),today=context.todayIso(),actual=context.actualForTarget(target);
      const rawRate=root.querySelector('[data-forecast-input="lock"]')?.value;
      const lockRate=rawRate!=null&&rawRate.trim()!==''?Number(rawRate)/100:NaN,validRate=Number.isFinite(lockRate)&&lockRate<=1&&(lockRate>0||(lockRate===0&&root._forecastTouched?.has(forecastDraftControlKey(root.querySelector('[data-forecast-input="lock"]')))));
      for(const {stage,unit,card} of cards){
        const node=card.querySelector('[data-forecast-import-result]'),notice=card.querySelector('[data-forecast-import-status]');
        const rows=(imported?.rows||[]).filter(row=>(stage==='small'?metricOf(row)==='small':['gross','lock'].includes(metricOf(row)))&&stageFor(row.date,target,stage)===stage&&(metricOf(row)!=='lock'||stage==='steady'));
        const forecasts=new Map();
        for(const row of rows){
          const value=stage==='steady'&&metricOf(row)==='gross'?(validRate?Math.round(row.quantity*lockRate):null):row.quantity;
          if(metricOf(row)==='lock'&&forecasts.has(row.date))continue;
          forecasts.set(row.date,{...row,value});
        }
        const actualRows=context.actualRows(stage,target,actual).filter(row=>row.date<=today&&stageFor(row.date,target,stage)===stage);
        const actualMap=new Map(actualRows.filter(row=>Number.isFinite(row.value)&&row.value>=0).map(row=>[row.date,row.value]));
        const dates=[...new Set([...forecasts.keys(),...actualMap.keys()])].sort();
        if(!notice.dataset.state&&imported){notice.dataset.state='success';notice.textContent='已恢复外部预测，共'+imported.rows.length+'条；三个阶段共享，按各自日期展示。';}
        if(!dates.length){node.innerHTML='<p>当前阶段暂无实际或外部预测数据。</p>';continue;}
        const values=dates.map(date=>forecasts.get(date)?.value??null),known=values.filter(Number.isFinite),total=known.reduce((a,b)=>a+b,0);
        const rateNote=stage==='steady'?(validRate?'外部预测锁单＝导入总大定 × '+(lockRate*100).toFixed(1)+'%（当前首销预测参数“大定到锁单率”，可人工调整；非留存大定率）。':'大定到锁单率缺失或无效，暂不能换算；已保留导入总大定。'):'导入值独立展示，不覆盖实际或系统预测。';
        node.innerHTML='<p><b>外部预测合计：'+(known.length?fmt(total):'—')+' 单（'+unit+'）</b>；'+esc(rateNote)+'</p>'+renderLifecycleLineChart({
          series:[{label:'实际'+unit+'（当天如有则为未完日快照）',values:dates.map(date=>actualMap.get(date)??null),color:'#1677FF',role:'actual'},{label:'外部预测（'+unit+'）',values,color:'#7C3AED',role:'reference',dashed:true}],
          labels:dates,unit:'number',title:stages[stage][0]+'实际与外部逐日预测',ariaLabel:stages[stage][0]+'外部逐日预测折线图',note:'仅展示本阶段日期。已过日期的导入预测保留；缺失留空，不补零；当日实际尚未结束。'
        })+'<details><summary>查看逐日预测</summary><div class="forecast-score-table"><table><thead><tr><th>日期</th><th>实际'+unit+'</th><th>外部预测'+unit+'</th>'+(stage==='steady'?'<th>导入总大定</th>':'')+'<th>来源文件</th></tr></thead><tbody>'+dates.map(date=>'<tr><td>'+esc(date)+(date===today?'（当日未结束）':'')+'</td><td>'+fmt(actualMap.get(date)??null)+'</td><td>'+fmt(forecasts.get(date)?.value??null)+'</td>'+(stage==='steady'?'<td>'+fmt(metricOf(forecasts.get(date)||{})==='gross'?forecasts.get(date)?.quantity??null:null)+'</td>':'')+'<td>'+esc(forecasts.get(date)?.source||'')+'</td></tr>').join('')+'</tbody></table></div></details>';
      }
    }
    root._renderImportedForecast=render;render();
  }

  const boardCache={};
  async function getDashboard(subjectId=state.subject,moduleId=state.module){
    const ownerId=moduleId==="sales_forecast"?(DATA.subjects.find(item=>item.modules.includes("sales_forecast"))?.id||subjectId):subjectId;
    const key=`${ownerId}|${moduleId}`;
    if(!(key in boardCache)){
      const b64=(DATA.dashboard_blocks||{})[key];
      boardCache[key]=b64?unpackDashboard(await decompressJson(b64)):null;
    }
    return boardCache[key];
  }
  function subject(){return DATA.subjects.find(item=>item.id===state.subject)}
  const quickBrandOrder=['问界','智界','享界','尊界','尚界'];
  const generationYear=name=>Math.max(...[...String(name||'').matchAll(/(20\d{2})\s*款/g)].map(match=>Number(match[1])),0);
  const generationAggregate=name=>String(name||'').match(/(总计|汇总|合计)\s*$/)?.[1]||'';
  const generationModelKey=name=>String(name||'').replace(/20\d{2}\s*款/g,'').replace(/总计|汇总|合计/g,'').replace(/\s+/g,'').toLowerCase();
  const quickGenerationExcluded=name=>/beta|预订|直订|盲订/i.test(String(name||''));
  const quickGenerationFamilyKey=name=>generationModelKey(name).replace(/增程|纯电|智驾版|标准版/g,'');
  const generationShortName=name=>{const raw=String(name||'').trim(),aggregate=generationAggregate(raw),value=raw.replace(/(总计|汇总|合计)\s*$/,'').trim(),year=generationYear(value),brand=quickBrandOrder.find(item=>value.startsWith(item))||value.match(/^[\u4e00-\u9fff]{1,3}界/)?.[0]||'',model=value.slice(brand.length).replace(/20\d{2}\s*款/g,'').replace(/\s+Ultimate\b/ig,'U').replace(/\s+典藏大观\b/g,'大观').replace(/\s+/g,' ').trim(),yearLabel=year?` ${String(year).slice(-2)}`:'';return `${model||value}${yearLabel}${aggregate}`};
  function latestQuickGenerations(){
    const candidates=DATA.subjects.filter(item=>item.type==='generation').filter(item=>!quickGenerationExcluded(item.name));
    const newestYear=new Map();
    candidates.forEach(item=>{const key=quickGenerationFamilyKey(item.name);newestYear.set(key,Math.max(newestYear.get(key)||0,generationYear(item.name)))});
    const latest=new Map();
    candidates.forEach(item=>{const year=generationYear(item.name);if(year<newestYear.get(quickGenerationFamilyKey(item.name)))return;const key=generationModelKey(item.name)+'|'+generationAggregate(item.name),old=latest.get(key);if(!old||year>generationYear(old.name)||(year===generationYear(old.name)&&item.name.localeCompare(old.name,'zh-CN')<0))latest.set(key,item)});
    return [...latest.values()].sort((left,right)=>{const brandLeft=quickBrandOrder.indexOf(left.parent),brandRight=quickBrandOrder.indexOf(right.parent);return (brandLeft<0?quickBrandOrder.length:brandLeft)-(brandRight<0?quickBrandOrder.length:brandRight)||generationModelKey(left.name).localeCompare(generationModelKey(right.name),'en')||left.name.localeCompare(right.name,'zh-CN')});
  }
  function syncTopbarQuickLayout(){
    const topbar=document.querySelector('.topbar'),list=$('#quickGenerationList');if(!topbar||!list)return;
    const rows=new Set([...list.children].map(button=>button.offsetTop));
    topbar.classList.toggle('quick-generation-wrapped',rows.size>1);
  }
  function renderQuickGenerationLinks(){
    const list=$('#quickGenerationList');if(!list)return;
    list.innerHTML=latestQuickGenerations().map(item=>`<button type="button" class="quick-generation-button${item.id===state.subject?' active':''}" data-quick-generation="${esc(item.id)}" title="${esc(item.name)}" aria-label="${esc(item.name)}" aria-pressed="${item.id===state.subject}">${esc(generationShortName(item.name))}</button>`).join('');
    syncTopbarQuickLayout();
  }
  const rawForecastModelKey=value=>String(value||"").toLowerCase().replace(/鸿蒙智行|车型|款|总计|汇总|合计|\s|[()（）/\\_&-]/g,"");
  const forecastModelAliases=()=>{const owner=DATA.subjects.find(item=>item.modules.includes("sales_forecast")),board=owner?boardCache[`${owner.id}|sales_forecast`]:null;return forecastDataFromBoard(board)?.model_aliases||{}};
  const forecastModelKey=(value,aliases=forecastModelAliases())=>{const raw=rawForecastModelKey(value);return rawForecastModelKey(aliases[raw]||value)};
  const sameForecastModel=(leftValue,rightValue,aliases=forecastModelAliases())=>{const left=forecastModelKey(leftValue,aliases),right=forecastModelKey(rightValue,aliases);return !!left&&!!right&&left===right};
  const moduleAvailable=(item,moduleId)=>moduleId==="sales_forecast"
    ?item.type==="generation"&&DATA.subjects.some(candidate=>candidate.modules.includes("sales_forecast"))
    :item.modules.includes(moduleId);
  function forecastDataFromBoard(board){const view=Object.values(board?.views||{})[0],page=Object.values(view?.pages||{})[0];return page?.workspace?.data}
  function linkedForecastData(data){
    const selected=subject();
    if(!data||selected?.type!=="generation")return data;
    const campaigns=(data.targets||[]).filter(item=>sameForecastModel(item.primary_generation||item.name,selected.name));
    const steady=(data.steady_targets||[]).find(item=>sameForecastModel(item.name,selected.name));
    const option=state.forecastStage==='steady'&&steady?steady:campaigns.find(item=>item.name===state.forecastCampaign)||campaigns.find(item=>item.stage==='active')||campaigns.toSorted((a,b)=>String(b.launch_date||'').localeCompare(String(a.launch_date||'')))[0];
    if(!option)return data;
    const original=data.target||{};
    if(sameForecastModel(option.name,original.name))return {...data,target:{...original,...option,name:option.name,launch_days:option.days??original.launch_days,total_small:Number(option.small??0)}};
    const reference=(data.history||[]).find(item=>sameForecastModel(item.model,option.history_model||option.name));
    return {...data,target:{
      name:option.name,primary_generation:option.primary_generation||option.name,secondary_generation:option.secondary_generation||"",has_small:option.has_small,history_model:option.history_model||reference?.model||"",
      tier:option.tier||reference?.tier||"未维护",energy:option.energy||reference?.energy||"未维护",
      launch_node:option.node||reference?.node||"未维护",launch_date:option.launch_date??reference?.launch_date??"",
      end_date:option.end_date??reference?.end_date??"",stage:option.stage||"unknown",stage_label:option.stage_label||"时间缺失",calendar_day:Number(option.calendar_day||0),date_source_label:option.date_source_label||"日期数据缺失",
      small_start_date:option.small_start_date||"",small_end_date:option.small_end_date||"",small_stage:option.small_stage||"unknown",small_stage_label:option.small_stage_label||"小订时间缺失",small_calendar_day:Number(option.small_calendar_day||0),small_days:Number(option.small_days||0),steady_start_date:option.steady_start_date||"",
      selected_source:option.selected_source||"missing",selected_source_label:option.selected_source_label||"数据缺失",data_missing:!!option.data_missing,
      field_sources:option.field_sources||{},missing_fields:option.missing_fields||[],source_latest_date:option.source_latest_date||"",
      launch_weekday:option.launch_weekday||reference?.launch_weekday||"未维护",launch_period:option.launch_period||reference?.launch_period||"未维护",
      launch_days:Number(option.days??reference?.days??35),total_small:Number(option.small??0),
      conversion:Number(reference?.conversion??0),direct_share:Number(reference?.direct_share??0),lock_rate:Number(reference?.lock_rate??0),
    }};
  }

  function linkedForecastSource(workspace){
    const data=workspace?.data||{},target=data.target||{},actual=(data.actuals||[]).find(item=>sameForecastModel(item.model,target.name,data.model_aliases||{}));
    return actual?.day_source||workspace?.source;
  }

  function forecastStageFromTarget(target){
    if(target?.stage==="ended")return "steady";
    if(target?.stage==="active")return "launch";
    if(target?.stage==="before")return "small";
    return ["before","d1","active","ended"].includes(target?.small_stage)?"small":"launch";
  }
  async function syncForecastStageToTarget(){
    if(state.module!=="sales_forecast"||!state.forecastStageAuto)return;
    const board=await getDashboard(),data=linkedForecastData(forecastDataFromBoard(board));
    state.forecastStage=forecastStageFromTarget(data?.target);
  }
  function syncUrl(mode="replace"){
    try{
      const url=new URL(location.href),params=url.searchParams;
      params.set("subject",state.subject||"");params.set("module",state.module);
      if(state.module==="sales_forecast"){params.set("forecastStage",state.forecastStage||"launch");params.set("forecastView",state.forecastView||"result");if(state.forecastCampaign)params.set("forecastCampaign",state.forecastCampaign);else params.delete("forecastCampaign")}else{params.delete("forecastStage");params.delete("forecastView");params.delete("forecastCampaign")}
      if(!["sales_forecast","generic","raw"].includes(state.module)){params.set("grain",state.grain);if(state.period)params.set("period",state.period)}else{params.delete("grain");params.delete("period")}
      history[`${mode}State`]({dashboard:true},"",url);
    }catch(error){console.debug("[导航状态] 当前环境不支持写入网址",error)}
  }
  async function restoreLocationState(){
    captureForecastDraft();
    const params=new URLSearchParams(location.search),requested=params.get("subject"),requestedSubject=DATA.subjects.find(item=>item.id===requested||item.name===requested);
    if(requestedSubject)state.subject=requestedSubject.id;
    state.module=params.get("module")||state.module;
    state.grain=params.get("grain")||state.grain;state.period=params.get("period")||null;
    if(state.module==="launch_rhythm"&&!params.get("grain"))state.grain="day";
    const requestedStage=params.get("forecastStage");state.forecastStageAuto=!forecastStages.some(item=>item.id===requestedStage);if(!state.forecastStageAuto)state.forecastStage=requestedStage;
    state.forecastCampaign=params.get("forecastCampaign")||null;
    const requestedView=params.get("forecastView");state.forecastView=forecastViews.includes(requestedView)?requestedView:"result";
    await ensureState();await renderAll();
  }

  async function init(){
    const params=new URLSearchParams(location.search),requested=params.get("subject");
    const requestedSubject=DATA.subjects.find(item=>item.id===requested||item.name===requested);
    state.subject=(requestedSubject||DATA.subjects.find(item=>item.modules.includes("overview"))||DATA.subjects[0]).id;
    state.module=params.get("module")||state.module;
    state.grain=params.get("grain")||state.grain;state.period=params.get("period")||state.period;
    if(state.module==="launch_rhythm"&&!params.get("grain"))state.grain="day";
    if(forecastStages.some(item=>item.id===params.get("forecastStage"))){state.forecastStage=params.get("forecastStage");state.forecastStageAuto=false}
    state.forecastCampaign=params.get("forecastCampaign")||null;
    if(forecastViews.includes(params.get("forecastView")))state.forecastView=params.get("forecastView");
    $("#updatedAt").textContent=`生成时间 ${DATA.meta.generated_at.replace("T"," ")}`;
    bindStatic();renderSubjectSelect();await ensureState();await renderAll();syncUrl("replace");
  }
  function bindStatic(){
    $("#subjectSelect").onchange=async event=>{captureForecastDraft();state.subject=event.target.value;if(state.module==="sales_forecast")state.forecastStageAuto=true;await ensureState();await renderAll();syncUrl("push")};
    $("#quickGenerationList").onclick=async event=>{const button=event.target.closest('[data-quick-generation]');if(!button)return;captureForecastDraft();state.subject=button.dataset.quickGeneration;if(state.module==="sales_forecast")state.forecastStageAuto=true;await ensureState();await renderAll();syncUrl("push")};
    $("#grainSelect").onclick=async event=>{const button=event.target.closest("button");if(!button||button.disabled)return;state.grain=button.dataset.grain;const board=await getDashboard();const view=board?.views?.[state.grain];state.period=view?.default_period||null;await renderAll();syncUrl("push")};
    $("#periodSelect").onchange=async event=>{if(state.module==="sales_forecast"){captureForecastDraft();state.forecastCampaign=event.target.value;await renderAll()}else{state.period=event.target.value;await renderPage()}syncUrl("push")};
    window.addEventListener("popstate",()=>restoreLocationState());
    window.addEventListener("resize",syncTopbarQuickLayout,{passive:true});
  }
  async function ensureState(){
    let item=subject();
    if(!moduleAvailable(item,state.module))state.module=item.modules.find(id=>id!=="raw")||"raw";
    if(state.module==="raw")return;
    const board=await getDashboard();
    const grains=Object.keys(board?.views||{});
    if(!grains.includes(state.grain))state.grain=grains[0]||"week";
    const view=board?.views?.[state.grain];
    if(!(view?.periods||[]).includes(state.period))state.period=view?.default_period||null;
    await syncForecastStageToTarget();
  }
  function renderSubjectSelect(){
    const order=state.module==="sales_forecast"?[["generation","预测代际"]]:[["group","集团"],["brand","品牌"],["generation","代际"]];
    let subjects=DATA.subjects;
    if(state.module==="sales_forecast"){
      const owner=DATA.subjects.find(item=>item.modules.includes("sales_forecast")),board=owner?boardCache[`${owner.id}|sales_forecast`]:null,targetNames=(forecastDataFromBoard(board)?.targets||[]).map(item=>item.primary_generation||item.name);
      const generations=DATA.subjects.filter(item=>item.type==="generation"),seen=new Set();
      subjects=targetNames.map(name=>generations.find(item=>item.name.replace(/\s+/g,'')===String(name).replace(/\s+/g,''))||generations.find(item=>sameForecastModel(item.name,name))).filter(item=>item&&!seen.has(item.id)&&seen.add(item.id));
    }
    $("#subjectSelect").innerHTML=order.map(([type,label])=>`<optgroup label="${label}">${subjects.filter(item=>item.type===type).map(item=>`<option value="${item.id}">${esc(item.name)}</option>`).join("")}</optgroup>`).join("");
    $("#subjectSelect").value=state.subject;
  }
  let navigationRevision=0,pageRevision=0;
  async function renderAll(){
    const revision=++navigationRevision,status=$("#pageStatus"),page=$("#page");
    page.setAttribute("aria-busy","true");
    const timer=setTimeout(()=>{if(revision===navigationRevision&&status){status.textContent="正在加载分析…";status.classList.add("show")}},180);
    try{renderSubjectSelect();renderQuickGenerationLinks();renderNav();await renderFilters();if(revision===navigationRevision)await renderPage()}
    finally{clearTimeout(timer);if(revision===navigationRevision){page.setAttribute("aria-busy","false");status?.classList.remove("show")}}
  }
  // Display-only summary of the existing explanation; never selects or changes data.
  function forecastSourceBrief(text){
    const value=String(text||''),short=name=>name.replaceAll('小订及首销数据整理','整理表').replaceAll('首销期订单节奏','首销节奏');
    if(/缺失|异常|不可用|原始数据错误/.test(value))return '数据缺失/异常';
    const main=value.match(/主来源([^，；（。]+)/)?.[1];
    if(main){
      const names=new Set([main]);
      const fields=value.split('字段来源：')[1]||'';
      fields.split('；').forEach(field=>{const match=field.match(/^(?:总小订|首销日明细|分时进度)：(.+)$/);if(match)names.add(match[1])});
      return names.size>1?'混合来源：'+[...names].map(short).join('＋'):'来源：'+short(main);
    }
    const finalSmall=value.match(/最终总小订取自([^。；]+)/)?.[1];
    if(finalSmall)return '总小订：'+short(finalSmall);
    const completed=value.match(/已发生(\d+)个完整日/)?.[1];
    if(completed)return '实绩：'+completed+'个完整日';
    if(/主辅参考|参考最终小订/.test(value))return '参考测算';
    if(/分时累计|分时进度/.test(value))return '分时实绩与估算';
    return '依据：'+(value.split(/[。；]/)[0]||'待核对');
  }
  function refreshForecastHeaderBrief(root){
    const source=root.querySelector('[data-forecast-day-source]')?.textContent||'';
    const time=root.querySelector('[data-forecast-time-summary]')?.textContent||'';
    const brief=root.querySelector('[data-forecast-source-brief]'),date=root.querySelector('[data-forecast-time-brief]');
    if(brief){brief.textContent=forecastSourceBrief(source);brief.title=source;brief.dataset.warning=String(/缺失|异常|不可用|原始数据错误/.test(source));}
    if(date){const day=time.match(/判定日期(\d{4}-\d{2}-\d{2})/)?.[1];date.textContent=day?'判定日 '+day:'判定日待核对';date.title=time;}
  }
  function showForecastStageSummary(root,id){
    if(!root)return;
    const suffix=id.charAt(0).toUpperCase()+id.slice(1),label=forecastStages.find(item=>item.id===id)?.label||"销量预测",badge=root.querySelector('[data-forecast-current-day]'),source=root.querySelector('[data-forecast-day-source]');
    if(badge)badge.textContent=root.dataset[`forecastStatus${suffix}`]||`${label}状态判定中`;
    if(source)source.textContent=root.dataset[`forecastSource${suffix}`]||`正在检查${label}的时间阶段与数据来源`;
    refreshForecastHeaderBrief(root);
  }
  function setForecastStageSummary(root,id,status,source){
    if(!root||!forecastStages.some(item=>item.id===id))return;
    const suffix=id.charAt(0).toUpperCase()+id.slice(1);
    if(status!==undefined)root.dataset[`forecastStatus${suffix}`]=status;
    if(source!==undefined)root.dataset[`forecastSource${suffix}`]=source;
    if(state.forecastStage===id)showForecastStageSummary(root,id);
  }
  function applyForecastView(root,id){
    if(!root||!forecastViews.includes(id))return;
    state.forecastView=id;
    const stage=forecastStages.some(item=>item.id===state.forecastStage)?state.forecastStage:"launch",prefix=stage==="launch"?"forecast":`${stage}-forecast`;
    root.querySelectorAll('[data-forecast-tab]').forEach(button=>{const active=button.dataset.forecastTab===id;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.setAttribute('aria-controls',`${prefix}-pane-${button.dataset.forecastTab}`);button.tabIndex=active?0:-1});
    root.querySelectorAll('[data-forecast-pane]').forEach(pane=>pane.classList.toggle('active',pane.dataset.forecastPane===id));
    root.querySelectorAll('[data-lifecycle-subpane]').forEach(pane=>pane.classList.toggle('active',pane.dataset.lifecycleSubpane===`${stage}-${id}`));
  }
  async function activateForecastStage(id,writeHistory=true){
    if(!forecastStages.some(item=>item.id===id))return;
    state.module="sales_forecast";state.forecastStage=id;state.forecastStageAuto=false;
    document.querySelectorAll("[data-forecast-stage-pane]").forEach(pane=>pane.classList.toggle("active",pane.dataset.forecastStagePane===id));
    const root=document.querySelector('.forecast-workspace.forecast-v2');showForecastStageSummary(root,id);applyForecastView(root,state.forecastView||"result");
    root?.querySelectorAll("[data-forecast-stage-switch]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.forecastStageSwitch===id)));
    const page=$("#page");if(page)page.scrollTo({top:0,behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});
    const owner=DATA.subjects.find(item=>item.modules.includes("sales_forecast")),source=forecastDataFromBoard(boardCache[`${owner?.id}|sales_forecast`]);
    if((source?.targets||[]).some(t=>t.secondary_generation&&sameForecastModel(t.primary_generation,subject()?.name))){captureForecastDraft();await renderFilters();await renderPage();}
    if(writeHistory)syncUrl("push");
  }
  function renderNav(){
    const item=subject();
    $("#moduleNav").innerHTML=DATA.config.module_order.map(id=>{
      const available=moduleAvailable(item,id),active=state.module===id;
      const hint=id==="sales_forecast"?"请选择具体车型（代际）后查看":"当前主体没有对应Sheet";
      return '<button data-module="'+id+'" class="'+(active?'active':'')+'" '+(active?'aria-current="page" ':'')+(available?'':'disabled ')+'title="'+(available?moduleLabels[id]:hint)+'">'+moduleLabels[id]+'</button>';
    }).join("");
    $("#moduleNav").onclick=async event=>{
      const button=event.target.closest("[data-module]");
      if(!button||button.disabled||button.dataset.module===state.module)return;
      captureForecastDraft();state.module=button.dataset.module;if(state.module==="sales_forecast")state.forecastStageAuto=true;if(state.module==="launch_rhythm")state.grain="day";await ensureState();await renderAll();syncUrl("push");
    };
  }
  function parseDay(text){
    const value=String(text||"").trim();
    let match=value.match(/^(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})/);
    if(match)return new Date(+match[1],+match[2]-1,+match[3]).getTime();
    match=value.match(/^(\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})$/);
    if(match)return new Date(2000+ +match[1],+match[2]-1,+match[3]).getTime();
    return null;
  }
  function sortPeriods(periods,grain){
    if(grain!=="day"||!(periods&&periods.length))return periods;
    return [...periods].sort((a,b)=>{
      const pa=parseDay(a),pb=parseDay(b);
      if(pa===null||pb===null)return 0;
      return pa-pb;
    });
  }
  async function renderFilters(){
    $("#filters").style.display="grid";
    $("#subjectSelect").closest("label").style.display="";
    $("#grainSelect").closest(".filter-group").style.display="";
    $("#periodSelect").closest("label").style.display="";
    if(["sales_forecast","generic","raw"].includes(state.module)){
      $("#grainSelect").innerHTML=Object.entries(DATA.config.grain_labels).map(([id,label])=>`<button data-grain="${id}" disabled>${label}</button>`).join("");
      const board=state.module==="sales_forecast"?await getDashboard():null,data=forecastDataFromBoard(board),selected=subject(),campaigns=(data?.targets||[]).filter(t=>sameForecastModel(t.primary_generation||t.name,selected?.name));
      const period=$("#periodSelect");
      if(state.module==="sales_forecast"&&state.forecastStage!=='steady'&&campaigns.some(t=>t.secondary_generation)){
        const current=linkedForecastData(data)?.target,small=state.forecastStage==='small';
        period.innerHTML=campaigns.map(t=>{const label=t.secondary_generation?.startsWith(t.primary_generation)?t.secondary_generation.slice(t.primary_generation.length).trim():t.secondary_generation||t.name;return `<option value="${esc(t.name)}">${esc(label)} · ${esc((small?t.small_start_date:t.launch_date)||'日期未维护')}—${esc((small?t.small_end_date:t.end_date)||'日期未维护')}</option>`}).join('');
        period.value=current?.name||campaigns[0]?.name;period.disabled=false;
      }else{period.innerHTML=`<option>${state.module==="sales_forecast"?(state.forecastStage==='steady'?'一级代际合并 · 平销':'按预测阶段窗口'):"按所选表格范围"}</option>`;period.disabled=true;}
      $("#grainSelect").title="此模块不使用日周月筛选";return;
    }
    $("#periodSelect").disabled=false;$("#grainSelect").title="";
    const board=await getDashboard();
    const grains=Object.keys(board?.views||{});
    $("#grainSelect").innerHTML=Object.entries(DATA.config.grain_labels).map(([id,label])=>`<button data-grain="${id}" class="${state.grain===id?"active":""}" ${grains.includes(id)?"":"disabled"}>${label}</button>`).join("");
    const view=board?.views?.[state.grain];
    const periodList=sortPeriods(view?.periods||[],state.grain);
    $("#periodSelect").innerHTML=periodList.map(period=>`<option value="${esc(period)}">${esc(period)}</option>`).join("");
    $("#periodSelect").value=state.period||"";
  }
  function alignOverviewChartScrollbars(){
    if(state.module!=="overview")return;
    document.querySelectorAll("#page .stacked-chart").forEach(chart=>{
      const align=()=>{chart.scrollLeft=Math.max(0,chart.scrollWidth-chart.clientWidth)};
      align();
      requestAnimationFrame(align);
    });
  }
  async function renderPage(){
    const revision=++pageRevision,moduleId=state.module,subjectId=state.subject;
    if(state.module==="raw"){await renderRaw();return}
    const board=await getDashboard(),page=board?.views?.[state.grain]?.pages?.[state.period];
    if(revision!==pageRevision||moduleId!==state.module||subjectId!==state.subject)return;
    if(!board||!page){$("#page").innerHTML='<div class="empty-page">当前主体暂无该分析</div>';return}
    if(page.layout==="workspace"&&page.workspace){
      const workspace=state.module==="sales_forecast"?{...page.workspace,data:linkedForecastData(page.workspace.data)}:page.workspace;
      if(state.module==="sales_forecast")workspace.source=linkedForecastSource(workspace);
      $("#page").innerHTML=renderWorkspacePage(workspace);
      if(state.module!=="sales_forecast")document.querySelector("[data-workspace-source]")?.addEventListener("click",()=>jumpToSource(workspace.source));
      bindForecastWorkspaceV2();restoreForecastDraft();
      return;
    }
    $("#page").innerHTML=`${renderKpis(page.kpis)}<div class="sections">${page.sections.map(renderSection).join("")}</div>`;
    alignOverviewChartScrollbars();
    document.querySelectorAll("[data-panel-source]").forEach(button=>button.onclick=()=>jumpToSource(page.sections[Number(button.dataset.panelSource)]?.source));
    document.querySelectorAll("[data-combo-switch]").forEach(button=>button.onclick=()=>{
      const root=button.closest(".combo-matrix"),target=button.dataset.comboSwitch;
      root.querySelectorAll("[data-combo-switch]").forEach(item=>{const active=item.dataset.comboSwitch===target;item.classList.toggle("active",active);item.setAttribute("aria-pressed",String(active))});
      root.querySelectorAll("[data-combo-panel]").forEach(item=>item.hidden=item.dataset.comboPanel!==target);
    });
    document.querySelectorAll("[data-hourly-select]").forEach(select=>select.onchange=()=>{
      const rows=JSON.parse(select.dataset.hourlyRows||"[]");
      select.closest(".hourly-wrap").querySelector("[data-hourly-body]").innerHTML=renderHourlyChart(rows,select.value);
    });
    document.querySelectorAll("[data-launch-hourly-select]").forEach(select=>select.onchange=()=>{
      const rows=JSON.parse(select.dataset.launchHourlyRows||"[]");
      select.closest(".hourly-wrap").querySelector("[data-launch-hourly-body]").innerHTML=renderLaunchHourlyChart(rows,select.value);
    });
    bindForecastWorkspaceV2();
  }
  function renderKpis(items){return `<div class="kpis ${items.length===5?"five":""}">${items.map(item=>`<article class="kpi" style="--accent:${colors[item.color]||colors.blue}"><span>${esc(item.label)}</span><strong>${fmt(item.value)}</strong><em>${esc(item.unit)}</em><small class="kpi-note">${esc(item.note)}</small>${renderKpiComparison(item)}</article>`).join("")}</div>`}
  function renderKpiComparison(item){
    const comparison=item.comparison;
    if(!comparison||comparison.status!=="available")return '<div class="kpi-compare neutral"><span>较上周期</span><b>暂无可比数据</b></div>';
    const direction=comparison.direction||"flat",verb=direction==="up"?"上涨":direction==="down"?"下降":"持平",arrow=direction==="up"?"↑":direction==="down"?"↓":"—";
    const movement=comparison.rate==null?`${fmt(Math.abs(comparison.delta))}${esc(item.unit)}`:`${Math.abs(comparison.rate*100).toFixed(1)}%`;
    return `<div class="kpi-compare ${direction}"><span>较上周期</span><b>${arrow} ${verb} ${movement}</b><em>上期 ${fmt(comparison.previous)}</em></div>`;
  }
  function renderSection(item,index){
    const pieBars=item.kind==='bars'&&item.title==='门店渠道订单量';
    const renderer=pieBars?renderPieChart:({stacked_trend:renderStackedTrend,table:renderTable,bars:renderBars,donut:renderPieChart,structure_cards:renderStructureCards,funnel:renderFunnel,cohort_matrix:renderCohortMatrix,rank_cards:renderRankCards,rise_rank_cards:data=>renderRankCards(data,'rise'),drop_rank_cards:data=>renderRankCards(data,'drop'),rights:renderRights,fee_band_structure:renderFeeBandStructure,fee_period_bands:renderFeePeriodBands,fee_heatmap:renderFeeHeatmap,heat_table:renderTable,sku_heatmap:renderSkuHeatmap,combo_heatmap:renderComboHeatmap,combo_matrix:renderComboMatrix,tail_distribution:renderTailDistribution,launch_composite:renderLaunch,launch_hourly:renderLaunchHourly,matrix:renderTable,trend:renderTrend,hourly:renderHourly,small_order_rhythm:renderSmallOrderRhythm,cancel_cards:renderCancelCards,history_table:renderHistoryTable,daily_cancel:renderDailyCancel}[item.kind]||renderUnknown);
    const body=renderer(item.data);
    const sourceButton=item.source?`<button class="panel-source" data-panel-source="${index}" aria-label="查看${esc(item.title)}的来源数据" title="跳转到底表"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7m0-7-9 9M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/></svg><span>来源数据</span></button>`:"";
    return `<article class="panel ${item.width==="half"?"":"full"}" data-section-kind="${esc(item.kind||"")}"><div class="panel-head"><div><h2>${esc(item.title)}</h2><span>${esc(item.meta)}</span></div>${sourceButton}</div><div class="panel-body">${body}</div></article>`;
  }
  function renderWorkspacePage(item){
    const renderer={forecast_workspace:renderForecastWorkspaceV2}[item.kind]||renderUnknown;
    return `<section class="page-workspace forecast-page"><div class="page-workspace-body">${renderer(item.data)}</div></section>`;
  }
  function renderStackedTrend(data){
    if(!data?.periods?.length)return '<div class="empty-image">图表Sheet暂无可绘制数据</div>';
    const originalImage=DATA.chart_assets?.[data.image_key];
    if(window.CHART_RENDER_MODE==="original"&&originalImage)return `<div class="original-chart"><img src="${originalImage}" alt="${esc(data.headline||"Excel原始图表")}"/></div>`;
    const trendLine="#0070C0",seriesFill=index=>stackedTrendPalette[index%stackedTrendPalette.length],periods=data.periods,series=data.series||[],totals=data.totals||[],maxTotal=chartMax(totals),labelMax=Math.max(...periods.map(period=>String(period||"").length),1),left=52,bottom=252,plotH=218,step=Math.max(42,Math.min(labelMax*4.8,90)),W=Math.max(380,periods.length*step+50),H=Math.max(310,bottom+Math.min(labelMax*4.2,80)+14),barW=stackedBarWidth(step);
    const segmentLabelYs=periods.map(()=>[]);
    const bars=periods.map((period,index)=>{const rates=series.map(item=>Math.max(0,Number(item.values[index]||0))),stackHeight=rates.reduce((sum,rate)=>sum+rate,0)*plotH;let y=bottom-stackHeight;const stacks=series.map((item,sIndex)=>{const rate=rates[sIndex],height=rate*plotH,segmentY=y;y+=height;if(!rate)return "";const labelY=avoidLabelY(segmentY+height/2,segmentLabelYs[index],12,bottom-4,12);segmentLabelYs[index].push(labelY);return `<rect x="${left+index*step+(step-barW)/2}" y="${segmentY}" width="${barW}" height="${height}" fill="${seriesFill(sIndex)}"/><text class="chart-data-label stack-segment-label" x="${left+index*step+step/2}" y="${labelY}" text-anchor="middle">${(rate*100).toFixed(0)}%</text>`}).join("");const lx=left+index*step+step-2,ly=bottom+13;return `${stacks}<text x="${lx}" y="${ly}" text-anchor="end" transform="rotate(-40 ${lx} ${ly})" font-size="9" fill="#718396">${esc(period)}</text>`}).join("");
    const points=totals.map((value,index)=>`${left+index*step+step/2},${bottom-Number(value)/maxTotal*plotH}`).join(" ");
    const values=totals.map((value,index)=>{const baseY=bottom-Number(value)/maxTotal*plotH-8,labelY=avoidLabelY(baseY,segmentLabelYs[index],12,bottom-8);return `<text class="chart-data-label total-label" x="${left+index*step+step/2}" y="${labelY}" text-anchor="middle">${fmt(value)}</text>`}).join("");
    const legend=series.map((item,index)=>`<span><i style="background:${seriesFill(index)}"></i>${esc(item.name)}</span>`).join("")+`<span><i class="line-key"></i>总计</span>`;
    return `<div class="stacked-chart"><svg viewBox="0 0 ${W} ${H}" style="width:${W}px;height:${H}px"><line x1="${left}" y1="${bottom}" x2="${W-20}" y2="${bottom}" stroke="#e6ebf1"/>${bars}<polyline points="${points}" fill="none" stroke="${trendLine}" stroke-width="2.5"/>${values}</svg></div><div class="legend trend-legend">${legend}</div>`;
  }
  function renderTable(data){
    if(!data?.columns)return '<div class="empty-image">暂无表格数据</div>';
    const formats=data.formats||[];
    const bodyRows=data.rows.map(row=>`<tr>${row.map((value,index)=>`<td class="${formats[index]&&formats[index]!=="text"?"num":""}">${formatTableCell(value,formats[index])}</td>`).join("")}</tr>`).join("")||`<tr><td class="table-empty" colspan="${data.columns.length}">暂无数据</td></tr>`;
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${data.columns.map((column,index)=>`<th class="${formats[index]&&formats[index]!=="text"?"num":""}">${esc(column)}</th>`).join("")}</tr></thead><tbody>${bodyRows}</tbody></table></div>`;
  }
  function renderHistoryBody(options,grain){
    const source=options[grain]||{columns:["周期"],rows:[]};
    return renderTable({columns:source.columns,rows:source.rows.slice().reverse(),formats:source.formats});
  }
  function renderHistoryTable(data){
    const options=data.granularities||{};
    const current=options[state.grain]?state.grain:(options[data.default]?data.default:(Object.keys(options)[0]||"week"));
    return `<div class="history-wrap"><div data-history-body>${renderHistoryBody(options,current)}</div></div>`;
  }
  function formatTableCell(value,type){const number=Number(value);if(type==="percent"&&Number.isFinite(number))return `${(number*100).toFixed(1)}%`;if(type==="signed_percent"&&Number.isFinite(number)){const result=number*100;return `<span class="change ${result>=0?"pos":"neg"}">${result>=0?"+":""}${result.toFixed(1)}%</span>`}if(type==="number"&&Number.isFinite(number))return number.toLocaleString("zh-CN",{maximumFractionDigits:1});return fmt(value)}
  function shareValue(row){const value=Number(row.share??row.value??0);return Math.abs(value)<=1.5?value*100:value}
  function renderBars(data){
    const rows=data?.rows||[],max=Math.max(...rows.map(shareValue),1),color=colors[data.color]||colors.blue;
    return `<div class="bars">${rows.map(row=>{const value=shareValue(row);return `<div class="bar-row"><label title="${esc(row.label)}">${esc(row.label)}</label><div class="track"><div class="fill" style="width:${Math.max(value/max*100,1)}%;background:${color}"></div></div><b>${value.toFixed(1)}%${row.count!=null?` (${fmt(row.count)})`:""}</b></div>`}).join("")}</div>`;
  }
  function renderPieChart(data){
    const source=(data?.rows||[]).map(row=>{const share=Number(row.share),count=Number(row.count),value=Number.isFinite(share)?share:Number.isFinite(count)?count:0;return {...row,value}}).filter(row=>row.value>0),total=source.reduce((sum,row)=>sum+row.value,0);
    if(!source.length||!total)return '<div class="empty-image">暂无可绘制数据</div>';
    const palette=Object.values(colors),radius=70,circumference=2*Math.PI*radius;let offset=0;
    const slices=source.map((row,index)=>{const length=row.value/total*circumference,markup=`<circle cx="100" cy="100" r="${radius}" stroke="${palette[index%palette.length]}" stroke-width="30" stroke-dasharray="${length} ${circumference-length}" stroke-dashoffset="${-offset}"/>`;offset+=length;return markup}).join('');
    offset=0;
    const sliceLabels=source.map((row,index)=>{const length=row.value/total*circumference,percent=row.value/total*100,angle=(offset+length/2)/circumference*2*Math.PI-Math.PI/2,x=100+Math.cos(angle)*radius,y=100+Math.sin(angle)*radius;offset+=length;return `<text class="pie-slice-label" x="${x.toFixed(2)}" y="${y.toFixed(2)}" text-anchor="middle" aria-label="${esc(row.label)} ${percent.toFixed(1)}%">${percent.toFixed(1)}%</text>`}).join('');
    const totalCount=source.every(row=>Number.isFinite(Number(row.count)))?source.reduce((sum,row)=>sum+Number(row.count||0),0):null;
    const legend=source.map((row,index)=>{const percent=row.value/total*100,count=Number.isFinite(Number(row.count))?` · ${fmt(Number(row.count))}单`:'';return `<div class="pie-legend-row"><span><i style="background:${palette[index%palette.length]}"></i><b title="${esc(row.label)}">${esc(row.label)}</b></span><strong>${percent.toFixed(1)}%${count}</strong></div>`}).join('');
    return `<div class="pie-chart"><div class="pie-visual"><svg viewBox="0 0 200 200" role="img" aria-label="占比圆环图"><circle class="pie-track" cx="100" cy="100" r="${radius}"/><g transform="rotate(-90 100 100)">${slices}</g><g class="pie-slice-labels">${sliceLabels}</g><text class="pie-total" x="100" y="96" text-anchor="middle">${totalCount!=null?fmt(totalCount):`${total.toFixed(1)}%`}</text><text class="pie-total-label" x="100" y="113" text-anchor="middle">${totalCount!=null?'合计':'占比'}</text></svg></div><div class="pie-legend">${legend}</div></div>`;
  }
  function renderStructureCards(groups){return `<div class="structure-grid">${groups.map((group,index)=>`<section class="structure-card"><h3>${esc(group.name)}</h3><div class="bars">${group.rows.map(row=>{const value=shareValue(row),change=Number(row.change||0)*100;return `<div class="bar-row"><label>${esc(row.label)}<span class="change ${change>=0?"pos":"neg"}">${change>=0?"+":""}${change.toFixed(1)}%</span></label><div class="track"><div class="fill" style="width:${Math.min(value,100)}%;background:${Object.values(colors)[index%5]}"></div></div><b>${value.toFixed(1)}%</b></div>`}).join("")}</div></section>`).join("")}</div>`}
  function renderFunnel(stages){
    const palette=Object.values(colors);return `<div class="funnel"><div class="funnel-row head"><span>阶段</span><span>规模</span><span>数量</span><span>总占比</span><span>阶段转化</span><span>流失</span></div>${stages.map((stage,index)=>`<div class="funnel-row"><span>${esc(stage.label)}</span><div class="funnel-track"><div class="funnel-fill" style="width:${Math.max(stage.total_rate*100,1)}%;background:${palette[index%palette.length]}">${(stage.total_rate*100).toFixed(1)}%</div></div><b>${fmt(stage.value)}</b><b>${(stage.total_rate*100).toFixed(1)}%</b><b>${(stage.stage_rate*100).toFixed(1)}%</b><b>${fmt(stage.loss)}</b></div>`).join("")}</div>`}
  function renderCohortMatrix(cohorts){
    const columns=["大定批次",...cohorts[0].stages.slice(1).map(stage=>stage.label),"大定→锁单","锁单→交付"];
    const rows=cohorts.map(cohort=>[cohort.period,...cohort.stages.slice(1).map(stage=>stage.total_rate),cohort.order_to_lock_days,cohort.lock_to_delivery_days]);
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map(column=>`<th>${esc(column)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map((value,index)=>index>0&&index<row.length-2?`<td class="heat-cell" style="background:rgba(39,133,232,${.05+Math.pow(Number(value),1.6)*.7})">${(Number(value)*100).toFixed(1)}%</td>`:`<td>${index>=row.length-2?fmt(value)+"天":esc(value)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function renderRankCards(cards,kind){const directional=kind==='rise'||kind==='drop',directionalClass=directional?` rank-grid-${kind}`:'';return `<div class="rank-grid${directionalClass}">${Object.entries(cards||{}).map(([name,rows])=>{const maxRate=Math.max(...rows.map(row=>Math.abs(Number(row.rate)||0)),0);return `<article class="rank-card"><h3>${esc(name)} · TOP${rows.length}</h3><ol>${rows.map(row=>{const meta=[row.rate!=null?`${(Number(row.rate)*100).toFixed(1)}%`:"",row.amount!=null?`${fmt(row.amount)}元`:""].filter(Boolean).join(" · ");if(!directional)return `<li><b>${row.rank}</b><span>${esc(row.label)}${meta?`<small>${esc(meta)}</small>`:""}</span></li>`;const rate=Number(row.rate),rateLabel=row.rate!=null&&Number.isFinite(rate)?`${(rate*100).toFixed(1)}%`:'—',width=maxRate>0&&Number.isFinite(rate)?Math.min(Math.abs(rate)/maxRate*100,100):0,amount=row.amount!=null?`${fmt(row.amount)}元`:'';return `<li><b class="rank-index">${row.rank}</b><span class="rank-name">${esc(row.label)}${amount?`<small>${esc(amount)}</small>`:''}</span><div class="rank-bar" aria-hidden="true"><i style="width:${width.toFixed(1)}%"></i></div><strong class="rank-rate">${rateLabel}</strong></li>`}).join("")}</ol></article>`}).join("")}</div>`}
  function renderRights(data){return `<div class="rights"><strong>权益金额 ${fmt(data.amount)} 元</strong><p>${esc(data.text)}</p></div>`}
  function renderFeeBandStructure(data){
    const bands=data?.bands||[],rows=data?.rows||[],palette=["#1677FF","#00C2FF","#00B578","#FFB020","#FF4D6D","#7C3AED","#ED7D31","#70AD47","#4472C4"];
    const legend=`<div class="legend fee-legend">${bands.map((band,index)=>`<span><i style="background:${palette[index%palette.length]}"></i>${esc(band)}</span>`).join("")}</div>`;
    const body=rows.map(row=>{const total=row.values.reduce((sum,value)=>sum+Number(value||0),0)||1;return `<div class="fee-band-row"><label title="${esc(row.label)}">${esc(row.label)}</label><div class="fee-band-chart"><div class="fee-band-track">${row.values.map((value,index)=>{const share=Number(value||0)/total*100;return `<i style="width:${share}%;background:${palette[index%palette.length]}" title="${esc(bands[index])} ${share.toFixed(1)}%"></i>`}).join("")}</div><div class="segment-data-labels">${row.values.map((value,index)=>{const share=Number(value||0)/total*100;return `<span><i style="background:${palette[index%palette.length]}"></i>${share.toFixed(1)}%</span>`}).join("")}</div></div><b>${fmt(total)}单</b></div>`}).join("");
    return `${legend}<div class="fee-band-list">${body}</div>`;
  }
  function renderFeePeriodBands(data){
    const periods=data?.periods||[],series=data?.series||[],palette=[chartPalette.yellow,chartPalette.green,chartPalette.blue,chartPalette.violet,chartPalette.rose];
    const legend=`<div class="legend fee-legend">${series.map((item,index)=>`<span><i style="background:${palette[index%palette.length]}"></i>${esc(item.name)}</span>`).join("")}</div>`;
    const columns=periods.map((period,index)=>{const total=series.reduce((sum,item)=>sum+Number(item.values[index]||0),0)||1;return `<div class="fee-period-col"><div class="fee-period-stack">${series.map((item,sIndex)=>{const share=Number(item.values[index]||0)/total*100;return `<i style="height:${share}%;background:${palette[sIndex%palette.length]}" title="${esc(item.name)} ${share.toFixed(1)}%"><span>${share.toFixed(1)}%</span></i>`}).join("")}</div><b>${esc(period)}</b><small>实际金额总计 ${fmt(data.actual_total||0)}元</small></div>`}).join("");
    return `${legend}<div class="fee-period-chart" style="--periods:${Math.max(periods.length,1)}">${columns}</div>`;
  }
  function renderFeeHeatmap(data){
    const periods=data?.periods||[],rows=data?.rows||[],columns=Math.max(periods.length,1);
    return `<div class="fee-heatmap"><div class="fee-heat-row" style="--cols:${columns}"><div class="heat-head">选配项</div>${periods.map(period=>`<div class="heat-head">${esc(period)}</div>`).join("")}</div>${rows.map(row=>`<div class="fee-heat-row" style="--cols:${columns}"><div class="heat-label" title="${esc(row.group)} · ${esc(row.label)}"><small>${esc(row.group)}</small>${esc(row.label)}</div>${periods.map((_,index)=>{const value=Number(row.values[index]||0);return `<div class="fee-heat-cell" style="background:rgba(22,119,255,${.08+Math.min(value,1)*.68})">${(value*100).toFixed(1)}%</div>`}).join("")}</div>`).join("")}</div>`;
  }
  function renderSkuHeatmap(data){
    const periods=data?.periods||[],rows=data?.rows||[],columns=Math.max(periods.length,1);
    return `<div class="heatmap"><div class="heatmap-row" style="--cols:${columns}"><div class="heat-head">累计锁单</div>${periods.map(p=>`<div class="heat-head">${esc(p)}</div>`).join("")}</div>${rows.map(row=>`<div class="heatmap-row" style="--cols:${columns}"><div class="heat-label">${esc(row.label)}</div>${periods.map((_,index)=>{const value=Number(row.values[index]||0);return `<div style="background:rgba(0,181,120,${.12+value*.72})">${(value*100).toFixed(1)}%</div>`}).join("")}</div>`).join("")}</div>`;
  }
  function renderComboHeatmap(data){
    const periods=data?.periods||[],rows=data?.rows||[],index=Math.max(periods.length-1,0);
    return `<div class="combo-grid">${rows.map(row=>`<div class="combo-cell"><b>${esc(row.rank)}</b><br>${row.labels.map(esc).join(" × ")}<br><strong>${esc(periods[index]||"总计")} ${(Number(row.values[index]??row.total)*100).toFixed(1)}%</strong></div>`).join("")}</div>`;
  }
  function renderComboMatrix(data){
    const groups=data?.groups||[];
    if(!groups.length)return '<div class="empty-image">组合Sheet暂无可绘制数据</div>';
    const controls=`<div class="combo-controls" role="group" aria-label="配置组合维度">${groups.map((group,index)=>`<button data-combo-switch="${index}" class="${index===0?"active":""}" aria-pressed="${index===0}">${esc(group.name)}</button>`).join("")}</div>`;
    const panels=groups.map((group,groupIndex)=>{const columns=Math.max(group.periods.length,1);const rows=group.rows||[];return `<div class="combo-matrix-panel" data-combo-panel="${groupIndex}" ${groupIndex?"hidden":""}><div class="combo-matrix-grid" style="--cols:${columns}"><div class="combo-matrix-head">组合</div>${group.periods.map(period=>`<div class="combo-matrix-head">${esc(period)}</div>`).join("")}${rows.map(row=>`<div class="combo-matrix-label" title="${esc(row.rank)} · ${esc(row.label)}"><b>${esc(row.rank)}</b><span>${esc(row.label)}</span></div>${row.values.map(value=>{const number=Number(value||0),alpha=.04+Math.min(number,1)*.6;return `<div class="combo-matrix-cell" style="background:rgba(0,181,120,${alpha.toFixed(2)})">${number?`<b>${(number*100).toFixed(1)}%</b>`:"—"}</div>`}).join("")}`).join("")}</div></div>`}).join("");
    return `<div class="combo-matrix">${controls}${panels}</div>`;
  }
  function renderTailDistribution(rows){return renderColumns(rows||[],colors.purple)}
  function cumulative(values){let total=0;return values.map(value=>(total+=Number(value||0)))}
  function renderLaunch(data){
    const periods=data.periods,metrics=data.metrics,dailyBig=metrics["当日大定数量"]||[],dailySmall=metrics["当日小订转大数量"]||metrics["当日小订转大定数量"]||[],dailyDirect=metrics["当日直接大定数量"]||dailyBig.map((value,index)=>Number(value||0)-Number(dailySmall[index]||0)),small=metrics["累计小订转大定数量"]||metrics["累计小订转大数量"]||cumulative(dailySmall),direct=metrics["累计直接大定数量"]||cumulative(dailyDirect),totals=periods.map((_,index)=>Number(small[index]||0)+Number(direct[index]||0)),maxBar=chartMax(totals),W=periods.length*86+90,H=330,left=45,bottom=282,step=86,plotH=236;
    const bars=totals.map((total,index)=>{const height=Number(total)/maxBar*plotH,smallHeight=Number(small[index]||0)/maxBar*plotH,directHeight=Number(direct[index]||0)/maxBar*plotH,barW=stackedBarWidth(step),x=left+index*step+step/2,totalY=Math.max(bottom-height-8,12),directY=Math.max(bottom-directHeight/2,12),smallY=avoidLabelY(bottom-height+Math.max(smallHeight/2,8),[directY,totalY],12,bottom-6);return `<rect x="${x-barW/2}" y="${bottom-directHeight}" width="${barW}" height="${directHeight}" fill="${colors.blue}"/><rect x="${x-barW/2}" y="${bottom-height}" width="${barW}" height="${smallHeight}" fill="${colors.green}"/><text class="chart-data-label on-color" x="${x}" y="${directY}" text-anchor="middle">${fmt(direct[index]||0)}</text><text class="chart-data-label on-color" x="${x}" y="${smallY}" text-anchor="middle">${fmt(small[index]||0)}</text><text class="chart-data-label" x="${x}" y="${totalY}" text-anchor="middle">${fmt(total)}</text><text x="${x}" y="${bottom+17}" text-anchor="middle" font-size="9" fill="#64748B">${esc(periods[index])}</text>`}).join("");
    const smallRate=metrics["累计小订转化率"]||null,bigRate=metrics["累计直接大定进度"]||null;
    const rateY=value=>bottom-Math.min(Math.max(Number(value||0),0),1)*(plotH-12);
    const labelYs=periods.map((_,index)=>{const totalY=Math.max(bottom-Number(totals[index]||0)/maxBar*plotH-8,12),occupied=[totalY],result={};const place=(key,base)=>{const y=avoidLabelY(base,occupied,12,bottom-8);occupied.push(y);result[key]=y};if(smallRate)place("smallRate",rateY(smallRate[index])-18);if(bigRate)place("bigRate",rateY(bigRate[index])+18);return result});
    const rateLines=[["smallRate","#00B578",smallRate],["bigRate","#7C3AED",bigRate]].filter(([, ,values])=>Array.isArray(values)&&values.length).map(([key,color,values])=>{const ratePoints=values.map((value,index)=>`${left+index*step+20},${rateY(value)}`).join(" ");const labels=values.map((value,index)=>`<text class="chart-data-label line-label" x="${left+index*step+20}" y="${labelYs[index][key]}" text-anchor="middle">${(Number(value||0)*100).toFixed(1)}%</text>`).join("");const dots=values.map((value,index)=>`<circle cx="${left+index*step+20}" cy="${rateY(value)}" r="4" fill="#fff" stroke="${color}" stroke-width="2.5"/>`).join("");return `<polyline points="${ratePoints}" fill="none" stroke="${color}" stroke-width="2.5"/>${dots}${labels}`}).join("");
    return `<div class="launch-chart"><svg viewBox="0 0 ${W} ${H}" style="width:${W}px;height:${H}px" role="img" aria-label="首销期累计订单来源，堆叠柱顶显示累计大定总数">${bars}${rateLines}</svg></div><div class="legend"><span><i style="background:${colors.blue}"></i>累计直接大定</span><span><i style="background:${colors.green}"></i>累计小订转大</span><span><i class="line-key" style="background:#00B578"></i>累计小转大率（累计小转大÷总小订）</span><span><i class="line-key" style="background:#7C3AED"></i>累计直接大定进度</span></div>`;
  }
  function renderSmallOrderRhythm(rows){
    if(!rows?.length)return '<div class="empty-image">暂无小订期节奏数据</div>';
    const W=rows.length*78+90,H=330,left=48,bottom=266,plotH=260,step=78,barW=Math.min(15,step*.22),maxValue=chartMax(rows.flatMap(row=>[row.orders,row.retained,row.cancel]));
    const x=index=>left+index*step+step/2,y=value=>bottom-Number(value||0)/maxValue*plotH,rateY=value=>bottom-Math.min(Math.max(Number(value||0),0),1)*(plotH-24);
    const bars=rows.map((row,index)=>{const total=Math.max(Number(row.orders||0),0),retained=Math.max(Number(row.retained||0),0),cancel=Math.max(Number(row.cancel||0),0);const totalH=total/maxValue*plotH,retainedH=retained/maxValue*plotH,cancelH=cancel/maxValue*plotH,yTop=bottom-totalH,cx=x(index),bw=stackedBarWidth(step),segmentYs=[];const segLabel=(value,yCenter)=>{if(value<=0)return "";const labelY=avoidLabelY(yCenter,segmentYs,bottom-plotH+8,bottom-8,12);segmentYs.push(labelY);return `<text class="chart-data-label on-color" x="${cx}" y="${labelY}" text-anchor="middle">${fmt(value)}</text>`};return `<g><rect x="${cx-bw/2}" y="${yTop}" width="${bw}" height="${retainedH}" fill="${colors.green}"><title>留存小订 ${fmt(retained)}</title></rect><rect x="${cx-bw/2}" y="${yTop+retainedH}" width="${bw}" height="${cancelH}" fill="${colors.coral}"><title>退订 ${fmt(cancel)}</title></rect>${segLabel(retained,yTop+retainedH/2)}${segLabel(cancel,yTop+retainedH+cancelH/2)}<text class="chart-data-label" x="${cx}" y="${Math.max(yTop-6,12)}" text-anchor="middle">${fmt(total)}</text><text x="${cx}" y="${bottom+19}" text-anchor="middle" font-size="9" fill="#64748B">${esc(row.period)}</text></g>`}).join("");
    const points=rows.map((row,index)=>`${x(index)},${rateY(row.retention_rate)}`).join(" ");
    const dots=rows.map((row,index)=>{const cy=rateY(row.retention_rate),totalY=Math.max(y(row.orders)-6,12),labelY=avoidLabelY(cy-9,[totalY],12,bottom-8);return `<circle cx="${x(index)}" cy="${cy}" r="4" fill="#fff" stroke="#0070C0" stroke-width="2.5"/><text class="chart-data-label line-label" x="${x(index)}" y="${labelY}" text-anchor="middle">${(Number(row.retention_rate||0)*100).toFixed(0)}%</text>`}).join("");
    return `<div class="small-order-chart"><svg viewBox="0 0 ${W} ${H}" style="width:${W}px;height:${H}px" role="img" aria-label="小订期间订单、留存、退订与留存率趋势"><line x1="${left}" y1="${bottom}" x2="${W-18}" y2="${bottom}" stroke="#DCE7F5"/>${bars}<polyline points="${points}" fill="none" stroke="#0070C0" stroke-width="2.5"/>${dots}</svg></div><div class="legend"><span><i style="background:${colors.green}"></i>留存小订</span><span><i style="background:${colors.coral}"></i>退订</span><span><i class="line-key purple"></i>留存率</span></div>`;
  }
  function renderTrend(rows){return renderColumns(rows.map(row=>({label:row.period,value:row.daily||0})),colors.coral)}
  function renderDailyCancel(rows){
    if(!rows?.length)return '<div class="empty-image">暂无日度退订数据</div>';
    const W=rows.length*78+90,H=286,left=48,bottom=214,plotH=160,step=78,barW=12,maxBar=chartMax(rows.map(row=>Number(row.daily||0)+Number(row.big_daily||0)));
    const x=index=>left+index*step+step/2,ry=value=>bottom-Math.min(Math.max(Number(value||0),0),1)*plotH;
    const bars=rows.map((row,index)=>{const small=Math.max(Number(row.daily||0),0),big=Math.max(Number(row.big_daily||0),0);const smallH=small/maxBar*plotH,bigH=big/maxBar*plotH,yTop=bottom-smallH-bigH,cx=x(index),bw=stackedBarWidth(step),segmentYs=[];const segLabel=(value,yCenter)=>{if(value<=0)return "";const labelY=avoidLabelY(yCenter,segmentYs,bottom-plotH+8,bottom-8,12);segmentYs.push(labelY);return `<text class="chart-data-label on-color" x="${cx}" y="${labelY}" text-anchor="middle">${fmt(value)}</text>`};return `<g><rect x="${cx-bw/2}" y="${bottom-smallH}" width="${bw}" height="${smallH}" fill="${colors.coral}"><title>当日小订退 ${fmt(small)}</title></rect><rect x="${cx-bw/2}" y="${yTop}" width="${bw}" height="${bigH}" fill="${colors.orange}"><title>当日大定退 ${fmt(big)}</title></rect>${segLabel(small,bottom-smallH/2)}${segLabel(big,yTop+bigH/2)}<text class="chart-data-label" x="${cx}" y="${Math.max(yTop-6,12)}" text-anchor="middle">${fmt(small+big)}</text><text x="${cx}" y="${bottom+16}" text-anchor="middle" font-size="9" fill="#64748B">${esc(row.period)}</text></g>`}).join("");
    const lineLabelYs=rows.map(row=>{const total=Math.max(Number(row.daily||0),0)+Math.max(Number(row.big_daily||0),0),totalY=Math.max(bottom-total/maxBar*plotH-6,12),smallY=avoidLabelY(ry(row.small_rate)+18,[totalY],12,bottom-8),bigY=avoidLabelY(ry(row.big_rate)-10,[totalY,smallY],12,bottom-8);return {small_rate:smallY,big_rate:bigY}}),lineDefs=[["small_rate","#0070C0"],["big_rate",colors.orange]];
    const lines=lineDefs.map(([field,color])=>{const points=rows.map((row,index)=>`${x(index)},${ry(row[field])}`).join(" ");const labels=rows.map((row,index)=>`<text class="chart-data-label line-label" x="${x(index)}" y="${lineLabelYs[index][field]}" text-anchor="middle">${(Number(row[field]||0)*100).toFixed(1)}%</text>`).join("");const dots=rows.map((row,index)=>`<circle cx="${x(index)}" cy="${ry(row[field])}" r="4" fill="#fff" stroke="${color}" stroke-width="2.5"/>`).join("");return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.5"/>${dots}${labels}`}).join("");
    return `<div class="daily-cancel-chart"><svg viewBox="0 0 ${W} ${H}" style="width:${W}px;height:${H}px" role="img" aria-label="日度退订与退订率趋势"><line x1="${left}" y1="${bottom}" x2="${W-18}" y2="${bottom}" stroke="#DCE7F5"/>${bars}${lines}</svg></div><div class="legend"><span><i style="background:${colors.coral}"></i>当日小订退</span><span><i style="background:${colors.orange}"></i>当日大定退</span><span><i class="line-key"></i>累计小订退率</span><span><i class="line-key" style="background:${colors.orange}"></i>大定退率</span></div>`;
  }
  function renderHourlyChart(rows,day){
    const filtered=day==="总计"?(rows||[]):(rows||[]).filter(row=>String(row.period||"")===day);
    const grouped=new Map();filtered.forEach(row=>{const key=String(row.hour),item=grouped.get(key)||{hour:key,count:0,cancel:0};item.count+=Number(row.count||0);item.cancel+=Number(row.cancel||0);grouped.set(key,item)});
    // 横轴统一从 0 时开始,固定 0-23 时,缺失时段补 0
    const data=Array.from({length:24},(_,hour)=>grouped.get(String(hour))||{hour:String(hour),count:0,cancel:0}),max=chartMax(data.map(row=>row.count));
    return `<div class="hourly-chart"><div class="hourly-inner">${data.map(row=>{const count=Number(row.count||0),cancel=Number(row.cancel||0),kept=Math.max(count-cancel,0);return `<div class="hourly-group"><div class="hourly-bars"><i style="height:${kept/max*100}%;background:${colors.blue}" title="小订留存 ${fmt(kept)}"><b class="in">${fmt(kept)}</b></i><i style="height:${cancel/max*100}%;background:${colors.coral}" title="退订 ${fmt(cancel)}"><b class="total">${fmt(count)}</b><b class="in">${fmt(cancel)}</b></i></div><span>${esc(row.hour)}时</span></div>`}).join("")}</div></div><div class="legend"><span><i style="background:${colors.blue}"></i>小订留存</span><span><i style="background:${colors.coral}"></i>退订</span></div>`
  }
  function renderHourly(rows){
    const days=[...new Set((rows||[]).map(row=>String(row.period||"")).filter(Boolean))];
    const options=["总计",...days].map(day=>`<option value="${esc(day)}">${esc(String(day).replace(/[ T]00:00:00$/, ""))}</option>`).join("");
    return `<div class="hourly-wrap"><div class="hourly-toolbar"><span>分时口径</span><select data-hourly-select data-hourly-rows="${esc(JSON.stringify(rows||[]))}">${options}</select></div><div data-hourly-body>${renderHourlyChart(rows,"总计")}</div></div>`
  }
  function renderLaunchHourlyChart(rows,day){
    const filtered=day==="总计"?(rows||[]):(rows||[]).filter(row=>String(row.period||"")===day);
    const grouped=new Map();filtered.forEach(row=>{const key=String(row.hour),item=grouped.get(key)||{hour:key,orders:0,small:0,direct:0};item.orders+=Number(row.orders||0);item.small+=Number(row.small||0);item.direct+=Number(row.direct||0);grouped.set(key,item)});
    const data=Array.from({length:24},(_,hour)=>grouped.get(String(hour))||{hour:String(hour),orders:0,small:0,direct:0}),max=chartMax(data.map(row=>row.orders));
    return `<div class="hourly-chart"><div class="hourly-inner">${data.map(row=>{const orders=Number(row.orders||0),small=Number(row.small||0),direct=Number(row.direct||0);return `<div class="hourly-group"><div class="hourly-bars"><i style="height:${small/max*100}%;background:${colors.green}" title="小订转大 ${fmt(small)}"><b class="in">${fmt(small)}</b></i><i style="height:${direct/max*100}%;background:${colors.blue}" title="直接大定 ${fmt(direct)}"><b class="total">${fmt(orders)}</b><b class="in">${fmt(direct)}</b></i></div><span>${esc(row.hour)}时</span></div>`}).join("")}</div></div><div class="legend"><span><i style="background:${colors.green}"></i>小订转大</span><span><i style="background:${colors.blue}"></i>直接大定</span></div>`
  }
  function renderLaunchHourly(rows){
    const days=[...new Set((rows||[]).map(row=>String(row.period||"")).filter(Boolean))];
    const options=["总计",...days].map(day=>`<option value="${esc(day)}">${esc(String(day).replace(/[ T]00:00:00$/, ""))}</option>`).join("");
    return `<div class="hourly-wrap"><div class="hourly-toolbar"><span>分时口径</span><select data-launch-hourly-select data-launch-hourly-rows="${esc(JSON.stringify(rows||[]))}">${options}</select></div><div data-launch-hourly-body>${renderLaunchHourlyChart(rows,"总计")}</div></div>`
  }
  function renderColumns(rows,color){const max=chartMax(rows.map(row=>row.value));return `<div class="trend">${rows.map(row=>`<div class="trend-col"><i style="height:${Number(row.value)/max*100}%;background:${color}"><b class="column-data-label">${fmt(row.value)}</b></i><span>${esc(row.label)}</span></div>`).join("")}</div>`}
  function renderCancelCards(groups){return `<div class="cancel-grid">${groups.map((group,index)=>`<section class="structure-card"><h3>${esc(group.name)}</h3>${renderBars({color:["orange","coral","purple","blue","coral","green","orange"][index%7],rows:group.rows})}</section>`).join("")}</div>`}
  function forecastReferenceOptions(data,selected){
    return `<option value="">证据不足时请人工选择</option>`+(data.history||[]).map(item=>`<option value="${esc(item.model)}"${item.model===selected?" selected":""}>${esc(item.model)}${item.mapped===false?' · 未映射':''}</option>`).join("");
  }
  function lifecycleReferenceOptions(history,selected=''){
    const counts=new Map();history.forEach(item=>counts.set(item.model,(counts.get(item.model)||0)+1));
    return '<option value="">证据不足时请人工选择</option>'+history.map(item=>{const key=item.event_id||item.model,date=item.small_start_date||item.steady_start_date;return `<option value="${esc(key)}" data-model="${esc(item.generation||item.model)}"${key===selected?' selected':''}>${esc(item.model)}${counts.get(item.model)>1&&date?`（${esc(date)}开始）`:''}${item.mapped===false?' · 未映射':''}</option>`}).join('');
  }
  const referenceBrand=item=>{
    const known=['问界','智界','享界','尊界','尚界'],declared=String(item.brand||'').trim();
    if(known.includes(declared))return declared;
    const inferred=known.find(brand=>[item.generation,item.model].some(name=>String(name||'').trim().startsWith(brand)));
    return inferred||(!['','界','其他','未维护','待维护','未知'].includes(declared)?declared:'其他');
  };
  const lifecycleUnavailable=(task,item)=>task==='hourly'&&!((item.small_hourly_curve||[]).some(value=>Number.isFinite(value)&&value>0));
  function renderLifecycleReferenceCard(stage,task,title,purpose,history,refAttr,weightAttr,chartAttr){
    const id=stage+'-'+task,options=lifecycleReferenceOptions(history),brands=[...new Set(history.map(referenceBrand))];
    return `<article class="forecast-ref-card" data-lifecycle-reference="${id}"><div class="forecast-ref-card-head"><div><span>${esc(title)}</span><small>${esc(purpose)}</small></div><i aria-hidden="true"></i></div><div class="forecast-ref-selects">${['主参考','辅助参考'].map((label,index)=>`<label>${label}<select ${refAttr}="${index}" data-lifecycle-ref="${id}" data-ref-slot="${index}">${options}</select></label>`).join('')}<div class="forecast-ref-weights">${['主','辅'].map((label,index)=>`${index?'<b>＋</b>':''}<label>${label}<input type="number" min="0" max="100" step="1" value="${index?30:70}" ${weightAttr}="${index}" data-lifecycle-weight="${id}" data-ref-slot="${index}"><small>%</small></label>`).join('')}<em data-lifecycle-weight-total>合计100%</em></div></div><details class="forecast-ref-score-details"><summary>查看评分对比表</summary><div class="forecast-ref-comparison" data-lifecycle-ref-reason></div></details><div class="forecast-ref-actions"><button type="button" data-lifecycle-score-jump>查看评分明细</button><details class="forecast-chart-picker"><summary>图表对比车型 <b data-lifecycle-picker-count>0项</b></summary><div class="forecast-chart-picker-panel"><div class="forecast-chart-quick">${[['primary','主辅'],['all','全选'],['none','清空']].map(([mode,label])=>`<button type="button" data-lifecycle-ref-quick="${mode}">${label}</button>`).join('')}${brands.map(brand=>`<button type="button" data-lifecycle-ref-quick="brand" data-brand="${esc(brand)}">${esc(brand)}</button>`).join('')}</div><small>额外勾选仅用于图表比较，不参与预测加权。同名后的开始日期用于区分不同传播事件。</small><div class="forecast-chart-options">${brands.map(brand=>`<fieldset><legend>${esc(brand)}</legend>${history.filter(item=>referenceBrand(item)===brand).map(item=>`<label><input type="checkbox" data-lifecycle-chart-ref="${id}" data-brand="${esc(brand)}" value="${esc(item.event_id||item.model)}"${lifecycleUnavailable(task,item)?' disabled title="该车型没有D1分时数据"':''}><span>${esc(item.model)}${lifecycleUnavailable(task,item)?' · 无D1分时数据':''}${history.filter(other=>other.model===item.model).length>1?`（${esc(item.small_start_date||item.steady_start_date||'日期未维护')}开始）`:''}</span></label>`).join('')}</fieldset>`).join('')}</div></div></details></div><div class="forecast-task-chart" ${chartAttr}></div></article>`;
  }
  function lifecycleChartReferences(card,history,selected){
    if(!card?.querySelectorAll)return selected.map((row,index)=>({...row,label:`${index?'辅助':'主参考'}${row.weight}% · ${row.item.model}`,color:index?'#7C3AED':'#FF8A00'}));
    const palette=['#D9485F','#00A6A6','#B7791F','#6B7280','#DB2777','#65A30D'];
    return [...card.querySelectorAll('[data-lifecycle-chart-ref]:checked:not(:disabled)')].map((input,index)=>{const item=history.find(item=>(item.event_id||item.model)===input.value),slot=selected.findIndex(row=>(row.item.event_id||row.item.model)===input.value),weight=slot>=0?selected[slot].weight:0;return item?{item,weight,label:`${slot>=0?(slot?'辅助':'主参考')+weight+'%':'对比'} · ${item.model}`,color:slot===0?'#FF8A00':slot===1?'#7C3AED':palette[index%palette.length]}:null}).filter(Boolean);
  }
  function renderLifecycleReferenceScores(rows,scoreFor){
    const body=rows.map(({item,weight},index)=>{const result=scoreFor(item);return `<tr><td>${index?'辅助参考':'主参考'}</td><td><b>${esc(item.model)}</b></td><td>${Math.round(result.score*100)}分</td><td>${result.parts.map(part=>`${esc(part.evidence)}：${Math.round(part.value*100)}%`).join('<br>')}</td><td>${weight}%</td></tr>`}).join('');
    return `<table><thead><tr><th>角色</th><th>参考车型</th><th>匹配分</th><th>逐项对比</th><th>分配权重</th></tr></thead><tbody>${body||'<tr><td colspan="5">暂无已选参考</td></tr>'}</tbody></table>`;
  }
  function bindLifecycleReferenceCards(workspace,root,update){
    workspace.querySelectorAll('[data-lifecycle-reference]').forEach(card=>{
      const selects=[...card.querySelectorAll('[data-lifecycle-ref]')],inputs=[...card.querySelectorAll('[data-lifecycle-chart-ref]')];
      const refresh=()=>{const sum=[...card.querySelectorAll('[data-lifecycle-weight]')].reduce((n,input)=>n+Math.max(Number(input.value)||0,0),0);card.querySelector('[data-lifecycle-weight-total]').textContent=`合计${sum}%${sum===100?'':' · 自动归一'}`;card.querySelector('[data-lifecycle-picker-count]').textContent=inputs.filter(input=>input.checked).length+'项';};
      const choose=mode=>{const primary=new Set(selects.map(select=>select.value));inputs.forEach(input=>input.checked=!input.disabled&&(mode==='all'||mode==='primary'&&primary.has(input.value)));refresh();};
      choose('primary');
      selects.forEach(select=>select.onchange=()=>{selects.forEach(other=>{if(other!==select&&select.value&&other.value===select.value)other.value='';});const input=inputs.find(input=>input.value===select.value);if(input)input.checked=true;inputs.forEach(input=>root._forecastTouched?.add(forecastDraftControlKey(input)));refresh();update();});
      card.querySelectorAll('[data-lifecycle-weight]').forEach(input=>input.oninput=()=>{refresh();update();});
      inputs.forEach(input=>input.onchange=()=>{root._forecastTouched?.add(forecastDraftControlKey(input));root.dataset.forecastDirty='true';refresh();update();captureForecastDraft();});
      card.querySelectorAll('[data-lifecycle-ref-quick]').forEach(button=>button.onclick=()=>{const mode=button.dataset.lifecycleRefQuick;if(mode==='brand')inputs.forEach(input=>input.checked=!input.disabled&&input.dataset.brand===button.dataset.brand);else choose(mode);inputs.forEach(input=>root._forecastTouched?.add(forecastDraftControlKey(input)));root.dataset.forecastDirty='true';refresh();update();captureForecastDraft();});
      card.querySelector('[data-lifecycle-score-jump]').onclick=()=>{applyForecastView(root,'score');syncUrl('push');};
      card._refreshLifecycleControls=refresh;
    });
  }
  function renderSmallOrderWorkspace(data){
    const target=data.target||{},history=data.small_order_history||[],options=lifecycleReferenceOptions(history);
    return `<div class="forecast-lifecycle-workspace forecast-small-order" data-small-order-workspace>
      <div class="forecast-data-error" data-small-error role="alert" aria-live="assertive" hidden></div>
      <section id="small-forecast-pane-result" aria-labelledby="forecast-tab-result" class="forecast-lifecycle-subpane${state.forecastView==='result'?' active':''}" role="tabpanel" data-lifecycle-subpane="small-result">
        <div class="forecast-lifecycle-kpis"><article><span>D1小订终值</span><strong data-small-kpi="d1">—</strong><small>单</small></article><article><span>预计最终总小订</span><strong data-small-kpi="total">—</strong><small>单</small></article><article><span>当前已发生</span><strong data-small-kpi="actual">—</strong><small>单</small></article></div>
        <div class="forecast-lifecycle-grid">
          <section class="forecast-lifecycle-controls"><div class="forecast-block-head"><div><small>当前对象驱动</small><h4>小订预测参数 · 参考见预测依据</h4></div><span>修改后实时重算</span></div><div class="forecast-lifecycle-fields"><label>线索量<input type="number" min="0" data-small-input="leads" placeholder="未维护"></label><label>互联网热度<input type="number" min="0" step="0.1" data-small-input="heat" placeholder="未维护"></label></div><p class="forecast-lifecycle-source" data-small-source>正在检查小订窗口和历史曲线。</p></section>
          <section class="forecast-lifecycle-chart-card"><div class="forecast-pane-head"><div><small>真实值冻结，未来按参考曲线分配</small><h4>小订逐日实际与预测</h4></div><span data-small-confidence>等待计算</span></div><div data-small-chart></div><div data-forecast-import-anchor="small"></div></section>
        </div>
        ${renderStageCommonControls('small')}
      </section>
      <section id="small-forecast-pane-evidence" aria-labelledby="forecast-tab-evidence" class="forecast-lifecycle-subpane${state.forecastView==='evidence'?' active':''}" role="tabpanel" data-lifecycle-subpane="small-evidence"><div class="forecast-lifecycle-evidence"><section><small>当前参考对比</small><h4>小订预测依据</h4><div data-small-evidence></div></section><section><small>阶段规则</small><h4>三阶段预测与回退</h4><ol>${(data.small_order_rules||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ol></section></div><div class="forecast-ref-grid">${renderLifecycleReferenceCard('small','progress','小订累计完成度','按已发生进度反推最终总小订',history,'data-small-ref','data-small-weight','data-small-reference-chart')}${renderLifecycleReferenceCard('small','daily','小订到天基础曲线','分配未来逐日小订；历史日历影响先剔除，再应用目标日期系数',history,'data-small-daily-ref','data-small-daily-weight','data-small-daily-reference-chart')}${renderLifecycleReferenceCard('small','hourly','D1 小订分时预测','按发布时间、分时斜率和累计占比选参考；不比较D1绝对量',history,'data-small-hourly-ref','data-small-hourly-weight','data-small-hourly-reference-chart')}</div></section>
      <section id="small-forecast-pane-score" aria-labelledby="forecast-tab-score" class="forecast-lifecycle-subpane${state.forecastView==='score'?' active':''}" role="tabpanel" data-lifecycle-subpane="small-score"><div data-small-score></div></section>
    </div>`;
  }
  function renderSteadyWorkspace(data){
    const target=data.target||{},history=data.steady_history||[],options=lifecycleReferenceOptions(history);
    return `<div class="forecast-lifecycle-workspace forecast-steady" data-steady-workspace>
      <div class="forecast-data-error" data-steady-error role="alert" aria-live="assertive" hidden></div>
      <section id="steady-forecast-pane-result" aria-labelledby="forecast-tab-result" class="forecast-lifecycle-subpane${state.forecastView==='result'?' active':''}" role="tabpanel" data-lifecycle-subpane="steady-result">
        <div class="forecast-boundary-rule"><b>口径边界</b><span>平销预测指标 = 交车锁单</span><em>真实日读取《锁单选配比例分析》by天，历史完整周读取by周；按天预测、按周汇总，不再预测平销大定。</em></div>
        <div class="forecast-lifecycle-kpis steady"><article><span>预测区间锁单（含已实现）</span><strong data-steady-kpi="total">—</strong><small>单</small></article><article><span>近期真实日均锁单</span><strong data-steady-kpi="daily">—</strong><small>单／天</small></article><article><span>未来日均较近期实际</span><strong data-steady-kpi="change">—</strong><small>%</small></article><article><span>当前预测依据</span><strong data-steady-kpi="basis">—</strong></article></div>
        <div class="forecast-lifecycle-grid">
          <section class="forecast-lifecycle-controls"><div class="forecast-block-head"><div><small>锁单选配 by周历史参考</small><h4>平销锁单依据 · 参考见预测依据</h4></div><span>主辅自动归一</span></div><p class="forecast-lifecycle-source" data-steady-source>正在读取《锁单选配比例分析》的平销期交车锁单。</p></section>
          <section class="forecast-lifecycle-chart-card"><div class="forecast-pane-head"><div><small>已结束日冻结，日预测汇总为周</small><h4>平销交车锁单by周</h4></div><span data-steady-confidence>等待计算</span></div><div data-steady-chart></div><div data-forecast-import-anchor="steady"></div></section>
        </div>
        ${renderStageCommonControls('steady')}
      </section>
      <section id="steady-forecast-pane-evidence" aria-labelledby="forecast-tab-evidence" class="forecast-lifecycle-subpane${state.forecastView==='evidence'?' active':''}" role="tabpanel" data-lifecycle-subpane="steady-evidence"><div class="forecast-lifecycle-evidence"><section><small>当前参考对比</small><h4>平销相对承接趋势</h4><div data-steady-evidence></div></section><section><small>业务规则</small><h4>平销交车锁单周预测</h4><ol>${(data.steady_rules||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ol></section></div><div class="forecast-ref-grid">${renderLifecycleReferenceCard('steady','weekly','平销交车锁单参考','首销全周期直接大定形状与平销承接趋势；到天按节假日、周末、工作日系数分配',history,'data-steady-ref','data-steady-weight','data-steady-reference-chart')}</div></section>
      <section id="steady-forecast-pane-score" aria-labelledby="forecast-tab-score" class="forecast-lifecycle-subpane${state.forecastView==='score'?' active':''}" role="tabpanel" data-lifecycle-subpane="steady-score"><div data-steady-score></div></section>
    </div>`;
  }
  function renderForecastWorkspaceV2(data){
    const target=data.target||{},tasks=data.tasks||[];
    const activeForecastStage=forecastStages.some(item=>item.id===state.forecastStage)?state.forecastStage:"launch";
    const activeForecastView=forecastViews.includes(state.forecastView)?state.forecastView:"result";
    const tierValues=[...new Set([target.tier,...(data.tiers||[])].filter(Boolean))];
    const tierOptions=tierValues.map(value=>`<option value="${esc(value)}"${value===target.tier?' selected':''}>${esc(value)}</option>`).join('');
    const nodeValues=[...new Set([target.launch_node,...(data.nodes||[])].filter(Boolean))];
    const nodeOptions=nodeValues.map(value=>`<option value="${esc(value)}"${value===target.launch_node?' selected':''}>${esc(value)}</option>`).join('');
    const energyValues=[...new Set([target.energy,...(data.energies||[]),'未维护'].filter(Boolean))];
    const energyOptions=energyValues.map(value=>`<option value="${esc(value)}"${value===target.energy?' selected':''}>${esc(value)}</option>`).join('');
    const periodOptions=['上午','下午','晚上','全天','未维护'].map(value=>`<option${value===(target.launch_period||'未维护')?' selected':''}>${value}</option>`).join('');
    const referenceModels=data.history||[],brands=[...new Set(referenceModels.map(referenceBrand))];
    const chartPicker=task=>{const defaults=new Set((task.recommended||[]).slice(0,2));return `<details class="forecast-chart-picker" data-forecast-chart-picker="${esc(task.key)}"><summary>图表对比车型 <b data-forecast-picker-count>${defaults.size}项</b></summary><div class="forecast-chart-picker-panel"><div class="forecast-chart-quick"><button type="button" data-forecast-ref-quick="primary">主辅</button><button type="button" data-forecast-ref-quick="all">全选</button><button type="button" data-forecast-ref-quick="none">清空</button>${brands.map(brand=>`<button type="button" data-forecast-ref-quick="brand" data-brand="${esc(brand)}">${esc(brand)}</button>`).join('')}</div><small>额外勾选仅用于图表比较，不参与主辅权重计算；“未映射”历史记录不会自动绑定当前订单分析代际。</small><div class="forecast-chart-options">${brands.map(brand=>`<fieldset><legend>${esc(brand)}</legend>${referenceModels.filter(item=>referenceBrand(item)===brand).map(item=>`<label><input type="checkbox" data-forecast-chart-ref="${esc(task.key)}" data-brand="${esc(brand)}" value="${esc(item.model)}"${defaults.has(item.model)?' checked':''}><span>${esc(item.model)}${item.mapped===false?' · 未映射':''}</span></label>`).join('')}</fieldset>`).join('')}</div></div></details>`};
    const refCard=task=>`<article class="forecast-ref-card" data-forecast-task="${esc(task.key)}"><div class="forecast-ref-card-head"><div><span>${esc(task.label)}</span><small>${esc(task.purpose)}</small></div><i aria-hidden="true"></i></div><div class="forecast-ref-selects"><label>主参考<select data-forecast-ref="${esc(task.key)}" data-ref-slot="0">${forecastReferenceOptions(data,task.recommended?.[0])}</select></label><label>辅助参考<select data-forecast-ref="${esc(task.key)}" data-ref-slot="1">${forecastReferenceOptions(data,task.recommended?.[1])}</select></label><div class="forecast-ref-weights"><label>主<input type="number" min="0" max="100" step="1" value="70" data-forecast-ref-weight="${esc(task.key)}" data-ref-slot="0"><small>%</small></label><b>＋</b><label>辅<input type="number" min="0" max="100" step="1" value="30" data-forecast-ref-weight="${esc(task.key)}" data-ref-slot="1"><small>%</small></label><em data-forecast-weight-total>合计100%</em></div></div><details class="forecast-ref-score-details"><summary>查看评分对比表</summary><div class="forecast-ref-comparison" data-forecast-ref-reason><div class="forecast-ref-comparison-empty">等待计算参与打分的参数</div></div></details><div class="forecast-ref-actions"><button type="button" data-forecast-score-jump="${esc(task.key)}">查看评分明细</button>${chartPicker(task)}</div><div class="forecast-task-chart" data-forecast-task-chart="${esc(task.key)}"></div></article>`;
    const slopeTask={key:'daily_slope',label:'每日斜率（仅展示）',purpose:'剔除日历影响后的日量较前一天变化率；D1及前日为0时无值。独立评分只用于选择斜率对比车型，不参与终局或剩余量分配。',recommended:tasks.find(task=>task.key==='daily')?.recommended||[]};
    const slopeCard=()=>refCard(slopeTask).replace(/<div class="forecast-ref-weights">.*?<\/div>/,'');
    const evidenceGroups=[
      {title:'方法一参考',note:'决定同期完成率反推所采用的历史曲线',keys:['small_progress','direct_progress']},
      {title:'方法二参考',note:'决定小订转化率与直接大定占比',keys:['conversion','direct_share']},
      {title:'公共参考',note:'共同影响D1、锁单换算与未来到天分配',keys:['hourly','lock','daily','daily_slope']},
    ].map(group=>{const cards=group.keys.map(key=>key==='daily_slope'?slopeTask:tasks.find(task=>task.key===key)).filter(Boolean).map(task=>task.key==='daily_slope'?slopeCard():refCard(task)).join('');return cards?`<section class="forecast-evidence-group"><div class="forecast-evidence-group-head"><div><small>${esc(group.note)}</small><h4>${esc(group.title)}</h4></div><span>${group.keys.length}个参考模块</span></div><div class="forecast-ref-grid">${cards}</div></section>`:''}).join('');
    const defaults=data.day_type_defaults||{};
    const smallOrderWorkspace=renderSmallOrderWorkspace(data),steadyWorkspace=renderSteadyWorkspace(data);
    const scenario=(key,title,subtitle)=>`<article class="forecast-scenario ${key}"><div class="forecast-scenario-head"><div><small>${esc(subtitle)}</small><h4>${esc(title)}</h4></div><span data-forecast-method-status="${key}">等待计算</span></div><div class="forecast-scenario-result"><div class="forecast-scenario-hero"><span>首销期大定</span><div><strong data-forecast-value="${key}-gross">—</strong><em>单</em></div><small data-forecast-kpi-note="${key}-gross"></small></div><div class="forecast-scenario-lock"><span>预计首销期锁单</span><div><strong data-forecast-value="${key}-lock">—</strong><em>单</em></div><small>按公共大定到锁单率换算</small></div></div><div class="forecast-scenario-breakdown"><article><span>小订转大</span><div><strong data-forecast-value="${key}-small">—</strong><em>单</em></div><small data-forecast-kpi-note="${key}-small"></small></article><article><span>直接大定</span><div><strong data-forecast-value="${key}-direct">—</strong><em>单</em></div><small data-forecast-kpi-note="${key}-direct"></small></article></div><div class="forecast-scenario-meta"><span>小订转化率 <b data-forecast-value="${key}-conversion">—</b>%</span><span>直接大定占比 <b data-forecast-value="${key}-share">—</b>%</span></div></article>`;
    return `<div class="forecast-workspace forecast-v2" data-forecast-config="${esc(JSON.stringify(data))}">
      <div class="forecast-scroll-body">
      <section class="forecast-target">
        <div class="forecast-target-heading"><small>当前预测对象</small><h3 data-forecast-target-title>${esc(target.name)}</h3></div>
        <div class="forecast-target-settings" role="group" aria-label="车型与时间参数"><span class="sr-only">车型与时间参数</span><div class="forecast-target-form">
          <label>产品档位<select data-forecast-target="tier">${tierOptions}</select></label>
          <label>能源类型<select data-forecast-target="energy">${energyOptions}</select></label>
          <label>发布类型<select data-forecast-target="node">${nodeOptions}</select></label>
          <label>小订开始日期<input type="date" data-forecast-target="smallStartDate" value="${esc(target.small_start_date||'')}"></label>
          <label>发布时段<select data-forecast-target="period">${periodOptions}</select></label>
          <label>首销开始<input type="date" data-forecast-target="launchDate" value="${esc(target.launch_date||'')}"></label>
          <label>首销天数<input type="number" min="1" max="90" data-forecast-target="days" value="${fmt(target.launch_days)}"><small>天</small></label>
        </div></div>
        <span class="forecast-status confirmed" data-forecast-feedback role="status" aria-live="polite"><i></i><span>参数实时生效</span></span>
        <div class="forecast-target-meta"><div class="forecast-stage-switcher" role="group" aria-label="选择预测阶段">${forecastStages.map(stage=>`<button type="button" data-forecast-stage-switch="${stage.id}" aria-pressed="${activeForecastStage===stage.id}">${stage.label}</button>`).join("")}</div><div class="forecast-tabs forecast-target-tabs" role="tablist" aria-label="预测内容"><button id="forecast-tab-result" class="${activeForecastView==='result'?'active':''}" role="tab" aria-selected="${activeForecastView==='result'}" tabindex="${activeForecastView==='result'?0:-1}" data-forecast-tab="result">预测结论</button><button id="forecast-tab-evidence" class="${activeForecastView==='evidence'?'active':''}" role="tab" aria-selected="${activeForecastView==='evidence'}" tabindex="${activeForecastView==='evidence'?0:-1}" data-forecast-tab="evidence">预测依据</button><button id="forecast-tab-score" class="${activeForecastView==='score'?'active':''}" role="tab" aria-selected="${activeForecastView==='score'}" tabindex="${activeForecastView==='score'?0:-1}" data-forecast-tab="score">预测打分</button></div><div class="forecast-target-sources"><b class="forecast-stage-status" data-forecast-current-day aria-live="polite">${esc(forecastStages.find(item=>item.id===activeForecastStage)?.label||'销量预测')}状态判定中</b><span class="forecast-source-brief" data-forecast-source-brief></span><span class="forecast-time-brief" data-forecast-time-brief></span><details class="forecast-source-details"><summary>来源与时间详情</summary><div class="forecast-source-decision"><b>数据来源</b><span data-forecast-day-source>正在检查当前预测阶段的时间窗口与数据来源</span></div><div class="forecast-source-decision"><b>时间口径</b><span data-forecast-time-summary>正在核对当前时间与各阶段窗口</span></div><p>人工参数和外部预测仅保存到当前浏览器，不上传；重新生成同路径页面后，人工修改项仍保留，真实值按最新数据读取。</p></details><button type="button" data-forecast-reset title="恢复当前车型三个阶段的参数、参考和权重；保留外部导入">恢复系统推荐</button></div></div>
      </section>
      <section class="forecast-stage-pane${activeForecastStage==='small'?' active':''}" role="tabpanel" data-forecast-stage-pane="small">${smallOrderWorkspace}</section>
      <section class="forecast-stage-pane${activeForecastStage==='launch'?' active':''}" role="tabpanel" data-forecast-stage-pane="launch">
      <div class="forecast-data-error" data-forecast-data-error role="alert" aria-live="assertive" tabindex="-1" hidden></div>
      <section id="forecast-pane-result" aria-labelledby="forecast-tab-result" class="forecast-pane${activeForecastView==='result'?' active':''}" role="tabpanel" data-forecast-pane="result">
        <div class="forecast-result-shell">
          <main class="forecast-result-main">
            <p class="forecast-progress-source">首销结论为总大定（小转大＋直接大定，未扣大定退订）；锁单单独展示。累计小转大率＝累计小转大÷总小订；真实累计与当日滚动估算分开显示。</p><div class="forecast-scenarios">${scenario('progress','方法一 · 同期完成率反推','真实累计量 ÷ 参考传播名同期完成率')}${scenario('parameter','方法二 · 转化参数测算','总小订 × 转化率，并按直接大定占比换算')}</div>
            <aside class="forecast-parameter-rail">
              <div class="forecast-rail-head"><div><small>人工确认与共同调整</small><h4>预测参数</h4></div><span>修改后实时重算</span></div>
              <div class="forecast-result-grid forecast-control-grid">
                <div class="forecast-assumptions forecast-progress-controls"><div class="forecast-block-head"><div><small>方法一人工确认区</small><h4>同期完成率参数</h4></div><button data-forecast-apply-progress>采用参考完成率</button></div><div class="forecast-progress-actuals"><span>已结束日真实小转大 <b data-forecast-progress-actual-small>—</b></span><span>已结束日真实直接大定 <b data-forecast-progress-actual-direct>—</b></span><span data-forecast-progress-intraday></span></div><div class="forecast-input-grid">
                  <label>参考车型同期小转大完成率<input data-forecast-input="progressSmallCompletion" type="number" min="0.1" max="100" step="0.1" placeholder="等待参考"><small>%</small></label>
                  <label>参考车型同期直接大定完成率<input data-forecast-input="progressDirectCompletion" type="number" min="0.1" max="100" step="0.1" placeholder="等待参考"><small>%</small></label>
                </div><p class="forecast-progress-source" data-forecast-progress-source>当前车型只提供真实累计量；完成率来自主辅历史参考车型，可以人工覆盖。</p></div>
                <div class="forecast-assumptions forecast-parameter-controls"><div class="forecast-block-head"><div><small>方法二人工确认区</small><h4>转化参数</h4></div><button data-forecast-apply>采用参考均值</button></div><div class="forecast-input-grid">
                  <label>总小订<input data-forecast-input="small" type="number" min="0" value="${target.total_small}"><small>份</small></label>
                  <label>小订转化率<input data-forecast-input="conversion" type="number" min="0" max="100" step="0.1" value="${(target.conversion*100).toFixed(1)}"><small>%</small></label>
                  <label>直接大定占比<input data-forecast-input="direct" type="number" min="0" max="95" step="0.1" value="${(target.direct_share*100).toFixed(1)}"><small>%</small></label>
                </div></div>
               </div>
              <div class="forecast-suggestion" data-forecast-suggestion></div>
            </aside>
            <div class="forecast-decision-grid">
              <section class="forecast-decision-card progress"><div class="forecast-pane-head"><div><small>方法一：已发生进度决定终局，未来只分配剩余量</small><h4>同期完成率法 · 到天拆解</h4></div><span>每个未来Dn基础权重 × 日期调整系数</span></div><div data-forecast-decision-chart="progress"></div><p class="forecast-monitor-status" data-forecast-monitor-status></p><details class="forecast-weekly"><summary>查看方法一by周预测汇总</summary><div data-forecast-weekly="progress"></div></details></section>
              <section class="forecast-decision-card parameter"><div class="forecast-pane-head"><div><small>方法二：总小订、转化率和直接大定占比决定终局</small><h4>转化参数法 · 到天拆解</h4></div><span>与方法一独立展示，不合并、不平均</span></div><div data-forecast-decision-chart="parameter"></div><details class="forecast-weekly"><summary>查看方法二by周预测汇总</summary><div data-forecast-weekly="parameter"></div></details></section>
             </div>
             <div data-forecast-import-anchor="launch"></div>
             <section class="forecast-common-controls"><div class="forecast-block-head"><div><small>两种方法公共参数</small><h4>首日锚点、锁单换算与逐日分配</h4></div><span>统一调整</span></div><div class="forecast-common-grid">
               <div class="forecast-d1-card" data-forecast-d1-card><div class="forecast-block-head"><div><small>首日锚点</small><h4 data-forecast-d1-title>D1大定</h4></div><span data-forecast-d1-stage>判定中</span></div><label data-forecast-d1-input-wrap>D1预测大定<input data-forecast-input="d1Gross" type="number" min="0" placeholder="系统自动"><small>单</small></label><div class="forecast-d1-value"><strong data-forecast-d1-value>—</strong><em>单</em><small data-forecast-d1-note></small></div><div class="forecast-d1-components"><span>小转大 <b data-forecast-d1-small>—</b></span><span>直接大定 <b data-forecast-d1-direct>—</b></span></div></div>
               <label class="forecast-common-lock">大定到锁单率<span>首销期锁单 ÷ 总大定</span><span class="forecast-common-lock-input"><input data-forecast-input="lock" type="number" min="0" max="100" step="0.1" value="${(target.lock_rate*100).toFixed(1)}"><small>%</small></span><em>用于两种方法的首销期锁单测算</em></label>
             </div><p data-forecast-allocation-note></p>${renderBridgeControls('launch')}</section>
             <section class="forecast-scale-check"><div class="forecast-pane-head"><div><small>不参与公式，只检查预测是否偏离可比传播名区间</small><h4>总体量级合理性校验</h4></div></div><div data-forecast-scale-check></div></section>
          </main>
        </div>
        <details class="forecast-method forecast-source-method"><summary>当前第几天与数据来源如何判断</summary><ol>${(data.source_rules||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ol></details>
      </section>
      <section id="forecast-pane-evidence" aria-labelledby="forecast-tab-evidence" class="forecast-pane${activeForecastView==='evidence'?' active':''}" role="tabpanel" data-forecast-pane="evidence"><div class="forecast-evidence-groups">${evidenceGroups}</div><details class="forecast-method"><summary>查看完整预测逻辑（7步）</summary><ol>${(data.method||[]).map(item=>`<li>${esc(item)}</li>`).join('')}</ol></details></section>
      <section id="forecast-pane-score" aria-labelledby="forecast-tab-score" class="forecast-pane${activeForecastView==='score'?' active':''}" role="tabpanel" data-forecast-pane="score"><div data-forecast-score-dashboard></div></section>
      </section>
      <section class="forecast-stage-pane${activeForecastStage==='steady'?' active':''}" role="tabpanel" data-forecast-stage-pane="steady">${steadyWorkspace}</section>
      </div>
    </div>`;
  }





  function forecastDateRanges(values){
    const dates=[...new Set(values)].sort(),ranges=[];let start=dates[0],last=start;
    const emit=()=>{if(start)ranges.push(start===last?start:`${start}～${last}`);};
    for(const day of dates.slice(1)){if(Date.parse(day)-Date.parse(last)===86400000)last=day;else{emit();start=last=day;}}emit();
    return ranges.join('、');
  }
  function showForecastCondition(node,{stage,state='条件不足',reasons=[],impact='该阶段暂不输出预测；已知实际数据保留。'}={}){
    if(!node)return;
    reasons=[...new Set(reasons.filter(Boolean))];node.hidden=!reasons.length;
    node.dataset.conditionState=state;node.setAttribute('role','status');node.setAttribute('aria-live','polite');
    node.innerHTML=reasons.length?`<strong>${esc(stage)} · ${esc(state)}</strong><span>原因：${reasons.map(esc).join('；')}</span><small>影响：${esc(impact)}</small>`:'';
  }
  function bindSmallOrderForecast(root,data,context){
    const workspace=root.querySelector('[data-small-order-workspace]');if(!workspace)return;
    const history=data.small_order_history||[],sameModel=context.sameModel,targetState=context.targetState,findActual=context.findActual,findStageActual=context.findStageActual,today=context.todayIso;
    const setEstimate=createForecastEstimateLogger(workspace);
    const targetItem=()=>{const target=targetState(),matches=history.filter(item=>sameModel(item.generation||item.model,target.name)||sameModel(item.model,target.name));return matches.find(item=>item.small_start_date===target.smallStartDate)||matches[0]||null};
    const minimumEvidence=3;
    const smallScoreRules=[
      {key:'tier',label:'产品档位',rule:'完全一致100%；同为SUV、MPV或轿车85%；其他已维护档位45%。'},
      {key:'energy',label:'能源类型',rule:'完全一致100%；不一致55%。'},
      {key:'node',label:'发布类型',rule:'完全一致100%；不一致62%。'},
      {key:'days',label:'小订窗口天数',rule:'1 − |两车小订天数差| ÷ max（当前小订天数，36），最低为0%。'},
      {key:'size',label:'已知小订量级',rule:'min（当前小订量，历史最终小订）÷ max（当前小订量，历史最终小订）。',missing:'任一侧没有正数小订量时不参与，并按剩余有效项重新平均'},
    ];
    const scoreResult=(item,target,current)=>smallReferenceScore(item,target,current,minimumEvidence);
    const attributeScore=(item,target,current)=>scoreResult(item,target,current).score;
    const hourlyContext=()=>{const target=targetState(),hours=(findActual(target.name)?.small_hourly_days||[]).find(row=>row.date===target.smallStartDate)?.hours||[],positive=hours.filter(row=>row.orders>0),startHour=positive.length?Math.min(...positive.map(row=>row.hour)):({'上午':9,'下午':14,'晚上':19,'夜间':20}[target.period]??-1);return {hours,startHour};};
    const ranked=(task='progress')=>{const target=targetState(),current=targetItem();return history.filter(item=>!sameModel(item.generation||item.model,target.name)&&Number(item.total)>0&&item.total_complete!==false&&(task!=='hourly'||window.ForecastMath.smallHourlyStart(item)>=0)).map(item=>({item,...(task==='hourly'?window.ForecastMath.smallHourlyReferenceScore(item,hourlyContext()):scoreResult(item,target,current))})).filter(row=>row.parts.length).sort((a,b)=>b.score-a.score)};
    const selects=[...workspace.querySelectorAll('[data-small-ref]')],weights=[...workspace.querySelectorAll('[data-small-weight]')];
    const groups={progress:{selects,weights},daily:{selects:[...workspace.querySelectorAll('[data-small-daily-ref]')],weights:[...workspace.querySelectorAll('[data-small-daily-weight]')]},hourly:{selects:[...workspace.querySelectorAll('[data-small-hourly-ref]')],weights:[...workspace.querySelectorAll('[data-small-hourly-weight]')]}};
    const referenceDailyShape=(item,index,days)=>{let raw=observedDailyPrefix(item.daily_orders||[]);if(!raw.some(value=>value>0)){const curve=rebasedForecastCompletionCurve(item,(item.small_progress||[]).some(Number)?'small_progress':'standard_progress',days);raw=curve.map((value,i)=>Math.max(value-(i?curve[i-1]:0),0));}if(!raw.length)return NaN;let running=0;const curve=window.ForecastMath.stretchCompletion(raw.map(value=>(running+=Number(value))),days),orders=curve.map((value,i)=>Math.max(value-(i?curve[i-1]:0),0)),factors=context.factors('small'),factor=i=>factors[context.calendarType(item.small_start_date||item.dates?.[0]||'',i).type]||1,first=orders[0]/factor(0);return first>0?orders[index]/factor(index)/first:NaN;};
    const itemKey=item=>item.event_id||item.model;
    const stageEligible=(item,stage)=>stage.key==='d1'?(Number(item.d1_share)>0&&(item.small_hourly_curve||[]).some(Number)):stage.key==='active'?((item.small_progress||[]).some(Number)||(item.standard_progress||[]).some(Number)):true;
    const initializeReferences=()=>{const target=targetState();Object.entries(groups).forEach(([task,group])=>{const rows=ranked(task).filter(row=>row.eligible&&(task==='hourly'||(stageEligible(row.item,{key:'active'})&&rebasedForecastCompletionCurve(row.item,(row.item.small_progress||[]).some(Number)?'small_progress':'standard_progress',target.smallDays).some(Number.isFinite))));group.selects.forEach((select,index)=>{[...select.options].forEach(option=>option.disabled=!!option.value&&(sameModel(option.dataset.model||option.textContent,target.name)||lifecycleUnavailable(task,history.find(item=>itemKey(item)===option.value)||{})));if(!select.value)select.value=rows[index]?itemKey(rows[index].item):'';});});};
    const selectedRefs=(task='progress')=>{const group=groups[task]?.selects.length?groups[task]:groups.progress;return group.selects.map((select,index)=>({item:history.find(candidate=>itemKey(candidate)===select.value),weight:Math.max(Number(group.weights[index]?.value||0),0)})).filter(row=>row.item&&row.item.total_complete!==false&&row.weight>0);};
    const weightedValue=(getter,fallback=NaN,task='progress')=>{const rows=selectedRefs(task).map(row=>({value:Number(getter(row.item)),weight:row.weight})).filter(row=>Number.isFinite(row.value)&&row.weight>0),total=rows.reduce((sum,row)=>sum+row.weight,0);return total?rows.reduce((sum,row)=>sum+row.value*row.weight,0)/total:fallback};
    const stageFor=target=>{const start=target.smallStartDate?new Date(`${target.smallStartDate}T00:00:00`):null,end=target.smallEndDate?new Date(`${target.smallEndDate}T00:00:00`):null,current=new Date(`${today()}T00:00:00`);if(!start||Number.isNaN(start.getTime()))return {key:'unknown',label:'小订时间缺失',day:0,days:0};if(!end||Number.isNaN(end.getTime()))return {key:'unknown',label:'小订结束日期缺失',day:0,days:0};if(end<start)return {key:'unknown',label:'小订窗口冲突',day:0,days:0};const finish=end,days=Math.round((finish-start)/86400000)+1;if(current<start)return {key:'before',label:'小订D1未到',day:0,days};if(+current===+start)return {key:'d1',label:'小订D1进行中',day:1,days};if(current>finish)return {key:'ended',label:'小订期已结束',day:days,days};return {key:'active',label:'小订D1已过',day:Math.round((current-start)/86400000)+1,days}};
    const referenceCompletion=(day,days)=>weightedValue(item=>{const field=(item.small_progress||[]).some(Number)?'small_progress':'standard_progress';return rebasedForecastCompletion(item,field,day,days).value});
    const referenceHourlyCompletion=hour=>weightedValue(item=>window.ForecastMath.smallHourlyCurve(item,hourlyContext().startHour)[hour],NaN,'hourly');
    const renderEvidence=(target,stage,forecast)=>{
      const refs=selectedRefs(),chartRefs=lifecycleChartReferences(workspace.querySelector('[data-lifecycle-reference="small-progress"]'),history,refs),body=refs.map(({item,weight},index)=>{const result=scoreResult(item,target,targetItem());return `<tr><td>${index?'辅助':'主参考'}${result.eligible?'':'·人工'}</td><td><b>${esc(item.model)}</b></td><td>${Math.round(result.score*100)}分 · ${result.evidenceCount}/${smallScoreRules.length}项</td><td>${fmt(item.total)}</td><td>${item.days||0}天</td><td>${(Number(item.d1_share||0)*100).toFixed(1)}%</td><td>${(item.small_hourly_curve||[]).some(Number)?'可用':'缺失'}</td><td>${weight.toFixed(0)}%</td></tr>`}).join('');
      const days=Math.max(Number(forecast?.targetDays||target.smallDays||1),1),labels=Array.from({length:days},(_,index)=>`D${index+1}`),total=Number(forecast?.total||0),actualValues=Array(days).fill(null),forecastValues=Array(days).fill(null);let running=0;
      (forecast?.actualRows||[]).forEach((row,index)=>{running+=Number(row.orders||0);if(index<days&&total>0)actualValues[index]=Math.min(running/total,1)});
      if(!forecast.error&&total>0){running=0;(forecast.rows||[]).forEach((row,index)=>{running+=Number(row.orders||0);if(index<days&&row.actual===false)forecastValues[index]=running/total});const anchor=(forecast.actualRows||[]).length-1;if(anchor>=0&&anchor<days&&forecastValues.some(Number.isFinite))forecastValues[anchor]=actualValues[anchor];}
      const chartSeries=[];if(actualValues.some(Number.isFinite))chartSeries.push({label:`${target.name} · 真实累计`,values:actualValues,color:'#1677FF',role:'actual'});if(forecastValues.some(Number.isFinite))chartSeries.push({label:`${target.name} · 预测累计`,values:forecastValues,color:'#00A878',role:'forecast',dashed:true});
      chartRefs.forEach(({item,label,color})=>{const field=(item.small_progress||[]).some(Number)?'small_progress':'standard_progress';chartSeries.push({label,values:rebasedForecastCompletionCurve(item,field,days),color,role:'reference'})});
      workspace.querySelector('[data-small-evidence]').innerHTML=`<div class="forecast-score-table"><table><thead><tr><th>角色</th><th>参考车型</th><th>匹配分/证据</th><th>最终小订</th><th>曲线天数</th><th>D1占比</th><th>D1分时</th><th>权重</th></tr></thead><tbody>${body||'<tr><td colspan="8">暂无有效参考车型</td></tr>'}</tbody></table></div><p>当前阶段：<b>${esc(stage.label)}</b>。系统自动推荐至少需要${minimumEvidence}项有效评分证据；证据不足的车型仅在人工选择后参与。真实逐日曲线优先，标准化“小订进度”只在真实曲线不可用时回退。主辅权重只影响后续预测加权，不反向改变候选车型得分。</p>`;
      workspace.querySelector('[data-small-reference-chart]').innerHTML=renderLifecycleLineChart({series:chartSeries,labels,unit:'percent',title:'当前真实进度与主辅参考累计完成度',note:'蓝色实线为已结束完整日真实累计÷本次预测终局；绿色虚线为本次预测的后续累计。橙/紫线为主辅参考按当前小订窗口重定基的完成度，与预测使用同一条参考曲线。周期对齐：D1、D2及最后两天的日占比保持不变，中间部分按剩余周期比例拉伸后重新累计；仅对齐参考曲线，不改写历史真实销量。同长度不拉伸；不同长度且任一周期不足5天时不自动推荐该完成度参考。',ariaLabel:`${target.name}当前真实累计小订完成度与主辅参考累计曲线对比`,empty:'当前与所选参考均没有可绘制的小订累计曲线'});
      const dailyNode=workspace.querySelector('[data-small-daily-reference-chart]');
      if(dailyNode){
        const selected=selectedRefs('daily'),dailyRefs=lifecycleChartReferences(workspace.querySelector('[data-lifecycle-reference="small-daily"]'),history,selected),dailySeries=dailyRefs.map(({item,label,color})=>({label,values:Array.from({length:days},(_,index)=>referenceDailyShape(item,index,days)),color,role:'reference'}));
        const current=(forecast.rows||[]).map((row,index)=>Number(row.orders)/(context.factors('small')[context.calendarType(target.smallStartDate,index).type]||1)),anchor=current.find(value=>value>0)||1;
        const actual=current.map((value,index)=>forecast.rows[index].actual?value/anchor:null),predicted=current.map((value,index)=>forecast.rows[index].actual?null:value/anchor);
        const last=(forecast.actualRows||[]).length-1;if(last>=0&&predicted.some(Number.isFinite))predicted[last]=actual[last];
        if(actual.some(Number.isFinite))dailySeries.push({label:target.name+' · 真实',values:actual,color:'#1677FF',role:'actual'});
        if(!forecast.error&&predicted.some(Number.isFinite))dailySeries.push({label:target.name+' · 预测',values:predicted,color:'#00A878',role:'forecast',dashed:true});
        dailyNode.innerHTML=renderLifecycleLineChart({series:dailySeries,labels,unit:'percent',title:'小订每日数量相对D1（到天基础曲线）',note:'主辅基础曲线决定未来逐日形状；先剔除历史日期系数，再按当前节假日、周末、工作日系数分配，日历影响只应用一次。',ariaLabel:'小订到天基础曲线'});
      }
      const hourlyNode=workspace.querySelector('[data-small-hourly-reference-chart]');
      if(hourlyNode){
        const actual=findActual(target.name),bucket=(actual?.small_hourly_days||[]).find(row=>row.date===target.smallStartDate),hourlySeries=[],ongoing=stage.key==='d1',d1Row=(forecast.actualRows||[]).find(row=>row.date===target.smallStartDate),terminal=ongoing&&!forecast.error?Number(forecast.d1):today()>target.smallStartDate?d1Row?.orders:NaN;
        const sampled=(bucket?.hours||[]).filter(row=>Number.isInteger(row.hour)&&row.hour>=0&&row.hour<24&&Number.isFinite(row.orders)&&row.orders>=0),lastHour=sampled.length?Math.max(...sampled.map(row=>row.hour)):-1,firstHour=sampled.filter(row=>row.orders>0).reduce((start,row)=>Math.min(start,row.hour),24);
        if(sampled.length&&Number.isFinite(terminal)&&terminal>0){const byHour=new Map();sampled.forEach(row=>byHour.set(row.hour,(byHour.get(row.hour)||0)+row.orders));const values=Array(24).fill(null);let cumulative=0;for(let hour=firstHour;hour<=lastHour;hour++){cumulative+=byHour.get(hour)||0;values[hour]=cumulative/terminal;}hourlySeries.push({label:target.name+' · D1真实累计',values,color:'#1677FF',role:'actual'});}
        if(forecast.hourly?.forecast?.some(Number.isFinite))hourlySeries.push({label:target.name+' · 后续小时预测',values:forecast.hourly.forecast,color:'#00A878',role:'forecast',dashed:true});
        lifecycleChartReferences(workspace.querySelector('[data-lifecycle-reference="small-hourly"]'),history,selectedRefs('hourly')).forEach(({item,label,color})=>{const start=window.ForecastMath.smallHourlyStart(item),values=Array.from({length:24},(_,hour)=>hour>=start&&Number.isFinite(item.small_hourly_curve?.[hour])?item.small_hourly_curve[hour]:null);if(values.some(Number.isFinite))hourlySeries.push({label:label+' · D1',values,color,role:'reference'});});
        const first=Math.min(...hourlySeries.map(row=>row.values.findIndex(Number.isFinite)).filter(hour=>hour>=0),23),hours=Array.from({length:24-first},(_,index)=>`${first+index}时`);
        const note=sampled.length?`当前已采集至${lastHour}时。已发生${fmt(forecast.hourly?.observed??sampled.reduce((sum,row)=>sum+row.orders,0))}单，后续小时预测${forecast.hourly?fmt(forecast.hourly.remaining):'—'}单；按已发生累计与最近3小时增量拟合历史曲线，全天量等于真实累计加未来预测。各参考从首个有效小订小时绘制（作为发布时间参考）。`:'当前车型D1分时数据缺失，仅展示可用历史参考；不使用整日数据冒充分时。';
        hourlyNode.innerHTML=renderLifecycleLineChart({series:hourlySeries.map(row=>({...row,values:row.values.slice(first)})),labels:hours,hourly:true,unit:'percent',title:'D1 小订分时累计进度',note,ariaLabel:target.name+'小订D1分时累计与主辅参考对比',empty:note});
      }
      workspace.querySelectorAll('[data-lifecycle-reference]').forEach(card=>{const task=card.dataset.lifecycleReference.split('-').at(-1),rows=selectedRefs(task);card.querySelector('[data-lifecycle-ref-reason]').innerHTML=renderLifecycleReferenceScores(rows,item=>task==='hourly'?window.ForecastMath.smallHourlyReferenceScore(item,hourlyContext()):scoreResult(item,target,targetItem()));card._refreshLifecycleControls?.();});










      workspace.querySelector('[data-small-score]').innerHTML=renderLifecycleScorePage({eyebrow:`小订预测独立评分 · ${target.name}`,title:'小订参考车型排名与逐项得分',description:'产品档位、能源类型、发布类型、小订窗口天数，以及双方均有正数时的小订量级共同决定参考。',rules:smallScoreRules,rows:ranked().slice(0,10),selected:selects.map(select=>select.value),empty:'暂无同时具备历史最终小订和可评分字段的候选车型',minimumEvidence});
      const hourlyRules=[{key:'release_hour',label:'发布时间',weight:.2,rule:'起始小时差越小越相似，差12小时为0分。'},{key:'hour_slope',label:'小时增量斜率',weight:.5,rule:'已发生小时新增占比的差异越小越相似；不比较D1绝对量。'},{key:'hour_progress',label:'前几小时累计占比',weight:.3,rule:'各小时累计占已发生总量的比例，与历史同期归一化曲线比较。'}];
      workspace.querySelector('[data-small-score]').innerHTML+=renderLifecycleScorePage({eyebrow:'D1分时独立评分',title:'按发布时间与分时曲线选择参考',description:'比较发布后的相对小时；发布时间20%、小时增量斜率50%、累计占比30%。缺项后按有效权重归一。',rules:hourlyRules,rows:ranked('hourly').slice(0,10),selected:groups.hourly.selects.map(select=>select.value),empty:'暂无可比较的真实分时曲线',minimumEvidence:1,weighted:true});
    };
    const enforceDistinctRefs=()=>{const used=new Set();selects.forEach(select=>{if(select.value&&used.has(select.value))select.value='';if(select.value)used.add(select.value)});selects.forEach(select=>{for(const option of select.options)option.disabled=!!option.value&&(sameModel(option.dataset.model||option.textContent,targetState().name)||selects.some(other=>other!==select&&other.value===option.value))})};
    const update=()=>{enforceDistinctRefs();const target=targetState(),stage=stageFor(target),current=targetItem(),actual=findActual(target.name),transition=findStageActual(target.name,'before'),transitionTotal=Number(transition?.total_small||0),transitionSource=transition?.field_sources?.['总小订']||transition?.selected_source_label||'数据缺失',targetDays=Math.max(stage.days||target.smallDays||current?.daily_orders?.length||1,1),leads=Number(workspace.querySelector('[data-small-input="leads"]')?.value||current?.leads||0),heat=Number(workspace.querySelector('[data-small-input="heat"]')?.value||current?.heat||0),refs=selectedRefs();
      const stageLabel=stage.key==='active'?`${stage.label} · D${stage.day}`:stage.label,error=root.querySelector('[data-small-error]');let message='',confidence='中置信度',d1=NaN,total=0,actualTotal=0,completion=NaN,intradayFloorInfo='',hourly=null;
      setForecastStageSummary(root,'small',stageLabel,'按小订日期校验已结束完整日；最终总小订由预测得出。');
      const dates=current?.dates||[],daily=current?.daily_orders||[],fallback=current?.daily_actual===true?daily.map((orders,index)=>({date:dates[index],orders})):[],checked=completedSmallOrderDays(target.smallStartDate,target.smallEndDate,today(),actual?.small_daily_days||[],fallback),actualRows=checked.rows;actualTotal=actualRows.reduce((sum,row)=>sum+row.orders,0);
      if(target.hasSmall===false){message='该车型没有小订阶段，直接进入大定；不需要小订数量或转化率。';}
      else if(stage.key==='unknown'){message=!target.smallStartDate?'小订开始日期未维护，无法确定小订预测窗口。':!target.smallEndDate?'小订结束日期未维护，无法确定小订预测窗口。':'小订结束日期早于开始日期，请核对时间窗口。';}
      else if(checked.error){message=checked.error;}else if(stage.key==='active'&&checked.missing.length){
        const latest=actualRows.at(-1)?.date||'',present=new Set([...(actual?.small_daily_days||[]),...fallback].map(row=>row.date)),unupdated=latest?checked.missing.filter(day=>day>latest&&!present.has(day)):[],gaps=checked.missing.filter(day=>!unupdated.includes(day));
        message=[gaps.length?`已结束日小订数量缺失或无效：${forecastDateRanges(gaps)}（共${gaps.length}天）`:'',unupdated.length?`小订尚未更新：${forecastDateRanges(unupdated)}（最新完整真实日${latest}）；未更新日期不补0`:'','仅需要过去完整日，不要求最终总小订'].filter(Boolean).join('；');
      }else if(!refs.length&&stage.key!=='ended'){message='没有达到要求的可比小订历史，无法形成预测。'}else if(stage.key==='before'){
        const estimates=refs.map(({item,weight})=>{let value=Number(item.total||0);if(leads>0&&Number(item.leads)>0)value=leads*(Number(item.total)/Number(item.leads));if(heat>0&&Number(item.heat)>0)value*=Math.min(Math.max(Math.sqrt(heat/Number(item.heat)),.6),1.6);return {value,weight}}).filter(row=>row.value>0),weightTotal=estimates.reduce((sum,row)=>sum+row.weight,0);total=weightTotal?estimates.reduce((sum,row)=>sum+row.value*row.weight,0)/weightTotal:0;d1=total*weightedValue(item=>item.d1_share,.2);confidence=leads>0&&heat>0?'中置信度':'低置信度 · 驱动字段未齐';
      }else if(stage.key==='d1'){
        const bucket=(actual?.small_hourly_days||[]).find(row=>row.date===target.smallStartDate);if(!bucket?.hours?.length){message='小订D1分时数据缺失，当前不使用完整日数据冒充分时快照。';}else{hourly=window.ForecastMath.smallHourlyForecast({hours:bucket.hours,references:selectedRefs('hourly'),startHour:hourlyContext().startHour});if(hourly.error)message=hourly.error;else{d1=hourly.total;const d1Share=referenceCompletion(1,targetDays);if(!Number.isFinite(d1Share)||d1Share<=0)message='所选累计参考缺少有效D1占比，无法由D1推算总小订。';else{total=targetDays===1?d1:d1/d1Share;actualTotal=hourly.observed;completion=actualTotal/Math.max(total,1);confidence='中高置信度 · 已发生＋剩余小时预测';}}}
      }else if(stage.key==='ended'){
        total=Number(transitionTotal||(current?.total_complete!==false?current?.total:0)||(!checked.missing.length?actualTotal:0)||0);d1=daily.length?Number(daily[0]):NaN;actualTotal=total;completion=total>0?1:NaN;confidence='真实终值';if(total<=0)message='小订期已结束，但“小订退订分析”和整理表都没有可冻结的最终总量。';
      }else{
        if(!actualRows.length){message='小订D1已过，但退订分析与整理表均没有已结束日期的真实小订。'}else{completion=referenceCompletion(checked.expected,targetDays);if(!Number.isFinite(completion)||completion<=0)message=`参考车型D${checked.expected}累计完成率不可用。`;else{total=Math.max(actualTotal,actualTotal/completion);d1=actualRows[0].orders;confidence=actualRows.length>=3?'高置信度 · 真实进度':'中置信度 · 早期进度';}}
      }
      total=Math.round(total);d1=Number.isFinite(d1)?Math.round(d1):NaN;const rows=[...actualRows];
      if(!message&&stage.key!=='ended'){
        if(stage.key==='d1'&&Number.isFinite(d1))rows.push({label:'D1',date:target.smallStartDate,orders:d1,actual:false,partial:true});
        const startIndex=rows.length,indices=Array.from({length:Math.max(targetDays-startIndex,0)},(_,i)=>startIndex+i),calendar=context.calendarType,factors=context.factors('small');
        const shape=index=>weightedValue(item=>referenceDailyShape(item,index,targetDays),NaN,'daily');
        const anchor=rows.at(-1),result=context.planBridge('small',{remaining:Math.max(total-rows.reduce((sum,row)=>sum+row.orders,0),0),anchor:anchor?.orders??null,anchorDate:anchor?.date||'',anchorShape:anchor?shape(startIndex-1):1,dates:indices.map(i=>calendar(target.smallStartDate,i).date),shapes:indices.map(shape)});
        if(result.error)message=result.error;else{const todayValue=actual?.small_daily_days?.find(row=>row.date===today())?.orders,hourValue=actual?.small_hourly_days?.find(row=>row.date===today())?.orders,observed=Number.isFinite(todayValue)?todayValue:Number.isFinite(hourValue)?hourValue:0,bounded=stage.key==='active'?window.ForecastMath.applyObservedFloor(result.values,observed):{values:result.values,raised:0};if(observed>Number(result.values[0]||0))intradayFloorInfo=`当日已发生${fmt(observed)}单，全天预测已按此下限调整${bounded.raised?`，终局抬升${fmt(bounded.raised)}单`:'，未来余量重新分配'}；当日仍未结束。`;total+=bounded.raised;bounded.values.forEach((orders,i)=>rows.push({label:`D${indices[i]+1}`,date:calendar(target.smallStartDate,indices[i]).date,orders,actual:false,observed:i===0?observed:undefined}));}
      }
      const setKpi=(key,value,suffix='')=>{const node=workspace.querySelector(`[data-small-kpi="${key}"]`);if(node)node.textContent=value};setKpi('d1',message||!Number.isFinite(d1)?'—':fmt(d1));setKpi('total',message?'—':fmt(total));setKpi('actual',fmt(actualTotal));setKpi('completion',message||!Number.isFinite(completion)?'—':(completion*100).toFixed(1));workspace.querySelector('[data-small-confidence]').textContent=message?(target.hasSmall===false?'无小订阶段':'预测条件不足'):confidence;workspace.querySelector('[data-small-chart]').innerHTML=message?(actualRows.length?renderLifecycleBars(actualRows,'orders'):'<div class="empty-image">暂无可绘制的小订数据，具体原因见上方提示</div>'):renderLifecycleBars(rows,'orders');showForecastCondition(error,{stage:'小订预测',state:target.hasSmall===false?'不适用':'条件不足',reasons:[message],impact:target.hasSmall===false?'不执行小订预测；首销和平销仍可预测。':'小订暂不输出预测；已知实际小订保留。'});const source=workspace.querySelector('[data-small-source]'),sourceText=message?message:stage.key==='before'?`按主辅参考最终小订量级${leads>0?'、线索量':''}${heat>0?'及互联网热度':''}测算；不把预测值当作真实进度。`:stage.key==='d1'?'D1真实累计＋按当前小时斜率与历史曲线推算的剩余小时；再按参考D1占比推算最终总小订。':stage.key==='ended'?`小订期已结束，与首销未开始共用“小订退订分析→整理表”优先级；最终总小订取自${transitionSource}。${current?.daily_actual===false?(daily.length?'逐日形状使用“小订进度”回退展示。':'当前无可用逐日形状。'):'逐日形状使用“小订by天”真实曲线。'}`:`已发生${actualRows.length}个完整日，真实累计${fmt(actualTotal)}单 ÷ 参考同期完成率${Number.isFinite(completion)?(completion*100).toFixed(1)+'%':'—'}。`;source.textContent=sourceText+(intradayFloorInfo?' '+intradayFloorInfo:'');setForecastStageSummary(root,'small',stageLabel,source.textContent);
      setEstimate('small_before_estimate',stage.key==='before'&&!message?`${target.name} | 小订终局总量为估算：主辅参考加权${leads>0?'，含线索量折算':''}${heat>0?'，含热度调整':''}；D1=总量×参考D1占比`:'');
      setEstimate('small_d1_extrapolation',stage.key==='d1'&&!message?`${target.name} | D1全天=真实累计${fmt(actualTotal)}＋未来小时预测${fmt(hourly?.remaining||0)}；总小订=D1÷累计参考D1占比`:'');
      setEstimate('small_active_completion',stage.key==='active'&&!message&&Number.isFinite(completion)?`${target.name} | 小订终局总量=真实累计${fmt(actualTotal)}÷参考同期完成率${(completion*100).toFixed(1)}%`:'');
      root._smallForecastResult={name:target.name,stage:stage.key,total:message?null:total,error:message,date:today(),rows};
      renderEvidence(target,stage,{total,actualRows,targetDays,rows,d1,hourly,error:message});context.onForecast?.();};
    initializeReferences();[...workspace.querySelectorAll('[data-small-input]')].forEach(control=>control.oninput=control.onchange=update);bindLifecycleReferenceCards(workspace,root,update);root._smallForecastUpdate=update;update();
  }

  function bindSteadyForecast(root,data,context){
    const workspace=root.querySelector('[data-steady-workspace]');if(!workspace)return;
    const history=data.steady_history||[],launchHistory=[...data.steady_launch_history||[],...data.history||[]],sameModel=context.sameModel,targetState=context.targetState;
    const setEstimate=createForecastEstimateLogger(workspace);
    const targetSteady=target=>history.find(item=>sameModel(item.generation||item.model,target.name)||sameModel(item.model,target.name));
    const targetLaunch=target=>launchHistory.find(item=>sameModel(item.generation||item.model,target.name)||sameModel(item.model,target.name));
    const minimumEvidence=3;
    const steadyScoreRules=[
      {key:'tier',label:'产品档位',weight:.05,rule:'完全一致100%；其他已维护档位50%。'},
      {key:'energy',label:'能源类型',weight:.05,rule:'完全一致100%；不一致55%。'},
      {key:'node',label:'发布类型',weight:.05,rule:'完全一致100%；不一致62%。'},
      {key:'lock',label:'首销期大定到锁单率',weight:.1,rule:'1 − |当前锁单率 − 历史锁单率|，结果限制在0～100%。'},
      {key:'launch_shape',label:'全首销直接大定曲线',weight:.55,rule:'全周期按相对进度适配，仅比较当前已有真实段；日历还原后比较归一化形状，不比较绝对量。'},
      {key:'steady_shape',label:'平销实际趋势',weight:.2,rule:'相同早期平销窗口的日历还原曲线，各自归一后比较。'},
    ];
    const directFeature=(item,target=null)=>{
      const launch=target?targetLaunch(target):launchHistory.find(row=>sameModel(row.generation||row.model,item.generation||item.model));
      const settings=context.factors('launch'),normal=(value,start,index)=>Number(value)/(settings[context.calendarType(start,index).type]||1);
      const currentRows=target?(context.findStageActual(target.name,context.todayIso()>target.endDate?'ended':'active')?.days||[]).filter(row=>row.date>=target.launchDate&&row.date<=target.endDate&&row.date<context.todayIso()).sort((a,b)=>a.date.localeCompare(b.date)):[];
      const direct=target?currentRows.map(row=>row.direct):observedDailyPrefix(launch?.daily_direct||[]);
      const start=target?.launchDate||launch?.launch_date,curve=direct.map((value,index)=>value==null?NaN:normal(value,start,index));
      const weeks=(item?.weeks||[]).filter(row=>row.end_date<context.todayIso()),steady=weeks.slice(-4).map(row=>Number(row.lock)/Array.from({length:7},(_,i)=>context.factors('steady')[context.calendarType(row.start_date,i).type]||1).reduce((a,b)=>a+b,0));
      return {lock_rate:launch?.lock_rate,launch_days:target?.days||launch?.days,direct_curve:curve,steady_curve:steady,launch};
    };
    const scoreResult=(item,target)=>{
      const current=targetSteady(target),left=directFeature(current,target),right=directFeature(item);
      const index=(date,start)=>Math.floor((Date.parse(date)-Date.parse(start))/604800000);
      const currentWeeks=(current?.weeks||[]).filter(row=>row.end_date<context.todayIso()).slice(-4),referenceWeeks=new Map((item.weeks||[]).filter(row=>row.end_date<context.todayIso()).map(row=>[index(row.start_date,item.steady_start_date),row]));
      right.steady_curve=currentWeeks.map(row=>{
        const ref=referenceWeeks.get(index(row.start_date,target.steadyStartDate));
        return ref?Number(ref.lock)/Array.from({length:7},(_,i)=>context.factors('steady')[context.calendarType(ref.start_date,i).type]||1).reduce((a,b)=>a+b,0):NaN;
      });
      return steadyReferenceScore({...item,...right},target,left,minimumEvidence);
    };
    const score=(item,target)=>scoreResult(item,target).score;
    const ranked=()=>{const target=targetState();return history.filter(item=>!sameModel(item.generation||item.model,target.name)&&item.weeks?.length).map(item=>({item,...scoreResult(item,target)})).filter(row=>row.parts.length).sort((a,b)=>b.score-a.score)};
    const selects=[...workspace.querySelectorAll('[data-steady-ref]')],weights=[...workspace.querySelectorAll('[data-steady-weight]')];
    const itemKey=item=>item.event_id||item.model;
    const initializeReferences=()=>{const target=targetState(),rows=ranked().filter(row=>row.eligible);selects.forEach((select,index)=>{[...select.options].forEach(option=>option.disabled=!!option.value&&sameModel(option.dataset.model||option.textContent,target.name));if(!select.value)select.value=rows[index]?itemKey(rows[index].item):''})};
    const refs=()=>selects.map((select,index)=>({item:history.find(candidate=>itemKey(candidate)===select.value),weight:Math.max(Number(weights[index]?.value||0),0)})).filter(row=>row.item&&row.weight>0);
    const weighted=(getter,fallback=NaN)=>{const rows=refs().map(row=>({value:Number(getter(row.item)),weight:row.weight})).filter(row=>Number.isFinite(row.value)&&row.weight>0),total=rows.reduce((sum,row)=>sum+row.weight,0);return total?rows.reduce((sum,row)=>sum+row.value*row.weight,0)/total:fallback};
    const lockValues=item=>(item?.weeks||[]).map(row=>Number(row.lock)).filter(value=>Number.isFinite(value)&&value>=0);
    const recentAverage=item=>{const values=lockValues(item).slice(-4);return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:NaN};
    const recentRatio=item=>{const values=lockValues(item),ratios=values.slice(1).map((value,index)=>values[index]>0?value/values[index]:NaN).filter(Number.isFinite).slice(-4);return ratios.length?ratios.reduce((sum,value)=>sum+value,0)/ratios.length:NaN};
    const isoWeekLabel=value=>{const date=value?new Date(`${value}T00:00:00`):null;if(!date||Number.isNaN(date.getTime()))return '';const utc=new Date(Date.UTC(date.getFullYear(),date.getMonth(),date.getDate())),day=utc.getUTCDay()||7;utc.setUTCDate(utc.getUTCDate()+4-day);const year=utc.getUTCFullYear(),yearStart=new Date(Date.UTC(year,0,1)),week=Math.ceil((((utc-yearStart)/86400000)+1)/7);return `${String(year).slice(-2)}WK${String(week).padStart(2,'0')}`};
    const firstFutureMonday=(target,actualWeeks)=>{if(actualWeeks.length){const last=new Date(`${actualWeeks.at(-1).start_date}T00:00:00`);last.setDate(last.getDate()+7);return last}const start=target.steadyStartDate?new Date(`${target.steadyStartDate}T00:00:00`):null;if(!start||Number.isNaN(start.getTime()))return null;const day=start.getDay(),offset=(8-(day||7))%7;if(offset)start.setDate(start.getDate()+offset);return start};
    const renderEvidence=(target,actualWeeks=[])=>{
      const selected=refs(),chartRefs=lifecycleChartReferences(workspace.querySelector('[data-lifecycle-reference="steady-weekly"]'),history,selected);
      const normalize=values=>{const first=values.find(v=>Number.isFinite(v)&&v>0);return first?values.map(v=>Number.isFinite(v)?v/first:null):values.map(()=>null);};
      const currentFeature=directFeature(targetSteady(target),target),series=[];
      series.push({label:target.name+' · 首销直接大定实际',values:normalize(currentFeature.direct_curve),color:'#1677FF',role:'actual'});
      chartRefs.forEach(({item,label,color})=>series.push({label,values:normalize(directFeature(item).direct_curve),color,role:'reference'}));
      const count=Math.max(...series.map(row=>row.values.length),1);
      workspace.querySelector('[data-steady-reference-chart]').innerHTML=renderLifecycleLineChart({series,labels:Array.from({length:count},(_,i)=>'D'+(i+1)),title:'全首销直接大定曲线规律',note:'各车型先剔除日历影响，再以首个正数日归一；实际历史不改写。评分按周期适配后比较形状，不比较绝对销量。'});
      const transitionSeries=chartRefs.map(({item,label,color})=>({label,values:normalize(directFeature(item).steady_curve),color,role:'reference'}));
      if(currentFeature.steady_curve.length)transitionSeries.unshift({label:target.name+' · 平销实际',values:normalize(currentFeature.steady_curve),color:'#1677FF',role:'actual'});
      workspace.querySelector('[data-steady-evidence]').innerHTML='<p>首销全周期直接大定形状决定参考；历史车型提供进入平销后的相对承接关系。本车型平销实际逐步校准规模和趋势，不套历史绝对量。</p>'+renderLifecycleLineChart({series:transitionSeries,labels:Array.from({length:Math.max(...transitionSeries.map(row=>row.values.length),1)},(_,i)=>'近期完整周'+(i+1)),title:'近期平销趋势（窗口首个正数周＝100%）',note:'仅完整自然周，剔除日历影响，展示各自最近4周；评分另按相同平销进度对齐。无有效完整周时留空。'});
      workspace.querySelectorAll('[data-lifecycle-reference]').forEach(card=>{card.querySelector('[data-lifecycle-ref-reason]').innerHTML=renderLifecycleReferenceScores(selected,item=>scoreResult(item,target));card._refreshLifecycleControls?.();});
      workspace.querySelector('[data-steady-score]').innerHTML=renderLifecycleScorePage({eyebrow:'平销趋势独立评分',title:'全首销直接大定与平销承接参考',description:'以全首销直接大定归一化形状为主，结合已发生平销趋势；无首销形状证据不自动推荐。',rules:steadyScoreRules,rows:ranked().slice(0,10),selected:selects.map(select=>select.value),empty:'暂无有效趋势参考',minimumEvidence,weighted:true});
    };
    const update=()=>{
      const target=targetState(),own=targetSteady(target),actualWeeks=[...(own?.weeks||[])].filter(row=>row.end_date<context.todayIso()).sort((a,b)=>String(a.start_date).localeCompare(String(b.start_date))),error=root.querySelector('[data-steady-error]'),future=[],calendar=context.calendarType,factors=context.factors('steady'),today=context.todayIso(),steadyNotStarted=!!target.steadyStartDate&&target.steadyStartDate>today,dateAt=(date,i)=>calendar(date,i).date,factor=date=>factors[calendar(date,0).type]||1;
      workspace._steadyDaily=[];
      let message='',warnings=[];
      const monday=value=>{const d=new Date(value+'T00:00:00');return dateAt(value,-((d.getDay()+6)%7))};
      const horizonStart=target.steadyStartDate>today?target.steadyStartDate:monday(today),first=target.steadyStartDate>horizonStart?target.steadyStartDate:horizonStart,weekStart=monday(first),dates=Array.from({length:28},(_,i)=>dateAt(weekStart,i)).filter(date=>date>=first),completed=dates.filter(date=>date<today),pending=dates.filter(date=>date>=today);
      const daily=new Map();for(const row of own?.daily||[])daily.set(row.date,daily.has(row.date)?null:row.lock);
      const valid=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value))&&Number(value)>=0;
      // 预测展示窗口只覆盖当前滚动的 4 周，但真实日完整性校验不能被这个窗口截断。
      // 平销开始以来的每一个已结束自然日都必须有真实锁单；否则不能把缺口静默当成预测值。
      const steadyElapsedDays=target.steadyStartDate&&target.steadyStartDate<today?Math.max(0,Math.round((new Date(`${today}T00:00:00`)-new Date(`${target.steadyStartDate}T00:00:00`))/86400000)):0,
        expectedSteadyDates=steadyElapsedDays?Array.from({length:steadyElapsedDays},(_,i)=>dateAt(target.steadyStartDate,i)):[],
        missing=expectedSteadyDates.filter(date=>!valid(daily.get(date))),yesterday=dateAt(today,-1),needsAnchor=target.steadyStartDate&&target.steadyStartDate<today;
      const compactMissingRanges=dates=>{if(!dates.length)return '';const distance=(left,right)=>Math.round((Date.parse(`${right}T00:00:00Z`)-Date.parse(`${left}T00:00:00Z`))/86400000),ranges=[],format=(start,end)=>start===end?start:`${start}～${end}（${distance(start,end)+1}天）`;let start=dates[0],previous=dates[0];for(const date of dates.slice(1)){if(distance(previous,date)===1){previous=date;}else{ranges.push(format(start,previous));start=previous=date;}}ranges.push(format(start,previous));return ranges.join('、')};
      const weekFactor=row=>Array.from({length:7},(_,i)=>factor(dateAt(row.start_date,i))).reduce((a,b)=>a+b,0);
      const normalWeeks=item=>(item?.weeks||[]).filter(row=>row.end_date<today).map(row=>Number(row.lock)/weekFactor(row));
      const normalLevel=item=>{const values=normalWeeks(item).slice(-4);return values.length?values.reduce((a,b)=>a+b,0)/values.length:NaN};
      const normalRatio=item=>{const rows=(item?.weeks||[]).filter(row=>row.end_date<today),values=normalWeeks(item),ratios=values.slice(1).map((value,i)=>values[i]>0&&Date.parse(rows[i+1].start_date)-Date.parse(rows[i].start_date)===604800000?value/values[i]:NaN).filter(Number.isFinite).slice(-4);return ratios.length?ratios.reduce((a,b)=>a+b,0)/ratios.length:NaN};
      const launchProfile=context.findStageActual(target.name,today>target.endDate?'ended':'active');
      const upstream=root._forecastComparison,upstreamScenario=upstream?.scenarios?.progress?.available?upstream.scenarios.progress:upstream?.scenarios?.parameter,upstreamMethod=upstreamScenario===upstream?.scenarios?.progress?'方法一':'方法二';
      const projectedRows=steadyNotStarted&&upstream?.name===target.name&&upstreamScenario?.available&&!upstreamScenario.bridgeError?(upstreamScenario.rows||[]).map(row=>({...row,lock:row.actual&&Number.isFinite(row.lock)?row.lock:row.gross*(upstreamScenario.gross>0?upstreamScenario.lock/upstreamScenario.gross:0)})):[];
      const projectedBaseline=window.ForecastMath.launchDirectLockBaseline({rows:projectedRows,launchDate:target.launchDate,endDate:target.endDate,today:target.steadyStartDate,factor});
      const useProjection=steadyNotStarted&&projectedBaseline.available;
      const launchBaseline=window.ForecastMath.launchDirectLockBaseline({rows:launchProfile?.days||[],launchDate:target.launchDate,endDate:target.endDate,today,factor});
      const hasLaunch=!!target.launchDate&&today>target.launchDate;
      const ownDaily=window.ForecastMath.recentSteadyBaseline({rows:own?.daily||[],startDate:target.steadyStartDate,today,factor});
      const ownLevel=normalLevel(own),ownRatio=normalRatio(own),hasOwn=ownDaily.available||Number.isFinite(ownLevel);
      const launchBasis=useProjection?projectedBaseline:launchBaseline;
      // Reference volumes become dimensionless transfer factors, never target volumes.
      const transfer=weighted(item=>{
        const feature=directFeature(item),curve=feature.direct_curve;
        if(curve.length!==Number(feature.launch_days)||!curve.every(v=>Number.isFinite(v)&&v>=0)||!(feature.lock_rate>0))return NaN;
        const directMean=curve.reduce((a,b)=>a+b,0)/curve.length;
        const start=target.steadyStartDate,relativeWeek=Math.max(0,Math.floor((Date.parse(first)-Date.parse(start))/604800000));
        const historicalWeeks=(item.weeks||[]).filter(row=>row.start_date&&row.end_date<today),aligned=historicalWeeks.filter(row=>{
          const refStart=item.steady_start_date||dateAt(feature.launch?.launch_date,Number(feature.launch_days));
          const index=Math.floor((Date.parse(row.start_date)-Date.parse(refStart))/604800000);
          return index>=relativeWeek&&index<relativeWeek+4;
        });
        if(!aligned.length||!(directMean>0))return NaN;
        const rates=aligned.map(row=>{
          const gross=Number.isFinite(row.gross)?row.gross:Number(row.lock)/feature.lock_rate;
          return gross/weekFactor(row)/directMean;
        }).filter(Number.isFinite);
        return rates.length?rates.reduce((a,b)=>a+b,0)/rates.length:NaN;
      });
      const referenceRatio=weighted(item=>{
        const relative=Math.max(0,Math.floor((Date.parse(first)-Date.parse(target.steadyStartDate))/604800000));
        return normalRatio({...item,weeks:(item.weeks||[]).filter(row=>{const index=Math.floor((Date.parse(row.start_date)-Date.parse(item.steady_start_date))/604800000);return index>=relative&&index<relative+4;})});
      }),ownBase=ownDaily.available?ownDaily.level:ownLevel;
      const ownTrend=ownDaily.available?ownDaily.ratio:ownRatio;
      const predictedLevel=launchBasis.available?launchBasis.level*(Number.isFinite(transfer)?transfer:1):NaN;
      const actualWeight=hasOwn?(Number.isFinite(predictedLevel)?Math.min((ownDaily.days||actualWeeks.length*7)/14,1):1):0;
      const level=actualWeight===1?ownBase:actualWeight>0?ownBase*actualWeight+predictedLevel*(1-actualWeight):predictedLevel;
      const historicalTrend=Number.isFinite(referenceRatio)?referenceRatio:launchBasis.ratio;
      const ratio=actualWeight===1?(Number.isFinite(ownTrend)?ownTrend:1):actualWeight>0?(Number.isFinite(ownTrend)?ownTrend:1)*actualWeight+historicalTrend*(1-actualWeight):historicalTrend;
      const basisText=(useProjection?'首销预测全周期直接大定':'首销全周期真实直接大定')+' × 大定到锁单率'+(Number.isFinite(transfer)?' × 历史相似曲线的平销承接系数 '+transfer.toFixed(3):'；缺少可比承接窗口，暂按1倍、全曲线趋势外推（低置信度）')+'；本车型近期平销实际校准权重'+(actualWeight*100).toFixed(0)+'%';
      workspace._steadyBasis={...launchBasis,level,ratio,actualWeight,transfer,source:actualWeight>=.5?'own_steady':useProjection?'launch_forecast':'launch_direct'};
      if(!target.steadyStartDate)message='平销开始日期缺失。';
      else if(!useProjection&&!hasOwn&&!launchBaseline.available)message=launchBaseline.reason;
      else if(missing.length){
        const latest=[...daily].filter(([day,value])=>day<today&&valid(value)).map(([day])=>day).sort().at(-1)||'',unupdated=latest?missing.filter(day=>day>latest&&!daily.has(day)):[],gaps=missing.filter(day=>!unupdated.includes(day));
        message=[gaps.length?`已结束日交车锁单缺失或无效：${compactMissingRanges(gaps)}（共${gaps.length}天）`:'',unupdated.length?`交车锁单尚未更新：${compactMissingRanges(unupdated)}（最新完整真实日${latest}）；未更新日期不补0`:''].filter(Boolean).join('；');
      }
      else if(needsAnchor&&!valid(daily.get(yesterday)))message=`缺少昨天${yesterday}真实交车锁单，无法以前一天真实值衔接。`;
      else if(!Number.isFinite(level)||!Number.isFinite(ratio)||ratio<0)message='参考完整周不足，无法确定日历修正后的滚动量级与趋势。';
      const actualTotal=completed.reduce((sum,date)=>sum+(valid(daily.get(date))?Number(daily.get(date)):0),0);
      if(!message){
        const dailyRatio=Math.pow(ratio,1/7),shape=date=>Math.pow(dailyRatio,Math.round((Date.parse(date)-Date.parse(first))/86400000)),rawTarget=Math.round(dates.reduce((sum,date)=>sum+level*shape(date)*factor(date),0)),targetTotal=Math.max(rawTarget,actualTotal);
        if(rawTarget<actualTotal)warnings.push('滚动区间总量低于已实现锁单，按真实累计抬升；未来剩余为0');
        const plan=context.planBridge('steady',{remaining:targetTotal-actualTotal,anchor:needsAnchor?Number(daily.get(yesterday)):null,anchorDate:needsAnchor?yesterday:'',anchorShape:needsAnchor?shape(yesterday):1,dates:pending,shapes:pending.map(shape)});
        if(plan.error)message=plan.error;else{
          warnings.push(...plan.warnings);const todayObserved=pending[0]===today&&valid(daily.get(today))?Number(daily.get(today)):0,bounded=window.ForecastMath.applyObservedFloor(plan.values,todayObserved);if(bounded.raised)warnings.push('当日已发生锁单突破原预测，滚动总量已按真实下限抬升');const forecastByDate=new Map(pending.map((date,i)=>[date,bounded.values[i]]));
          for(let week=0;week<4;week++){const start=dateAt(weekStart,week*7),weekDates=dates.filter(date=>date>=start&&date<dateAt(start,7)),real=weekDates.filter(date=>date<today).reduce((sum,date)=>sum+Number(daily.get(date)||0),0),estimate=weekDates.filter(date=>date>=today).reduce((sum,date)=>sum+(forecastByDate.get(date)||0),0);future.push({label:isoWeekLabel(start),date:start,lock:real+estimate,actual:false,real,estimate})}
          workspace._steadyDaily=dates.map(date=>({date,lock:date<today?Number(daily.get(date)):forecastByDate.get(date),actual:date<today}));
        }
      }
      const rows=actualWeeks.filter(row=>row.end_date<weekStart).map(row=>({label:row.period,lock:row.lock,actual:true}));
      rows.push(...future.map(row=>({...row,label:`${row.label}（实际${row.real}＋预测${row.estimate}）`})));
      const blocked=!!message;
      const realRecent=(own?.daily||[]).filter(row=>row.date<today&&row.date>=target.steadyStartDate&&Number.isFinite(row.lock)).sort((a,b)=>a.date.localeCompare(b.date)).slice(-7),realMean=realRecent.length?realRecent.reduce((sum,row)=>sum+row.lock,0)/realRecent.length:NaN;
      const futureMean=pending.length?workspace._steadyDaily.filter(row=>!row.actual).reduce((sum,row)=>sum+row.lock,0)/pending.length:NaN;
      workspace.querySelector('[data-steady-kpi="daily"]').textContent=Number.isFinite(realMean)?fmt(Math.round(realMean)):'—';
      workspace.querySelector('[data-steady-kpi="change"]').textContent=!blocked&&realMean>0&&Number.isFinite(futureMean)?((futureMean/realMean-1)*100).toFixed(1):'—';
      workspace.querySelector('[data-steady-kpi="basis"]').textContent=blocked?'等待有效数据':actualWeight>=.5?'平销实际主导':'首销曲线推算主导';
      workspace.querySelector('[data-steady-kpi="total"]').textContent=blocked?'—':fmt(future.reduce((sum,row)=>sum+row.lock,0));
      workspace.querySelector('[data-steady-chart]').innerHTML=blocked?(rows.length?renderLifecycleBars(rows,'lock'):'<div class="empty-image">暂无可绘制的平销数据，具体原因见上方提示</div>'):renderLifecycleBars(rows,'lock');
      workspace.querySelector('[data-steady-confidence]').textContent=message?'预测条件不足':steadyNotStarted?'平销前预测 · 上游估算输入':'按天衔接 · 按周汇总';
      showForecastCondition(error,{stage:'平销预测',reasons:[message],impact:'平销暂不输出预测；已知实际交车锁单保留。'});
      const sourceText=message||`${basisText}。本周起4周滚动区间，已实现${fmt(actualTotal)}单；日历修正的滚动总量减去真实累计，再以前一天真实锁单衔接并渐进分配。真实日不变。${warnings.join('；')}`;
      const stageLabel=target.steadyStartDate>today?'平销尚未开始':'平销期进行中';workspace.querySelector('[data-steady-source]').textContent=sourceText;setForecastStageSummary(root,'steady',stageLabel,sourceText);renderEvidence(target,actualWeeks);
    };
    initializeReferences();bindLifecycleReferenceCards(workspace,root,update);root._steadyForecastUpdate=update;update();
  }


  function renderForecastReferenceChartV2(root,data,history,scopeCard=null){
    const referencePalette=['#FF8A00','#7C3AED','#D9485F','#00A6A6','#B7791F','#6B7280','#DB2777','#65A30D','#C2410C','#475569','#9333EA','#0F766E'],referenceColor=index=>referencePalette[index%referencePalette.length],actualColor='#1677FF',forecastColor='#00A878',comparison=root._forecastComparison||null;
    const taskSpecs={
      hourly:{metric:'hourly_curve',title:comparison?.hourly?.date?`D${comparison.hourly.day} · ${comparison.hourly.date} 分时累计进度`:'D1 分时累计参考',unit:'rate',hourly:true},
      small_progress:{metric:'daily_small',title:'小转大真实斜率与预测完成度',unit:'rate',observableShape:true,component:'small_to_big'},
      direct_progress:{metric:'daily_direct',title:'直接大定真实斜率与预测完成度',unit:'rate',observableShape:true,component:'direct'},
      daily:{metric:'daily_orders',title:'首销每日大定相对D1（基础曲线）',unit:'rate',normalize:true},
      daily_slope:{metric:'daily_orders',title:'每日斜率 · 较前一天变化率（仅展示）',unit:'rate',slope:true},
    };
    const splitCurrent=(values,actualFlags)=>{const actual=values.map((value,index)=>actualFlags[index]?value:null),forecast=values.map((value,index)=>actualFlags[index]?null:value),firstForecast=actualFlags.findIndex(value=>!value);if(firstForecast>0&&Number.isFinite(Number(values[firstForecast-1])))forecast[firstForecast-1]=values[firstForecast-1];return {actual,forecast}};
    const currentTaskSeries=(task,spec)=>{
      if(!comparison)return {actual:[],forecast:[]};
      if(task==='hourly')return {actual:comparison.hourlyActual||[],forecast:comparison.hourlyForecast||[]};
      const rows=spec.observableShape?(comparison.progressRows||[]):(comparison.rows||[]);let values=[];
      if(spec.observableShape){const terminal=rows.reduce((sum,row)=>sum+Math.max(Number(row[spec.component]||0),0),0);let running=0;const actual=rows.map(row=>{if(!row.actual)return null;running+=Math.max(Number(row[spec.component]||0),0);return terminal>0?running/terminal:null});return {actual,forecast:[]}}
      if(task==='daily'||spec.slope)values=rows.map(row=>Number(row.daily_gross||0));
      else if(task==='small_progress')values=rows.map(row=>Number(row.small_completion||0));
      else if(task==='direct_progress')values=rows.map(row=>Number(row.direct_completion||0));
      if((task==='daily'||spec.slope)&&root._forecastDailyEvidence?.targetFactor){values=values.map((value,index)=>value/root._forecastDailyEvidence.targetFactor(index));const anchor=values.find(value=>value>0)||1;values=values.map(value=>value/anchor)}else if(spec.normalize){const anchor=values.find(value=>value>0)||1;values=values.map(value=>value/anchor)}
      if(spec.slope)values=window.ForecastMath.dailySlope(values);
      return splitCurrent(values,rows.map(row=>!!row.actual));
    };
    const referenceMeta=(card,item,index)=>{const selects=[...card.querySelectorAll('[data-forecast-ref]')],main=selects[0]?.value,aux=selects[1]?.value,mainWeight=Number(card.querySelector('[data-forecast-ref-weight][data-ref-slot="0"]')?.value||0),auxWeight=Number(card.querySelector('[data-forecast-ref-weight][data-ref-slot="1"]')?.value||0);if(item.model===main)return {label:card.dataset.forecastTask==='daily_slope'?`主参考 · ${item.model}`:`主参考${mainWeight}% · ${item.model}`,color:'#FF8A00',core:true};if(item.model===aux)return {label:card.dataset.forecastTask==='daily_slope'?`辅助参考 · ${item.model}`:`辅助参考${auxWeight}% · ${item.model}`,color:'#7C3AED',core:true};return {label:`对比 · ${item.model}`,color:referenceColor(index+2),core:false}};
    const renderLockChart=(target,items,card)=>{
      const fields=[['net_rate','留存大定率'],['lock_rate','大定到锁单率']],W=920,H=245,left=48,right=20,top=28,bottom=46,plotW=W-left-right,plotH=H-top-bottom,groupW=plotW/fields.length,currentName=comparison?.name||'当前预测代际';
      const series=[];
      if(comparison&&Object.values(comparison.actualRates||{}).some(Number.isFinite))series.push({name:`${currentName} · 真实`,values:comparison.actualRates,color:actualColor,kind:'actual'});
      if(comparison)series.push({name:`${currentName} · 预测`,values:comparison.forecastRates,color:forecastColor,kind:'forecast'});
      items.forEach((item,index)=>{const meta=referenceMeta(card,item,index);series.push({name:meta.label,values:item,color:meta.color,kind:'reference'})});
      const barW=Math.max(5,Math.min(34,(groupW-18)/Math.max(series.length,1)-3)),barGap=Math.max(1,Math.min(8,barW*.25));
      const grid=[0,.25,.5,.75,1].map(rate=>{const y=top+plotH*(1-rate);return `<line x1="${left}" y1="${y}" x2="${W-right}" y2="${y}" stroke="#E8F0F7"/><text x="${left-8}" y="${y+4}" text-anchor="end" font-size="9" fill="#7890A6">${Math.round(rate*100)}%</text>`}).join('');
      const bars=fields.map(([field,label],fieldIndex)=>{const center=left+(fieldIndex+.5)*groupW,content=series.map((item,itemIndex)=>{const raw=Number(item.values?.[field]);if(!Number.isFinite(raw))return '';const value=Math.min(Math.max(raw,0),1),x=center+(itemIndex-(series.length-1)/2)*(barW+barGap)-barW/2,y=top+plotH*(1-value),forecast=item.kind==='forecast',showLabel=series.length<=8||item.kind!=='reference';return `<rect x="${x}" y="${y}" width="${barW}" height="${top+plotH-y}" rx="${Math.min(4,barW/2)}" fill="${forecast?'#E7F8F1':item.color}" stroke="${item.color}" stroke-width="${forecast?2:1}" ${forecast?'stroke-dasharray="5 3"':''} opacity=".9"><title>${esc(item.name)} · ${label} ${(value*100).toFixed(1)}%</title></rect>${showLabel?`<text x="${x+barW/2}" y="${Math.max(y-7,12)}" text-anchor="middle" font-size="9" font-weight="700" fill="${item.color}">${(value*100).toFixed(1)}%</text>`:''}`}).join('');return `${content}<text x="${center}" y="${H-18}" text-anchor="middle" font-size="10" fill="#60778D">${label}</text>`}).join('');
      const legend=series.map(item=>`<span><i class="${item.kind==='forecast'?'forecast-outline-key':''}" style="background:${item.kind==='forecast'?'#E7F8F1':item.color};border-color:${item.color}"></i>${esc(item.name)}</span>`).join('');
      target.innerHTML=`<div class="forecast-task-chart-title"><strong>留存大定率与大定到锁单率对比</strong><span>大定到锁单率＝首销期锁单÷总大定；实心柱为真实/历史，绿色描边柱为当前预测</span></div><div class="forecast-svg-scroll"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="当前预测代际与参考传播名留存大定率和大定到锁单率比较">${grid}${bars}</svg></div><div class="legend forecast-task-legend">${legend}</div>`;
    };
    const renderParameterDailyChart=(target,items,card,task)=>{
      const conversionTask=task==='conversion',title=conversionTask?'方法二 · 小订转化率 by天':'方法二 · 直接大定占比 by天',currentName=comparison?.name||'当前预测代际',parameterRows=comparison?.parameterRows||[],series=[];
      const currentValues=parameterRows.map(row=>row[conversionTask?'small_conversion':'direct_share']??NaN),split=splitCurrent(currentValues,parameterRows.map(row=>!!row.actual));
      if(split.actual.some(Number.isFinite))series.push({name:currentName+' · 真实',values:split.actual,color:actualColor,kind:'actual',dash:''});
      if(split.forecast.some(Number.isFinite))series.push({name:currentName+' · 方法二预测',values:split.forecast,color:'#00A878',kind:'parameter',dash:'7 5'});
      items.forEach((item,index)=>{const dailySmall=observedDailyPrefix(item.daily_small||[]),dailyDirect=observedDailyPrefix(item.daily_direct||[]),dailyGross=observedDailyPrefix(item.daily_orders||[]),length=conversionTask?dailySmall.length:Math.min(dailyDirect.length,dailyGross.length),values=[];let cumulativeSmall=0,cumulativeDirect=0,cumulativeGross=0;for(let day=0;day<length;day+=1){cumulativeSmall+=Math.max(Number(dailySmall[day]||0),0);cumulativeDirect+=Math.max(Number(dailyDirect[day]||0),0);cumulativeGross+=Math.max(Number(dailyGross[day]||0),0);values.push(conversionTask?(Number(item.small)>0?cumulativeSmall/Number(item.small):NaN):(cumulativeGross>0?cumulativeDirect/cumulativeGross:NaN))}const meta=referenceMeta(card,item,index);if(values.some(Number.isFinite))series.push({name:meta.label,values,color:meta.color,kind:'reference',dash:''})});
      const finiteValues=series.flatMap(item=>item.values.filter(Number.isFinite));if(!finiteValues.length){target.innerHTML='<div class="empty-image">暂无可比较的by天比例曲线</div>';return}
      const maxPoints=Math.max(...series.map(item=>item.values.length),1),W=Math.max(920,maxPoints*23+105),H=270,left=52,right=22,top=30,bottom=48,plotW=W-left-right,plotH=H-top-bottom,peak=Math.max(...finiteValues,.01),yMax=Math.min(1,Math.max(.1,Math.ceil(peak*1.12*10)/10)),x=index=>left+(maxPoints===1?0:index/(maxPoints-1))*plotW,y=value=>top+plotH*(1-Math.min(Math.max(value/yMax,0),1));
      const grid=[0,.25,.5,.75,1].map(rate=>{const gy=top+plotH*(1-rate);return `<line x1="${left}" y1="${gy}" x2="${W-right}" y2="${gy}" stroke="#E8F0F7"/><text x="${left-8}" y="${gy+4}" text-anchor="end" font-size="9" fill="#7890A6">${(yMax*rate*100).toFixed(0)}%</text>`}).join('');
      const lines=series.map(curve=>{const indexes=curve.values.map((value,index)=>Number.isFinite(value)?index:-1).filter(index=>index>=0),points=indexes.map(index=>`${x(index)},${y(curve.values[index])}`).join(' '),labels=indexes.map((index,position)=>{if(position!==indexes.length-1&&(index+1)%7!==0)return '';const value=curve.values[index];return `<circle cx="${x(index)}" cy="${y(value)}" r="3" fill="#fff" stroke="${curve.color}" stroke-width="2"/><text x="${x(index)}" y="${y(value)+(curve.kind==='parameter'?-9:14)}" text-anchor="middle" font-size="9.5" font-weight="700" fill="${curve.color}">${(value*100).toFixed(1)}%</text>`}).join('');return `${points?`<polyline points="${points}" fill="none" stroke="${curve.color}" stroke-width="${curve.kind==='parameter'?3:2}" ${curve.dash?`stroke-dasharray="${curve.dash}"`:''}><title>${esc(curve.name)}</title></polyline>`:''}${labels}`}).join('');
      const tickCount=Math.min(maxPoints,8),ticks=Array.from({length:tickCount},(_,slot)=>{const index=Math.round(slot*(maxPoints-1)/Math.max(tickCount-1,1));return `<text x="${x(index)}" y="${H-16}" text-anchor="middle" font-size="9" fill="#7890A6">D${index+1}</text>`}).join(''),legend=series.map(curve=>`<span><i class="line-key${curve.dash?' dotted':''}" style="border-color:${curve.color}"></i>${esc(curve.name)}</span>`).join('');
      const note=conversionTask?'逐日累计小转大 ÷ 总小订':'逐日累计直接大定 ÷ 逐日累计总大定';
      target.innerHTML=`<div class="forecast-task-chart-title"><strong>${title}</strong><span>${note}；蓝色实线为当前真实；绿色虚线为方法二估算/预测；其余实线为历史参考</span></div><div class="forecast-svg-scroll"><svg viewBox="0 0 ${W} ${H}" style="width:${W}px" role="img" aria-label="${title}折线图">${grid}${lines}${ticks}</svg></div><div class="legend forecast-task-legend">${legend}</div>`;
    };
    const cards=scopeCard?[scopeCard]:[...root.querySelectorAll('[data-forecast-task]')];
    cards.forEach(card=>{
      const task=card.dataset.forecastTask,target=card.querySelector('[data-forecast-task-chart]'),selectedNames=[...card.querySelectorAll(`[data-forecast-chart-ref="${task}"]:checked`)].map(node=>node.value),items=[...new Set(selectedNames)].map(name=>history.get(name)).filter(Boolean);
      if(!target)return;
      if(!items.length&&!comparison){target.innerHTML='<div class="empty-image">暂无可比较的车型曲线</div>';return}
      if(task==='lock'){renderLockChart(target,items,card);return}
      if(task==='conversion'||task==='direct_share'){renderParameterDailyChart(target,items,card,task);return}
      const spec=taskSpecs[task]||taskSpecs.daily,current=currentTaskSeries(task,spec),targetDays=Math.max(1,Number(comparison?.progressRows?.length||data.target?.launch_days||data.target?.days||1));
      const references=items.map((item,index)=>{let values=(item[spec.metric]||[]).map(value=>value==null?NaN:Number(value));if(spec.observableShape){const completionField=task==='small_progress'?'small_progress':'direct_progress';values=rebasedForecastCompletionCurve(item,completionField,targetDays)}else if(spec.slope){values=values.map((value,day)=>value/(root._forecastDailyEvidence?.historicalFactor(item,day)||1))}else if(task==='daily'&&root._forecastDailyEvidence){const orders=root._forecastDailyEvidence.adaptedDailyOrders(item,targetDays),first=Number(orders[0]||0)/root._forecastDailyEvidence.historicalFactor(item,0);values=orders.map((order,day)=>{const adjusted=Number(order||0)/root._forecastDailyEvidence.historicalFactor(item,day);return first>0&&adjusted>=0?adjusted/first:NaN})}else if(spec.hourly){values=window.ForecastMath.smallHourlyCurve(window.ForecastMath.launchHourlyItem(item));}else{values=values.filter(Number.isFinite);if(spec.normalize){const anchor=values.find(value=>value>0)||1;values=values.map(value=>value/anchor)}}if(spec.slope)values=window.ForecastMath.dailySlope(values);const meta=referenceMeta(card,item,index);return {name:meta.label,values,color:meta.color,role:'reference',dash:'',core:meta.core}}).filter(item=>item.values.some(Number.isFinite));
      if(spec.hourly&&comparison?.hourly?.referenceCurve?.length)references.push({name:comparison.hourly.referenceLabel,values:comparison.hourly.referenceCurve,color:'#60768D',role:'reference',dash:'',core:true});
      const currentSeries=[];
      if((current.actual||[]).some(Number.isFinite))currentSeries.push({name:spec.observableShape?(task==='small_progress'?'小转大真实归一化累计斜率':'直接大定真实归一化累计斜率'):`当前 ${comparison?.name||''} · 真实`,values:current.actual,color:actualColor,role:'actual',dash:''});
      if(spec.observableShape){const completionField=task==='small_progress'?'small_completion':'direct_completion',completionValues=(comparison?.progressRows||[]).map(row=>Number(row[completionField]));if((comparison?.progressRows||[]).some(row=>!row.actual))currentSeries.push({name:task==='small_progress'?'参考确认后的小转大预测完成度':'参考确认后的直接大定预测完成度',values:splitCurrent(completionValues,(comparison?.progressRows||[]).map(row=>!!row.actual)).forecast,color:forecastColor,role:'forecast',dash:'7 5'})}
      if(!spec.observableShape&&(current.forecast||[]).some(Number.isFinite))currentSeries.push({name:`当前 ${comparison?.name||''} · 预测`,values:current.forecast,color:forecastColor,role:'forecast',dash:'7 5'});
      const series=[...references,...currentSeries],hourStarts=spec.hourly?series.map(row=>row.values.findIndex(Number.isFinite)).filter(i=>i>=0):[],hourOffset=hourStarts.length?Math.min(...hourStarts):0;if(hourOffset)series.forEach(row=>row.values=row.values.slice(hourOffset));const finiteValues=series.flatMap(item=>item.values.filter(Number.isFinite));
      if(!finiteValues.length){target.innerHTML='<div class="empty-image">当前预测代际及所选参考暂无对应曲线（分时缺失时：无D1分时数据）</div>';return}
      const maxPoints=Math.max(...series.map(item=>item.values.length),1),format=value=>spec.unit==='rate'?`${(value*100).toFixed(value<.1?1:0)}%`:Math.round(value).toLocaleString('zh-CN');
      const note=spec.hourly?`${comparison?.hourly?.missing?'无D1分时数据。':''}发布前留空，参考从各自首个有效成交小时开始（发布时间近似）。分子为截至各小时真实大定；${comparison?.hourly?.ongoing?'分母为当日预计全天大定，因此蓝线百分比也受预测分母影响':'分母为同一天实际大定，数据未齐时不强行拉到100%'}。绿色虚线为后续小时估算；橙/紫线为历史D1对比。滚动采用${comparison?.hourly?.referenceLabel||'历史D1参考'}。${comparison?.hourly?.date?`当前累计${fmt(comparison.hourly.observed)}单 / 全天${fmt(comparison.hourly.terminal)}单。`:''}`:spec.slope?'斜率＝（剔除日历影响后的当天日量÷前一天日量－1）×100%；D1、前一天为0或数据缺失时不计算；独立评分仅用于选择对比车型，不参与销量预测。蓝色为真实、绿色虚线为预测。':spec.observableShape?`蓝色实线＝截至各日真实累计量÷方法一预测终局，因此当前真实日不会提前归一到100%；绿色虚线和历史参考均按预测对象首销周期重定基，只有首销结束日达到100%；预测完成度仅用于方法一展示和反推，不参与参考车型评分`:(task==='daily'?`曲线值＝适配到当前首销周期后的每日总大定÷历史日期类型系数，再除以剔除日历影响后的D1；D1=100%，用于未来余量的基础形状，当前日期系数在分配时另乘`:'蓝色实线为当前真实，绿色虚线为当前预测');
      target.innerHTML=renderForecastEvidenceLines({series,labels:Array.from({length:maxPoints},(_,index)=>spec.hourly?`${index+hourOffset}时`:`D${index+1}`),ariaLabel:spec.title,title:spec.title,note:note+(spec.observableShape?'周期对齐：D1、D2及最后两天的日占比保持不变，中间部分按剩余周期比例拉伸后重新累计；仅对齐参考曲线，不改写历史真实销量。同长度不拉伸；不同长度且任一周期不足5天时不自动推荐该完成度参考。':''),unit:spec.unit,slope:!!spec.slope,hourly:!!spec.hourly,extra:'',table:true});
    });
  }

  function renderForecastDecisionChartV2(root,rows,method='parameter'){
    const target=root.querySelector(`[data-forecast-decision-chart="${method}"]`);if(!target)return;
    if(!rows.length){target.innerHTML='<div class="empty-image">暂无可绘制的首销期预测</div>';return}
    const W=Math.max(980,rows.length*23+110),H=330,left=58,right=54,top=34,bottom=52,plotW=W-left-right,plotH=H-top-bottom,maxGross=Math.max(...rows.map(row=>row.cumulative_gross||0),1)*1.12,barW=Math.max(7,Math.min(16,plotW/rows.length*.62));
    const x=i=>left+(i+.5)*plotW/rows.length,yGross=value=>top+plotH*(1-value/maxGross),yRate=value=>top+plotH*(1-Math.min(Math.max(value,0),1));
    const grid=[0,.25,.5,.75,1].map(rate=>{const y=top+plotH*(1-rate);return `<line x1="${left}" y1="${y}" x2="${left+plotW}" y2="${y}" stroke="#E8F0F7"/><text x="${left-9}" y="${y+4}" text-anchor="end" font-size="10" fill="#7890A6">${Math.round(maxGross*rate).toLocaleString('zh-CN')}</text><text x="${left+plotW+9}" y="${y+4}" font-size="10" fill="#7890A6">${Math.round(rate*100)}%</text>`}).join('');
    const futureFill=method==='progress'?'#43CFA0':'#FFB340',bars=rows.map((row,index)=>{const y=yGross(row.cumulative_gross),fill=row.actual?'#6DB5FF':row.partial?'#FFAE42':row.past_missing?'#AAB8C5':row.current_estimate?'#F5C56B':futureFill,label=index===0||index===rows.length-1||row.cut||row.past_missing||((index+1)%7===0);return `<rect x="${x(index)-barW/2}" y="${y}" width="${barW}" height="${top+plotH-y}" rx="3" fill="${fill}" opacity=".9"><title>${esc(row.day)} ${esc(row.date||'')} · ${esc(row.day_type_label||'')} · 当日${fmt(row.daily_gross)} · 累计${fmt(row.cumulative_gross)}</title></rect>${label?`<text x="${x(index)}" y="${Math.max(y-7,13)}" text-anchor="middle" font-size="10" font-weight="700" fill="#49647D">${fmt(row.cumulative_gross)}</text>`:''}`}).join('');
    const line=(field,color)=>{const segments=predicate=>{const result=[];let current=[];rows.forEach((row,index)=>{if(predicate(row)&&row[field]!=null&&Number.isFinite(Number(row[field])))current.push(index);else if(current.length){result.push(current);current=[]}});if(current.length)result.push(current);return result},path=indexes=>indexes.length>1?indexes.map(index=>`${x(index)},${yRate(Number(rows[index][field]))}`).join(' '):'',actualPaths=segments(row=>row.actual),estimatePaths=segments(row=>!row.actual).map(indexes=>indexes[0]>0&&rows[indexes[0]-1]?.actual?[indexes[0]-1,...indexes]:indexes);return `${actualPaths.map(indexes=>path(indexes)).filter(Boolean).map(points=>`<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.5"/>`).join('')}${estimatePaths.map(indexes=>path(indexes)).filter(Boolean).map(points=>`<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2.5" stroke-dasharray="7 5"/>`).join('')}`};
    const dots=rows.map((row,index)=>index===rows.length-1||row.cut||((index+1)%7===0)?`<circle cx="${x(index)}" cy="${yRate(row.small_conversion)}" r="3" fill="#fff" stroke="#1677FF" stroke-width="2"/><text x="${x(index)}" y="${yRate(row.small_conversion)-7}" text-anchor="middle" font-size="9" font-weight="700" fill="#1677FF">${(row.small_conversion*100).toFixed(1)}%</text><circle cx="${x(index)}" cy="${yRate(row.direct_share)}" r="3" fill="#fff" stroke="#C00000" stroke-width="2"/><text x="${x(index)}" y="${yRate(row.direct_share)+13}" text-anchor="middle" font-size="9" font-weight="700" fill="#C00000">${(row.direct_share*100).toFixed(1)}%</text>`:'').join('');
    const latestCancelIndex=rows.reduce((found,row,index)=>row.cancel_rate!=null&&Number.isFinite(Number(row.cancel_rate))?index:found,-1),latestCancel=latestCancelIndex>=0?rows[latestCancelIndex]:null,cancelDot=latestCancel?`<rect x="${x(latestCancelIndex)-3}" y="${yRate(latestCancel.cancel_rate)-3}" width="6" height="6" rx="1" fill="#F59E0B"/><text x="${x(latestCancelIndex)}" y="${yRate(latestCancel.cancel_rate)-8}" text-anchor="middle" font-size="9" font-weight="700" fill="#9A5B00">${(latestCancel.cancel_rate*100).toFixed(1)}%</text>`:'';
    const ticks=rows.map((row,index)=>index===0||index===rows.length-1||((index+1)%7===0)?`<text x="${x(index)}" y="${H-27}" text-anchor="middle" font-size="9" fill="#6F879D">${esc(row.day)}</text><text x="${x(index)}" y="${H-13}" text-anchor="middle" font-size="8" fill="#94A6B7">${esc(row.day_type_short||'')}</text>`:'').join('');
    target.innerHTML=`<div class="forecast-svg-scroll"><svg class="forecast-decision-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="累计大定柱形与小订转化率、直接大定占比折线组合图">${grid}${bars}${line('small_conversion','#1677FF')}${line('direct_share','#C00000')}${dots}${ticks}</svg></div><div class="legend forecast-chart-legend"><span><i style="background:#6DB5FF"></i>已冻结累计大定</span><span><i style="background:#FFAE42"></i>分时滚动</span><span><i style="background:#AAB8C5"></i>过期缺失补估</span><span><i style="background:#F5C56B"></i>当日整日估算</span><span><i style="background:${futureFill}"></i>${method==='progress'?'方法一未来预测':'方法二未来预测'}</span><span><i class="line-key" style="border-color:#1677FF"></i>累计小转大率（累计小转大÷总小订）</span><span><i class="line-key" style="border-color:#C00000"></i>直接大定占比</span><span><i class="line-key dotted" style="border-color:#60768D"></i>估算与预测段统一虚线</span></div>`;
  }

  function renderForecastWeeklyV2(root,rows,method='parameter'){
    const target=root.querySelector(`[data-forecast-weekly="${method}"]`);if(!target)return;
    const groups=new Map(),weekKey=value=>{const date=value?new Date(`${value}T00:00:00`):null;if(!date||Number.isNaN(date.getTime()))return '';const utc=new Date(Date.UTC(date.getFullYear(),date.getMonth(),date.getDate())),day=utc.getUTCDay()||7;utc.setUTCDate(utc.getUTCDate()+4-day);const yearStart=new Date(Date.UTC(utc.getUTCFullYear(),0,1)),week=Math.ceil((((utc-yearStart)/86400000)+1)/7);return `${utc.getUTCFullYear()}W${String(week).padStart(2,'0')}`};
    rows.forEach((row,index)=>{const key=weekKey(row.date)||`第${Math.floor(index/7)+1}周`,group=groups.get(key)||{key,daily:0,end:0,actual:0,forecast:0,backfill:0};group.daily+=Number(row.daily_gross||0);group.end=Number(row.cumulative_gross||0);if(row.actual)group.actual+=Number(row.daily_gross||0);else if(row.past_missing)group.backfill+=Number(row.daily_gross||0);else group.forecast+=Number(row.daily_gross||0);groups.set(key,group)});
    target.innerHTML=[...groups.values()].map(group=>`<article><span>${esc(group.key)}</span><strong>${fmt(group.daily)}</strong><small>周大定 · 期末累计${fmt(group.end)}</small><em>${group.backfill?`含过期补估${fmt(group.backfill)}${group.forecast?` · 未来预测${fmt(group.forecast)}`:''}`:group.forecast?`含预测${fmt(group.forecast)}`:'全部真实'}</em></article>`).join('');
  }

  function bindForecastWorkspaceV2(){
    const root=document.querySelector('.forecast-workspace.forecast-v2');if(!root)return;
    const draftTarget=JSON.parse(root.dataset.forecastConfig||'{}').target;
    root._forecastSubjectId=state.subject+(draftTarget?.secondary_generation?'|'+forecastModelKey(draftTarget.name):'');root._forecastTouched=new Set();
    const data=JSON.parse(root.dataset.forecastConfig||'{}'),historyList=data.history||[],history=new Map(historyList.map(item=>[item.model,item])),targetList=[...data.targets||[],...data.steady_targets||[]],actualList=[...data.steady_actuals||[],...data.actuals||[]],modelAliases=data.model_aliases||{};
    const modelKey=value=>forecastModelKey(value,modelAliases),sameModel=(a,b)=>sameForecastModel(a,b,modelAliases),findTarget=name=>targetList.find(item=>sameModel(item.name,name)),findActual=name=>actualList.find(item=>sameModel(item.model,name));
    const findStageActual=(name,stage)=>{const base=findActual(name),variant=base?.stage_profiles?.[stage];return variant?{...base,...variant}:base};
    const isoDate=date=>[date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');
    const calendarConfig=data.china_calendar||{},holidayMap=new Map(Object.entries(calendarConfig.holidays||{})),adjustedWorkdays=new Set(calendarConfig.adjusted_workdays||[]),publishedYears=new Set((calendarConfig.published_years||[]).map(Number));
    const calendarType=(launchDate,index)=>{const launch=launchDate?new Date(`${launchDate}T00:00:00`):null;if(!launch||Number.isNaN(launch.getTime()))return {date:'',type:'workday',label:'工作日',name:'',adjusted:false,official:false};launch.setDate(launch.getDate()+index);const date=isoDate(launch),official=publishedYears.has(launch.getFullYear());if(adjustedWorkdays.has(date))return {date,type:'workday',label:'调休工作日',name:'调休上班',adjusted:true,official:true};if(holidayMap.has(date))return {date,type:'holiday',label:holidayMap.get(date),name:holidayMap.get(date),adjusted:false,official:true};if(launch.getDay()===0||launch.getDay()===6)return {date,type:'weekend',label:'周末',name:'',adjusted:false,official};return {date,type:'workday',label:'工作日',name:'',adjusted:false,official}};
    const dayIndexForDate=(launchDate,value)=>{const launch=launchDate?new Date(`${launchDate}T00:00:00`):null,date=value?new Date(`${value}T00:00:00`):null;if(!launch||!date||Number.isNaN(launch.getTime())||Number.isNaN(date.getTime()))return -1;return Math.round((date-launch)/86400000)};
    const calendarProfile=(launchDate,days)=>{if(!launchDate)return {valid:false,days:0,early_types:[]};const rows=Array.from({length:Math.max(1,Number(days||35))},(_,index)=>calendarType(launchDate,index)),names=[...new Set(rows.map(row=>row.name).filter(Boolean))];return {valid:true,days:rows.length,workdays:rows.filter(row=>row.type==='workday').length,weekends:rows.filter(row=>row.type==='weekend').length,holidays:rows.filter(row=>row.type==='holiday').length,adjusted_workdays:rows.filter(row=>row.adjusted).length,holiday_names:names,early_types:rows.slice(0,14).map(row=>row.type),covered:rows.every(row=>row.official)}};
    const calendarSimilarity=(left,right)=>{if(!left?.valid||!right?.valid||!left.early_types?.length||!right.early_types?.length)return NaN;const ratio=(a,b)=>Math.max(0,1-Math.abs(Number(a||0)-Number(b||0))/Math.max(Number(a||0),Number(b||0),1)),pairs=left.early_types.map((value,index)=>[value,right.early_types[index]]).filter(([,value])=>value),early=pairs.length?pairs.filter(([a,b])=>a===b).length/pairs.length:NaN;return Number.isFinite(early)?(0.5*ratio(left.holidays,right.holidays)+0.35*early+0.15*ratio(left.adjusted_workdays,right.adjusted_workdays)):NaN};
    const chosen=()=>{const result={};root.querySelectorAll('[data-forecast-ref]').forEach(select=>(result[select.dataset.forecastRef]??=[]).push(history.get(select.value)));return result};
    const slotWeight=(index,task)=>{const raw=Number(root.querySelector(`[data-forecast-ref-weight="${task}"][data-ref-slot="${index}"]`)?.value);return Number.isFinite(raw)&&raw>=0?raw/100:index===0?.7:index===1?.3:0};
    const weighted=(items,field,fallback,task)=>{const values=(items||[]).map((item,index)=>({value:Number(item?.[field]),weight:slotWeight(index,task)})).filter(row=>Number.isFinite(row.value)&&row.weight>0),total=values.reduce((sum,row)=>sum+row.weight,0);return total?values.reduce((sum,row)=>sum+row.value*row.weight,0)/total:fallback};
    const scoringSmall=(name,configured)=>{
      const result=root._smallForecastResult,ongoing=(configured?.small_end_date||data.target?.small_end_date||'')>=todayIso();
      if(ongoing&&result&&!result.error&&sameModel(result.name,name)&&result.date===todayIso()&&Number.isFinite(result.total)&&result.total>0)return {value:result.total,estimated:true};
      return {value:root._smallForecastLinked?Number(configured?.small||0):Number(root.querySelector('[data-forecast-input="small"]')?.value||0),estimated:false};
    };
    const targetState=()=>{const name=data.target?.name||'',configured=findTarget(name),launchDate=root.querySelector('[data-forecast-target="launchDate"]')?.value||'',launchDay=launchDate?new Date(`${launchDate}T00:00:00`):null,weekday=launchDay&&!Number.isNaN(launchDay.getTime())?['周日','周一','周二','周三','周四','周五','周六'][launchDay.getDay()]:(configured?.launch_weekday||data.target?.launch_weekday||'未维护');return {name,hasSmall:configured?.has_small??data.target?.has_small??true,tier:root.querySelector('[data-forecast-target="tier"]')?.value||'',energy:root.querySelector('[data-forecast-target="energy"]')?.value||'',node:root.querySelector('[data-forecast-target="node"]')?.value||'',weekday,period:root.querySelector('[data-forecast-target="period"]')?.value||'未维护',launchDate,days:Math.max(1,Number(root.querySelector('[data-forecast-target="days"]')?.value||35)),small:scoringSmall(name,configured).value,smallEstimated:scoringSmall(name,configured).estimated,endDate:configured?.end_date||'',configuredLaunchDate:configured?.launch_date||'',smallStartDate:root.querySelector('[data-forecast-target="smallStartDate"]')?.value||configured?.small_start_date||data.target?.small_start_date||'',smallEndDate:configured?.small_end_date||data.target?.small_end_date||'',smallDays:Number(configured?.small_days||data.target?.small_days||0),steadyStartDate:configured?.steady_start_date||data.target?.steady_start_date||'',smallDateSourceLabel:configured?.small_date_source_label||data.target?.small_date_source_label||'',steadyDateSourceLabel:configured?.steady_date_source_label||data.target?.steady_date_source_label||'',dateSourceLabel:configured?.date_source_label||'日期数据缺失',selectedSource:configured?.selected_source||'missing',selectedSourceLabel:configured?.selected_source_label||'数据缺失',fieldSources:configured?.field_sources||{},missingFields:configured?.missing_fields||[],hardErrors:configured?.hard_errors||[],dataError:!!configured?.data_error,dataMissing:!!configured?.data_missing,sourceLatestDate:configured?.source_latest_date||''}};
    const configuredAsOfDate=String(DATA.config?.forecast_as_of_date||'').trim(),todayIso=()=>/^\d{4}-\d{2}-\d{2}$/.test(configuredAsOfDate)?configuredAsOfDate:isoDate(new Date()),absoluteStage=target=>{const today=new Date(`${todayIso()}T00:00:00`),start=target.launchDate?new Date(`${target.launchDate}T00:00:00`):null;if(!start||Number.isNaN(start.getTime()))return {key:'unknown',label:'时间缺失',day:0,start:'',end:''};let end=null;if(target.endDate&&target.launchDate===target.configuredLaunchDate)end=new Date(`${target.endDate}T00:00:00`);if(!end||Number.isNaN(end.getTime())||end<start){end=new Date(start);end.setDate(end.getDate()+Math.max(Number(target.days||1)-1,0))}const day=Math.min(Math.max(Math.floor((today-start)/86400000)+1,1),Math.max(Number(target.days||1),1));if(today<start)return {key:'before',label:'首销期未开始',day:0,start:isoDate(start),end:isoDate(end)};if(today>end)return {key:'ended',label:'首销期已结束',day:Number(target.days||day),start:isoDate(start),end:isoDate(end)};return {key:'active',label:'首销期进行中',day,start:isoDate(start),end:isoDate(end)}};
    const actualForTarget=target=>{const base=findActual(target.name),stage=absoluteStage(target).key,variant=base?.stage_profiles?.[stage];return variant?{...base,...variant}:base};
    const actualSignals=target=>{const actual=actualForTarget(target),indexed=[...(actual?.days||[])].filter(row=>row.date&&row.date<todayIso()).map(row=>({...row,index:dayIndexForDate(target.launchDate,row.date)})).filter(row=>row.index>=0&&row.index<target.days).sort((a,b)=>a.index-b.index),byIndex=new Map(indexed.map(row=>[row.index,row])),days=[];for(let index=0;byIndex.has(index);index+=1)days.push(byIndex.get(index));const d1=byIndex.get(0),d2=byIndex.get(1),stageInfo=absoluteStage(target);return {actual,days,d1,d2,stage:stageInfo.key==='active'?`${stageInfo.label} · D${stageInfo.day}`:stageInfo.label,stageInfo}};
    const closeness=(a,b,floor=.05)=>Number.isFinite(a)&&Number.isFinite(b)?Math.max(0,1-Math.abs(a-b)/Math.max(Math.abs(a),Math.abs(b),floor)):NaN;
    const averageCloseness=pairs=>{const values=pairs.map(([a,b,floor])=>closeness(a,b,floor)).filter(Number.isFinite);return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:NaN};
    const normalizedCumulative=values=>{let running=0;const cumulative=values.map(value=>(running+=Math.max(Number(value||0),0)));const terminal=cumulative.at(-1)||0;return terminal>0?cumulative.map(value=>value/terminal):[]};
    const curveShapeCloseness=(currentDaily,referenceDaily)=>{const count=Math.min(currentDaily.length,referenceDaily.length);if(count<3)return NaN;const current=normalizedCumulative(currentDaily.slice(0,count)),reference=normalizedCumulative(referenceDaily.slice(0,count));if(!current.length||!reference.length)return NaN;const values=current.slice(0,-1).map((value,index)=>closeness(value,reference[index],.05)).filter(Number.isFinite);return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:NaN};
    const scoreSpecs={hourly:[['发布时间','release_hour',.2],['小时新增归一化形状','hour_slope',.5],['观测窗口累计占比','hour_progress',.3]],small_progress:[['产品档位','tier',.1],['能源类型','energy',.06],['首销天数','days',.1],['总小订量级','size',.08],['D1可观测小转大结构','earlySmall',.16],['D2可观测小转大斜率','smallSlope',.12],['D1～当前Dn归一化斜率','dnSmallShape',.25],['历史累计曲线可用性','curve',.13]],direct_progress:[['产品档位','tier',.07],['发布类型','node',.07],['发布星期','weekday',.05],['发布时段','period',.05],['首销天数','days',.09],['D1可观测直接大结构','earlyDirect',.16],['D2可观测直接大斜率','directSlope',.14],['D1～当前Dn归一化斜率','dnDirectShape',.24],['历史累计曲线可用性','curve',.13]],conversion:[['产品档位','tier',.15],['能源类型','energy',.1],['首销天数','days',.1],['总小订量级','size',.13],['D1可观测小转大结构','earlySmall',.14],['D2可观测小转大斜率','smallSlope',.1],['D1～当前Dn归一化斜率','dnSmallShape',.18],['早期退订质量','earlyCancel',.06],['最终转化率可用','final',.04]],direct_share:[['产品档位','tier',.1],['发布类型','node',.08],['发布时段','period',.06],['首销天数','days',.08],['总小订量级','size',.06],['D1订单来源结构','earlyDirect',.17],['D2订单来源斜率','directSlope',.15],['D1～当前Dn归一化斜率','dnDirectShape',.2],['最终占比可用','final',.1]],lock:[['产品档位','tier',.2],['能源类型','energy',.08],['首销天数','days',.12],['总小订量级','size',.12],['早期退订质量','earlyCancel',.18],['锁单留存数据','lock',.3]],daily:[['产品档位','tier',.1],['首销天数','days',.35],['假期与调休结构','holiday',.2],['发布星期','weekday',.1],['到天曲线完整性','curve',.25]],daily_slope:[['产品档位','tier',.15],['首销天数','days',.2],['假期与调休结构','holiday',.15],['真实日环比相似度','dailySlopeMatch',.4],['斜率曲线可用性','curve',.1]],scale:[['产品档位','tier',.4],['能源类型','energy',.1],['首销天数','days',.2],['总小订量级','size',.3]]};
    const scoreRuleText={
      tier:'产品档位完全一致100%；同为SUV、MPV或轿车95%；档位关键词相近68%；其他40%。',
      energy:'历史车型能源字段包含当前能源类型100%；否则55%。',
      node:'发布类型完全一致100%；其他类型62%。',
      weekday:'发布星期一致100%；不一致45%。',
      release_hour:'发布时间越接近越相似：1−小时差/12；首个有效成交小时仅作为近似。',hour_slope:'在共同已观测窗口内，逐小时新增量各自归一后比较，不使用D1绝对量。',hour_progress:'在共同已观测窗口内，比较各小时累计量占该窗口总量的比例，不使用预测全天量作分母。',period:'发布时段一致100%；不一致或未维护50%。',
      days:'1−|两车首销天数差|÷max(当前首销天数,35)，最低为0%。',
      size:'min(两车总小订)÷max(两车总小订)；当前车型可引用已联动的小订预测总量并标注；任一侧缺少有效总量时不参与评分。',
      holiday:'假期天数相似度×50%＋前14日日期类型一致率×35%＋调休工作日相似度×15%。',
      earlySmall:'比较D1小转大/总小订、D1小转大/D1大定，最小阈值分别为2、5个百分点，两个相似度取平均。',
      smallSlope:'比较D2小转大/D2大定、D2/D1小转大、D1小转大占前两日，最小阈值分别为5、10、10个百分点，三个相似度取平均。',
      dailySlopeMatch:'至少2个有效日环比（通常需3个完整真实日）；双方逐日大定先剔除日历影响，再比较当天÷前一天−1。按10个百分点最小阈值计算相似度并取平均，预测日、缺失日及前一天为0的比值不计。',
      dnSmallShape:'至少3个完整真实日；双方累计小转大各自归一到当前Dn=100%，按5个百分点最小阈值逐日比较（末日固定100%不计），再取平均。',
      earlyDirect:'比较D1直接大定/D1大定，按3个百分点最小阈值计算相似度。',
      directSlope:'比较D2直接大/D2大定、D2/D1直接大、D1直接大占前两日，最小阈值分别为3、10、10个百分点，三个相似度取平均。',
      dnDirectShape:'至少3个完整真实日；双方累计直接大定各自归一到当前Dn=100%，按5个百分点最小阈值逐日比较（末日固定100%不计），再取平均。',
      earlyCancel:'比较D1退订率、D2单日退订率、D1+D2累计退订率，最小阈值分别为2、2、3个百分点，三个相似度取平均。',
      curve:'历史曲线存在且可用100%；缺失35%。',
      final:'历史最终指标在0–100%内且口径校验通过100%；否则不参与评分。',
      lock:'留存大定率和大定到锁单率每可用一项计50%，两项均可用100%。',
    };
    const scoreRuleFor=(key,task)=>key==='curve'&&task==='daily_slope'?'至少有一个有效相邻日比值100%；否则35%。':key==='curve'&&task==='hourly'?'D1分时累计曲线存在且可用100%；缺失35%。':key==='curve'&&task==='daily'?'到天大定曲线存在且可用100%；缺失35%。':scoreRuleText[key]||'采用当前任务配置的标准化相似度规则。';
    const scoreMissingRule=key=>({curve:'缺失仍按35%计分',lock:'按可用项数计0%/50%/100%'}[key]||'任一侧未维护或缺少可比较数据时不参与，并重新归一有效权重');
    const scoreParts=(item,task,target)=>{
      if(!item||sameModel(item.model,target.name))return [];
      if(task==='hourly'){
        if(!(item.hourly_curve||[]).some(Number))return [];
        const hours=(actualForTarget(target)?.hourly_days||[]).find(row=>row.date===target.launchDate)?.hours||[];
        const start=hours.find(row=>row.gross>0)?.hour??({'上午':9,'下午':14,'晚上':19}[target.period]??-1);
        const result=window.ForecastMath.smallHourlyReferenceScore(window.ForecastMath.launchHourlyItem(item),{hours:hours.map(row=>({hour:row.hour,orders:row.gross})),startHour:start});
        return result.parts.map(part=>({...part,label:scoreSpecs.hourly.find(row=>row[1]===part.key)?.[0]||part.key,current:'当前D1真实观测窗口',reference:part.evidence}));
      }
      const signals=actualSignals(target),known=value=>!['','未维护','待维护'].includes(String(value||'').trim()),words=['旗舰','豪华','大型','中大型','中型','MPV','SUV','轿车'].filter(word=>String(target.tier||'').includes(word)),itemTier=String(item.tier||''),exactBody=['MPV','SUV','轿车'].some(word=>String(target.tier||'').includes(word)&&itemTier.includes(word));
      const values={tier:known(target.tier)&&known(itemTier)?(target.tier.replace(/\s/g,'')===itemTier.replace(/\s/g,'')?1:exactBody?.95:words.some(word=>itemTier.includes(word))?.68:.4):NaN,energy:known(target.energy)&&known(item.energy)?(String(item.energy||'').includes(target.energy)?1:.55):NaN,node:known(target.node)&&known(item.node)?(target.node===item.node?1:.62):NaN,days:Number(target.days)>0&&Number(item.days)>0?Math.max(0,1-Math.abs(Number(item.days)-target.days)/Math.max(target.days,35)):NaN,weekday:known(target.weekday)&&known(item.launch_weekday)?(target.weekday===item.launch_weekday?1:.45):NaN,period:known(target.period)&&known(item.launch_period)?(target.period===item.launch_period?1:.5):NaN,size:target.small>0&&Number(item.small)>0?Math.min(target.small,Number(item.small))/Math.max(target.small,Number(item.small)):NaN,holiday:NaN};
      const targetCalendar=calendarProfile(target.launchDate,target.days),itemCalendar=calendarProfile(item.launch_date,item.days);values.holiday=calendarSimilarity(targetCalendar,itemCalendar);
      const d1=signals.d1,d2=signals.d2,targetD1SmallRate=d1&&target.small?Number(d1.small_to_big||0)/target.small:NaN,itemD1SmallRate=Number(item.small)>0?Number(item.d1_small||0)/Number(item.small):NaN,targetD1SmallShare=d1&&Number(d1.gross)>0?Number(d1.small_to_big||0)/Number(d1.gross):NaN,targetD2SmallShare=d2&&Number(d2.gross)>0?Number(d2.small_to_big||0)/Number(d2.gross):NaN,targetD1DirectShare=d1&&Number(d1.gross)>0?Number(d1.direct||0)/Number(d1.gross):NaN,targetD2DirectShare=d2&&Number(d2.gross)>0?Number(d2.direct||0)/Number(d2.gross):NaN;
      const targetSmallD2D1=d1&&d2&&Number(d1.small_to_big)>0?Number(d2.small_to_big||0)/Number(d1.small_to_big):NaN,targetSmallD1D12=d1&&d2&&Number(d1.small_to_big)+Number(d2.small_to_big)>0?Number(d1.small_to_big)/(Number(d1.small_to_big)+Number(d2.small_to_big)):NaN,targetDirectD2D1=d1&&d2&&Number(d1.direct)>0?Number(d2.direct||0)/Number(d1.direct):NaN,targetDirectD1D12=d1&&d2&&Number(d1.direct)+Number(d2.direct)>0?Number(d1.direct)/(Number(d1.direct)+Number(d2.direct)):NaN;
      const targetD1CancelRate=d1&&target.small&&Number(d1.cancel)>0?Number(d1.cancel)/target.small:NaN,targetD2CancelRate=d1&&d2&&target.small&&Number(d2.cancel)>Number(d1.cancel)?(Number(d2.cancel)-Number(d1.cancel))/target.small:NaN,targetD12CancelRate=d2&&target.small&&Number(d2.cancel)>0?Number(d2.cancel)/target.small:NaN;
      values.earlySmall=d1&&item.d1_valid!==false?averageCloseness([[targetD1SmallRate,itemD1SmallRate,.02],[targetD1SmallShare,Number(item.d1_small_share),.05]]):NaN;
      values.smallSlope=d2&&item.d1_valid!==false&&item.d2_valid!==false&&item.d12_valid!==false?averageCloseness([[targetD2SmallShare,Number(item.d2_small_share),.05],[targetSmallD2D1,Number(item.small_d2_d1),.1],[targetSmallD1D12,Number(item.small_d1_d12),.1]]):NaN;
      values.earlyDirect=d1&&item.d1_valid!==false?closeness(targetD1DirectShare,Number(item.d1_direct_share),.03):NaN;
      values.directSlope=d2&&item.d1_valid!==false&&item.d2_valid!==false&&item.d12_valid!==false?averageCloseness([[targetD2DirectShare,Number(item.d2_direct_share),.03],[targetDirectD2D1,Number(item.direct_d2_d1),.1],[targetDirectD1D12,Number(item.direct_d1_d12),.1]]):NaN;
      values.earlyCancel=d1?averageCloseness([[targetD1CancelRate,Number(item.d1_cancel_rate),.02],[targetD2CancelRate,Number(item.d2_cancel_rate),.02],[targetD12CancelRate,Number(item.d12_cancel_rate),.03]]):NaN;
      const currentSmallDaily=signals.days.map(row=>Number(row.small_to_big||0)),currentDirectDaily=signals.days.map(row=>Number(row.direct||0));
      values.dnSmallShape=curveShapeCloseness(currentSmallDaily,item.daily_small||[]);values.dnDirectShape=curveShapeCloseness(currentDirectDaily,item.daily_direct||[]);
      const curveField={hourly:'hourly_curve',small_progress:'small_progress',direct_progress:'direct_progress',daily:'daily_orders',daily_slope:'daily_orders'}[task],curve=task==='daily_slope'?window.ForecastMath.dailySlope(observedDailyPrefix(item.daily_orders||[])).some(Number.isFinite):curveField?(item[curveField]||[]).some(Number):false,lockData=['net_rate','lock_rate'].filter(field=>Number(item[field])>0).length/2;
      if(task==='daily_slope'){
        const factors=bridgeSettings(root,'launch',0).factors;
        const normalize=(values,start)=>values.map((value,i)=>value===null||value===undefined||value===''?NaN:Number(value)/(factors[calendarType(start,i).type]||1));
        const current=window.ForecastMath.dailySlope(normalize(signals.days.map(row=>row.gross),target.launchDate));
        const reference=window.ForecastMath.dailySlope(normalize(observedDailyPrefix(item.daily_orders||[]).slice(0,Number(item.days||0)),item.launch_date));
        const scores=current.map((value,i)=>closeness(value,reference[i],.1)).filter(Number.isFinite);
        values.dailySlopeMatch=scores.length>=2?scores.reduce((a,b)=>a+b,0)/scores.length:NaN;
      }
      const specs=scoreSpecs[task]||[];
      const issues=String(item.quality_issues||''),finalField=task==='conversion'?'conversion':'direct_share',finalValue=Number(item[finalField]);
      values.curve=curve?1:.35;values.final=finalValue>0&&finalValue<=1&&!issues.includes(task==='conversion'?'小订转化率':'直接大定占比')?1:NaN;values.lock=lockData;
      const curveDetail=task==='small_progress'?`累计小转大曲线${curve?'可用':'缺失'}；${adaptationText([item],'small_progress',target.days)}`:task==='direct_progress'?`累计直接大定曲线${curve?'可用':'缺失'}；${adaptationText([item],'direct_progress',target.days)}`:task==='hourly'?`D1分时曲线${curve?'完整':'缺失'}；不比较绝对数量`:curve?'完整':'缺失';
      const calendarText=profile=>`${profile.holidays||0}天假期 / ${profile.weekends||0}天周末 / ${profile.adjusted_workdays||0}天调休工作日${profile.holiday_names?.length?`（${profile.holiday_names.join('、')}）`:''}`;
      const pairEvidence=(label,left,right)=>Number.isFinite(left)&&Number.isFinite(right)?`${label} ${(left*100).toFixed(1)}% ↔ ${(right*100).toFixed(1)}%`:'';
      const evidenceList=(...items)=>items.filter(Boolean).join('；');
      const percentValue=(label,value)=>Number.isFinite(value)?`${label} ${(value*100).toFixed(1)}%`:'';
      const shapeDay=signals.days.length,evidence={dailySlopeMatch:Number.isFinite(values.dailySlopeMatch)?`仅比较D1～D${shapeDay}已结束真实日，剔除日历影响后相似度${(values.dailySlopeMatch*100).toFixed(1)}%`:'至少需要2个有效真实日环比；预测值不参与',tier:`${target.tier||'未维护'} ↔ ${item.tier||'未维护'}`,energy:`${target.energy||'未维护'} ↔ ${item.energy||'未维护'}`,node:`${target.node||'未维护'} ↔ ${item.node||'未维护'}`,days:`${target.days}天 ↔ ${item.days||0}天`,weekday:`${target.weekday} ↔ ${item.launch_weekday||'未维护'}`,period:`${target.period} ↔ ${item.launch_period||'未维护'}`,size:`${fmt(target.small)} ↔ ${fmt(item.small)}`,holiday:`${calendarText(targetCalendar)} ↔ ${calendarText(itemCalendar)}（系统识别）`,earlySmall:d1&&item.d1_valid!==false?evidenceList(pairEvidence('D1小转大/总小订',targetD1SmallRate,itemD1SmallRate),pairEvidence('D1小转大/D1大定',targetD1SmallShare,Number(item.d1_small_share))):'D1未结束或参考D1口径异常，暂不评分',smallSlope:Number.isFinite(values.smallSlope)?evidenceList(pairEvidence('D2小转大/D2大定',targetD2SmallShare,Number(item.d2_small_share)),pairEvidence('D2/D1小转大',targetSmallD2D1,Number(item.small_d2_d1)),pairEvidence('D1小转大占前两日',targetSmallD1D12,Number(item.small_d1_d12))):'D2未结束或参考D1/D2口径异常，暂不评分',earlyDirect:d1&&item.d1_valid!==false?pairEvidence('D1直接大/D1大定',targetD1DirectShare,Number(item.d1_direct_share)):'D1未结束或参考D1口径异常，暂不评分',directSlope:Number.isFinite(values.directSlope)?evidenceList(pairEvidence('D2直接大/D2大定',targetD2DirectShare,Number(item.d2_direct_share)),pairEvidence('D2/D1直接大',targetDirectD2D1,Number(item.direct_d2_d1)),pairEvidence('D1直接大占前两日',targetDirectD1D12,Number(item.direct_d1_d12))):'D2未结束或参考D1/D2口径异常，暂不评分',dnSmallShape:Number.isFinite(values.dnSmallShape)?`当前与历史D1～D${shapeDay}累计小转大各自归一到D${shapeDay}=100%后比较，形状相似度${(values.dnSmallShape*100).toFixed(1)}%`:`至少需要3个完整真实日`,dnDirectShape:Number.isFinite(values.dnDirectShape)?`当前与历史D1～D${shapeDay}累计直接大定各自归一到D${shapeDay}=100%后比较，形状相似度${(values.dnDirectShape*100).toFixed(1)}%`:`至少需要3个完整真实日`,earlyCancel:Number.isFinite(values.earlyCancel)?evidenceList(pairEvidence('D1退订率',targetD1CancelRate,Number(item.d1_cancel_rate)),pairEvidence('D2单日退订率',targetD2CancelRate,Number(item.d2_cancel_rate)),pairEvidence('D1+D2累计退订率',targetD12CancelRate,Number(item.d12_cancel_rate))):'当前无可用早期退订数据，暂不评分',curve:curveDetail,final:values.final===1?`${(finalValue*100).toFixed(1)}%`:`该最终指标缺失或口径异常，不参与评分`,lock:`${Math.round(lockData*2)}/2项可用（留存大定率、大定到锁单率）`};
      const comparison={
        dailySlopeMatch:{current:`D1～D${shapeDay}已结束真实日环比`,reference:'历史对应日环比（剔除日历影响）'},
        tier:{current:target.tier||'未维护',reference:item.tier||'未维护'},energy:{current:target.energy||'未维护',reference:item.energy||'未维护'},node:{current:target.node||'未维护',reference:item.node||'未维护'},days:{current:`${target.days}天`,reference:`${item.days||0}天`},weekday:{current:target.weekday||'未维护',reference:item.launch_weekday||'未维护'},period:{current:target.period||'未维护',reference:item.launch_period||'未维护'},size:{current:fmt(target.small)+(target.smallEstimated?'（小订预测）':''),reference:fmt(item.small)},holiday:{current:calendarText(targetCalendar),reference:calendarText(itemCalendar)},
        earlySmall:{current:evidenceList(percentValue('D1小转大/总小订',targetD1SmallRate),percentValue('D1小转大/D1大定',targetD1SmallShare)),reference:evidenceList(percentValue('D1小转大/总小订',itemD1SmallRate),percentValue('D1小转大/D1大定',Number(item.d1_small_share)))},
        smallSlope:{current:evidenceList(percentValue('D2小转大/D2大定',targetD2SmallShare),percentValue('D2/D1小转大',targetSmallD2D1),percentValue('D1占前两日',targetSmallD1D12)),reference:evidenceList(percentValue('D2小转大/D2大定',Number(item.d2_small_share)),percentValue('D2/D1小转大',Number(item.small_d2_d1)),percentValue('D1占前两日',Number(item.small_d1_d12)))},
        earlyDirect:{current:percentValue('D1直接大/D1大定',targetD1DirectShare),reference:percentValue('D1直接大/D1大定',Number(item.d1_direct_share))},
        directSlope:{current:evidenceList(percentValue('D2直接大/D2大定',targetD2DirectShare),percentValue('D2/D1直接大',targetDirectD2D1),percentValue('D1占前两日',targetDirectD1D12)),reference:evidenceList(percentValue('D2直接大/D2大定',Number(item.d2_direct_share)),percentValue('D2/D1直接大',Number(item.direct_d2_d1)),percentValue('D1占前两日',Number(item.direct_d1_d12)))},
        dnSmallShape:{current:`D1～D${shapeDay}真实累计曲线`,reference:`D1～D${shapeDay}历史累计曲线`},dnDirectShape:{current:`D1～D${shapeDay}真实累计曲线`,reference:`D1～D${shapeDay}历史累计曲线`},
        earlyCancel:{current:evidenceList(percentValue('D1退订率',targetD1CancelRate),percentValue('D2退订率',targetD2CancelRate),percentValue('D1+D2退订率',targetD12CancelRate)),reference:evidenceList(percentValue('D1退订率',Number(item.d1_cancel_rate)),percentValue('D2退订率',Number(item.d2_cancel_rate)),percentValue('D1+D2退订率',Number(item.d12_cancel_rate)))},
        curve:{current:task==='hourly'?'当前D1分时进度':task==='daily'?`目标${target.days}天到天曲线`:`目标${target.days}天累计曲线`,reference:curveDetail},final:{current:'当前预测环节',reference:`历史最终值 ${(finalValue*100).toFixed(1)}%`},lock:{current:'留存大定率、大定到锁单率',reference:`${Math.round(lockData*2)}/2项可用`},
      };
      return specs.map(([label,key,weight])=>({label:key==='size'&&target.smallEstimated?label+'（小订预测）':label,key,weight,value:Number(values[key]),evidence:evidence[key],current:comparison[key]?.current||'数据不足',reference:comparison[key]?.reference||'数据不足'})).filter(part=>Number.isFinite(part.value));
    };
    const scoreSummary=(item,task,target)=>{const rawParts=scoreParts(item,task,target),effectiveWeight=rawParts.reduce((sum,part)=>sum+part.weight,0),configuredWeight=(scoreSpecs[task]||[]).reduce((sum,part)=>sum+part[2],0),score=effectiveWeight?rawParts.reduce((sum,part)=>sum+part.value*part.weight,0)/effectiveWeight:-1,parts=rawParts.map(part=>({...part,contribution:effectiveWeight?part.value*part.weight/effectiveWeight*100:0})).sort((a,b)=>b.contribution-a.contribution);return {score,parts,effectiveWeight,configuredWeight,coverage:configuredWeight?effectiveWeight/configuredWeight:0,text:parts.slice(0,3).map(part=>`${part.label}：${part.evidence}（贡献${part.contribution.toFixed(1)}分）`).join('；')}};
    const updateWeightSummary=card=>{const values=[...card.querySelectorAll('[data-forecast-ref-weight]')].map(input=>Math.max(Number(input.value||0),0)),total=values.reduce((a,b)=>a+b,0),node=card.querySelector('[data-forecast-weight-total]');if(node){node.textContent=Math.abs(total-100)<.01?'合计100%':`合计${total.toFixed(0)}% · 自动归一`;node.classList.toggle('warn',Math.abs(total-100)>=.01)}};
    const updatePickerCount=card=>{const node=card.querySelector('[data-forecast-picker-count]');if(node)node.textContent=`${card.querySelectorAll('[data-forecast-chart-ref]:checked').length}项`};
    const setChartSelection=(card,mode,brand='')=>{const primaryCard=card,primary=new Set([...(primaryCard?.querySelectorAll('[data-forecast-ref]')||[])].map(select=>select.value));card.querySelectorAll('[data-forecast-chart-ref]').forEach(input=>{input.checked=input.disabled?false:mode==='all'?true:mode==='none'?false:mode==='brand'?input.dataset.brand===brand:primary.has(input.value)});updatePickerCount(card)};
    const minimumScoreCoverage=.45;
    const scoredForTask=(task,target)=>historyList.filter(item=>!sameModel(item.model,target.name)).map(item=>({item,summary:scoreSummary(item,task,target)})).filter(row=>row.summary.score>=0).sort((a,b)=>b.summary.score-a.summary.score);
    const rankedForTask=(task,target,limit=historyList.length)=>scoredForTask(task,target).filter(row=>row.summary.coverage>=(task==='hourly'?.2:minimumScoreCoverage)&&(!['small_progress','direct_progress'].includes(task)||rebasedForecastCompletionCurve(row.item,task,target.days).some(Number.isFinite))).slice(0,limit);
    const scoreBar=(score,label='匹配分')=>`<div class="forecast-score-bar" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(Math.max(score,0)*100)}"><i style="width:${Math.max(0,Math.min(score,1))*100}%"></i><b>${score>=0?`${Math.round(score*100)}分`:'—'}</b></div>`;
    const renderScoreDashboard=target=>{
      const node=root.querySelector('[data-forecast-score-dashboard]');if(!node)return;
      const taskList=data.tasks||[],previousTask=node.querySelector('[data-forecast-score-task]')?.value,selectedTask=taskList.some(item=>item.key===previousTask)?previousTask:(taskList[0]?.key||'');
      if(!selectedTask){node.innerHTML='<div class="empty-image">暂无预测打分任务</div>';return}
      const stage=actualSignals(target).stage,taskMeta=taskList.find(item=>item.key===selectedTask),selectedCard=root.querySelector(`[data-forecast-task="${selectedTask}"]`),selectedRefs=selectedCard?[...selectedCard.querySelectorAll('[data-forecast-ref]')].map(select=>select.value):[],summaryRows=taskList.map(task=>{const ranked=rankedForTask(task.key,target,2),first=ranked[0],second=ranked[1];return `<tr><td><b>${esc(task.label)}</b><small>${esc(task.purpose)}</small></td><td>${first?esc(first.item.model):'—'}</td><td>${first?scoreBar(first.summary.score,`${task.label}第一名`):'—'}</td><td class="forecast-score-why">${first?esc(first.summary.text):'—'}</td><td>${second?esc(second.item.model):'—'}</td><td>${second?`${Math.round(second.summary.score*100)}分`:'—'}</td><td>${first?`${(first.summary.effectiveWeight*100).toFixed(0)}% / ${(first.summary.configuredWeight*100).toFixed(0)}%`:'—'}</td></tr>`}).join('');
      const ranked=scoredForTask(selectedTask,target).slice(0,8),ruleRows=(scoreSpecs[selectedTask]||[]).map(([label,key,weight])=>`<tr><td><b>${esc(label)}</b></td><td>${Math.round(weight*100)}%</td><td>${esc(scoreRuleFor(key,selectedTask))}</td><td>${esc(scoreMissingRule(key))}</td></tr>`).join(''),detailRows=ranked.map(({item,summary},index)=>{const sufficient=summary.coverage>=(selectedTask==='hourly'?.2:minimumScoreCoverage),status=!sufficient?'证据不足':item.model===selectedRefs[0]?'主参考':item.model===selectedRefs[1]?'辅助参考':'候选',partMap=new Map(summary.parts.map(part=>[part.key,part])),parts=(scoreSpecs[selectedTask]||[]).map(([label,key,weight])=>{const part=partMap.get(key);return part?`<span class="forecast-score-part"><b>${esc(label)}</b><small><i>实际对比</i>${esc(part.evidence)}</small><em class="forecast-score-part-rule">评分规则：${esc(scoreRuleFor(key,selectedTask))}</em><em>本项结果：相似度 ${Math.round(part.value*100)}% · 配置权重 ${Math.round(weight*100)}% · 折算贡献 ${part.contribution.toFixed(1)}分</em></span>`:`<span class="forecast-score-part unavailable"><b>${esc(label)}</b><small><i>实际对比</i>当前缺少可比较数据</small><em class="forecast-score-part-rule">评分规则：${esc(scoreRuleFor(key,selectedTask))}</em><em>缺失处理：${esc(scoreMissingRule(key))}</em></span>`}).join(''),quality=item.quality_status&&item.quality_status!=='通过'?`<small>${esc(item.quality_status)}${item.quality_issues?` · ${esc(item.quality_issues)}`:''}</small>`:'';return `<tr><td>${index+1}</td><td><b>${esc(item.model)}</b><em class="forecast-score-status ${status==='候选'?'':'selected'}">${status}</em>${quality}</td><td>${scoreBar(summary.score,`${item.model}有效总分`)}</td><td>${(summary.effectiveWeight*100).toFixed(0)}% / ${(summary.configuredWeight*100).toFixed(0)}%${sufficient?'':' · 不自动推荐'}</td><td><div class="forecast-score-parts">${parts}</div></td></tr>`}).join('');
      node.innerHTML=`<div class="forecast-score-page"><section class="forecast-score-hero"><div><small>当前预测对象 · ${esc(target.name)}</small><h4>预测打分说明</h4><p>当前阶段：<b>${esc(stage)}</b>。页面直接调用实际排序函数与同一份权重配置，不另算展示分；一般任务有效指标覆盖低于45%不自动推荐；D1分时已有发布时间20%证据即可初选，小时真实数据形成后再按曲线形状排序。</p></div><div class="forecast-score-formula"><span>单项相似度 <b>0–100%</b></span><i>×</i><span>配置权重</span><i>÷</i><span>有效权重</span><strong>= 有效总分</strong></div></section><div class="forecast-score-rules"><article><b>基础属性怎么打</b><p>档位、能源、发布节点和时间用于先判断“背景是否可比”；未维护字段不计中性分，直接从有效权重中移除。</p></article><article><b>真实进度怎么打</b><p>结构、斜率和累计曲线只比较真实已发生部分；总小订量级可引用上一阶段小订预测，并明确标注。</p></article><article><b>分数如何落到结论</b><p>每个预测环节使用独立指标和权重；一般任务要求45%有效权重；D1分时允许用已知发布时间初选，缺失的小时形状指标不计分。</p></article></div><section class="forecast-score-summary"><div class="forecast-score-section-head"><div><small>所有预测任务</small><h4>推荐排名汇总</h4></div><span>按有效总分降序</span></div><div class="forecast-score-table forecast-score-summary-table"><table><thead><tr><th>预测任务</th><th>第一名</th><th>第一名得分</th><th>第一名主要得分原因</th><th>第二名</th><th>第二名得分</th><th>第一名有效/配置权重</th></tr></thead><tbody>${summaryRows}</tbody></table></div></section><section class="forecast-score-detail"><div class="forecast-score-section-head"><div><small>逐项核对</small><h4>${esc(taskMeta?.label||selectedTask)}</h4></div><label>评分任务<select data-forecast-score-task>${taskList.map(task=>`<option value="${esc(task.key)}"${task.key===selectedTask?' selected':''}>${esc(task.label)}</option>`).join('')}</select></label></div><p class="forecast-score-purpose">${esc(taskMeta?.purpose||'')}</p><div class="forecast-score-rule-box"><div class="forecast-score-rule-head"><div><small>当前任务实际使用</small><b>为什么这样打分</b></div><span>只有本任务列出的指标参与</span></div><p class="forecast-score-similarity-formula">数值型相似度统一为：1 − |当前值 − 历史值| ÷ max（|当前值|，|历史值|，该指标最小阈值），结果限制在0–100%。</p><div class="forecast-score-table forecast-score-rule-table"><table><thead><tr><th>评分指标</th><th>配置权重</th><th>相似度计算规则</th><th>缺失处理</th></tr></thead><tbody>${ruleRows}</tbody></table></div><p>候选车型有效总分 = Σ（单项相似度 × 配置权重）÷ Σ有效指标权重。某项不参与时，其权重从分母移除，不按0分处理；明确规定缺失分的曲线可用性指标除外。</p></div><div class="forecast-score-table forecast-score-detail-table"><table><thead><tr><th>排名</th><th>候选车型</th><th>有效总分</th><th>有效/配置权重</th><th>实际对比、评分规则与贡献</th></tr></thead><tbody>${detailRows}</tbody></table></div></section></div>`;
      node.querySelector('[data-forecast-score-task]').onchange=()=>renderScoreDashboard(target);
    };
    const refreshCardExplanation=(card,target)=>{
      const task=card.dataset.forecastTask,selected=[...card.querySelectorAll('[data-forecast-ref]')].slice(0,2).map(select=>history.get(select.value)||null),reason=card.querySelector('[data-forecast-ref-reason]');
      if(!reason)return;
      const summaries=selected.map(item=>item?scoreSummary(item,task,target):null),partMaps=summaries.map(summary=>new Map((summary?.parts||[]).map(part=>[part.key,part]))),rows=(scoreSpecs[task]||[]).map(([label,key])=>{const main=partMaps[0].get(key),aux=partMaps[1].get(key),current=main?.current||aux?.current;if(!main&&!aux)return '';const scores=`<span class="primary">主 ${main?Math.round(main.value*100)+'分':'—'}</span><span class="auxiliary">辅 ${aux?Math.round(aux.value*100)+'分':'—'}</span>`;return `<tr><td><b>${esc(label)}</b></td><td>${esc(current||'数据不足')}</td><td>${esc(main?.reference||'数据不足')}</td><td>${esc(aux?.reference||'数据不足')}</td><td><div class="forecast-ref-row-scores">${scores}</div></td></tr>`}).join('');
      if(!rows){reason.innerHTML='<div class="forecast-ref-comparison-empty">有效指标覆盖不足，当前没有可横向比较的打分参数；可人工选择参考车型</div>';return}
      const name=(item,fallback)=>item?.model||fallback,total=(summary,prefix,kind)=>`<span class="${kind}">${prefix} ${summary&&summary.score>=0?Math.round(summary.score*100)+'分':'—'}</span>`;
      reason.innerHTML=`<table><thead><tr><th>参与打分参数</th><th>当前 · ${esc(target.name)}</th><th>主参考 · ${esc(name(selected[0],'未选择'))}</th><th>辅助参考 · ${esc(name(selected[1],'未选择'))}</th><th>单项打分</th></tr></thead><tbody>${rows}</tbody><tfoot><tr><td><b>综合得分</b></td><td>—</td><td>${esc(name(selected[0],'未选择'))}</td><td>${esc(name(selected[1],'未选择'))}</td><td><div class="forecast-ref-row-scores">${total(summaries[0],'主','primary')}${total(summaries[1],'辅','auxiliary')}</div></td></tr></tfoot></table>`;
    };
    const refreshReferences=()=>{const target=targetState();root.querySelectorAll('[data-forecast-task]').forEach(card=>{const task=card.dataset.forecastTask,ranked=rankedForTask(task,target,3);card.querySelectorAll('[data-forecast-ref]').forEach((select,index)=>{[...select.options].forEach(option=>{option.disabled=!!option.value&&(sameModel(option.value,target.name)||(task==='hourly'&&!(history.get(option.value)?.hourly_curve||[]).some(Number)));if(task==='hourly'&&option.value){option.textContent=option.textContent.replace(/ · 无D1分时数据$/,'')+(!(history.get(option.value)?.hourly_curve||[]).some(Number)?' · 无D1分时数据':'')}});select.value=ranked[index]?.item.model||''});card.querySelectorAll('[data-forecast-chart-ref]').forEach(input=>{input.disabled=sameModel(input.value,target.name)||(task==='hourly'&&!(history.get(input.value)?.hourly_curve||[]).some(Number));if(task==='hourly'){const label=input.closest('label')?.querySelector('span');if(label)label.textContent=label.textContent.replace(/ · 无D1分时数据$/,'')+(!(history.get(input.value)?.hourly_curve||[]).some(Number)?' · 无D1分时数据':'')}input.closest('label')?.classList.toggle('disabled',input.disabled)});setChartSelection(card,'primary');updateWeightSummary(card);refreshCardExplanation(card,target)});renderForecastReferenceChartV2(root,data,history);renderScoreDashboard(target)};
    const suggestions=()=>{const refs=chosen(),lockRefs=(refs.lock||[]).map(item=>Number(item?.lock_rate)>0&&Number(item?.lock_rate)<=1?item:undefined);return {conversion:weighted(refs.conversion,'conversion',data.target.conversion,'conversion'),direct:weighted(refs.direct_share,'direct_share',data.target.direct_share,'direct_share'),lock:weighted(lockRefs,'lock_rate',data.target.lock_rate,'lock')}};
    const setEstimate=createForecastEstimateLogger(root);
    let manualOverride=false,progressOverride={small:false,direct:false};
    const setOverride=value=>{manualOverride=!!value};
    const applySystemSuggestion=()=>{const value=suggestions();root.querySelector('[data-forecast-input="conversion"]').value=(value.conversion*100).toFixed(1);root.querySelector('[data-forecast-input="direct"]').value=(value.direct*100).toFixed(1);root.querySelector('[data-forecast-input="lock"]').value=(value.lock*100).toFixed(1);setOverride(false)};
    const progressEstimate=(items,field,day,targetDays,task)=>{const values=(items||[]).map((item,slot)=>{if(day===1&&item?.d1_valid===false)return {value:NaN,weight:0};if(day===2&&(item?.d2_valid===false||item?.d12_valid===false))return {value:NaN,weight:0};const adapted=rebasedForecastCompletion(item,field,day,targetDays);return {value:adapted.value,weight:slotWeight(slot,task)}}).filter(row=>Number.isFinite(row.value)&&row.value>0&&row.weight>0),total=values.reduce((sum,row)=>sum+row.weight,0),raw=total?values.reduce((sum,row)=>sum+row.value*row.weight,0)/total:NaN;return protectCompletion(raw)};
    const adaptationText=(items,field,targetDays)=>(items||[]).filter(Boolean).map(item=>{const curve=forecastReferenceCurve(item,field);return !window.ForecastMath.stretchCompletion(curve,targetDays).length?`${item.model}：曲线缺失或短周期不兼容`:`${item.model} ${curve.length}→${targetDays}天：保留头两天、尾两天各日占比，中间按比例拉伸`}).join('；');
    const historicalFactor=(item,index)=>{const meta=calendarType(item?.launch_date,index);return bridgeSettings(root,'launch',0).factors[meta.type]||1};
    const adaptedDailyOrders=(item,targetDays)=>{const horizon=Math.max(1,targetDays),source=observedDailyPrefix((item?.daily_orders||[]).slice(0,Math.max(1,Number(item?.days||0)))).map(value=>Math.max(Number(value)||0,0));if(!source.some(value=>value>0))return [];let running=0;const cumulative=source.map(value=>(running+=value)),adapted=window.ForecastMath.stretchCompletion(cumulative,horizon).map(value=>value*running);return adapted.map((value,index)=>Math.max(value-(index?adapted[index-1]:0),0))};
    root._forecastDailyEvidence={adaptedDailyOrders,historicalFactor};
    const dailyShape=(refs,index,targetDays)=>{const values=(refs||[]).map((item,slot)=>{const orders=adaptedDailyOrders(item,targetDays),first=Number(orders[0]||0)/historicalFactor(item,0),order=Number(orders[index]||0)/historicalFactor(item,index);return {value:first>0&&order>=0?order/first:NaN,weight:slotWeight(slot,'daily')}}).filter(row=>Number.isFinite(row.value)&&row.weight>0),total=values.reduce((sum,row)=>sum+row.weight,0);return total?values.reduce((sum,row)=>sum+row.value*row.weight,0)/total:genericDailyShape(index)};
    const dailyComponentShare=(items,index,field,fallback,task)=>{const values=(items||[]).map((item,slot)=>{const gross=Number((item?.daily_orders||[])[index]),part=Number((item?.[field]||[])[index]);return {value:gross>0&&part>=0?part/gross:NaN,weight:slotWeight(slot,task)}}).filter(row=>Number.isFinite(row.value)&&row.weight>0),total=values.reduce((sum,row)=>sum+row.weight,0);return total?values.reduce((sum,row)=>sum+row.value*row.weight,0)/total:fallback};
    const hourlyCompletion=(refs,hour)=>{const values=(refs||[]).map((item,slot)=>({value:Number((item?.hourly_curve||[])[hour]),weight:slotWeight(slot,'hourly')})).filter(row=>Number.isFinite(row.value)&&row.value>0&&row.weight>0),total=values.reduce((sum,row)=>sum+row.weight,0);return total?Math.min(Math.max(values.reduce((sum,row)=>sum+row.value*row.weight,0)/total,.05),1):genericHourlyCompletion(hour)};
    const distribute=distributeInteger;
    const setScenarioValues=(key,scenario,lockRate,available)=>{const set=(field,value,rate=false)=>{const node=root.querySelector(`[data-forecast-value="${key}-${field}"]`);if(node)node.textContent=available&&value!==null&&Number.isFinite(Number(value))?(rate?(Number(value)*100).toFixed(1):Math.round(value).toLocaleString('zh-CN')):'—'};set('small',scenario.small);set('direct',scenario.direct);set('conversion',scenario.conversion,true);set('share',scenario.share,true);set('gross',scenario.gross);set('lock',scenario.lock);const lockCard=root.querySelector(`[data-forecast-value="${key}-lock"]`)?.closest('.forecast-scenario-lock');if(lockCard){lockCard.querySelector('span').textContent='预计首销期锁单';lockCard.querySelector('small').textContent='按公共大定到锁单率换算';}const status=root.querySelector(`[data-forecast-method-status="${key}"]`);if(status)status.textContent=available?(scenario.adjusted?'原参数已被实际突破 · 按真实下限抬升':`大定到锁单率 ${(lockRate*100).toFixed(1)}%`):'等待D1真实进度';['small','direct','gross'].forEach(field=>{const node=root.querySelector(`[data-forecast-kpi-note="${key}-${field}"]`);if(node)node.textContent=key==='progress'?(available?'真实累计量 ÷ 历史参考同期完成率':'D1结束后启用'):(scenario.adjusted?'KPI与未来剩余量已同步到真实下限':field==='gross'?'严格按转化参数公式':'采用人工确认参数')})};
    const renderScaleCheck=(target,scenarios)=>{const node=root.querySelector('[data-forecast-scale-check]');if(!node)return;if(target.hasSmall===false){node.innerHTML='<div class="empty-image">无小订阶段，不适用“大定／小订”量级校验；首销与平销按直接大定曲线预测。</div>';return}if(!(Number(target.small)>0)){node.innerHTML='<div class="empty-image">缺少经过字段级回退与一致性校验的总小订，暂不进行总体量级校验</div>';return}const rows=rankedForTask('scale',target,5).filter(row=>Number(row.item.small)>0&&Number(row.item.gross)>0).map(({item,summary})=>({item,score:summary.score,ratio:Number(item.gross)/Number(item.small),equivalent:target.small*Number(item.gross)/Number(item.small)}));if(!rows.length){node.innerHTML='<div class="empty-image">可比车型有效指标覆盖不足45%，暂不输出量级区间</div>';return}const low=Math.min(...rows.map(row=>row.equivalent)),high=Math.max(...rows.map(row=>row.equivalent)),center=rows.reduce((sum,row)=>sum+row.equivalent*row.score,0)/Math.max(rows.reduce((sum,row)=>sum+row.score,0),.001);const judgement=(label,value,available=true)=>{if(!available)return `<article><span>${label}</span><strong>等待D1</strong><small>方法一尚未形成终局</small></article>`;const gap=value<low?(value-low)/low:value>high?(value-high)/high:0,status=value<low?`低于区间${Math.abs(gap*100).toFixed(1)}%`:value>high?`高于区间${(gap*100).toFixed(1)}%`:'位于可比区间内';return `<article class="${gap?'warn':'ok'}"><span>${label}</span><strong>${fmt(value)}</strong><small>${status}</small></article>`};node.innerHTML=`<div class="forecast-scale-formula"><b>校验公式</b><span>可比大定 = 当前总小订 ×（历史传播名首销期大定 ÷ 历史传播名总小订）</span><span>参考区间取有效指标覆盖至少45%的前5个传播名；加权中心按匹配分归一计算。只预警，不修改结果。</span></div><div class="forecast-scale-summary"><article><span>可比区间</span><strong>${fmt(low)}–${fmt(high)}</strong><small>加权中心 ${fmt(center)}</small></article>${judgement('方法一预测',scenarios.progress.gross,scenarios.progress.available)}${judgement('方法二预测',scenarios.parameter.gross,scenarios.parameter.available)}</div><details><summary>查看量级校验对比表</summary><div class="forecast-score-table"><table><thead><tr><th>可比传播名</th><th>结构匹配分</th><th>历史总小订</th><th>历史大定</th><th>大定/小订</th><th>折算当前量级</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.item.model)}</td><td>${Math.round(row.score*100)}分</td><td>${fmt(row.item.small)}</td><td>${fmt(row.item.gross)}</td><td>${(row.ratio*100).toFixed(1)}%</td><td><b>${fmt(row.equivalent)}</b></td></tr>`).join('')}</tbody></table></div></details>`};
    const update=()=>{
      const smallInput=root.querySelector('[data-forecast-input="small"]'),smallResult=root._smallForecastResult,smallOngoing=targetState().hasSmall!==false&&targetState().smallEndDate>=todayIso();
      const linkSmall=smallOngoing&&smallResult&&sameModel(smallResult.name,targetState().name)&&smallResult.date===todayIso();
      if(linkSmall){smallInput.value=Number.isFinite(smallResult.total)&&smallResult.total>0?smallResult.total:0;root._smallForecastLinked=true;smallInput.readOnly=true;smallInput.title='来自当前小订预测；调整小订参考后自动更新';}
      else if(root._smallForecastLinked){smallInput.value=Number(actualForTarget(targetState())?.total_small||findTarget(targetState().name)?.small||0);root._smallForecastLinked=false;smallInput.readOnly=false;smallInput.title='';}
      const linkedSignature=linkSmall?String(smallResult.total):'';
      if(root._linkedSmallSignature!==linkedSignature){
        root._linkedSmallSignature=linkedSignature;
        const target=targetState();
        root.querySelectorAll('[data-forecast-task]').forEach(card=>{
          const ranked=rankedForTask(card.dataset.forecastTask,target,3);
          card.querySelectorAll('[data-forecast-ref]').forEach((select,index)=>{
            if(!select.value&&!root._forecastTouched?.has(forecastDraftControlKey(select))){
              select.value=ranked[index]?.item.model||'';
              const input=[...card.querySelectorAll('[data-forecast-chart-ref]')].find(input=>input.value===select.value);
              if(input)input.checked=true;
            }
          });
          updatePickerCount(card);refreshCardExplanation(card,target);
        });
        if(!manualOverride)applySystemSuggestion();
      }
      const get=id=>Number(root.querySelector(`[data-forecast-input="${id}"]`)?.value||0),target=targetState(),stageInfo=absoluteStage(target),small=get('small'),baseConversion=get('conversion')/100,baseShare=Math.min(get('direct')/100,.95),lockRate=get('lock')/100,refs=chosen(),actual=actualForTarget(target),today=todayIso();
      root._forecastDailyEvidence.targetFactor=index=>bridgeSettings(root,'launch',0).factors[calendarType(target.launchDate,index).type]||1;
      if(actual){target.selectedSource=actual.selected_source||'missing';target.selectedSourceLabel=actual.selected_source_label||'数据缺失';target.fieldSources=actual.field_sources||{};target.missingFields=actual.missing_fields||[];target.dataMissing=!!actual.data_missing;target.sourceLatestDate=actual.source_latest_date||''}
      const sourceButton=document.querySelector('[data-workspace-source]');if(sourceButton)sourceButton.onclick=()=>jumpToSource(actual?.day_source||data.history_source);
      const timeSummary=root.querySelector('[data-forecast-time-summary]');if(timeSummary){const stageNow=absoluteStage(target),generated=String(DATA.meta?.generated_at||'').replace('T',' ').slice(0,16);timeSummary.textContent=`判定日期${today}（数据生成于${generated||'未知'}）；小订窗口 ${target.smallStartDate||'未维护'} ~ ${target.smallEndDate||'未维护'}（${target.smallDateSourceLabel||'来源缺失'}）；首销窗口 ${target.launchDate||'未维护'} ~ ${stageNow.end||'未维护'}，共${target.days}天（${target.dateSourceLabel}）；平销自 ${target.steadyStartDate||'缺失'} 起（${target.steadyDateSourceLabel||'来源缺失'}）`}
      refreshForecastHeaderBrief(root);
      const indexedDays=[...(actual?.days||[])].filter(row=>row.date&&row.date<=today).map(row=>({...row,index:dayIndexForDate(target.launchDate,row.date)})).filter(row=>row.index>=0&&row.index<target.days).sort((a,b)=>a.index-b.index),todayIndex=stageInfo.key==='active'?stageInfo.day-1:-1,todayRow=indexedDays.find(row=>row.index===todayIndex&&row.date===today),latestHourly=[...(actual?.hourly_days||[])].filter(row=>row.date===today).sort((a,b)=>Number(a.last_hour||0)-Number(b.last_hour||0)).at(-1);let partial=null;
      if(stageInfo.key==='active'&&latestHourly)partial={...latestHourly,index:todayIndex};if(!partial&&stageInfo.key==='active'&&todayIndex>0&&todayRow)partial={...todayRow,index:todayIndex,last_hour:Math.max(0,Math.min(Number(String(DATA.meta?.generated_at||'').slice(11,13))||0,23)),from_day_snapshot:true};const fixed=indexedDays.filter(row=>row.date<today),calendarCompletedDays=stageInfo.key==='ended'?target.days:stageInfo.key==='active'?Math.max(stageInfo.day-1,0):0,actualIndexes=new Set(fixed.map(row=>row.index)),pastMissingIndexes=Array.from({length:calendarCompletedDays},(_,index)=>index).filter(index=>!actualIndexes.has(index)),historyComplete=pastMissingIndexes.length===0;
      const defaultSmallShare=target.hasSmall===false?0:Math.max(1-baseShare,.05),resolvedFixed=fixed.map(row=>target.hasSmall===false?({...row,small_to_big:row.small_to_big??0,direct:row.direct??row.gross}):({...row}));
      const d1Fit=todayIndex===0?window.ForecastMath.smallHourlyForecast({hours:(partial?.hours||[]).map(row=>({hour:row.hour,orders:row.gross})),references:refs.hourly.map((item,slot)=>({item:window.ForecastMath.launchHourlyItem(item),weight:slotWeight(slot,'hourly')}))}):null;
      const d1Unavailable=todayIndex===0&&(!partial?.hours?.length||!!d1Fit?.error);
      if(d1Unavailable)partial=null;
      const ownHourly=todayIndex>0?window.ForecastMath.intradayReference({buckets:actual?.hourly_days||[],days:resolvedFixed,today,launchDate:target.launchDate,dayType:date=>calendarType(date,0).type}):{curve:[],days:0},rollingHourlyCompletion=hour=>ownHourly.curve.length?Math.max(ownHourly.curve[hour],.005):hourlyCompletion(refs.hourly,hour);
      const sum=field=>resolvedFixed.reduce((total,row)=>total+Number(row[field]||0),0),actualGross=sum('gross'),actualSmall=resolvedFixed.every(row=>row.small_to_big!=null&&Number.isFinite(Number(row.small_to_big))&&Number(row.small_to_big)>=0)?sum('small_to_big'):NaN,actualDirect=resolvedFixed.every(row=>row.direct!=null&&Number.isFinite(Number(row.direct))&&Number(row.direct)>=0)?sum('direct'):NaN,completeLock=resolvedFixed.length===target.days&&resolvedFixed.every(row=>Number.isFinite(row.lock)),endedLockReference=stageInfo.key==='ended'&&!completeLock?historyList.find(item=>sameModel(item.generation||item.model,target.name)&&item.launch_date===target.launchDate&&Number(item.days)===target.days&&Math.abs(Number(item.gross)-actualGross)<.5&&Number(item.lock)>0&&Number(item.lock)<=actualGross):null,actualLock=endedLockReference?Number(endedLockReference.lock):stageInfo.key==='ended'&&!completeLock?NaN:sum('lock'),elapsed=calendarCompletedDays,partialFactor=partial?(todayIndex===0&&d1Fit?.total>0?d1Fit.observed/d1Fit.total:rollingHourlyCompletion(Math.max(Number(partial.last_hour||0),0))):1,dayIndex=partial?.index??elapsed;
      const hourlyFallbackUsed=!ownHourly.days&&!refs.hourly.some(item=>(item?.hourly_curve||[]).some(value=>Number(value)>0)),dailyFallbackUsed=!refs.daily.some(item=>adaptedDailyOrders(item,target.days).some(value=>Number(value)>0));
      const partialSmallRatio=dailyComponentShare(refs.small_progress,dayIndex,'daily_small',weighted(refs.small_progress,'d1_small_share',defaultSmallShare,'small_progress'),'small_progress'),partialDirectRatio=dailyComponentShare(refs.direct_progress,dayIndex,'daily_direct',weighted(refs.direct_progress,'d1_direct_share',baseShare,'direct_progress'),'direct_progress'),partialRatioTotal=partialSmallRatio+partialDirectRatio||1,partialEstimate=window.ForecastMath.intradayComponents(target.hasSmall===false&&partial?{...partial,small_to_big:0,direct:partial.gross}:partial,partialFactor,target.hasSmall===false?0:partialSmallRatio/partialRatioTotal),observedPartialSmall=partialEstimate.observedSmall,observedPartialDirect=partialEstimate.observedDirect,partialGross=partialEstimate.gross,partialSmall=partialEstimate.small,partialDirect=partialEstimate.direct,anchorSmall=actualSmall+partialSmall,anchorDirect=actualDirect+partialDirect,effectiveDays=Math.min(elapsed+(partial?1:0),target.days);
      const validQuantity=value=>value!==null&&value!==undefined&&value!==''&&typeof value!=='boolean'&&Number.isFinite(Number(value))&&Number(value)>=0;
      const componentIssues=['small_to_big','direct'].flatMap(field=>{
        const missing=resolvedFixed.filter(row=>!validQuantity(row[field])).map(row=>row.date);
        return missing.length?[`${field==='direct'?'直接大定':'小转大'}缺失或无效：${forecastDateRanges(missing)}（共${missing.length}天）`]:[];
      });
      const blockingErrors=[...(actual?.hard_errors||target.hardErrors||[])].filter(item=>item!=='总小订缺失或不大于0'&&!item.startsWith('已结束日期缺少真实数据：'));
      if(stageInfo.key==='unknown')blockingErrors.push(!target.launchDate?'首销开始日期未维护，无法确定预测窗口':'首销结束日期或天数未维护，无法确定预测窗口');
      const missingGross=resolvedFixed.filter(row=>!validQuantity(row.gross)).map(row=>row.date);
      if(missingGross.length)blockingErrors.push(`大定缺失或无效：${forecastDateRanges(missingGross)}`);
      if(pastMissingIndexes.length){
        const missingDates=pastMissingIndexes.map(index=>isoDate(new Date(new Date(target.launchDate+'T00:00:00').getTime()+index*86400000))),latest=resolvedFixed.filter(row=>validQuantity(row.gross)).at(-1)?.date||'',
          unupdated=latest?missingDates.filter(day=>day>latest):[],gaps=missingDates.filter(day=>!unupdated.includes(day));
        if(gaps.length)blockingErrors.push(`已结束日大定缺失：${forecastDateRanges(gaps)}（共${gaps.length}天）`);
        if(unupdated.length)blockingErrors.push(`大定尚未更新：${forecastDateRanges(unupdated)}（最新完整真实日${latest}）；未更新日期不补0`);
      }
      const uniqueBlockingErrors=[...new Set(blockingErrors.filter(Boolean))],rawDataError=uniqueBlockingErrors.length>0,errorNode=root.querySelector('[data-forecast-data-error]');
      const hasSmall=target.hasSmall!==false,componentsReady=componentIssues.length===0;
      const d1Parts=(refs.daily||[]).map((item,slot)=>{const orders=adaptedDailyOrders(item,target.days),sum=orders.reduce((a,b)=>a+b,0);return {value:sum>0?orders[0]/sum:NaN,weight:slotWeight(slot,'daily')}}).filter(row=>Number.isFinite(row.value)&&row.weight>0),d1Weight=d1Parts.reduce((sum,row)=>sum+row.weight,0),d1Ratio=d1Weight?d1Parts.reduce((sum,row)=>sum+row.value*row.weight,0)/d1Weight:0;
      const directD1=resolvedFixed.find(row=>row.index===0)?.gross??(partial?.index===0?partialGross:null)??get('d1Gross');
      const endedComplete=stageInfo.key==='ended'&&!rawDataError&&historyComplete;
      const parameterAvailable=!rawDataError&&(endedComplete||(componentsReady&&(hasSmall?(small>0&&baseConversion>0):(directD1>0&&d1Ratio>0)))),
        parameterRawSmall=parameterAvailable&&hasSmall?small*baseConversion:0,
        parameterRawDirect=parameterAvailable?(hasSmall?parameterRawSmall*baseShare/Math.max(1-baseShare,.05):directD1/d1Ratio):0,
        parameterSmall=endedComplete?actualSmall:parameterAvailable?Math.max(parameterRawSmall,anchorSmall):0,
        parameterDirect=endedComplete?actualDirect:parameterAvailable?Math.max(parameterRawDirect,anchorDirect):0,
        parameterGross=endedComplete?actualGross:parameterSmall+parameterDirect,
        parameterAdjusted=!endedComplete&&parameterAvailable&&(parameterSmall>parameterRawSmall+.5||parameterDirect>parameterRawDirect+.5);
      const referenceSmallEstimate=progressEstimate(refs.small_progress,'small_progress',effectiveDays,target.days,'small_progress'),referenceDirectEstimate=progressEstimate(refs.direct_progress,'direct_progress',effectiveDays,target.days,'direct_progress'),referenceSmallCompletion=referenceSmallEstimate.applied,referenceDirectCompletion=referenceDirectEstimate.applied,smallCompletionInput=root.querySelector('[data-forecast-input="progressSmallCompletion"]'),directCompletionInput=root.querySelector('[data-forecast-input="progressDirectCompletion"]');if(smallCompletionInput&&!progressOverride.small)smallCompletionInput.value=Number.isFinite(referenceSmallCompletion)?(referenceSmallCompletion*100).toFixed(1):'';if(directCompletionInput&&!progressOverride.direct)directCompletionInput.value=Number.isFinite(referenceDirectCompletion)?(referenceDirectCompletion*100).toFixed(1):'';const manualSmallCompletion=progressOverride.small&&smallCompletionInput?.value.trim()?Number(smallCompletionInput.value)/100:NaN,manualDirectCompletion=progressOverride.direct&&directCompletionInput?.value.trim()?Number(directCompletionInput.value)/100:NaN,smallCompletion=endedComplete?1:Number.isFinite(manualSmallCompletion)&&manualSmallCompletion>0?manualSmallCompletion:referenceSmallCompletion,directCompletion=endedComplete?1:Number.isFinite(manualDirectCompletion)&&manualDirectCompletion>0?manualDirectCompletion:referenceDirectCompletion,progressAvailable=!rawDataError&&historyComplete&&(endedComplete||(!d1Unavailable&&componentsReady&&effectiveDays>0&&anchorSmall+anchorDirect>0&&(!hasSmall||Number.isFinite(smallCompletion))&&Number.isFinite(directCompletion))),progressSmall=endedComplete?actualSmall:!hasSmall?0:progressAvailable?Math.max(anchorSmall,anchorSmall/smallCompletion):0,progressDirect=endedComplete?actualDirect:progressAvailable?Math.max(anchorDirect,anchorDirect/directCompletion):0,progressGross=endedComplete?actualGross:progressSmall+progressDirect;
      if(smallCompletionInput)smallCompletionInput.placeholder=Number.isFinite(referenceSmallCompletion)?`参考 ${(referenceSmallCompletion*100).toFixed(1)}%`:'等待参考';if(directCompletionInput)directCompletionInput.placeholder=Number.isFinite(referenceDirectCompletion)?`参考 ${(referenceDirectCompletion*100).toFixed(1)}%`:'等待参考';const actualSmallNode=root.querySelector('[data-forecast-progress-actual-small]'),actualDirectNode=root.querySelector('[data-forecast-progress-actual-direct]'),progressSource=root.querySelector('[data-forecast-progress-source]'),completionWarnings=[referenceSmallEstimate.clamped?`小转大原始${(referenceSmallEstimate.raw*100).toFixed(2)}% → 安全下限${(referenceSmallEstimate.applied*100).toFixed(1)}%`:'' ,referenceDirectEstimate.clamped?`直接大定原始${(referenceDirectEstimate.raw*100).toFixed(2)}% → 安全下限${(referenceDirectEstimate.applied*100).toFixed(1)}%`:'' ].filter(Boolean);if(actualSmallNode)actualSmallNode.textContent=!hasSmall?'不适用':resolvedFixed.length&&Number.isFinite(actualSmall)?`${fmt(actualSmall)}单`:'—';if(actualDirectNode)actualDirectNode.textContent=resolvedFixed.length&&Number.isFinite(actualDirect)?`${fmt(actualDirect)}单`:'—';const intradayNode=root.querySelector('[data-forecast-progress-intraday]');if(intradayNode){intradayNode.hidden=!partial;intradayNode.style.display=partial?'':'none';intradayNode.textContent=partial?`D${partial.index+1}全天估算：小转大${fmt(partialSmall)} / 直接大定${fmt(partialDirect)}；仅计入预测基准，不计入上述真实累计`:'';}if(progressSource){progressSource.classList.toggle('warning',completionWarnings.length>0);progressSource.innerHTML=`参考车型同期小转大完成率 <b>${Number.isFinite(smallCompletion)?(smallCompletion*100).toFixed(1)+'%':'—'}</b>${progressOverride.small?'（人工覆盖）':'（主辅加权）'}，同期直接大定完成率 <b>${Number.isFinite(directCompletion)?(directCompletion*100).toFixed(1)+'%':'—'}</b>${progressOverride.direct?'（人工覆盖）':'（主辅加权）'}。完成率已统一到当前车型${target.days}天首销周期：${esc(adaptationText(refs.small_progress,'small_progress',target.days))}；${esc(adaptationText(refs.direct_progress,'direct_progress',target.days))}。${completionWarnings.length?`<strong>低完成率保护已生效：${esc(completionWarnings.join('；'))}，请人工复核。</strong>`:'当前车型只提供真实累计量，不预先计算自身完成率。'}`;}
      const systemD1=Math.round(parameterGross*Math.min(Math.max(d1Ratio||.3,.08),.75)),manualD1=get('d1Gross'),plannedD1=manualD1||systemD1;
      const buildRows=(scenario,availableScenario)=>{if(!availableScenario)return [];if(!endedComplete){scenario.small=Math.round(scenario.small);scenario.direct=Math.round(scenario.direct);scenario.gross=scenario.small+scenario.direct;scenario.lock=Math.max(Math.round(scenario.gross*lockRate),actualLock);scenario.conversion=hasSmall&&small>0?scenario.small/small:NaN;scenario.share=scenario.gross?scenario.direct/scenario.gross:0;}const rows=resolvedFixed.map(row=>({...row,actual:true,day_type_label:'真实日',day_type_short:'真实'})),knownIndexes=new Set(rows.map(row=>row.index));let scenarioAnchorSmall=actualSmall,scenarioAnchorDirect=actualDirect;if(partial){rows.push({day:`D${partial.index+1}`,date:partial.date,gross:Math.round(partialGross),small_to_big:Math.round(partialSmall),direct:Math.round(partialDirect),actual:false,partial:true,index:partial.index,day_type_label:'分时滚动日',day_type_short:'分时'});knownIndexes.add(partial.index);scenarioAnchorSmall+=Math.round(partialSmall);scenarioAnchorDirect+=Math.round(partialDirect)}else if(stageInfo.key==='before'){const d1=Math.min(Math.max(plannedD1,0),Math.max(scenario.gross,0)),smallRatio=scenario.gross?scenario.small/scenario.gross:1-baseShare,d1Small=Math.round(d1*smallRatio),meta=calendarType(target.launchDate,0);rows.push({day:'D1',date:meta.date,gross:d1,small_to_big:d1Small,direct:Math.max(d1-d1Small,0),actual:false,d1_forecast:true,index:0,day_type_label:'D1专项预测',day_type_short:'D1'});knownIndexes.add(0);scenarioAnchorSmall=d1Small;scenarioAnchorDirect=Math.max(d1-d1Small,0)}
        if(partial&&knownIndexes.size===target.days){
          const last=rows.find(row=>row.partial);
          last.small_to_big=Math.max(Math.round(scenario.small-actualSmall),Math.ceil(observedPartialSmall));
          last.direct=Math.max(Math.round(scenario.direct-actualDirect),Math.ceil(observedPartialDirect));
          last.gross=last.small_to_big+last.direct;
          scenario.small=actualSmall+last.small_to_big;scenario.direct=actualDirect+last.direct;
          scenario.gross=scenario.small+scenario.direct;scenario.lock=Math.max(Math.round(scenario.gross*lockRate),actualLock);
          scenario.conversion=hasSmall&&small>0?scenario.small/small:NaN;scenario.share=scenario.gross?scenario.direct/scenario.gross:0;
          scenarioAnchorSmall=scenario.small;scenarioAnchorDirect=scenario.direct;
        }
        const factors=bridgeSettings(root,'launch',0).factors,pending=Array.from({length:target.days},(_,index)=>index).filter(index=>!knownIndexes.has(index)).map(index=>{const meta=calendarType(target.launchDate,index);return {index,...meta,past_missing:index<calendarCompletedDays,current_estimate:stageInfo.key==='active'&&index===todayIndex,shape:Math.max(dailyShape(refs.daily,index,target.days),.0001)}});
        const anchor=resolvedFixed.at(-1),allocationShape=index=>dailyShape(refs.daily,index,target.days);
        const allocate=(field,remaining)=>endedComplete||(!pending.length&&Math.round(remaining)<=0)?{values:[],warnings:[],error:''}:planBridge(root,calendarType,'launch',{remaining:Math.max(Math.round(remaining),0),anchor:anchor?Number(anchor[field]):null,anchorDate:anchor?.date||'',anchorShape:anchor?allocationShape(anchor.index):1,dates:pending.map(row=>row.date),shapes:pending.map(row=>allocationShape(row.index))});
        const smallPlan=allocate('small_to_big',scenario.small-scenarioAnchorSmall),directPlan=allocate('direct',scenario.direct-scenarioAnchorDirect);
        scenario.bridgeError=smallPlan.error||directPlan.error;scenario.bridgeWarnings=[...smallPlan.warnings,...directPlan.warnings];
        if(scenario.bridgeError){scenario.available=false;return [];}
        let futureSmall=smallPlan.values,futureDirect=directPlan.values;
        if(d1Unavailable&&pending[0]?.date===today){
          const observed=window.ForecastMath.intradayComponents(latestHourly||todayRow,1,scenario.gross?scenario.small/scenario.gross:.5);
          const smallFloor=window.ForecastMath.applyObservedFloor(futureSmall,observed.observedSmall),directFloor=window.ForecastMath.applyObservedFloor(futureDirect,observed.observedDirect);
          futureSmall=smallFloor.values;futureDirect=directFloor.values;
          if(smallFloor.raised||directFloor.raised){scenario.small+=smallFloor.raised;scenario.direct+=directFloor.raised;scenario.gross=scenario.small+scenario.direct;scenario.lock=Math.max(Math.round(scenario.gross*lockRate),actualLock);scenario.conversion=hasSmall&&small>0?scenario.small/small:NaN;scenario.share=scenario.gross?scenario.direct/scenario.gross:0;scenario.bridgeWarnings.push('当天快照突破终局，按真实下限抬升；无D1分时，不将快照冒充全天实际');}
        }
        pending.forEach((row,index)=>rows.push({day:`D${row.index+1}`,date:row.date,gross:futureSmall[index]+futureDirect[index],small_to_big:futureSmall[index],direct:futureDirect[index],actual:false,index:row.index,past_missing:row.past_missing,current_estimate:row.current_estimate,day_type:row.type,day_type_label:row.past_missing?'历史缺失估算':row.current_estimate?'当日整日估算':row.label,day_type_short:row.past_missing?'补估':row.current_estimate?'今日':row.adjusted?'调':{workday:'工',weekend:'周',holiday:'假'}[row.type],adjusted:row.adjusted,official:row.official}));rows.sort((a,b)=>a.index-b.index);let cg=0,cs=0,cd=0,cc=0;return rows.map(row=>{cg+=Number(row.gross||0);cs+=Number(row.small_to_big||0);cd+=Number(row.direct||0);if(row.actual)cc=row.cancel!=null&&row.cancel!==''&&Number.isFinite(Number(row.cancel))?Number(row.cancel):NaN;if(row.actual&&!validQuantity(row.small_to_big))cs=NaN;if(row.actual&&!validQuantity(row.direct))cd=NaN;return {...row,daily_gross:Number(row.gross||0),cumulative_gross:cg,cumulative_small:Number.isFinite(cs)?cs:null,cumulative_direct:Number.isFinite(cd)?cd:null,small_completion:hasSmall&&scenario.small&&Number.isFinite(cs)?cs/scenario.small:null,direct_completion:scenario.direct&&Number.isFinite(cd)?cd/scenario.direct:null,small_conversion:hasSmall&&small>0&&Number.isFinite(cs)?cs/small:null,direct_share:cg&&Number.isFinite(cd)?cd/cg:null,cancel_rate:row.actual&&small&&Number.isFinite(cc)?cc/small:null,cut:row.index===Math.max(effectiveDays-1,0)}})};
      const scenarios={progress:{available:progressAvailable,small:progressSmall,direct:progressDirect,gross:progressGross,conversion:hasSmall&&small>0?progressSmall/small:NaN,share:progressGross?progressDirect/progressGross:0,lock:endedComplete?actualLock:progressGross*lockRate},parameter:{available:parameterAvailable,small:parameterSmall,direct:parameterDirect,gross:parameterGross,conversion:hasSmall&&small>0?parameterSmall/small:NaN,share:parameterGross?parameterDirect/parameterGross:0,lock:endedComplete?actualLock:parameterGross*lockRate,adjusted:parameterAdjusted,rawSmall:parameterRawSmall,rawDirect:parameterRawDirect,rawGross:parameterRawSmall+parameterRawDirect,requestedConversion:baseConversion,requestedShare:baseShare}};scenarios.progress.rows=buildRows(scenarios.progress,progressAvailable);scenarios.parameter.rows=buildRows(scenarios.parameter,parameterAvailable);
      setScenarioValues('progress',scenarios.progress,lockRate,progressAvailable&&!scenarios.progress.bridgeError);setScenarioValues('parameter',scenarios.parameter,lockRate,parameterAvailable&&!scenarios.parameter.bridgeError);
      const progressReasons=[...uniqueBlockingErrors],parameterReasons=[...uniqueBlockingErrors];
      if(!endedComplete){
        progressReasons.push(...componentIssues);parameterReasons.push(...componentIssues);
        if(d1Unavailable)progressReasons.push('D1分时缺失或参考分时曲线不足，无法估算D1全天');
        else if(effectiveDays<=0)progressReasons.push('尚无完整真实日或有效当日分时，方法一等待实际进度');
        else if((hasSmall&&!Number.isFinite(smallCompletion))||!Number.isFinite(directCompletion))progressReasons.push(`D${effectiveDays}参考累计完成率不足：${[hasSmall&&!Number.isFinite(smallCompletion)?'小转大':'',!Number.isFinite(directCompletion)?'直接大定':''].filter(Boolean).join('、')}`);
        else if(!(anchorSmall+anchorDirect>0))progressReasons.push('已发生数量为0，尚无有效实际进度用于推算终局');
        if(hasSmall){
          if(!(small>0))parameterReasons.push(smallOngoing?`有效小订预测总量尚未取得${smallResult?.error?'：'+smallResult.error:''}`:'最终总小订未取得，方法二缺少数量输入');
          if(!(baseConversion>0))parameterReasons.push('小订转化率缺失或不大于0');
        }else{
          if(!(directD1>0))parameterReasons.push('无小订车型需要有效D1大定量：优先真实／分时预测，首销前可人工填写D1预测');
          if(!(d1Ratio>0))parameterReasons.push('到天参考曲线缺少有效D1占比，不能推算直接大定终局');
        }
      }
      if(scenarios.progress.bridgeError)progressReasons.push(scenarios.progress.bridgeError);
      if(scenarios.parameter.bridgeError)parameterReasons.push(scenarios.parameter.bridgeError);
      const progressMissingReason=[...new Set(progressReasons)].join('；'),parameterMissingReason=[...new Set(parameterReasons)].join('；');
      const affected=[!scenarios.progress.available||scenarios.progress.bridgeError?'方法一':'',!scenarios.parameter.available||scenarios.parameter.bridgeError?'方法二':''].filter(Boolean);
      const noticeReasons=[...(!scenarios.progress.available||scenarios.progress.bridgeError?progressReasons.map(reason=>'方法一：'+reason):[]),...(!scenarios.parameter.available||scenarios.parameter.bridgeError?parameterReasons.map(reason=>'方法二：'+reason):[]),...(endedComplete?componentIssues:[])];
      showForecastCondition(errorNode,{stage:'首销预测',state:endedComplete?'实际分项不完整':'条件不足',reasons:noticeReasons,impact:endedComplete?'真实总大定正常展示；缺失分项及无法计算的比率留空，不再分配预测余量。':`${affected.join('、')}暂不输出预测；其他可用方法及已知实际数据保留。`});
      const bridgeErrors=[scenarios.progress.bridgeError,scenarios.parameter.bridgeError].filter(Boolean),bridgeNotice=root.querySelector('[data-bridge-stage="launch"] [data-bridge-notice]');
      if(bridgeNotice&&!bridgeErrors.length)bridgeNotice.textContent=[...new Set([...scenarios.progress.bridgeWarnings||[],...scenarios.parameter.bridgeWarnings||[]])].join('；')||'两种方法分别保持自身剩余量；以前一完整真实日衔接，再按逐日权重渐进分配。';
      const parameterMethodStatus=root.querySelector('[data-forecast-method-status="parameter"]');if(parameterMethodStatus&&!parameterAvailable)parameterMethodStatus.textContent=parameterMissingReason;
      const progressMethodStatus=root.querySelector('[data-forecast-method-status="progress"]');if(progressMethodStatus)progressMethodStatus.textContent=progressAvailable?(hasSmall?`完成率 ${(smallCompletion*100).toFixed(1)}% / ${(directCompletion*100).toFixed(1)}%`:`直接大定完成率 ${(directCompletion*100).toFixed(1)}%`):progressMissingReason;
      for(const task of ['small_progress','conversion','direct_share'])root.querySelectorAll(`[data-forecast-task="${task}"]`).forEach(card=>card.hidden=!hasSmall);
      for(const field of ['small','conversion','direct','progressSmallCompletion']){const input=root.querySelector(`[data-forecast-input="${field}"]`);if(input?.closest('label'))input.closest('label').hidden=!hasSmall;}
      if(!hasSmall)for(const method of ['progress','parameter']){
        for(const field of ['small','conversion']){const node=root.querySelector(`[data-forecast-value="${method}-${field}"]`);if(node)node.textContent='不适用';}
        const note=root.querySelector(`[data-forecast-kpi-note="${method}-gross"]`);if(note)note.textContent=method==='progress'?'直接大定真实进度 ÷ 参考同期完成率':'有效D1大定量 ÷ 到天参考D1占比';
      }
      const d1Row=resolvedFixed.find(row=>row.index===0),d1Completed=!!d1Row,d1Wrap=root.querySelector('[data-forecast-d1-input-wrap]'),d1Title=root.querySelector('[data-forecast-d1-title]'),d1Stage=root.querySelector('[data-forecast-d1-stage]'),d1Value=root.querySelector('[data-forecast-d1-value]'),d1Note=root.querySelector('[data-forecast-d1-note]'),stageNeedsActual=stageInfo.key==='active'||stageInfo.key==='ended',d1FieldSource=field=>target.fieldSources?.[`首销日·${field}`]||'数据缺失',d1SourceText=`大定：${d1FieldSource('gross')}；小转大：${d1FieldSource('small_to_big')}；直接大定：${d1FieldSource('direct')}`;if(d1Wrap)d1Wrap.hidden=target.hasSmall===false?!(!d1Completed&&!partial):d1Completed||!!partial||stageNeedsActual;if(d1Completed){d1Title.textContent='D1实际大定';d1Stage.textContent='已结束 · 真实值冻结';d1Value.textContent=fmt(d1Row.gross);d1Note.textContent=`${d1SourceText}。预测值不再填写和使用`}else if(partial&&partial.index===0){d1Title.textContent='D1预计全天大定';d1Stage.textContent=`进行中 · 截至${partial.last_hour}时`;d1Value.textContent=fmt(partialGross);d1Note.textContent=`当前累计${fmt(partial.gross)}单 ÷ 同期分时完成率${(partialFactor*100).toFixed(1)}%；${hourlyFallbackUsed?'无可用历史分时曲线，当前使用通用线性回退（低置信度）':'来自当前主辅分时参考'}`}else if(stageNeedsActual){d1Title.textContent='D1真实大定';d1Stage.textContent=d1Unavailable?'无D1分时数据':'数据缺失';d1Value.textContent='—';d1Note.textContent=d1Unavailable?'无D1分时数据或参考不足，无法估算D1全天；首销方法二可独立使用有效小订输入。':`按绝对日期已${stageInfo.key==='ended'?'结束':'开始'}，D1大定按阶段顺序逐字段回退后仍缺失`}else{d1Title.textContent='D1预测大定';d1Stage.textContent='首销前 · 可人工调整';d1Value.textContent=fmt(plannedD1);d1Note.textContent=manualD1?'采用人工输入值':`系统按D1参考传播名相对量级建议${fmt(systemD1)}单`};root.querySelector('[data-forecast-d1-small]').textContent=stageNeedsActual&&!d1Completed&&partial?.index!==0?'—':fmt(d1Completed?d1Row.small_to_big:partial?.index===0?partialSmall:plannedD1*(1-baseShare));root.querySelector('[data-forecast-d1-direct]').textContent=stageNeedsActual&&!d1Completed&&partial?.index!==0?'—':fmt(d1Completed?d1Row.direct:partial?.index===0?partialDirect:plannedD1*baseShare);
      const suggest=suggestions(),gapWarning=pastMissingIndexes.length?`；D${pastMissingIndexes.map(index=>index+1).join('、D')}已过期但数据缺失`:'' ,status=effectiveDays?`绝对日期判定为${stageInfo.label}${stageInfo.key==='active'?`D${stageInfo.day}`:''}；已取得${resolvedFixed.length}/${calendarCompletedDays}个完整真实日，真实大定 <b>${fmt(actualGross)}</b> 单${partial?`；当前日按${partial.last_hour}时进度反推全天`:''}${gapWarning}`:stageInfo.key==='before'?'首销期尚未开始，方法一等待真实进度':`绝对日期判定为${stageInfo.label}，但当前优先数据源没有可用真实进度`,parameterWarning=parameterAdjusted?`<strong>方法二原参数终值${fmt(parameterRawSmall+parameterRawDirect)}单已低于真实累计分量，现按真实下限抬升至${fmt(parameterGross)}单；KPI和未来剩余量已同步。</strong>`:'',implicitConversionWarning=progressAvailable&&scenarios.progress.conversion>1?`<strong>方法一隐含小订转化率${(scenarios.progress.conversion*100).toFixed(1)}%超过100%，请复核总小订、真实累计量及参考完成率。</strong>`:'';root.querySelector('[data-forecast-suggestion]').innerHTML=rawDataError?'首销预测条件不足，具体原因和影响范围见上方提示；已知实际数据保留。':`${status}。${parameterAvailable?`方法二系统建议：转化率<b>${(suggest.conversion*100).toFixed(1)}%</b> · 直接大定占比<b>${(suggest.direct*100).toFixed(1)}%</b>；公共参数建议：大定到锁单率<b>${(suggest.lock*100).toFixed(1)}%</b>（首销期锁单÷总大定）。当前${manualOverride?'含人工调整':'与参考均值同步'}。${parameterWarning}${implicitConversionWarning}`:`方法二不可用：${parameterMissingReason}，当前不输出结果。${implicitConversionWarning}`}`;
      if(!hasSmall&&!endedComplete){
        if(progressSource)progressSource.textContent=`无小订阶段，仅使用直接大定真实累计量和参考同期完成率（${Number.isFinite(directCompletion)?(directCompletion*100).toFixed(1)+'%':'未取得'}）；不计算小转大和小订转化率。`;
        root.querySelector('[data-forecast-suggestion]').textContent=`无小订阶段：方法一按直接大定实际进度推算；方法二按有效D1大定量÷到天参考D1占比推算。两种方法共用到天基础曲线分配剩余量。大定到锁单率${(lockRate*100).toFixed(1)}%。`;
        if(parameterAvailable&&parameterMethodStatus)parameterMethodStatus.textContent=`直接大定参数法 · D1量${fmt(directD1)} ÷ D1占比${(d1Ratio*100).toFixed(1)}%`;
      }
      const pendingRows=scenarios.parameter.rows.filter(row=>!row.actual&&!row.partial),backfillRows=pendingRows.filter(row=>row.past_missing),todayEstimateRows=pendingRows.filter(row=>row.current_estimate),futureRows=pendingRows.filter(row=>!row.past_missing&&!row.current_estimate),counts={workday:futureRows.filter(row=>row.day_type==='workday').length,weekend:futureRows.filter(row=>row.day_type==='weekend').length,holiday:futureRows.filter(row=>row.day_type==='holiday').length,adjusted:futureRows.filter(row=>row.adjusted).length,uncovered:futureRows.filter(row=>row.date&&!row.official).length},allocation=root.querySelector('[data-forecast-allocation-note]');if(allocation){allocation.classList.toggle('warning',dailyFallbackUsed);allocation.textContent=`到天基础曲线：${dailyFallbackUsed?'无可用历史参考，使用通用幂衰减回退（低置信度）':'当前主辅历史参考'}。过期缺失补估${backfillRows.length}天，当日整日估算${todayEstimateRows.length}天，真正未来日期${futureRows.length}天：工作日${counts.workday}天（含调休上班${counts.adjusted}天）、普通周末${counts.weekend}天、法定放假${counts.holiday}天；周末调休按工作日处理。三类日期不会混标；两种方法共用首销日历系数，分别以前一完整真实日衔接，再将差额渐进分配，保持各自剩余量不变。${counts.uncovered?`其中${counts.uncovered}天超出已公布年度，仅按自然周判断。`:''}`;}
      if(endedComplete){
        const closedText='首销期已结束 · 按真实结果收口，不再分配预测余量';
        for(const key of ['progress','parameter']){
          const methodStatus=root.querySelector(`[data-forecast-method-status="${key}"]`);
          if(methodStatus)methodStatus.textContent=closedText;
          root.querySelectorAll(`[data-forecast-kpi-note^="${key}-"]`).forEach(node=>node.textContent='首销期完整真实累计');
        }
        if(bridgeNotice)bridgeNotice.textContent=closedText;
        if(progressSource){progressSource.classList.remove('warning');progressSource.textContent=closedText;}
        if(allocation){allocation.classList.remove('warning');allocation.textContent=closedText;}
        root.querySelector('[data-forecast-suggestion]').textContent=closedText+(componentIssues.length?'；'+componentIssues.join('；'):'');root.querySelectorAll('.forecast-scenario-lock>span').forEach(node=>node.textContent='首销期实际锁单');root.querySelectorAll('.forecast-scenario-lock>small').forEach(node=>node.textContent=endedLockReference?'逐日锁单未完整，采用汇总表已确认终值':'完整真实日锁单合计');
      }
      setEstimate('day_component_split',resolvedFixed.some(row=>row.component_derived)?`${target.name} | 已结束日小转大/直接大定缺失，按参考占比拆分真实大定：${resolvedFixed.filter(row=>row.component_derived).map(row=>row.day).join('、')}`:'');
      setEstimate('hourly_fallback',todayIndex!==0&&!endedComplete&&hourlyFallbackUsed?`${target.name} | D1分时完成率无可用历史分时曲线，按通用线性回退（低置信度）`:'');
      setEstimate('daily_fallback',!endedComplete&&dailyFallbackUsed?`${target.name} | 到天基础曲线无可用历史参考，按通用幂衰减回退（低置信度）`:'');
      setEstimate('partial_day',partial?`${target.name} | D${partial.index+1}全天量按分时进度反推：真实累计${fmt(partial.gross)}÷同期完成率${(partialFactor*100).toFixed(1)}%${partial.from_day_snapshot?'（无by时数据，按by天快照估算，低置信度）':ownHourly.days?`（本车型${ownHourly.days}个完整非D1日分时基准）`:partial.index>0?'（借用历史D1分时曲线，低置信度）':''}`:'');
      setEstimate('method1_completion',!endedComplete&&progressAvailable?`${target.name} | 方法一同期完成率取自主辅历史参考并重定基：${adaptationText(refs.small_progress,'small_progress',target.days)}；${adaptationText(refs.direct_progress,'direct_progress',target.days)}`:'');
      setEstimate('method1_floor',completionWarnings.length?`${target.name} | 方法一低完成率保护已生效：${completionWarnings.join('；')}`:'');
      setEstimate('method2_params',parameterAvailable&&!manualOverride?`${target.name} | 方法二参数采用参考加权均值（估算）：转化率${(suggest.conversion*100).toFixed(1)}% / 直接大定占比${(suggest.direct*100).toFixed(1)}% / 大定到锁单率${(suggest.lock*100).toFixed(1)}%`:'');
      setEstimate('method2_floor',parameterAdjusted?`${target.name} | 方法二原参数终局${fmt(parameterRawSmall+parameterRawDirect)}单低于真实累计，已按真实下限抬升至${fmt(parameterGross)}单`:'');
      setEstimate('d1_forecast',stageInfo.key==='before'&&!manualD1&&parameterAvailable?`${target.name} | D1为预测值：方法二终局${fmt(parameterGross)}×历史D1占比${(Math.min(Math.max(d1Ratio||.3,.08),.75)*100).toFixed(1)}%（钳制8%~75%）`:'');
      setEstimate('calendar_uncovered',counts.uncovered?`${target.name} | ${counts.uncovered}个未来日期超出已公布年度放假安排，日历类型按自然周估算`:'');
      const stageBadge=stageInfo.key==='active'?`${stageInfo.label} · D${stageInfo.day}${partial?'（分时）':''}`:stageInfo.label,latest=target.sourceLatestDate?`，数据更新至${target.sourceLatestDate}`:'',sheet=actual?.day_source?.sheet?`（${actual.day_source.sheet}）`:'',fieldText=Object.entries(target.fieldSources||{}).filter(([field])=>['总小订','首销日明细','分时进度'].includes(field)).map(([field,value])=>`${field}：${value}`).join('；'),missing=target.missingFields?.length?`；缺失字段：${target.missingFields.join('、')}`:'',gaps=pastMissingIndexes.length?`；过期缺失日期：${pastMissingIndexes.map(index=>`D${index+1}`).join('、')}`:'',stageSource=target.dataMissing?`${stageInfo.label}；时间窗口取自${target.dateSourceLabel}；按规则应读取的数据源均无可用数据，当前标记为数据缺失`:`${stageInfo.label}；时间窗口取自${target.dateSourceLabel}；主来源${target.selectedSourceLabel}${sheet}${latest}${fieldText?`；字段来源：${fieldText}`:''}${missing}${gaps}`;setForecastStageSummary(root,'launch',stageBadge,stageSource);
      const hourlyBucket=(actual?.hourly_days||[]).find(row=>row.date===target.launchDate&&row.date<=today),hourlyDay=indexedDays.find(row=>row.date===hourlyBucket?.date),hourly=window.ForecastMath.hourlyComparison(hourlyBucket,{today,dailyTotal:hourlyDay?.gross,forecastTotal:partialGross,completion:todayIndex===0&&!d1Unavailable?hour=>d1Fit.curve[hour]:undefined}),hourlyActual=hourly.actual,hourlyForecast=hourly.forecast;if(todayIndex===0&&!d1Unavailable){hourlyActual.splice(0,24,...d1Fit.actual);hourlyForecast.splice(0,24,...d1Fit.forecast);}const startHour=hourlyBucket?.hours?.find(row=>row.gross>0)?.hour??-1;if(startHour>=0)for(let hour=0;hour<startHour;hour++){hourlyActual[hour]=null;hourlyForecast[hour]=null;}hourly.day=hourly.date?dayIndexForDate(target.launchDate,hourly.date)+1:null;hourly.referenceCurve=[];hourly.referenceLabel='D1真实小时新增与累计占比拟合；不参考历史D1绝对量';hourly.missing=!hourlyBucket?.hours?.length;
      let knownGross=0,knownSmall=0,knownDirect=0;
      const knownActualRows=resolvedFixed.filter(row=>validQuantity(row.gross)).map(row=>{
        knownGross+=Number(row.gross);knownSmall=validQuantity(row.small_to_big)&&Number.isFinite(knownSmall)?knownSmall+Number(row.small_to_big):NaN;knownDirect=validQuantity(row.direct)&&Number.isFinite(knownDirect)?knownDirect+Number(row.direct):NaN;
        return {...row,actual:true,daily_gross:row.gross,cumulative_gross:knownGross,cumulative_small:Number.isFinite(knownSmall)?knownSmall:null,cumulative_direct:Number.isFinite(knownDirect)?knownDirect:null,small_conversion:hasSmall&&small>0&&Number.isFinite(knownSmall)?knownSmall/small:null,direct_share:knownGross&&Number.isFinite(knownDirect)?knownDirect/knownGross:null};
      });
      root._forecastComparison={name:target.name,rows:scenarios.progress.rows.length?scenarios.progress.rows:scenarios.parameter.rows.length?scenarios.parameter.rows:knownActualRows,progressRows:scenarios.progress.rows,parameterRows:scenarios.parameter.rows,scenarios,hourlyActual,hourlyForecast,hourly,actualRates:{net_rate:NaN,lock_rate:actualGross?actualLock/actualGross:NaN},forecastRates:endedComplete?{net_rate:NaN,lock_rate:actualGross?actualLock/actualGross:NaN}:{net_rate:weighted(refs.lock,'net_rate',NaN,'lock'),lock_rate:lockRate}};
      if(linkSmall){const node=root.querySelector('[data-forecast-suggestion]');node.textContent=(smallResult.error?`小订预测不可用：${smallResult.error}`:`首销方法二的总小订采用当前小订预测 ${fmt(small)} 单；该值为预测，随小订参数更新。`)+(node.textContent?' '+node.textContent:'');}
      root._steadyForecastUpdate?.();root._renderImportedForecast?.();renderScaleCheck({...target,small},scenarios);renderForecastDecisionChartV2(root,scenarios.progress.rows.length?scenarios.progress.rows:knownActualRows,'progress');renderForecastDecisionChartV2(root,scenarios.parameter.rows.length?scenarios.parameter.rows:knownActualRows,'parameter');renderForecastWeeklyV2(root,scenarios.progress.rows.length?scenarios.progress.rows:knownActualRows,'progress');renderForecastWeeklyV2(root,scenarios.parameter.rows.length?scenarios.parameter.rows:knownActualRows,'parameter');renderForecastReferenceChartV2(root,data,history);if(root.querySelector('[data-forecast-pane="score"].active'))renderScoreDashboard(target);
    };
    const activateForecastTab=(id,writeHistory=true)=>{if(!forecastViews.includes(id))return;applyForecastView(root,id);if(state.forecastStage==='launch'&&id==='evidence'){const target=targetState();root.querySelectorAll('[data-forecast-task]').forEach(card=>refreshCardExplanation(card,target));renderForecastReferenceChartV2(root,data,history)}if(state.forecastStage==='launch'&&id==='score')renderScoreDashboard(targetState());if(writeHistory)syncUrl('push')};
    root.querySelectorAll('[data-forecast-stage-switch]').forEach(button=>button.onclick=()=>activateForecastStage(button.dataset.forecastStageSwitch));
    const forecastTabButtons=[...root.querySelectorAll('[data-forecast-tab]')];
    forecastTabButtons.forEach((button,index)=>{button.onclick=()=>activateForecastTab(button.dataset.forecastTab);button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?forecastTabButtons.length-1:(index+(event.key==='ArrowRight'?1:-1)+forecastTabButtons.length)%forecastTabButtons.length;forecastTabButtons[next].focus();activateForecastTab(forecastTabButtons[next].dataset.forecastTab)}});
    root.querySelectorAll('[data-forecast-score-jump]').forEach(button=>button.onclick=()=>{activateForecastTab('score');const select=root.querySelector('[data-forecast-score-task]');if(select){select.value=button.dataset.forecastScoreJump;renderScoreDashboard(targetState())}requestAnimationFrame(()=>{const detail=root.querySelector('.forecast-score-detail');if(detail){detail.tabIndex=-1;detail.focus({preventScroll:true});detail.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'})}})});
    let forecastUpdateTimer=null;const scheduleForecastUpdate=()=>{clearTimeout(forecastUpdateTimer);forecastUpdateTimer=setTimeout(()=>{if(root.isConnected)update()},120)};
    root.querySelectorAll('[data-forecast-input],[data-forecast-allocation]').forEach(input=>input.oninput=()=>{if(['small','conversion','direct','lock'].includes(input.dataset.forecastInput))setOverride(true);if(input.dataset.forecastInput==='progressSmallCompletion')progressOverride.small=true;if(input.dataset.forecastInput==='progressDirectCompletion')progressOverride.direct=true;scheduleForecastUpdate()});
    root.querySelectorAll('[data-forecast-ref]').forEach(select=>select.onchange=()=>{const card=select.closest('[data-forecast-task]');if(card.dataset.forecastTask==='daily_slope'){const others=[...card.querySelectorAll('[data-forecast-ref]')];for(const other of others)if(other!==select&&select.value&&other.value===select.value)other.value='';}const matching=[...card.querySelectorAll('[data-forecast-chart-ref]')].find(input=>input.value===select.value);if(matching)matching.checked=true;updatePickerCount(card);refreshCardExplanation(card,targetState());renderForecastReferenceChartV2(root,data,history,card);renderScoreDashboard(targetState());if(card.dataset.forecastTask==='daily_slope')return;if(!manualOverride)applySystemSuggestion();update()});
    root.querySelectorAll('[data-forecast-ref-weight]').forEach(input=>input.oninput=()=>{const card=input.closest('[data-forecast-task]');updateWeightSummary(card);if(!manualOverride)applySystemSuggestion();scheduleForecastUpdate()});
    root.querySelectorAll('[data-forecast-chart-ref]').forEach(input=>input.onchange=()=>{const card=input.closest('[data-forecast-task]');updatePickerCount(card);renderForecastReferenceChartV2(root,data,history,card)});
    root.querySelectorAll('[data-forecast-ref-quick]').forEach(button=>button.onclick=()=>{root.dataset.forecastDirty='true';const card=button.closest('[data-forecast-task]');setChartSelection(card,button.dataset.forecastRefQuick,button.dataset.brand||'');renderForecastReferenceChartV2(root,data,history,card)});
    root.querySelectorAll('[data-forecast-target]').forEach(control=>control.onchange=()=>{refreshReferences();applySystemSuggestion();update();root._smallForecastUpdate?.();root._steadyForecastUpdate?.()});
    root.querySelector('[data-forecast-apply]').onclick=()=>{root.dataset.forecastDirty='true';applySystemSuggestion();update()};root.querySelector('[data-forecast-apply-progress]').onclick=event=>{root.dataset.forecastDirty='true';progressOverride={small:false,direct:false};update();event.currentTarget.textContent='已采用参考完成率'};
    bindForecastImport(root,{sameModel,targetState,todayIso,stageInfo:absoluteStage,actualForTarget,actualRows:(stage,target,actual)=>{
      if(stage==='launch')return (actual?.days||[]).map(row=>({date:row.date,value:row.gross}));
      if(stage==='steady')return (data.steady_history||[]).find(item=>sameModel(item.generation||item.model,target.name))?.daily?.map(row=>({date:row.date,value:row.lock}))||[];
      const rows=(actual?.small_daily_days||[]).map(row=>({date:row.date,value:row.orders}));
      const history=(data.small_order_history||[]).find(item=>sameModel(item.generation||item.model,target.name)&&item.small_start_date===target.smallStartDate);
      if(history?.daily_actual!==false)(history?.dates||[]).forEach((date,i)=>{if(!rows.some(row=>row.date===date))rows.push({date,value:history.daily_orders?.[i]});});
      return rows;
    }});
    const lifecycleContext={sameModel,findTarget,findActual,findStageActual,targetState,todayIso,calendarType,planBridge:(stage,args)=>planBridge(root,calendarType,stage,args),factors:stage=>bridgeSettings(root,stage,0).factors,onForecast:()=>scheduleForecastUpdate()};bindSmallOrderForecast(root,data,lifecycleContext);bindSteadyForecast(root,data,lifecycleContext);
    root.querySelectorAll('[data-bridge-control]').forEach(input=>input.onchange=()=>{root.dataset.forecastDirty='true';root._smallForecastUpdate?.();root._steadyForecastUpdate?.();update()});
    refreshReferences();applySystemSuggestion();update();activateForecastTab(state.forecastView||'result',false);bindForecastLifecycleNavigation(root);
    root._forecastDraftState=()=>({manualOverride,progressOverride:{...progressOverride}});
    root._forecastRestoreDraft=(meta={})=>{manualOverride=!!meta.manualOverride;progressOverride={small:!!meta.progressOverride?.small,direct:!!meta.progressOverride?.direct};root.querySelectorAll('[data-forecast-task]').forEach(card=>{updateWeightSummary(card);updatePickerCount(card);refreshCardExplanation(card,targetState())});if(!manualOverride)applySystemSuggestion();root._smallForecastUpdate?.();update();root._steadyForecastUpdate?.();activateForecastTab(state.forecastView||'result',false)};
    root.querySelector('[data-forecast-reset]').onclick=async()=>{
      if(!window.confirm('清除当前车型在本机保存的人工参数，恢复本次数据的系统参数？外部预测导入不会删除。'))return;
      forecastDrafts.delete(root._forecastSubjectId);root.dataset.forecastDirty='false';const saved=persistForecastState();
      await renderPage();showToast(saved?'已清除当前车型草稿，恢复系统参数。':forecastStorageWarning);
    };
    let feedbackTimer;
    const reflectParameterChange=event=>{
      if(!event.target.matches(forecastDraftSelector))return;
      root._forecastTouched.add(forecastDraftControlKey(event.target));
      if(event.target.matches('[data-forecast-ref]'))event.target.closest('[data-forecast-task]')?.querySelectorAll('[data-forecast-ref],[data-forecast-chart-ref]').forEach(control=>root._forecastTouched.add(forecastDraftControlKey(control)));
      root.dataset.forecastDirty='true';root.setAttribute('aria-busy','true');
      const feedback=root.querySelector('[data-forecast-feedback]');if(feedback){feedback.dataset.state='loading';feedback.querySelector('span').textContent='正在应用参数…'}
      clearTimeout(feedbackTimer);feedbackTimer=setTimeout(()=>{
        if(!root.isConnected)return;
        root.setAttribute('aria-busy','false');
        const saved=captureForecastDraft();if(feedback){feedback.dataset.state=saved?'success':'loading';feedback.querySelector('span').textContent=saved?'已应用 · 本机已保存':'已应用 · 保存失败';feedback.title=saved?'只保留人工修改项；刷新可恢复。未修改参数和真实订单仍跟随生成数据。':forecastStorageWarning}
      },220);
    };
    root.addEventListener('input',reflectParameterChange,true);root.addEventListener('change',reflectParameterChange,true);
    root.addEventListener('click',event=>{
      const button=event.target.closest('[data-forecast-apply],[data-forecast-apply-progress],[data-forecast-ref-quick]');if(!button)return;
      if(button.hasAttribute('data-forecast-ref-quick'))button.closest('[data-forecast-task]').querySelectorAll('[data-forecast-chart-ref]').forEach(control=>root._forecastTouched.add(forecastDraftControlKey(control)));
      const resetFields=button.hasAttribute('data-forecast-apply')?['conversion','direct','lock']:button.hasAttribute('data-forecast-apply-progress')?['progressSmallCompletion','progressDirectCompletion']:[];
      root.querySelectorAll('[data-forecast-input]').forEach(control=>{if(resetFields.includes(control.dataset.forecastInput))root._forecastTouched.delete(forecastDraftControlKey(control))});
      root.dataset.forecastDirty='true';const saved=captureForecastDraft(),feedback=root.querySelector('[data-forecast-feedback]');
      if(feedback){feedback.dataset.state=saved?'success':'loading';feedback.querySelector('span').textContent=saved?'已应用 · 本机已保存':'已应用 · 保存失败';feedback.title=forecastStorageWarning||'刷新后可恢复人工设置。'}
    });
    if(forecastStorageWarning){const feedback=root.querySelector('[data-forecast-feedback]');feedback.dataset.state='loading';feedback.querySelector('span').textContent='本机保存不可用';feedback.title=forecastStorageWarning;}
  }
  function renderUnknown(){return '<div class="empty-image">暂不支持该组件</div>'}

  let rawRowsCache=[],rawRowsKey=null,rawRenderRevision=0;
  async function loadRawRows(fileIndex,sheetIndex){
    const key=`${fileIndex}|${sheetIndex}`;
    if(rawRowsKey!==key){
      const b64=RAW_BLOCKS[key]||"";
      rawRowsCache=b64?((await decompressJson(b64)).rows||[]):[];
      rawRowsKey=key;
    }
    return rawRowsCache;
  }
  function visibleRawRows(rows,query){const header=rows.length?[rows[0]]:[];return[...header,...filterRawRows(rows.slice(1),query)]}
  async function renderRaw(){
    const revision=++rawRenderRevision,fileIndex=state.rawFile,sheetIndex=state.rawSheet,file=DATA.raw_files[fileIndex]||DATA.raw_files[0],sheet=file?.sheets[sheetIndex]||file?.sheets[0];
    const rows=await loadRawRows(fileIndex,sheetIndex);
    if(revision!==rawRenderRevision||state.module!=="raw"||fileIndex!==state.rawFile||sheetIndex!==state.rawSheet)return;
    const visibleRows=visibleRawRows(rows,state.rawQuery);
    $("#page").innerHTML=`<div class="raw-layout"><label class="raw-file-picker"><span>选择底表文件</span><select id="rawFile" aria-label="选择底表文件">${DATA.raw_files.map((item,index)=>`<option value="${index}"${index===state.rawFile?" selected":""}>${esc(item.name)}</option>`).join("")}</select></label><aside class="file-list">${DATA.raw_files.map((item,index)=>`<button data-file="${index}" class="${index===state.rawFile?"active":""}" title="${esc(item.name)}">${esc(item.name)}</button>`).join("")}</aside><section class="raw-main"><div class="raw-toolbar"><div class="raw-title"><strong>${esc(file?.name||"")}</strong><small>${sheet?.total_rows||0} 行 × ${sheet?.total_cols||0} 列 · <span id="rawMatchCount" role="status" aria-live="polite">${Math.max(visibleRows.length-1,0)} 条数据（不含表头）</span> · 横向滚动查看其余列</small></div><label><span>Sheet</span><select id="rawSheet">${(file?.sheets||[]).map((item,index)=>`<option value="${index}">${esc(item.name)}</option>`).join("")}</select></label><label><span>表内搜索</span><input id="rawSearch" type="search" value="${esc(state.rawQuery)}" placeholder="在当前 Sheet 中搜索" aria-controls="rawTable" aria-describedby="rawMatchCount"></label><button type="button" id="clearRawSearch" ${state.rawQuery?"":"disabled"}>清空搜索</button><div class="raw-freeze-controls" role="group" aria-label="锁窗格"><label class="raw-freeze-toggle"><input id="rawFreezeRow" type="checkbox" ${state.rawFreezeRow?"checked":""}><span>锁定首行</span></label><label class="raw-freeze-toggle" title="自动锁定左侧连续的文字标题列"><input id="rawFreezeColumn" type="checkbox" ${state.rawFreezeColumn?"checked":""}><span>锁定标题列</span></label></div><button class="export-button" id="exportRaw">导出当前数据</button></div><div class="raw-table ${state.rawFreezeRow?"freeze-row":""} ${state.rawFreezeColumn?"freeze-column":""}" id="rawTable">${renderRawTable(visibleRows)}</div><div class="raw-empty" id="rawEmpty" ${visibleRows.length>1?"hidden":""}><strong>没有匹配的数据</strong><p>请尝试其他关键词，或清空搜索查看当前 Sheet。</p></div></section></div>`;
    document.querySelectorAll("[data-file]").forEach(button=>button.onclick=()=>{state.rawFile=Number(button.dataset.file);state.rawSheet=0;state.rawQuery="";renderRaw()});
    $("#rawFile").onchange=event=>{state.rawFile=Number(event.target.value);state.rawSheet=0;state.rawQuery="";renderRaw()};
    $("#rawSheet").value=state.rawSheet;$("#rawSheet").onchange=event=>{state.rawSheet=Number(event.target.value);state.rawQuery="";renderRaw()};
    applyRawFrozenColumns(visibleRows);
    const updateRawSearch=()=>{const filtered=visibleRawRows(rows,state.rawQuery);$("#rawTable").innerHTML=renderRawTable(filtered);$("#rawMatchCount").textContent=`${Math.max(filtered.length-1,0)} 条数据（不含表头）`;$("#rawEmpty").hidden=filtered.length>1;$("#clearRawSearch").disabled=!state.rawQuery;applyRawFrozenColumns(filtered)};
    $("#rawSearch").oninput=event=>{state.rawQuery=event.target.value;updateRawSearch()};
    $("#clearRawSearch").onclick=()=>{state.rawQuery="";$("#rawSearch").value="";updateRawSearch();$("#rawSearch").focus()};
    $("#rawFreezeRow").onchange=event=>{state.rawFreezeRow=event.target.checked;$("#rawTable").classList.toggle("freeze-row",state.rawFreezeRow)};
    $("#rawFreezeColumn").onchange=event=>{state.rawFreezeColumn=event.target.checked;$("#rawTable").classList.toggle("freeze-column",state.rawFreezeColumn);applyRawFrozenColumns(visibleRawRows(rows,state.rawQuery))};
    $("#exportRaw").onclick=()=>exportRaw(file,sheet);
  }
  function filterRawRows(rows,query){const keyword=(query||"").trim().toLowerCase();return keyword?rows.filter(row=>row.some(value=>String(value??"").toLowerCase().includes(keyword))):rows}
  function rawCellIsData(value){
    if(typeof value==="number")return Number.isFinite(value);
    const text=String(value??"").trim();
    if(!text)return false;
    return /^(?:[¥￥$€£]\s*)?[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?%?$/.test(text)||/^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+.*)?$/.test(text)||/^\d{1,2}:\d{2}(?::\d{2})?$/.test(text);
  }
  function rawTitleColumnCount(rows){
    const width=Math.max(...rows.map(row=>row.length),0),body=rows.slice(1,101);let count=0;
    for(let col=0;col<width;col+=1){
      const values=body.map(row=>row[col]).filter(value=>String(value??"").trim()!=="");
      if(!values.length){if(col===0&&width)count=1;break}
      if(values.filter(rawCellIsData).length/values.length>=.5)break;
      count+=1;
    }
    return count;
  }
  function applyRawFrozenColumns(rows){
    const root=$("#rawTable");if(!root)return;
    root.querySelectorAll(".raw-frozen-column,.raw-frozen-edge").forEach(cell=>{cell.classList.remove("raw-frozen-column","raw-frozen-edge");cell.style.removeProperty("left")});
    if(!state.rawFreezeColumn)return;
    const count=rawTitleColumnCount(rows);if(!count)return;
    requestAnimationFrame(()=>{
      if(!root.isConnected||root!==$("#rawTable")||!state.rawFreezeColumn)return;
      let left=0;
      for(let col=0;col<count;col+=1){
        const cells=[...root.querySelectorAll(`[data-raw-col="${col}"]`)],measure=cells[0];if(!measure)break;
        cells.forEach(cell=>{cell.classList.add("raw-frozen-column");cell.style.left=`${left}px`;if(col===count-1)cell.classList.add("raw-frozen-edge")});
        left+=measure.getBoundingClientRect().width;
      }
    });
  }
  function renderRawTable(rows){const width=Math.max(...rows.map(row=>row.length),0);return `<table class="data-table"><tbody>${rows.map((row,index)=>`<tr>${Array.from({length:width},(_,col)=>{const cell=row[col]??"";const title=String(cell)!==""?` title="${esc(cell)}"`:"";return `<${index===0?"th":"td"} data-raw-col="${col}"${title}>${fmt(cell)}</${index===0?"th":"td"}>`}).join("")}</tr>`).join("")}</tbody></table>`}
  function exportRaw(file,sheet){
    const rows=visibleRawRows(rawRowsCache,state.rawQuery),csv="\ufeff"+rows.map(row=>row.map(csvCell).join(",")).join("\r\n"),blob=new Blob([csv],{type:"text/csv;charset=utf-8"}),url=URL.createObjectURL(blob),link=document.createElement("a"),base=(file?.name||"底表").replace(/\.xlsx?$/i,"").replace(/[\\/:*?\"<>|]/g,"_");
    link.href=url;link.download=`${base}_${(sheet?.name||"Sheet").replace(/[\\/:*?\"<>|]/g,"_")}.csv`;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),500);showToast(`已导出 ${rows.length} 行 CSV`);
  }
  function csvCell(value){const text=String(value??"");return /[",\r\n]/.test(text)?`"${text.replace(/"/g,'""')}"`:text}
  async function jumpToSource(source){
    if(!source){showToast("当前看板没有独立来源");return}
    const fileIndex=DATA.raw_files.findIndex(item=>item.name===source.file);if(fileIndex<0){showToast("未找到对应底表文件");return}
    const sheetIndex=DATA.raw_files[fileIndex].sheets.findIndex(item=>item.name===source.sheet||item.source_sheet===source.sheet);captureForecastDraft();state.module="raw";state.rawFile=fileIndex;state.rawSheet=Math.max(sheetIndex,0);state.rawQuery="";await renderAll();syncUrl("push");$("#rawSearch")?.focus({preventScroll:true});$("#page")?.scrollTo({top:0,behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});showToast(`已定位到 ${source.sheet}；浏览器后退可返回分析`)
  }
  function showToast(message){const node=$("#toast");if(!node)return;node.textContent=message;node.classList.add("show");clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>node.classList.remove("show"),4000)}
  function renderBridgeControls(stage){
    return `<section class="forecast-day-allocation" data-bridge-stage="${stage}"><strong>真实日衔接与差额渐进分配</strong><div class="forecast-allocation-inputs">${[['workday','工作日',1],['weekend','周末',1.15],['holiday','节假日',1.3]].map(([key,label,value])=>`<label title="调休按工作日，节假日不叠加周末">${label}<input data-bridge-control="${key}" type="number" min="0.01" max="5" step="0.05" value="${value}"><small>倍</small></label>`).join('')}</div><label title="填写时需覆盖全部待预测日期，以逗号分隔；0表示优先保护该日。实际分配还乘当日基础量。">逐日差额权重（从首个待预测日开始）<input data-bridge-control="weights" type="text" placeholder="留空使用0,0.5,1,1,…；第3天起封顶"><small>逗号分隔；留空按默认递增</small></label><p data-bridge-notice aria-live="polite"></p></section>`;
  }
  function renderStageCommonControls(stage){
    return `<section class="forecast-common-controls forecast-stage-common"><div class="forecast-block-head"><div><small>当前阶段公共参数</small><h4>真实日衔接与差额渐进分配</h4></div><span>修改后实时重算</span></div>${renderBridgeControls(stage)}</section>`;
  }
  function bridgeSettings(root,stage,count){
    const panel=root.querySelector(`[data-bridge-stage="${stage}"]`),factors={workday:1,weekend:1.15,holiday:1.3};
    let error='';
    for(const key of Object.keys(factors)){const control=panel?.querySelector(`[data-bridge-control="${key}"]`);if(control){const value=Number(control.value);if(!control.value.trim()||!Number.isFinite(value)||value<=0||value>5)error='日历系数需为大于0且不超过5的数字';else factors[key]=value}}
    const text=panel?.querySelector('[data-bridge-control="weights"]')?.value.trim()||'',weights=text?text.split(/[,，\s]+/).map(Number):window.ForecastMath.defaultBridgeWeights(count);
    if(count>0&&text&&(weights.length!==count||!weights.every(value=>Number.isFinite(value)&&value>=0)))error=`请填写${count}个非负差额权重，对应全部待预测日期`;
    return {factors,weights:count?weights:[],error,panel};
  }
  function planBridge(root,calendarType,stage,{remaining,anchor=null,anchorDate='',anchorShape=1,dates=[],shapes=[]}){
    const settings=bridgeSettings(root,stage,dates.length),factor=date=>settings.factors[calendarType(date,0).type];
    const result=settings.error?{values:[],warnings:[],error:settings.error}:window.ForecastMath.anchoredAllocate({remaining,anchor,anchorFactor:anchorDate?factor(anchorDate):1,anchorShape,shapes,factors:dates.map(factor),weights:settings.weights});
    const notice=settings.panel?.querySelector('[data-bridge-notice]');if(notice)notice.textContent=result.error||`${dates.length}个待预测日；权重${settings.weights.join(', ')}；${result.warnings.join('；')||'以前一完整真实日为基准，按渐进权重和基础量分配差额，合计保持不变'}。`;
    return result;
  }
  function bindForecastLifecycleNavigation(root){
    const bindTabset=(buttons,panes,idOf,paneIdOf)=>{
      const activate=id=>{buttons.forEach(button=>{const active=idOf(button)===id;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1});panes.forEach(pane=>pane.classList.toggle('active',paneIdOf(pane)===id))};
      buttons.forEach((button,index)=>{button.onclick=()=>activate(idOf(button));button.onkeydown=event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();activate(idOf(buttons[next]))}});
    };
    root.querySelectorAll('[data-small-order-workspace],[data-steady-workspace]').forEach(workspace=>bindTabset([...workspace.querySelectorAll('[data-lifecycle-subtab]')],[...workspace.querySelectorAll('[data-lifecycle-subpane]')],button=>button.dataset.lifecycleSubtab,pane=>pane.dataset.lifecycleSubpane));
  }
  function renderLifecycleBars(rows,valueKey,labelKey='label'){
    if(!rows.length)return '<div class="empty-image">暂无可绘制数据</div>';
    const max=Math.max(...rows.map(row=>Number(row[valueKey]||0)),1),width=Math.max(rows.length*46,620);
    return `<div class="forecast-lifecycle-bars-scroll"><div class="forecast-lifecycle-bars" style="min-width:${width}px">${rows.map(row=>`<article class="${row.actual?'actual':'forecast'}"><div class="forecast-lifecycle-bar"><i style="height:${Math.max(Number(row[valueKey]||0)/max*100,1)}%"></i><b>${fmt(row[valueKey])}</b></div><span>${esc(row[labelKey]||'')}</span><small>${row.actual?'实际':'预测'}</small></article>`).join('')}</div></div>`;
  }
  function renderForecastEvidenceLines({series,labels,ariaLabel,title='',note='',unit='rate',slope=false,hourly=false,extra='',lifecycle=false,table=false,empty='暂无可比较曲线'}){
    const usable=series.filter(item=>(item.values||[]).some(Number.isFinite));if(!usable.length||!labels.length)return `<div class="empty-image">${esc(empty)}</div>`;
    const maxPoints=Math.max(labels.length,...usable.map(item=>item.values.length),1),W=920,H=245,left=48,right=20,top=30,bottom=42,plotW=W-left-right,plotH=H-top-bottom,finiteValues=usable.flatMap(item=>item.values.filter(Number.isFinite)),rawMax=Math.max(...finiteValues,1),yMax=unit==='rate'?Math.max(rawMax,1):rawMax*1.12,yMin=slope?Math.min(...finiteValues,0):0;
    const x=index=>left+(maxPoints===1?0:index/(maxPoints-1))*plotW,y=value=>top+plotH*(1-Math.min(Math.max((value-yMin)/(yMax-yMin),0),1)),format=value=>unit==='rate'?`${(value*100).toFixed(value<.1?1:0)}%`:Math.round(value).toLocaleString('zh-CN')+(lifecycle?'单':'');
    const grid=[0,.25,.5,.75,1].map(rate=>{const gy=top+plotH*(1-rate);return `<line x1="${left}" y1="${gy}" x2="${W-right}" y2="${gy}" stroke="#E8F0F7"/><text x="${left-8}" y="${gy+4}" text-anchor="end" font-size="9" fill="#7890A6">${format(yMin+(yMax-yMin)*rate)}</text>`}).join('');
    const placedLabels=new Map(),placeLabel=(index,preferred)=>{const occupied=placedLabels.get(index)||[],start=Math.min(Math.max(preferred,12),H-bottom+13),candidates=[0,-14,14,-28,28,-42,42,-56,56,-70,70].map(delta=>start+delta),chosen=candidates.find(value=>value>=12&&value<=H-bottom+13&&occupied.every(other=>Math.abs(value-other)>=12))??start;occupied.push(chosen);placedLabels.set(index,occupied);return chosen;};
    const lines=usable.map((curve,seriesIndex)=>{
      const indexes=curve.values.map((value,index)=>Number.isFinite(value)?index:-1).filter(index=>index>=0),segments=[];let segment=[];
      curve.values.forEach((value,index)=>{if(Number.isFinite(value))segment.push(`${x(index)},${y(value)}`);else if(segment.length){segments.push(segment);segment=[];}});if(segment.length)segments.push(segment);
      const step=curve.role==='reference'?(hourly?8:14):(hourly?4:7),dots=indexes.map((index,position)=>{const value=curve.values[index],show=curve.role!=='reference'||curve.core?position===0||position===indexes.length-1||(index+1)%step===0:false,offset=curve.role==='actual'?-10:curve.role==='forecast'?15:seriesIndex%2?-19:25,labelY=show?placeLabel(index,y(value)+offset):0,tooltip=`${curve.name} · ${labels[index]||''} · ${format(value)}`;return `<circle cx="${x(index)}" cy="${y(value)}" r="${show?(curve.role==='reference'?2.2:3):2}" fill="#fff" stroke="${curve.color}" stroke-width="${curve.role==='reference'?1.5:2}" tabindex="0" role="img" aria-label="${esc(tooltip)}"><title>${esc(tooltip)}</title></circle>${show?`<text x="${x(index)}" y="${labelY}" text-anchor="middle" font-size="9.5" font-weight="700" fill="${curve.color}">${format(value)}</text>`:''}`}).join('');
      return segments.map(points=>`<polyline points="${points.join(' ')}" fill="none" stroke="${curve.color}" stroke-width="${curve.role==='reference'?(curve.core?2.2:1.35):3}" opacity="${curve.role==='reference'&&!curve.core?'.62':'1'}" ${curve.dash?`stroke-dasharray="${curve.dash}"`:''}><title>${esc(curve.name)}</title></polyline>`).join('')+dots;
    }).join('');
    const tickCount=Math.min(maxPoints,8),ticks=Array.from({length:tickCount},(_,slot)=>{const index=Math.round(slot*(maxPoints-1)/Math.max(tickCount-1,1));return `<text x="${x(index)}" y="${H-15}" text-anchor="middle" font-size="9" fill="#7890A6">${esc(labels[index]||'')}</text>`}).join('');
    const legend=usable.map(curve=>{const lastIndex=curve.values.reduce((found,value,index)=>Number.isFinite(value)?index:found,-1),latest=lastIndex>=0?format(curve.values[lastIndex]):'—';return `<span><i class="line-key${curve.dash?' dotted':''}" style="border-color:${curve.color}"></i>${esc(curve.name)} · 最新${latest}</span>`}).join('');
    const valuesTable=table?`<details class="forecast-ref-score-details"><summary>查看图表数值</summary><div class="forecast-score-table"><table><thead><tr><th scope="col">车型／曲线</th>${labels.map(label=>`<th scope="col">${esc(label)}</th>`).join('')}</tr></thead><tbody>${usable.map(curve=>`<tr><th scope="row">${esc(curve.name)}</th>${labels.map((_,index)=>`<td>${Number.isFinite(curve.values[index])?format(curve.values[index]):'—'}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`:'';
    return `${title||note?`<div class="forecast-task-chart-title"><strong>${esc(title)}</strong><span>${esc(note)}</span></div>`:''}<div class="forecast-svg-scroll forecast-evidence-line-scroll${lifecycle?' forecast-lifecycle-line-scroll':''}"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(ariaLabel)}">${grid}${lines}${ticks}</svg></div><div class="legend forecast-task-legend${lifecycle?' forecast-lifecycle-line-legend':''}">${legend}</div>${extra}${valuesTable}`;
  }
  function renderLifecycleLineChart({series,labels,ariaLabel,unit='percent',hourly=false,title='',note='',empty='暂无可比较曲线'}){
    return renderForecastEvidenceLines({series:series.map(item=>({...item,name:item.label,role:item.role||'reference',core:true,dash:item.dashed?'7 5':''})),labels,ariaLabel,unit:unit==='percent'?'rate':'number',hourly,title,note,lifecycle:true,table:true,empty});
  }
  function renderLifecycleScorePage({eyebrow,title,description,rules,rows,selected,empty,minimumEvidence=3,weighted=false}){
    const scoreBar=(score,label)=>`<div class="forecast-score-bar" role="progressbar" aria-label="${esc(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(score*100)}"><i style="width:${Math.max(0,Math.min(score,1))*100}%"></i><b>${Math.round(score*100)}分</b></div>`;
    const ruleRows=rules.map(rule=>`<tr><td><b>${esc(rule.label)}</b></td><td>${weighted?Math.round((rule.weight||0)*100)+'%':'等权'}</td><td>${esc(rule.rule)}</td><td>${esc(rule.missing||'任一侧缺失时不参与，并按剩余有效项重新平均')}</td></tr>`).join('');
    const detailRows=rows.map((row,index)=>{const partMap=new Map(row.parts.map(part=>[part.key,part])),effective=row.parts.length,totalWeight=row.parts.reduce((sum,part)=>sum+(weighted?(part.weight||0):1),0),itemKey=row.item.event_id||row.item.model,selectedRole=itemKey===selected[0]?'主参考':itemKey===selected[1]?'辅助参考':'',role=selectedRole?(row.eligible===false?`${selectedRole}·人工`:selectedRole):(row.eligible===false?'证据不足':'候选'),parts=rules.map(rule=>{const part=partMap.get(rule.key);return part?`<span class="forecast-score-part"><b>${esc(rule.label)}</b><small><i>实际对比</i>${esc(part.evidence)}</small><em class="forecast-score-part-rule">评分规则：${esc(rule.rule)}</em><em>本项结果：相似度 ${Math.round(part.value*100)}% · ${weighted?'按有效权重归一':'有效项等权'} · 折算贡献 ${(part.value*(weighted?(part.weight||0):1)/Math.max(totalWeight,.001)*100).toFixed(1)}分</em></span>`:`<span class="forecast-score-part unavailable"><b>${esc(rule.label)}</b><small><i>实际对比</i>当前缺少可比较数据</small><em class="forecast-score-part-rule">评分规则：${esc(rule.rule)}</em><em>缺失处理：${esc(rule.missing||'不参与，并按剩余有效项重新平均')}</em></span>`}).join('');return `<tr><td>${index+1}</td><td><b>${esc(row.item.model)}</b><em class="forecast-score-status ${role==='候选'?'':'selected'}">${role}</em>${row.meta?`<small>${esc(row.meta)}</small>`:''}</td><td>${scoreBar(row.score,`${row.item.model}有效总分`)}</td><td>${effective}/${rules.length}项</td><td><div class="forecast-score-parts">${parts}</div></td></tr>`}).join('');
    return `<div class="forecast-score-page"><section class="forecast-score-hero"><div><small>${esc(eyebrow)}</small><h4>${esc(title)}</h4><p>${esc(description)} 排序与本页明细直接调用同一个逐项评分结果，不另算展示分。</p></div><div class="forecast-score-formula"><span>${weighted?'有效相似度 × 对应权重之和':'有效单项相似度之和'}</span><i>÷</i><span>${weighted?'有效权重之和':'有效项数'}</span><strong>= 有效总分</strong></div></section><div class="forecast-score-rules"><article><b>如何计算</b><p>${weighted?'按下表各项配置权重加权，缺项后归一；':'所有可用指标等权平均；'}分值统一为0～100%，没有隐藏的车型加分或人工修正。</p></article><article><b>缺失怎么处理</b><p>缺失项不按0分处理，而是从分母移除；少于${minimumEvidence}项有效证据时标为“证据不足”。</p></article><article><b>如何用于预测</b><p>系统只从至少${minimumEvidence}项有效证据的候选中自动选择主辅参考；证据不足的车型仍可人工选择，并明确标记。</p></article></div><section class="forecast-score-detail"><div class="forecast-score-section-head"><div><small>当前评分实际使用</small><h4>评分指标与候选车型逐项明细</h4></div><span>按有效总分降序</span></div><div class="forecast-score-rule-box"><div class="forecast-score-rule-head"><div><small>评分口径</small><b>为什么这样打分</b></div><span>${rules.length}个候选指标 · 自动推荐至少${minimumEvidence}项</span></div><div class="forecast-score-table forecast-score-rule-table"><table><thead><tr><th>评分指标</th><th>权重</th><th>相似度计算规则</th><th>缺失处理</th></tr></thead><tbody>${ruleRows}</tbody></table></div><p>${weighted?'候选车型有效总分 = Σ（相似度×有效权重）÷ 有效权重之和。':'候选车型有效总分 = Σ有效单项相似度 ÷ 有效项数。'}页面展示的每项贡献相加即为最终得分。</p></div><div class="forecast-score-table forecast-score-detail-table"><table><thead><tr><th>排名</th><th>候选车型</th><th>有效总分</th><th>有效项</th><th>实际对比、评分规则与贡献</th></tr></thead><tbody>${detailRows||`<tr><td colspan="5">${esc(empty)}</td></tr>`}</tbody></table></div></section></div>`;
  }
  const observedDailyPrefix=values=>{const gap=values.findIndex(value=>value===null||value===undefined||value===''||!Number.isFinite(Number(value))||Number(value)<0);return gap<0?values:values.slice(0,gap)};
  const forecastReferenceCurve=(item,field)=>{const dailyField={small_progress:'daily_small',direct_progress:'daily_direct',gross_progress:'daily_orders'}[field],observed=dailyField&&item?.[dailyField]?.length?observedDailyPrefix(item[dailyField]).length:null,raw=observedDailyPrefix(item?.[field]||[]),days=Math.max(0,Math.min(raw.length,Number(item?.days||raw.length),observed??raw.length));let previous=0;return raw.slice(0,days).map(value=>{const number=Number(value);if(Number.isFinite(number)&&number>=previous)previous=number;return previous})};
  const extendForecastCurve=(curve,length)=>{const result=[...curve];if(!result.length)return result;const increments=result.map((value,index)=>Math.max(value-(index?result[index-1]:0),0)),recent=increments.filter(value=>value>0).slice(-7),ratios=recent.slice(1).map((value,index)=>value/recent[index]).filter(Number.isFinite).sort((a,b)=>a-b),median=ratios.length?ratios[Math.floor(ratios.length/2)]:.88,decay=Math.min(Math.max(median,.65),.98);let increment=recent.slice(-3).reduce((sum,value)=>sum+value,0)/Math.max(Math.min(recent.length,3),1);while(result.length<length){increment*=decay;result.push(result.at(-1)+Math.max(increment,.000001))}return result};
  const rebasedForecastCompletion=(item,field,day,targetDays)=>{const curve=forecastReferenceCurve(item,field),horizon=Math.max(1,Math.round(targetDays||1)),current=Math.min(Math.max(1,Math.round(day||1)),horizon),adapted=curve.length===Number(item?.days||curve.length)?window.ForecastMath.stretchCompletion(curve,horizon):[];return {value:adapted[current-1]??NaN,extrapolated:false,sourceDays:curve.length}};
  const rebasedForecastCompletionCurve=(item,field,targetDays)=>Array.from({length:Math.max(1,Math.round(targetDays||1))},(_,index)=>rebasedForecastCompletion(item,field,index+1,targetDays).value);
  function createForecastEstimateLogger(owner){
    const logs=owner._forecastEstimateLogs||(owner._forecastEstimateLogs=new Map());
    return (key,message)=>{
      if(!message){logs.delete(key);return}
      if(logs.get(key)===message)return;
      logs.set(key,message);
      console.warn(`[销量预测估算] ${key} | ${message}`);
      (window.__FORECAST_ESTIMATE_LOGS=window.__FORECAST_ESTIMATE_LOGS||[]).push({time:new Date().toISOString(),key,message});
    };
  }

  init();
})();
