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
  const DYNAMIC = Boolean(window.ORDER_DASHBOARD_API_BASE);
  let DATA;
  function apiUrl(path, params = {}) {
    const base = new URL(window.ORDER_DASHBOARD_API_BASE || 'api/', document.baseURI);
    const url = new URL(path, base);
    const query = {...(DATA?.dataset_id ? {dataset: DATA.dataset_id} : {}), ...params};
    for (const [key, value] of Object.entries(query)) if (value != null) url.searchParams.set(key, value);
    return url;
  }
  async function apiRequest(path, params = {}, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(apiUrl(path, params), {credentials:'same-origin', cache:'no-store', ...options, signal:controller.signal});
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        const error = new Error(typeof detail.detail === 'string' ? detail.detail : `请求失败（${response.status}）`);
        error.status = response.status;
        throw error;
      }
      return response;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('请求超时，请重试。');
      if (error instanceof TypeError) throw new Error('无法连接订单服务，请重试。');
      throw error;
    } finally { clearTimeout(timer); }
  }
  async function apiJson(path, params = {}, options = {}) {
    return (await apiRequest(path, params, options)).json();
  }
  for (;;) {
    try { DATA = DYNAMIC ? await apiJson('catalog') : await decompressJson(window.DASHBOARD_DATA_B64); break; }
    catch (error) {
      const page=document.querySelector('#page'),message=document.createElement('p');
      message.textContent=DYNAMIC&&error.status===503?'等待订单数据更新…':error.message;
      page.setAttribute('role','status');page.replaceChildren(message);
      if(!DYNAMIC)throw error;
      await new Promise(resolve=>setTimeout(resolve,15000));
    }
  }
  document.querySelector('#page').removeAttribute('role');
  DATA.dashboard_blocks=window.DASHBOARD_BLOCKS_B64||DATA.dashboard_blocks||{};
  window.DASHBOARD_DATA = DATA;
  const RAW_BLOCKS = window.DASHBOARD_RAW_B64 = window.DASHBOARD_RAW_B64 || {};
  window.CHART_RENDER_MODE = DATA.config.chart_render_mode || "generated";
  const $ = selector => document.querySelector(selector);
  const displayText = value => String(value ?? "").replaceAll("净大定", "留存大定");
  const esc = value => displayText(value).replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const numberFormatter = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 1});
  const fmt = value => typeof value === "number" ? numberFormatter.format(value) : esc(value);
  const colors = {blue:"#2859f5",green:"#249463",orange:"#cd681a",purple:"#7655bb",coral:"#b72d59"};
  const moduleIcons = {
    overview:"M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    channel_analysis:"M4 20h16M7 16v-5m5 5V7m5 9V4",
    cancellation:"M4 5v15h16M7 10l4 3 4-5 5 2",
    launch_rhythm:"M3 13h4l2-7 4 13 3-9 2 3h3",
    conversion:"M3 4h18l-7 8v7l-4 2v-9z",
    sku:"M12 3l9 5-9 5-9-5zM3 8v8l9 5 9-5V8m-9 5v8",
    option_fee:"M4 6h16v12H4zM8 12h1m6 0h1m-5 0a1 1 0 1 0 2 0 1 1 0 0 0-2 0",
    generic:"M5 4h10l4 4v12H5zM14 4v5h5m-7 2v6m-3-3h6",
    raw:"M3 5h18v14H3zM3 10h18M9 5v14"
  };
  const outlineIcon = (path, className="module-icon") =>
    `<svg class="${className}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="${path}"/></svg>`;
  const LABEL_SCALE_HEADROOM=1.18;
  const chartMax=values=>Math.max(...values.map(value=>Number(value||0)),1)*LABEL_SCALE_HEADROOM;
  const stackedBarWidth=step=>Math.min(42,step*.58);
  // One pixel-space renderer for all daily/hourly rhythm charts. Adapters below
  // retain their existing quantities, aggregation and formatting contracts.
  const RHYTHM_LAYOUT=Object.freeze({height:224,frameHeight:240,top:30,bottom:190,left:30,right:30,barWidth:28,minStep:40,lineWidth:2,pointRadius:3,fontSize:10,minFontSize:9,lineLabelMaxOffset:24,defaultWidth:960});
  const rhythmKnown=value=>typeof value==='number'&&Number.isFinite(value);
  function rhythmGeometry(count,availableWidth=RHYTHM_LAYOUT.defaultWidth,labelWidth=0){
    // Keep the plot's natural density; a wide viewport must not stretch the gaps.
    // Only unusually long totals may increase the step to preserve legibility.
    const n=Math.max(count,1),step=Math.max(RHYTHM_LAYOUT.minStep,labelWidth+8),width=RHYTHM_LAYOUT.left+RHYTHM_LAYOUT.right+n*step;
    return {...RHYTHM_LAYOUT,width,viewportWidth:Math.min(availableWidth,width),plotHeight:RHYTHM_LAYOUT.bottom-RHYTHM_LAYOUT.top,step};
  }
  const rhythmTextWidth=(text,fontSize=RHYTHM_LAYOUT.fontSize)=>Array.from(String(text)).reduce((width,char)=>width+(char.charCodeAt(0)>255?fontSize:fontSize*.62),0);
  const rhythmLabelBox=(text,x,y,fontSize=RHYTHM_LAYOUT.fontSize)=>({left:x-rhythmTextWidth(text,fontSize)/2-2,right:x+rhythmTextWidth(text,fontSize)/2+2,top:y-fontSize-2,bottom:y+3});
  const rhythmAxisText=text=>String(text).replace(/^\d{4}-(\d{2})-(\d{2})$/, '$1-$2');
  const rhythmBoxesOverlap=(a,b,gap=2)=>a.left<b.right+gap&&a.right>b.left-gap&&a.top<b.bottom+gap&&a.bottom>b.top-gap;
  function rhythmLabelClear(box,occupied,points,segments){
    if(occupied.some(other=>rhythmBoxesOverlap(box,other))||points.some(point=>rhythmBoxesOverlap(box,{left:point.x-4,right:point.x+4,top:point.y-4,bottom:point.y+4},1)))return false;
    return !segments.some(([a,b])=>{
      const left=Math.max(box.left,a.x),right=Math.min(box.right,b.x);if(left>right||a.x===b.x)return false;
      const y=x=>a.y+(b.y-a.y)*(x-a.x)/(b.x-a.x),low=Math.min(y(left),y(right)),high=Math.max(y(left),y(right));
      return high>=box.top-1&&low<=box.bottom+1;
    });
  }
  function rhythmLineLabel(point,text,occupied,points,segments,geometry,complete=false){
    for(const fontSize of [RHYTHM_LAYOUT.fontSize,RHYTHM_LAYOUT.minFontSize])for(const offset of [-10,-16,-RHYTHM_LAYOUT.lineLabelMaxOffset,18,RHYTHM_LAYOUT.lineLabelMaxOffset]){
      const y=point.y+offset,box=rhythmLabelBox(text,point.x,y,fontSize);
      if(box.top<5||box.bottom>geometry.bottom-4||!rhythmLabelClear(box,occupied,points,segments))continue;
      return {x:point.x,y,box,fontSize,pointY:point.y};
    }
    if(complete){
      // This two-rate chart must keep every label. Wider date columns isolate
      // their text; search nearby vertical slots before relaxing line avoidance.
      const fontSize=RHYTHM_LAYOUT.minFontSize,candidates=Array.from({length:geometry.bottom-fontSize-8},(_,index)=>index+fontSize+7).sort((a,b)=>Math.abs(a-point.y)-Math.abs(b-point.y));
      for(const avoidLines of [true,false])for(const y of candidates){
        if(avoidLines&&Math.abs(y-point.y)>48)continue;
        const box=rhythmLabelBox(text,point.x,y,fontSize);
        if(box.bottom>geometry.bottom-4||!rhythmLabelClear(box,occupied,points,avoidLines?segments:[]))continue;
        return {x:point.x,y,box,fontSize,pointY:point.y,leader:Math.abs(y-point.y)>RHYTHM_LAYOUT.lineLabelMaxOffset};
      }
    }
    return null;
  }
  function renderRhythmSvg(spec,availableWidth){
    const rows=spec.rows||[],complete=spec.kind==='cancel-day',labelWidths=rows.flatMap(row=>[rhythmTextWidth(rhythmKnown(row.total)?fmt(row.total):'—',complete?RHYTHM_LAYOUT.fontSize:RHYTHM_LAYOUT.minFontSize),...(complete?(spec.lines||[]).filter(line=>rhythmKnown(row.rates?.[line.key])).map(line=>rhythmTextWidth((row.rates[line.key]*100).toFixed(line.digits??1)+'%')):[])]),geometry=rhythmGeometry(rows.length,availableWidth,Math.max(0,...labelWidths)),{width,height,left,right,bottom,plotHeight,step,barWidth}=geometry;
    const x=index=>left+index*step+step/2,barY=value=>bottom-value/spec.maxValue*plotHeight,rateY=value=>bottom-Math.min(Math.max(value,0),1)*plotHeight;
    const series=spec.series||[],lines=spec.lines||[],occupied=[],labels=[],points=[],segments=[],barAreas=[];
    const lineData=lines.map(line=>{
      let previous=null,path='';const dots=rows.map((row,index)=>{
        const value=row.rates?.[line.key];if(!rhythmKnown(value)){previous=null;return null;}
        const point={x:x(index),y:rateY(value),value,index,line};path+=(previous?'L':'M')+point.x+','+point.y+' ';
        if(previous)segments.push([previous,point]);previous=point;points.push(point);return point;
      });return {line,path,dots};
    });
    const saveLabel=label=>{occupied.push(label.box);labels.push(label);};
    // Reserve every column's total first. Never sample away a known value (or
    // turn a missing value into zero) just because the viewport is narrow.
    rows.forEach((row,index)=>{
      const text=rhythmKnown(row.total)?fmt(row.total):'—',top=rhythmKnown(row.total)?barY(row.total):bottom,cx=x(index);
      let placement=null;
      for(const fontSize of [RHYTHM_LAYOUT.fontSize,RHYTHM_LAYOUT.minFontSize]){
        for(const offset of [-8,-20,-32,16,28]){
          const y=top+offset,box=rhythmLabelBox(text,cx,y,fontSize);
          if(box.top<5||box.bottom>bottom-4||!rhythmLabelClear(box,occupied,points,segments))continue;
          placement={text,x:cx,y,box,fontSize,kind:'total',index};break;
        }
        if(placement)break;
      }
      // A steep curve can cross every nearby position. The total still belongs
      // above its column; never silently remove it as the old collision pass did.
      if(!placement){const y=Math.max(RHYTHM_LAYOUT.fontSize+8,top-8),fontSize=RHYTHM_LAYOUT.minFontSize;placement={text,x:cx,y,box:rhythmLabelBox(text,cx,y,fontSize),fontSize,kind:'total',index};}
      saveLabel(placement);
    });
    rows.forEach((_,index)=>{
      const column=points.filter(point=>point.index===index).sort((a,b)=>b.y-a.y),rotation=index%Math.max(column.length,1);
      // Rotate label priority: two close curves must not permanently hide one another.
      [...column.slice(rotation),...column.slice(0,rotation)].forEach(point=>{
        if(complete&&point.value===0)return;
        const text=(point.value*100).toFixed(point.line.digits??1)+'%',placement=rhythmLineLabel(point,text,occupied,points,segments,geometry,complete);
        if(placement)saveLabel({...placement,text,kind:'line',color:point.line.color,series:point.line.key,index});
      });
    });
    const bars=rows.map((row,index)=>{
      const cx=x(index),title=esc(row.tooltip||'');
      if(!rhythmKnown(row.total))return `<g data-rhythm-row="${index}" data-total=""><title>${title}</title></g>`;
      let stack=0;const rectangles=series.map(item=>{
        const value=row.values[item.key],displayValue=Math.max(value,0),barHeight=displayValue/spec.maxValue*plotHeight,top=barY(stack+displayValue);stack+=displayValue;
        if(barHeight>0)barAreas.push({left:cx-barWidth/2,right:cx+barWidth/2,top,bottom:top+barHeight});
        const text=fmt(value);
        for(const fontSize of [RHYTHM_LAYOUT.fontSize,RHYTHM_LAYOUT.minFontSize]){
          if(value<=0||barHeight<fontSize+8||rhythmTextWidth(text,fontSize)>barWidth-4)continue;
          const y=top+barHeight/2+fontSize*.35,box=rhythmLabelBox(text,cx,y,fontSize);
          if(!rhythmLabelClear(box,occupied,points,segments))continue;
          saveLabel({text,x:cx,y,box,fontSize,kind:'segment',index});break;
        }
        return `<rect data-rhythm-bar="${esc(item.key)}" data-value="${value}" x="${cx-barWidth/2}" y="${top}" width="${barWidth}" height="${barHeight}" fill="${item.color}"><title>${esc(row.tips?.[item.key]||item.label+' '+fmt(value))}</title></rect>`;
      }).join('');
      return `<g data-rhythm-row="${index}" data-total="${row.total}"><title>${title}</title>${rectangles}</g>`;
    }).join('');
    const curves=lineData.map(({line,path,dots})=>`<path data-rhythm-series="${esc(line.key)}" d="${path}" fill="none" stroke="${line.color}" stroke-width="${RHYTHM_LAYOUT.lineWidth}"/>${dots.filter(Boolean).map(point=>`<circle data-rhythm-point="${esc(line.key)}" data-index="${point.index}" data-value="${point.value}" cx="${point.x}" cy="${point.y}" r="${RHYTHM_LAYOUT.pointRadius}" fill="#fff" stroke="${line.color}" stroke-width="${RHYTHM_LAYOUT.lineWidth}"><title>${esc(rows[point.index].label)} · ${esc(line.label)} ${(point.value*100).toFixed(line.digits??1)}%</title></circle>`).join('')}`).join('');
    const labelLinks=labels.filter(label=>label.leader).map(label=>`<line data-rhythm-label-link="${esc(label.series)}" data-index="${label.index}" aria-hidden="true" x1="${label.x}" x2="${label.x}" y1="${label.pointY+(label.y<label.pointY?-4:4)}" y2="${label.y+(label.y<label.pointY?4:-label.fontSize-2)}" stroke="${label.color}" stroke-width="1" opacity=".55"/>`).join('');
    const valueLabels=labels.map(label=>{
      // Only bar labels use dark text over colored stacks. Line percentages
      // always retain their series color, matching the line and legend.
      const color=label.kind==='line'?label.color:(barAreas.some(area=>rhythmBoxesOverlap(label.box,area,0))?'#102238':label.color);
      return `<text class="rhythm-value-label rhythm-${label.kind}-label" data-rhythm-label="${label.kind}" data-index="${label.index}"${label.pointY==null?'':` data-point-y="${label.pointY}" data-series="${esc(label.series)}"`} x="${label.x}" y="${label.y}" text-anchor="middle" style="font-size:${label.fontSize}px${color?`;fill:${color}`:''}">${esc(label.text)}</text>`;
    }).join('');
    const axisStride=Math.max(1,Math.ceil((Math.max(...rows.map(row=>rhythmTextWidth(rhythmAxisText(row.label),9)),0)+10)/step)),axisBoxes=[],axisIndices=[];
    [0,rows.length-1,...rows.map((_,index)=>index).filter(index=>index%axisStride===0)].forEach(index=>{
      if(!rows[index]||axisIndices.includes(index))return;const box=rhythmLabelBox(rhythmAxisText(rows[index].label),x(index),bottom+20,9);
      if(axisBoxes.some(other=>rhythmBoxesOverlap(box,other)))return;axisBoxes.push(box);axisIndices.push(index);
    });
    const axis=axisIndices.sort((a,b)=>a-b).map(index=>`<text class="rhythm-axis-label" x="${x(index)}" y="${bottom+20}" text-anchor="middle">${esc(rhythmAxisText(rows[index].label))}<title>${esc(rows[index].label)}</title></text>`).join('');
    return `<svg class="rhythm-svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="width:${width}px;height:${height}px" data-plot-left="${left}" data-plot-right="${right}" data-plot-height="${plotHeight}" role="img" aria-label="${esc(spec.title)}"><line aria-hidden="true" class="rhythm-axis-line" x1="${left}" y1="${bottom}" x2="${width-right}" y2="${bottom}"/>${bars}${curves}${labelLinks}${valueLabels}${axis}</svg>`;
  }
  function renderRhythmChart(spec){
    const legend=[...(spec.series||[]),...(spec.lines||[]).map(line=>({...line,line:true}))].map(item=>`<span><i${item.line?' class="line-key"':''} style="background:${item.color}"></i>${esc(item.label)}</span>`).join('');
    return `<div class="rhythm-chart" data-rhythm-kind="${esc(spec.kind)}" data-rhythm-config="${esc(JSON.stringify(spec))}" style="--rhythm-frame-height:${RHYTHM_LAYOUT.frameHeight}px" role="region" tabindex="0" aria-label="${esc(spec.title)}，可横向滚动">${renderRhythmSvg(spec)}</div><div class="legend rhythm-legend">${legend}</div>`;
  }
  let rhythmObserver=null;
  function bindRhythmCharts(){
    rhythmObserver?.disconnect();rhythmObserver=null;
    const charts=[...document.querySelectorAll('#page [data-rhythm-config]')];
    const paint=chart=>{
      const width=Math.floor(chart.clientWidth);if(width<=0||width===chart._rhythmWidth)return;
      chart._rhythmSpec??=JSON.parse(chart.dataset.rhythmConfig);chart._rhythmWidth=width;
      chart.innerHTML=renderRhythmSvg(chart._rhythmSpec,width);
    };
    charts.forEach(paint);
    if(charts.length&&typeof ResizeObserver!=='undefined'){
      rhythmObserver=new ResizeObserver(entries=>entries.forEach(entry=>paint(entry.target)));
      charts.forEach(chart=>rhythmObserver.observe(chart));
    }
  }
  function renderLaunchRateTrends(rows,lines){
    if(!lines.length)return '';
    const series=lines.map(line=>({...line,points:rows.map((row,index)=>rhythmKnown(row.rates?.[line.key])?{index,value:row.rates[line.key],label:row.label}:null)})),known=series.flatMap(line=>line.points.filter(Boolean));
    const text=(value,line)=>(value*100).toFixed(line.digits??1)+'%',labelWidth=Math.max(0,...series.flatMap(line=>line.points.filter(Boolean).map(point=>rhythmTextWidth(text(point.value,line),10))));
    const left=48,right=30,step=Math.max(40,labelWidth+12),width=left+right+Math.max(rows.length,1)*step,x=index=>left+index*step+step/2;
    const min=known.length?Math.min(...known.map(point=>point.value)):0,max=known.length?Math.max(...known.map(point=>point.value)):1;
    const padding=max>min?(max-min)*.12:Math.max(Math.abs(max)*.1,.01),low=min>=0?Math.max(0,min-padding):min-padding,high=max<=1?Math.min(1,max+padding):max+padding;
    const rough=Math.max(high-low,.0001)/4,magnitude=10**Math.floor(Math.log10(rough)),tick=([1,2,5,10].find(value=>value>=rough/magnitude)||10)*magnitude;
    const axisMin=known.length?Math.floor(low/tick+1e-9)*tick:0,axisMax=known.length?Math.max(axisMin+tick,Math.ceil(high/tick-1e-9)*tick):1,y=value=>170-(value-axisMin)/(axisMax-axisMin)*140;
    const axisText=value=>Number((value*100).toPrecision(4))+'%',bounds=`<text class="launch-rate-bound" data-rate-bound="max" x="${left-6}" y="33" text-anchor="end">${axisText(axisMax)}</text><text class="launch-rate-bound" data-rate-bound="min" x="${left-6}" y="173" text-anchor="end">${axisText(axisMin)}</text>`;
    const labelY=new Map();
    rows.forEach((_,index)=>{
      const column=series.filter(line=>line.points[index]).map(line=>({line,point:line.points[index]})).sort((a,b)=>y(a.point.value)-y(b.point.value)),occupied=[];
      column.forEach(({line,point})=>{
        const value=text(point.value,line),pointY=y(point.value);let cy=pointY-10,box=rhythmLabelBox(value,x(index),cy,10);
        if(occupied.some(other=>rhythmBoxesOverlap(box,other))){cy=pointY+18;box=rhythmLabelBox(value,x(index),cy,10)}
        occupied.push(box);labelY.set(line.key+'|'+index,cy);
      });
    });
    const legend=series.map(line=>`<span data-launch-rate-legend="${esc(line.key)}" title="${esc(line.label)}"><i class="line-key" style="background:${line.color}"></i>${esc(line.label.split('（')[0])}</span>`).join('');
    const curves=series.map(line=>{
      let path='',previous=false;line.points.forEach(point=>{if(!point){previous=false;return}path+=(previous?'L':'M')+x(point.index)+','+y(point.value)+' ';previous=true});
      const values=line.points.filter(Boolean),dots=values.map(point=>{const tip=`${point.label} · ${line.label} ${text(point.value,line)}`;return `<circle data-launch-rate-point="${esc(line.key)}" data-index="${point.index}" data-value="${point.value}" cx="${x(point.index)}" cy="${y(point.value)}" r="3" tabindex="0" role="img" aria-label="${esc(tip)}"><title>${esc(tip)}</title></circle>`}).join('');
      const labels=values.map(point=>`<text class="launch-rate-value" data-launch-rate-label="${esc(line.key)}" data-index="${point.index}" data-point-y="${y(point.value)}" x="${x(point.index)}" y="${labelY.get(line.key+'|'+point.index)}" text-anchor="middle">${text(point.value,line)}</text>`).join('');
      return `<g data-launch-rate="${esc(line.key)}" style="--rate-color:${line.color}"><path data-launch-rate-line="${esc(line.key)}" d="${path}" fill="none"/>${dots}${labels}</g>`;
    }).join('');
    const stride=Math.max(1,Math.ceil((Math.max(0,...rows.map(row=>rhythmTextWidth(rhythmAxisText(row.label),9)))+10)/step)),axisBoxes=[];
    const axis=[...new Set([0,rows.length-1,...rows.map((_,index)=>index).filter(index=>index%stride===0)])].map(index=>{
      const value=rhythmAxisText(rows[index].label),box=rhythmLabelBox(value,x(index),210,9);if(axisBoxes.some(other=>rhythmBoxesOverlap(box,other)))return '';axisBoxes.push(box);
      return `<text class="rhythm-axis-label" x="${x(index)}" y="210" text-anchor="middle">${esc(value)}<title>${esc(rows[index].label)}</title></text>`;
    }).join('');
    return `<section class="launch-rate-trends" aria-label="累计比例趋势"><div class="launch-rate-history" tabindex="0" role="region" aria-label="累计比例趋势，可横向滚动"><svg width="${width}" height="224" viewBox="0 0 ${width} 224" style="width:${width}px;height:224px" data-rate-min="${axisMin}" data-rate-max="${axisMax}" role="img" aria-label="${esc(lines.map(line=>line.label).join('、'))}，共享百分比范围${axisText(axisMin)}至${axisText(axisMax)}"><line class="rhythm-axis-line" x1="${left}" y1="170" x2="${width-right}" y2="170"/>${bounds}${curves}${axis}</svg></div><div class="legend rhythm-legend">${legend}</div></section>`;
  }
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
  let moduleLabels = DATA.config.module_labels;
  const state = {subject:null,module:"overview",grain:"week",period:null,rawFile:0,rawSheet:0,rawQuery:"",rawOffset:0,rawFreezeRow:true,rawFreezeColumn:false,rawFreezeFirstColumn:true};
  const boardCache={};
  async function getDashboard(subjectId=state.subject,moduleId=state.module){
    const key=`${DYNAMIC?DATA.dataset_id+"|":""}${subjectId}|${moduleId}`;
    if(!(key in boardCache)){
      const load=async()=>{
        if(DYNAMIC)return unpackDashboard(await apiJson('dashboard',{subject:subjectId,module:moduleId}));
        const b64=(DATA.dashboard_blocks||{})[`${subjectId}|${moduleId}`];
        return b64?unpackDashboard(await decompressJson(b64)):null;
      };
      boardCache[key]=load().catch(error=>{delete boardCache[key];throw error});
    }
    return boardCache[key];
  }
  function subject(){return DATA.subjects.find(item=>item.id===state.subject)}
  const annotationStorageKey = 'order-dashboard.trend-annotations.v1';
  const annotationVisibilityKey = 'order-dashboard.trend-annotations.visible';
  let trendAnnotationState = readTrendAnnotations(), refreshAnnotationCharts=()=>{}, refreshAnnotationList=()=>{};
  let annotationReadRevision=0;
  function localTrendAnnotations(){
    try {
      const saved=JSON.parse(localStorage.getItem(annotationStorageKey));
      if(Array.isArray(saved?.entries))return {visible:saved.visible===true,entries:saved.entries.filter(note=>note&&typeof note.id==='string'&&typeof note.subject==='string'&&typeof note.text==='string'&&window.TrendAnnotations.dateKey(note.date,'day'))};
    } catch {}
    return {visible:false,entries:[]};
  }
  function readTrendAnnotations(){
    const local=localTrendAnnotations();
    if(!DYNAMIC)return local;
    let visible=local.visible;
    try { const saved=localStorage.getItem(annotationVisibilityKey); if(saved!==null)visible=saved==='true'; } catch {}
    return {visible,entries:[]};
  }
  function saveTrendAnnotations(next){
    try { localStorage.setItem(DYNAMIC?annotationVisibilityKey:annotationStorageKey,DYNAMIC?String(next.visible):JSON.stringify(next)); }
    catch { if(!DYNAMIC)return false; }
    trendAnnotationState=next; return true;
  }
  function annotationScopes(subjectId){
    const allowed=new Set(['*',...DATA.subjects.filter(item=>item.type==='group').map(item=>item.id)]),seen=new Set();
    let current=DATA.subjects.find(item=>item.id===subjectId);
    while(current&&!seen.has(current.id)){
      seen.add(current.id);allowed.add(current.id);
      current=DATA.subjects.find(item=>item.id===current.parent||item.name===current.parent);
    }
    return allowed;
  }
  function trendAnnotationsFor(subjectId){
    const scopes=annotationScopes(subjectId);
    return trendAnnotationState.entries.filter(note=>scopes.has(note.subject));
  }
  async function refreshSharedAnnotations(){
    if(!DYNAMIC)return;
    const revision=++annotationReadRevision,result=await apiJson('annotations');
    if(revision!==annotationReadRevision)return;
    const changed=JSON.stringify(result.entries)!==JSON.stringify(trendAnnotationState.entries);
    trendAnnotationState.entries=result.entries||[];
    if(changed){refreshAnnotationCharts();refreshAnnotationList();}
  }
  function annotationOptions(){
    return [new Option('所有主体','*'),...DATA.subjects.map(item=>new Option(item.name,item.id))];
  }
  async function openTrendAnnotationEditor(refreshCharts){
    const dialog=$('#trendAnnotationEditor'),form=$('#trendAnnotationForm'),list=$('#trendAnnotationList'),error=$('#trendAnnotationError');
    const cancel=$('#cancelTrendAnnotationEdit'),submit=form.querySelector('button[type="submit"]');
    const subjectId=state.subject,date=form.elements.namedItem('date'),scope=form.elements.namedItem('subject'),text=form.elements.namedItem('text');
    let editingId=null,editingVersion=null,busy=false;
    scope.replaceChildren(...annotationOptions());
    const fail=problem=>{error.textContent=problem.message;error.hidden=false};
    function resetForm(){form.reset();scope.value=subjectId;text.setCustomValidity('');error.hidden=true;editingId=null;editingVersion=null;cancel.hidden=true;submit.textContent='添加批注';}
    function renderList(){
      const notes=trendAnnotationsFor(subjectId).sort((a,b)=>b.date.localeCompare(a.date));
      list.replaceChildren(...notes.map(note=>{
        const item=document.createElement('li'),heading=document.createElement('small'),content=document.createElement('strong');
        heading.textContent=note.date+' · '+(note.subject==='*'?'所有主体':DATA.subjects.find(item=>item.id===note.subject)?.name||note.subject);
        content.textContent=note.text;
        const edit=document.createElement('button'),remove=document.createElement('button');
        edit.className=remove.className='trend-annotation-button';edit.type=remove.type='button';edit.textContent='编辑';remove.textContent='删除';
        edit.disabled=remove.disabled=busy;
        edit.onclick=()=>{resetForm();editingId=note.id;editingVersion=note.version;date.value=note.date;scope.value=note.subject;text.value=note.text;submit.textContent='保存修改';cancel.hidden=false;text.focus()};
        remove.onclick=async()=>{
          if(busy||!window.confirm('删除这条批注？'))return;
          await mutate(async()=>{
            if(DYNAMIC)await apiJson('annotations/'+encodeURIComponent(note.id),{version:note.version},{method:'DELETE'});
            else if(!saveTrendAnnotations({...localTrendAnnotations(),entries:localTrendAnnotations().entries.filter(entry=>entry.id!==note.id)}))throw new Error('无法保存批注，请检查浏览器存储权限。');
            if(editingId===note.id)resetForm();
          });
        };
        item.append(heading,content,edit,remove);return item;
      }));
    }
    async function mutate(operation){
      if(busy)return;busy=true;submit.disabled=cancel.disabled=date.disabled=scope.disabled=text.disabled=true;renderList();error.hidden=true;
      try{await operation();if(DYNAMIC)await refreshSharedAnnotations();refreshCharts();}
      catch(problem){if(problem.status===409){await refreshSharedAnnotations().catch(()=>{});problem.message='批注已被他人修改，请重新选择后编辑。';}fail(problem);}
      finally{busy=false;submit.disabled=cancel.disabled=date.disabled=scope.disabled=text.disabled=false;renderList();}
    }
    resetForm();renderList();refreshAnnotationList=()=>{if(dialog.open)renderList()};
    text.oninput=()=>text.setCustomValidity('');cancel.onclick=()=>{resetForm();date.focus()};
    form.onsubmit=async event=>{
      event.preventDefault();if(busy)return;
      const value=text.value.trim();if(!value){text.setCustomValidity('请输入批注内容。');text.reportValidity();return;}
      if(!window.TrendAnnotations.dateKey(date.value,'day'))return;
      const note={date:date.value,subject:scope.value,text:value};
      await mutate(async()=>{
        if(DYNAMIC){
          const options={method:editingId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(editingId?{...note,version:editingVersion}:note)};
          await apiJson(editingId?'annotations/'+encodeURIComponent(editingId):'annotations',{},options);
        }else{
          const latest=localTrendAnnotations(),id=editingId||window.crypto.randomUUID?.()||Date.now()+'-'+Math.random().toString(36).slice(2);
          if(!saveTrendAnnotations({visible:true,entries:[...latest.entries.filter(entry=>entry.id!==id),{...note,id}]}))throw new Error('无法保存批注，请检查浏览器存储权限。');
        }
        saveTrendAnnotations({...trendAnnotationState,visible:true});resetForm();
      });
    };
    let importButton=$('#importLocalTrendAnnotations');
    if(DYNAMIC&&!importButton){
      importButton=document.createElement('button');importButton.id='importLocalTrendAnnotations';importButton.className='trend-annotation-button';importButton.type='button';importButton.textContent='导入本机批注';form.after(importButton);
    }
    if(importButton){
      importButton.hidden=!localTrendAnnotations().entries.length;
      importButton.onclick=()=>mutate(async()=>{
        await refreshSharedAnnotations();
        for(const note of localTrendAnnotations().entries){
          if(trendAnnotationState.entries.some(saved=>saved.date===note.date&&saved.subject===note.subject&&saved.text===note.text))continue;
          const saved=await apiJson('annotations',{}, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date:note.date,subject:note.subject,text:note.text})});
          trendAnnotationState.entries.push(saved);
        }
        importButton.hidden=true;
      });
    }
    dialog.showModal();date.focus();
    if(DYNAMIC)await refreshSharedAnnotations().catch(fail);
  }
  function bindTrendAnnotations(sections){
    const charts=[...document.querySelectorAll('[data-trend-chart]')],toggles=[...document.querySelectorAll('[data-trend-annotation-toggle]')];
    const refreshCharts=()=>{
      for(const chart of charts){
        if(!chart.isConnected)continue;
        const previous=chart.querySelector('.stacked-chart,.original-chart'),scroll=previous?.scrollLeft||0,atEnd=previous&&previous.scrollWidth-previous.clientWidth-scroll<2;
        chart.innerHTML=renderStackedTrend(sections[Number(chart.dataset.trendChart)].data);
        const current=chart.querySelector('.stacked-chart,.original-chart');if(current)current.scrollLeft=atEnd?current.scrollWidth-current.clientWidth:scroll;
      }
      for(const button of toggles){button.textContent=trendAnnotationState.visible?'隐藏批注':'显示批注';button.setAttribute('aria-expanded',String(trendAnnotationState.visible));}
    };
    refreshAnnotationCharts=refreshCharts;
    for(const button of toggles)button.onclick=()=>{const next={...trendAnnotationState,visible:!trendAnnotationState.visible};if(!saveTrendAnnotations(next))trendAnnotationState=next;refreshCharts();};
    document.querySelectorAll('[data-trend-annotation-manage]').forEach(button=>{button.onclick=()=>openTrendAnnotationEditor(refreshCharts)});
  }
  const quickBrandOrder=['问界','智界','享界','尊界','尚界'];
  const generationYear=name=>Math.max(...[...String(name||'').matchAll(/(20\d{2})\s*款/g)].map(match=>Number(match[1])),0);
  const generationAggregateSuffix=name=>String(name||'').match(/(总计|汇总|合计)\s*$/)?.[1]||'';
  const generationAggregate=name=>String(name||'').includes('&')||Boolean(generationAggregateSuffix(name));
  const generationModelKey=name=>String(name||'').replace(/20\d{2}\s*款/g,'').replace(/总计|汇总|合计/g,'').replace(/\s+/g,'').toLowerCase();
  const quickGenerationExcluded=name=>/beta|预订|直订|盲订/i.test(String(name||''));
  const quickGenerationFamilyKey=name=>generationModelKey(name).replace(/增程|纯电|智驾版|标准版/g,'');
  const generationShortName=name=>{const raw=String(name||'').trim(),aggregate=generationAggregateSuffix(raw),value=raw.replace(/(总计|汇总|合计)\s*$/,'').trim(),year=generationYear(value),brand=quickBrandOrder.find(item=>value.startsWith(item))||value.match(/^[\u4e00-\u9fff]{1,3}界/)?.[0]||'',model=value.slice(brand.length).replace(/20\d{2}\s*款/g,'').replace(/\s+Ultimate\b/ig,'U').replace(/\s+典藏大观\b/g,'大观').replace(/\s+/g,' ').trim(),yearLabel=year?` ${String(year).slice(-2)}`:'';return `${model||value}${yearLabel}${aggregate}`};
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
  const moduleAvailable=(item,moduleId)=>!!item?.modules.includes(moduleId);
  function syncUrl(mode="replace"){
    try{
      const url=new URL(location.href),params=url.searchParams;
      params.set("subject",state.subject||"");params.set("module",state.module);
      if(!["generic","raw"].includes(state.module)){params.set("grain",state.grain);if(state.period)params.set("period",state.period)}else{params.delete("grain");params.delete("period")}
      if(state.module==='raw'){
        params.set('rawFile',DATA.raw_files[state.rawFile]?.name||'');
        params.set('rawSheet',DATA.raw_files[state.rawFile]?.sheets[state.rawSheet]?.name||'');
        if(state.rawQuery)params.set('rawQuery',state.rawQuery);else params.delete('rawQuery');
        if(state.rawOffset)params.set('rawOffset',state.rawOffset);else params.delete('rawOffset');
      }else for(const key of ['rawFile','rawSheet','rawQuery','rawOffset'])params.delete(key);
      history[`${mode}State`]({...(mode==='replace'?history.state:{}),dashboard:true},"",url);
      rememberReadingPosition();
    }catch(error){console.debug("[导航状态] 当前环境不支持写入网址",error)}
  }
  let restoringReadingPosition=false;
  function rememberReadingPosition(){
    if(restoringReadingPosition||$('#page')?.getAttribute('aria-busy')==='true')return;
    const page=$('#page'),table=$('#rawTable');
    try{history.replaceState({...history.state,reading:{page:page?.scrollTop||0,tableTop:table?.scrollTop||0,tableLeft:table?.scrollLeft||0}},'',location.href)}catch{}
  }
  function readRawLocation(params){
    if(!params.has('rawFile'))return;
    const file=DATA.raw_files.findIndex(item=>item.name===params.get('rawFile'));
    state.rawFile=Math.max(file,0);
    state.rawSheet=Math.max(DATA.raw_files[state.rawFile]?.sheets.findIndex(item=>item.name===params.get('rawSheet'))??0,0);
    state.rawQuery=params.get('rawQuery')||'';state.rawOffset=Math.max(0,Number(params.get('rawOffset'))||0);
  }
  async function restoreLocationState(){
    const reading=history.state?.reading;restoringReadingPosition=true;
    const params=new URLSearchParams(location.search),requested=params.get("subject"),requestedSubject=DATA.subjects.find(item=>item.id===requested||item.name===requested);
    if(requestedSubject)state.subject=requestedSubject.id;
    state.module=params.get("module")||state.module;
    state.grain=params.get("grain")||state.grain;state.period=params.get("period")||null;
    if(state.module==="launch_rhythm"&&!params.get("grain"))state.grain="day";
    readRawLocation(params);
    try{if(await ensureState()===false)return;await renderAll();if(reading){$('#page').scrollTop=reading.page||0;const table=$('#rawTable');if(table){table.scrollTop=reading.tableTop||0;table.scrollLeft=reading.tableLeft||0;}}}
    finally{restoringReadingPosition=false;}
  }

  async function init(){
    const params=new URLSearchParams(location.search),requested=params.get("subject");
    const requestedSubject=DATA.subjects.find(item=>item.id===requested||item.name===requested);
    state.subject=(requestedSubject||DATA.subjects.find(item=>item.modules.includes("overview"))||DATA.subjects[0]).id;
    state.module=params.get("module")||state.module;
    state.grain=params.get("grain")||state.grain;state.period=params.get("period")||state.period;
    readRawLocation(params);
    if(state.module==="launch_rhythm"&&!params.get("grain"))state.grain="day";
    bindStatic();renderSubjectSelect();if(await ensureState()===false)return;await renderAll();syncUrl("replace");
  }
  function bindStatic(){
    history.scrollRestoration='manual';
    let readingTimer;
    document.addEventListener('scroll',event=>{if(event.target.matches?.('#page,#rawTable')&&!readingTimer)readingTimer=setTimeout(()=>{readingTimer=null;rememberReadingPosition()},500)},true);
    document.addEventListener('click',event=>{if(event.target.closest('[data-module],[data-panel-source],[data-file],[data-grain],[data-quick-generation]'))rememberReadingPosition()},true);
    document.addEventListener('change',event=>{if(event.target.matches('#subjectSelect,#periodSelect,#rawFile,#rawSheet'))rememberReadingPosition()},true);
    $("#subjectSelect").onchange=async event=>{state.subject=event.target.value;if(await ensureState()===false)return;await renderAll();syncUrl("push")};
    $("#quickGenerationList").onclick=async event=>{const button=event.target.closest('[data-quick-generation]');if(!button)return;state.subject=button.dataset.quickGeneration;if(await ensureState()===false)return;await renderAll();syncUrl("push")};
    $("#grainSelect").onclick=async event=>{const button=event.target.closest("button");if(!button||button.disabled)return;state.grain=button.dataset.grain;const board=await getDashboard();const view=board?.views?.[state.grain];state.period=view?.default_period||null;await renderAll();syncUrl("push")};
    $("#periodSelect").onchange=async event=>{state.period=event.target.value;await renderPage();syncUrl("push")};
    window.addEventListener("popstate",()=>restoreLocationState());
    window.addEventListener("resize",syncTopbarQuickLayout,{passive:true});
  }
  async function ensureState(){
    const revision=ensureState.revision=(ensureState.revision||0)+1;
    let item=subject();
    if(!moduleAvailable(item,state.module))state.module=item.modules.find(id=>id!=="raw"&&moduleAvailable(item,id))||"raw";
    if(state.module==="raw")return true;
    const subjectId=state.subject,moduleId=state.module;
    let board;
    const status=$('#pageStatus'),pageNode=$('#page');
    if(DYNAMIC)pageNode.setAttribute('aria-busy','true');
    const timer=DYNAMIC?setTimeout(()=>{if(revision===ensureState.revision){status.textContent='正在加载…';status.classList.add('show')}},180):null;
    try{board=await getDashboard();}catch(error){
      if(revision===ensureState.revision&&subjectId===state.subject&&moduleId===state.module)showPageError(error);
      return false;
    }finally{clearTimeout(timer);if(DYNAMIC&&revision===ensureState.revision){pageNode.setAttribute('aria-busy','false');status.classList.remove('show')}}
    // A previous subject/module may finish decompressing after the next one.
    // Check request identity too: switching A -> B -> A invalidates the first A.
    if(revision!==ensureState.revision||subjectId!==state.subject||moduleId!==state.module)return false;
    const grains=Object.keys(board?.views||{});
    if(!grains.includes(state.grain))state.grain=grains[0]||"week";
    const view=board?.views?.[state.grain];
    if(!(view?.periods||[]).includes(state.period))state.period=view?.default_period||null;
    return revision===ensureState.revision&&subjectId===state.subject&&moduleId===state.module;
  }
  function renderSubjectSelect(){
    const order=[["group","集团"],["brand","品牌"],["generation","代际"]];
    const subjects=DATA.subjects;
    $("#subjectSelect").innerHTML=order.map(([type,label])=>`<optgroup label="${label}">${subjects.filter(item=>item.type===type).map(item=>`<option value="${item.id}">${esc(item.name)}</option>`).join("")}</optgroup>`).join("");
    $("#subjectSelect").value=state.subject;
  }
  let navigationRevision=0,pageRevision=0;
  async function renderAll(){
    const revision=++navigationRevision,status=$("#pageStatus"),page=$("#page");
    const viewKey=state.subject+'|'+state.module,changed=page.dataset.viewKey!==viewKey;
    page.setAttribute("aria-busy","true");
    const timer=setTimeout(()=>{if(revision===navigationRevision&&status){status.textContent=`正在加载${subject()?.name||''} · ${moduleLabels[state.module]||'分析'}…`;status.classList.add("show")}},180);
    try{renderSubjectSelect();renderQuickGenerationLinks();renderNav();if(await renderFilters()===false)return;if(revision===navigationRevision){await renderPage();page.dataset.viewKey=viewKey;if(changed&&!restoringReadingPosition)page.scrollTop=0;}}
    catch(error){if(revision===navigationRevision)showPageError(error);}
    finally{clearTimeout(timer);if(revision===navigationRevision){page.setAttribute("aria-busy","false");status?.classList.remove("show");page.getAnimations().forEach(animation=>animation.cancel());if(!matchMedia('(prefers-reduced-motion: reduce)').matches)page.animate([{opacity:.78},{opacity:1}],{duration:160,easing:'ease-out'});}}
  }
  function showPageError(error){
    $('#page').innerHTML=`<div class="empty-page" role="alert"><p>${esc(error.message)}</p><button type="button" data-page-retry>重新加载</button></div>`;
    $('[data-page-retry]').onclick=async()=>{if(await ensureState()!==false)await renderAll()};
  }
  function renderNav(){
    const item=subject();
    const navigationModules=DATA.config.module_order;
    $('#moduleSelect').innerHTML=navigationModules.map(id=>`<option value="${esc(id)}" ${moduleAvailable(item,id)?'':'disabled'}>${esc(moduleLabels[id])}${moduleAvailable(item,id)?'':'（当前主体不可用）'}</option>`).join('');
    $('#moduleSelect').value=state.module;
    $('#moduleSelect').onchange=event=>$('#moduleNav').querySelector(`[data-module="${event.target.value}"]`)?.click();
    $("#moduleNav").innerHTML=navigationModules.map(id=>{
      const available=moduleAvailable(item,id),active=state.module===id;
      const hint="当前主体没有对应Sheet";
      const icon=outlineIcon(moduleIcons[id]||"M4 6h16M4 12h16M4 18h16M9 6v12");
      return '<button data-module="'+id+'" class="'+(active?'active':'')+'" '+(active?'aria-current="page" ':'')+(available?'':'disabled ')+'title="'+(available?moduleLabels[id]:hint)+'">'+icon+moduleLabels[id]+'</button>';
    }).join("");
    $("#moduleNav").onclick=async event=>{
      const button=event.target.closest("[data-module]");
      if(!button||button.disabled||button.dataset.module===state.module)return;
      state.module=button.dataset.module;if(state.module==="launch_rhythm")state.grain="day";if(await ensureState()===false)return;await renderAll();syncUrl("push");
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
    const revision=renderFilters.revision=(renderFilters.revision||0)+1;
    const subjectId=state.subject,moduleId=state.module;
    const isCurrent=()=>revision===renderFilters.revision&&subjectId===state.subject&&moduleId===state.module;
    $('#filters').dataset.mode='period';
    $('#grainSelect').closest('.filter-group').hidden=false;
    $('#periodSelect').closest('label').hidden=false;
    $('#periodContext').hidden=true;
    $("#filters").style.display="grid";
    $("#subjectSelect").closest("label").style.display="";
    $("#grainSelect").closest(".filter-group").style.display="";
    $("#periodSelect").closest("label").style.display="";
    if(["generic","raw"].includes(state.module)){
      $('#filters').dataset.mode='window';
      $('#grainSelect').closest('.filter-group').hidden=true;
      $("#grainSelect").innerHTML=Object.entries(DATA.config.grain_labels).map(([id,label])=>`<button data-grain="${id}" disabled>${label}</button>`).join("");
      const period=$("#periodSelect");
      period.innerHTML="<option>按所选表格范围</option>";period.disabled=true;
      $('#periodSelect').closest('label').hidden=period.disabled;
      $('#periodContext').hidden=!period.disabled;
      $('#periodContext').textContent=period.selectedOptions[0]?.textContent||'';
      $("#grainSelect").title="此模块不使用日周月筛选";return;
    }
    $("#periodSelect").disabled=false;$("#grainSelect").title="";
    const board=await getDashboard();
    if(!isCurrent())return false;
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
    rhythmObserver?.disconnect();rhythmObserver=null;
    channelPanelResizeObserver?.disconnect();channelPanelResizeObserver=null;
    const revision=++pageRevision,moduleId=state.module,subjectId=state.subject;
    if(state.module==="raw"){await renderRaw();return}
    const board=await getDashboard(),page=board?.views?.[state.grain]?.pages?.[state.period];
    if(revision!==pageRevision||moduleId!==state.module||subjectId!==state.subject)return;
    if(!board||!page){$("#page").innerHTML=`<div class="empty-page">当前主体暂无该分析</div>`;return}
    channelPanelData.clear();
    const heading=moduleId==="overview"?"":`<header class="page-section-heading"><h1>${esc(moduleLabels[moduleId])}</h1><p>${esc(subject()?.name)}</p></header>`;
    $("#page").innerHTML=`${heading}${renderKpis(page.kpis)}<div class="sections">${renderSections(page.sections)}</div>`;
    bindRhythmCharts();
    bindChannelPanels();
    bindSkuHeatmaps();
    bindTrendAnnotations(page.sections);
    alignOverviewChartScrollbars();
    document.querySelectorAll("[data-panel-source]").forEach(button=>button.onclick=()=>jumpToSource(page.sections[Number(button.dataset.panelSource)]?.source));
    document.querySelectorAll("[data-combo-switch]").forEach(button=>button.onclick=()=>{
      const root=button.closest(".combo-matrix"),target=button.dataset.comboSwitch;
      root.querySelectorAll("[data-combo-switch]").forEach(item=>{const active=item.dataset.comboSwitch===target;item.classList.toggle("active",active);item.setAttribute("aria-pressed",String(active))});
      root.querySelectorAll("[data-combo-panel]").forEach(item=>item.hidden=item.dataset.comboPanel!==target);
      bindSkuHeatmaps();
    });
    document.querySelectorAll("[data-hourly-select]").forEach(select=>select.onchange=()=>{
      const rows=JSON.parse(select.dataset.hourlyRows||"[]");
      select.closest(".hourly-wrap").querySelector("[data-hourly-body]").innerHTML=renderHourlyChart(rows,select.value);
      bindRhythmCharts();
    });
    document.querySelectorAll("[data-launch-hourly-select]").forEach(select=>select.onchange=()=>{
      const rows=JSON.parse(select.dataset.launchHourlyRows||"[]");
      select.closest(".hourly-wrap").querySelector("[data-launch-hourly-body]").innerHTML=renderLaunchHourlyChart(rows,select.value);
      bindRhythmCharts();
    });
  }
  function renderKpis(items){return `<div class="kpis ${items.length===5?"five":""}">${items.map(item=>`<article class="kpi"><span>${esc(item.label)}</span>${outlineIcon("M4 20h16M7 16v-4m5 4V8m5 8V4","kpi-icon")}<strong>${item.value==null?"—":fmt(item.value)}</strong><em>${esc(item.unit)}</em><small class="kpi-note">${esc(item.note)}</small>${renderKpiComparison(item)}</article>`).join("")}</div>`}
  function renderKpiComparison(item){
    const comparison=item.comparison;
    if(!comparison||comparison.status!=="available")return '<div class="kpi-compare neutral"><span>较上周期</span><b>暂无可比数据</b></div>';
    const direction=comparison.direction||"flat",verb=direction==="up"?"上涨":direction==="down"?"下降":"持平",arrow=direction==="up"?"↑":direction==="down"?"↓":"—";
    const movement=comparison.rate==null?`${fmt(Math.abs(comparison.delta))}${esc(item.unit)}`:`${Math.abs(comparison.rate*100).toFixed(1)}%`;
    return `<div class="kpi-compare ${direction}"><span>较上周期</span><b>${arrow} ${verb} ${movement}</b><em>上期 ${fmt(comparison.previous)}</em></div>`;
  }
  function renderSections(items){
    const rankingIndex=state.module==='cancellation'?items.findIndex(item=>item.kind==='bars'&&item.title==='选配退订率排行'):-1;
    const trendIndex=rankingIndex>=0?items.findIndex(item=>item.kind==='daily_cancel'):-1;
    return items.map((item,index)=>{
      if(trendIndex>=0&&index===rankingIndex)return '';
      const ranking=index===trendIndex?items[rankingIndex]:null;
      const appendix=ranking?`<section class="cancel-ranking" aria-label="${esc(ranking.title)}"><div class="cancel-ranking-head"><div><h3>${esc(ranking.title)}</h3><span>${esc(ranking.meta)}</span></div>${renderPanelSource(ranking,rankingIndex)}</div>${renderBars(ranking.data)}</section>`:'';
      return renderSection(item,index,appendix);
    }).join('');
  }
  function renderPanelSource(item,index){
    return item.source?`<button class="panel-source" data-panel-source="${index}" aria-label="查看${esc(item.title)}的来源数据" title="跳转到底表"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7m0-7-9 9M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/></svg><span>来源数据</span></button>`:"";
  }
  function renderSection(item,index,appendix=''){
    const pieBars=item.kind==='bars'&&item.title==='门店渠道订单量';
    const renderer=pieBars?renderPieChart:({channel_panel:renderChannelPanel,stacked_trend:renderStackedTrend,table:renderTable,bars:renderBars,donut:renderPieChart,structure_cards:renderStructureCards,funnel:renderFunnel,cohort_matrix:renderCohortMatrix,rank_cards:renderRankCards,rise_rank_cards:data=>renderRankCards(data,'rise'),drop_rank_cards:data=>renderRankCards(data,'drop'),rights:renderRights,fee_band_structure:renderFeeBandStructure,fee_period_bands:renderFeePeriodBands,fee_heatmap:renderFeeHeatmap,heat_table:renderTable,sku_heatmap:renderSkuHeatmap,combo_heatmap:renderComboHeatmap,combo_matrix:renderComboMatrix,tail_distribution:renderTailDistribution,launch_composite:renderLaunch,launch_hourly:renderLaunchHourly,matrix:renderTable,trend:renderTrend,hourly:renderHourly,small_order_rhythm:renderSmallOrderRhythm,cancel_cards:renderCancelCards,history_table:renderHistoryTable,daily_cancel:renderDailyCancel}[item.kind]||renderUnknown);
    const annotationControls=item.kind==="stacked_trend" && item.data?.periods?.length;
    const chartId="trendChart"+index;
    const actions=annotationControls ? `<div class="trend-annotation-actions">
      <button type="button" class="trend-annotation-button" data-trend-annotation-toggle aria-controls="${chartId}" aria-expanded="${trendAnnotationState.visible}">${trendAnnotationState.visible ? "隐藏批注" : "显示批注"}</button>
      <button type="button" class="trend-annotation-button" data-trend-annotation-manage>管理批注</button>
    </div>` : "";
    const content=renderer(item.data);
    const body=annotationControls ? `${actions}<div id="${chartId}" data-trend-chart="${index}">${content}</div>` : content;
    return `<article class="panel ${item.width==="half"?"":"full"}${appendix?' has-cancel-ranking':''}" data-section-kind="${esc(item.kind||"")}"><div class="panel-head"><div><h2>${esc(item.title)}</h2><span>${esc(item.meta)}</span></div>${renderPanelSource(item,index)}</div><div class="panel-body">${body}${appendix}</div></article>`;
  }
  const channelPanelData=new Map();
  let channelPanelResizeObserver=null;
  const channelKnown=value=>typeof value==='number'&&Number.isFinite(value);
  const channelColors={"华为授权体验店":"#3173B4","华为智能生活馆":"#218C8C","华为旗舰店":"#C27B38","鸿蒙智行用户中心":"#7B61A8","问界用户中心":"#507F3A","智界用户中心":"#C35A66","享界用户中心":"#88743B","尊界用户中心":"#4D6088","尚界用户中心":"#A55F95","未知门店类型":"#738191","综合店":"#547D9A","尊界体验中心":"#9F5943"};
  function channelColor(name){
    if(channelColors[name])return channelColors[name];
    const hash=Array.from(String(name)).reduce((value,char)=>(value*31+char.charCodeAt(0))>>>0,0);
    return Object.values(channelColors)[hash%Object.keys(channelColors).length];
  }
  function channelValue(value,format='number',signed=false){
    if(!channelKnown(value))return '—';
    const prefix=signed&&value>0?'+':'';
    if(format==='percent')return prefix+(value*100).toFixed(1)+'%';
    if(format==='points')return prefix+(value*100).toFixed(1)+' 个百分点';
    if(format==='capacity')return prefix+value.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
    return prefix+fmt(value);
  }
  function channelHistory(data){
    const history=Array.isArray(data.history)?data.history:[],index=history.findIndex(item=>String(item.period)===String(data.period));
    return index>=0?history.slice(0,index+1):[{period:data.period,rows:data.rows||[],totals:data.totals||{}}];
  }
  function channelNames(data,history){return [...new Set([...(data.rows||[]),...history.flatMap(entry=>entry.rows||[])].filter(row=>row.store_count!==0).map(row=>row.channel).filter(Boolean))]}
  function channelRow(entry,name){return (entry.rows||[]).find(row=>row.channel===name)}
  function channelHistoryMatrix(data,history,names,key,label,format,unit,totalKey){
    const showStores=key==='productivity';
    const storeCell=value=>showStores?`<td class="channel-store-count" data-store-count="${channelKnown(value)?value:''}">${channelValue(value)}</td>`:'';
    const valuesFor=name=>history.map(entry=>channelRow(entry,name)?.[key]);
    const cells=values=>values.map((value,index)=>`<td data-period="${esc(history[index].period)}" data-value="${channelKnown(value)?value:''}"${index===history.length-1?' class="channel-current-period"':''}>${channelValue(value,format)}</td>`).join('');
    const body=names.map(name=>{
      const current=channelRow({rows:data.rows},name),stores=key==='active_rate'?`<small>配置 ${channelValue(current?.store_count)} 家</small>`:'';
      return `<tr data-channel="${esc(name)}"><th scope="row"><span class="channel-row-heading"><i style="background:${channelColor(name)}" aria-hidden="true"></i><span>${esc(name)}${stores}</span></span></th>${storeCell(current?.store_count)}${cells(valuesFor(name))}</tr>`;
    }).join('');
    const total=totalKey?`<tfoot><tr data-channel="__total__"><th scope="row">${key==='active_rate'?'整体出单率':key==='productivity'?'整体单店产能':'合计'}</th>${storeCell(data.totals?.store_count)}${cells(history.map(entry=>entry.totals?.[totalKey]))}</tr></tfoot>`:'';
    return `<section class="channel-table-block"><div class="channel-subhead"><h3>${esc(label)}</h3><span>${esc(unit)}</span></div><div class="channel-matrix-scroll" data-channel-scroll tabindex="0" role="region" aria-label="${esc(label)}历史表，渠道${showStores?'及门店数':''}列固定，可横向滚动"><table class="channel-matrix" data-channel-table="${key}"><caption class="sr-only">${esc(label)}，${showStores?'门店数为当前配置，':''}各渠道为行、历史周期为列</caption><colgroup><col class="channel-name-col">${showStores?'<col class="channel-store-col">':''}${history.map(()=>'<col class="channel-period-col">').join('')}</colgroup><thead><tr><th scope="col">门店渠道</th>${showStores?'<th scope="col" class="channel-store-count" title="当前配置门店数（家）">门店数</th>':''}${history.map((entry,index)=>`<th scope="col" data-period="${esc(entry.period)}"${index===history.length-1?' class="channel-current-period"':''}>${esc(entry.period)}</th>`).join('')}</tr></thead><tbody>${body}</tbody>${total}</table></div></section>`;
  }
  function channelAxisMax(values){
    const maximum=Math.max(0,...values.filter(channelKnown));if(!maximum)return 1;
    const power=10**Math.floor(Math.log10(maximum)),scaled=maximum/power;
    return (scaled<=1?1:scaled<=2?2:scaled<=5?5:10)*power;
  }
  function channelChartGeometry(history,names,pairedTables){
    const height=pairedTables?Math.min(570,Math.max(330,names.length*28+180)):330;
    return {width:Math.max(360,history.length*52),height,top:26,bottom:height-46,step:Math.max(360,history.length*52)/Math.max(history.length,1)};
  }
  function channelAxisMarkup(maximum,format,g,side){
    return `<div class="channel-y-axis ${side}" aria-hidden="true">${[0,.25,.5,.75,1].map(ratio=>`<span style="top:${g.bottom-ratio*(g.bottom-g.top)}px">${channelValue(maximum*ratio,format)}</span>`).join('')}</div>`;
  }
  function channelLinePath(values,g,maximum){
    let connected=false,path='';
    values.forEach((value,index)=>{if(!channelKnown(value)){connected=false;return}path+=`${connected?'L':'M'}${((index+.5)*g.step).toFixed(2)} ${(g.bottom-value/maximum*(g.bottom-g.top)).toFixed(2)} `;connected=true;});
    return path;
  }
  function channelPeriodDescription(data,entry,names){
    const parts=[String(entry.period)];
    if(data.metric==='sales')parts.push('总留存大定 '+channelValue(entry.totals?.count)+' 单');
    names.forEach(name=>{const row=channelRow(entry,name);parts.push(data.metric==='sales'?`${name} ${channelValue(row?.count)} 单，占比 ${channelValue(row?.share,'percent')}`:data.metric==='stores'?`${name} 出单率 ${channelValue(row?.active_rate,'percent')}，${channelValue(row?.active_count)} / ${channelValue(row?.store_count)} 家`:`${name} ${channelValue(row?.productivity,'capacity')} 单/店/本周期`)});
    return parts.join('；');
  }
  function channelPointOverlays(data,history,names,g){
    return history.map((entry,index)=>`<g class="channel-period-target" data-channel-point="${index}" data-period="${esc(entry.period)}" tabindex="${index===history.length-1?'0':'-1'}" role="img" aria-label="${esc(channelPeriodDescription(data,entry,names))}"><rect x="${index*g.step}" y="${g.top-10}" width="${g.step}" height="${g.bottom-g.top+16}" fill="transparent"/><title>${esc(channelPeriodDescription(data,entry,names))}</title></g>`).join('');
  }
  function channelLegend(names,sales){
    return `<div class="channel-legend">${names.map(name=>`<span><i style="background:${channelColor(name)}" aria-hidden="true"></i>${esc(name)}</span>`).join('')}${sales?'<span class="channel-total-key"><i aria-hidden="true"></i>总留存大定（右轴）</span>':''}</div>`;
  }
  function channelHistoryChart(data,history,names){
    const sales=data.metric==='sales',stores=data.metric==='stores',key=stores?'active_rate':'productivity',format=stores?'percent':'capacity',g=channelChartGeometry(history,names,sales||stores);
    const totals=history.map(entry=>entry.totals?.count),totalMax=channelAxisMax(totals);
    const sums=history.map(entry=>{const values=names.map(name=>channelRow(entry,name)?.share);return values.every(channelKnown)?values.reduce((sum,value)=>sum+value,0):null});
    const lineValues=names.map(name=>history.map(entry=>channelRow(entry,name)?.[key]));
    const leftMax=sales?Math.max(1,Math.ceil(Math.max(0,...sums.filter(channelKnown))*4-1e-10)/4):channelAxisMax(lineValues.flat());
    if(!sales&&!lineValues.flat().some(channelKnown)){
      const unconfigured=!(data.rows||[]).some(row=>channelKnown(row.store_count)),title=stores?'各渠道出单门店比例趋势':'各渠道单店产能趋势',message=unconfigured?'未配置该主体的门店总数':stores?'暂无可用的出单门店比例数据':'暂无可用的单店产能数据';
      return `<section class="channel-chart-block"><div class="channel-subhead"><h3>${title}</h3></div><div class="channel-chart-empty" data-channel-chart role="status"><strong>${message}</strong><p>${unconfigured?'维护当前主体的渠道门店总数后，重新生成看板即可查看。':'当前历史范围内数据缺失，表格以 — 保留。'}</p></div>${channelLegend(names,false)}<div class="channel-tooltip" data-channel-tooltip hidden role="tooltip"></div></section>`;
    }
    const grid=[0,.25,.5,.75,1].map(ratio=>{const y=g.bottom-ratio*(g.bottom-g.top);return `<line x1="0" x2="${g.width}" y1="${y}" y2="${y}"/>`}).join('');
    let marks='';
    if(sales){
      marks=history.map((entry,index)=>{
        if(!channelKnown(sums[index]))return `<text class="channel-missing-mark" x="${(index+.5)*g.step}" y="${g.bottom-8}" text-anchor="middle" data-channel-missing-stack data-period="${esc(entry.period)}">缺失</text>`;
        let cumulative=0;
        return names.map(name=>{const row=channelRow(entry,name),value=row.share,barHeight=value/leftMax*(g.bottom-g.top),y=g.bottom-(cumulative+value)/leftMax*(g.bottom-g.top);cumulative+=value;return `<rect data-channel="${esc(name)}" data-period="${esc(entry.period)}" data-value="${value}" x="${(index+.5)*g.step-17}" y="${y}" width="34" height="${Math.max(0,barHeight)}" fill="${channelColor(name)}"><title>${esc(name)} · ${esc(entry.period)} · ${channelValue(value,'percent')}</title></rect>${barHeight>=19?`<text class="channel-stack-label" x="${(index+.5)*g.step}" y="${y+barHeight/2+3}" text-anchor="middle">${(value*100).toFixed(0)}%</text>`:''}`}).join('');
      }).join('');
      marks+=`<path class="channel-total-line" d="${channelLinePath(totals,g,totalMax)}"/>`+totals.map((value,index)=>channelKnown(value)?`<circle class="channel-total-point" data-channel="__total__" data-period="${esc(history[index].period)}" data-value="${value}" cx="${(index+.5)*g.step}" cy="${g.bottom-value/totalMax*(g.bottom-g.top)}" r="3.5"><title>${esc(history[index].period)} · 总留存大定 ${channelValue(value)} 单</title></circle>`:'').join('');
    }else{
      marks=names.map((name,series)=>`<path class="channel-series-line" data-channel="${esc(name)}" d="${channelLinePath(lineValues[series],g,leftMax)}" stroke="${channelColor(name)}"/>${lineValues[series].map((value,index)=>channelKnown(value)?`<circle class="channel-series-point" data-channel="${esc(name)}" data-period="${esc(history[index].period)}" data-value="${value}" cx="${(index+.5)*g.step}" cy="${g.bottom-value/leftMax*(g.bottom-g.top)}" r="2.6" fill="${channelColor(name)}"><title>${esc(name)} · ${esc(history[index].period)} · ${channelValue(value,format)}</title></circle>`:'').join('')}`).join('');
      if(!stores){
        const clipId=`channel-capacity-plot-${channelPanelData.size}`;
        marks=`<defs><clipPath id="${clipId}"><rect x="0" y="${g.top}" width="${g.width}" height="${g.bottom-g.top}"/></clipPath></defs><g clip-path="url(#${clipId})">${marks}</g>`;
      }
    }
    const xLabels=history.map((entry,index)=>{const x=(index+.5)*g.step,label=String(entry.period).replace(/^20(\d{2})[-/](\d{2})[-/](\d{2})$/,'$2-$3');return `<text class="channel-axis-label" x="${x}" y="${g.bottom+20}" text-anchor="middle">${esc(label)}<title>${esc(entry.period)}</title></text>`}).join('');
    const title=sales?'渠道占比与留存大定总量':stores?'各渠道出单门店比例趋势':'各渠道单店产能趋势',leftUnit=sales?'渠道销量占比（%）':stores?'出单门店比例（%）':'单店产能（单/店/本周期）';
    return `<section class="channel-chart-block"><div class="channel-subhead"><h3>${title}</h3></div><div class="channel-axis-units"><span>${leftUnit}</span>${sales?'<span>总留存大定（单）</span>':''}</div><div class="channel-chart-frame ${sales?'channel-dual-axis':'channel-single-axis'}" data-channel-chart style="--channel-chart-height:${g.height}px">${channelAxisMarkup(leftMax,sales||stores?'percent':'capacity',g,'left')}<div class="channel-plot-scroll" data-channel-scroll tabindex="0" role="region" aria-label="${title}，左右方向键可查看各周期"><svg width="${g.width}" height="${g.height}" viewBox="0 0 ${g.width} ${g.height}" role="group" aria-label="${title}"><g class="channel-chart-grid">${grid}</g>${marks}${xLabels}${channelPointOverlays(data,history,names,g)}</svg></div>${sales?channelAxisMarkup(totalMax,'number',g,'right'):''}</div>${channelLegend(names,sales)}<p class="channel-chart-note">${sales?'柱：原始销量占比；线：总留存大定。':'每条线对应一个渠道。'}悬停或聚焦周期查看明细，缺失数据保留空缺。</p><div class="channel-tooltip" data-channel-tooltip hidden role="tooltip"></div></section>`;
  }
  function renderChannelPanel(data){
    const id=String(channelPanelData.size),history=channelHistory(data),names=channelNames(data,history);channelPanelData.set(id,data);
    const tables=data.metric==='sales'?channelHistoryMatrix(data,history,names,'count','渠道留存大定','number','单','count')+channelHistoryMatrix(data,history,names,'share','渠道销量占比','percent','%'):data.metric==='stores'?channelHistoryMatrix(data,history,names,'active_count','贡献订单门店数量','number','家','active_count')+channelHistoryMatrix(data,history,names,'active_rate','贡献订单门店比例','percent','%','active_rate'):channelHistoryMatrix(data,history,names,'productivity','渠道单店产能','capacity','单/店/本周期','productivity');
    const note=data.metric==='sales'?'留存大定数量和占比直接读取门店类型指标。':data.metric==='stores'?'出单门店比例 = 当期出单门店数 ÷ 该渠道配置门店总数。':'单店产能 = 当期渠道留存大定 ÷ 该渠道配置门店总数。';
    return `<div class="channel-panel" data-channel-panel="${id}" data-channel-metric="${esc(data.metric)}"><div class="channel-panel-intro"><p>${note}</p><span>截至 ${esc(data.period)} · ${history.length} 个周期 · 向左查看历史</span></div><div class="channel-history-grid"><div class="channel-history-tables">${tables}</div>${channelHistoryChart(data,history,names)}</div></div>`;
  }
  function refreshChannelCapacityAxis(scroll){
    if(!scroll.classList.contains('channel-plot-scroll'))return;
    const root=scroll.closest('[data-channel-panel]'),data=channelPanelData.get(root?.dataset.channelPanel);
    if(data?.metric!=='capacity'||!scroll.clientWidth)return;
    const history=channelHistory(data),names=channelNames(data,history),g=channelChartGeometry(history,names,false),chart=scroll.closest('[data-channel-chart]');
    const first=Math.max(0,Math.ceil(scroll.scrollLeft/g.step-.5)),last=Math.min(history.length-1,Math.floor((scroll.scrollLeft+scroll.clientWidth)/g.step-.5));
    const series=names.map(name=>history.map(entry=>channelRow(entry,name)?.productivity));
    const visible=series.flatMap(values=>values.slice(first,last+1)),peak=Math.max(0,...visible.filter(channelKnown));
    // Keep zero as the baseline, with modest headroom and stable rounded steps.
    const step=channelAxisMax([peak])/5,maximum=peak?Math.ceil(peak*1.08/step-1e-10)*step:1;
    if(Number(chart.dataset.channelAxisMax)===maximum)return;
    chart.dataset.channelAxisMax=String(maximum);
    chart.querySelectorAll('.channel-y-axis.left span').forEach((label,index)=>{label.textContent=channelValue(maximum*index/4,'capacity')});
    chart.querySelectorAll('.channel-series-line').forEach((line,index)=>{line.setAttribute('d',channelLinePath(series[index],g,maximum))});
    chart.querySelectorAll('.channel-series-point').forEach(point=>{point.setAttribute('cy',g.bottom-Number(point.dataset.value)/maximum*(g.bottom-g.top))});
  }
  function bindChannelScrollers(scrollers){
    channelPanelResizeObserver?.disconnect();channelPanelResizeObserver=null;
    if(!scrollers.length)return;
    const positions=new WeakMap();
    channelPanelResizeObserver=new ResizeObserver(entries=>entries.forEach(({target:scroll})=>{
      const saved=positions.get(scroll);if(!saved)return;
      const width=scroll.clientWidth,max=Math.max(0,scroll.scrollWidth-width);
      if(width===saved.width&&max===saved.max)return;
      // Preserve a user's historical position; only a previously anchored view follows the end.
      saved.width=width;saved.max=max;
      scroll.scrollLeft=saved.atEnd?max:Math.min(saved.left,max);
      saved.expected=scroll.scrollLeft;
      if(saved.atEnd)saved.left=scroll.scrollLeft;
      refreshChannelCapacityAxis(scroll);
    }));
    scrollers.forEach(scroll=>{
      scroll.scrollLeft=scroll.scrollWidth;
      const saved={width:scroll.clientWidth,max:Math.max(0,scroll.scrollWidth-scroll.clientWidth),left:scroll.scrollLeft,expected:scroll.scrollLeft,atEnd:true};
      positions.set(scroll,saved);
      refreshChannelCapacityAxis(scroll);
      scroll.addEventListener('scroll',()=>{
        refreshChannelCapacityAxis(scroll);
        const max=Math.max(0,scroll.scrollWidth-scroll.clientWidth);
        // Resize-induced/clamped scroll events must not be mistaken for a user choosing the end.
        if(scroll.clientWidth!==saved.width||max!==saved.max||Math.abs(scroll.scrollLeft-saved.expected)<1)return;
        saved.left=scroll.scrollLeft;saved.expected=scroll.scrollLeft;saved.atEnd=max-scroll.scrollLeft<=2;
      },{passive:true});
      channelPanelResizeObserver.observe(scroll);
    });
  }
  function bindChannelPanels(){
    bindChannelScrollers([...document.querySelectorAll('.channel-panel [data-channel-scroll]')]);
    document.querySelectorAll('[data-channel-panel]').forEach(root=>{
      const data=channelPanelData.get(root.dataset.channelPanel);if(!data)return;
      const history=channelHistory(data),names=channelNames(data,history),chart=root.querySelector('.channel-chart-block'),tooltip=root.querySelector('[data-channel-tooltip]');
      const showPoint=target=>{
        const entry=history[Number(target.dataset.channelPoint)];if(!entry)return;
        tooltip.innerHTML=`<strong>${esc(entry.period)}${data.metric==='sales'?` · 总留存大定 ${channelValue(entry.totals?.count)} 单`:''}</strong><ul>${names.map(name=>{const row=channelRow(entry,name),value=data.metric==='sales'?`${channelValue(row?.count)} 单 · ${channelValue(row?.share,'percent')}`:data.metric==='stores'?`${channelValue(row?.active_rate,'percent')} · ${channelValue(row?.active_count)} / ${channelValue(row?.store_count)} 家`:`${channelValue(row?.productivity,'capacity')} 单/店`;return `<li><span><i style="background:${channelColor(name)}"></i>${esc(name)}</span><b>${value}</b></li>`}).join('')}</ul>`;
        tooltip.hidden=false;
        const chartBox=chart.getBoundingClientRect(),pointBox=target.getBoundingClientRect(),left=Math.min(Math.max(4,pointBox.left-chartBox.left+pointBox.width/2-tooltip.offsetWidth/2),Math.max(4,chart.clientWidth-tooltip.offsetWidth-4));
        tooltip.style.left=left+'px';tooltip.style.top=Math.max(46,pointBox.top-chartBox.top+16)+'px';
      };
      chart.addEventListener('pointerover',event=>{const point=event.target.closest('[data-channel-point]');if(point)showPoint(point)});
      chart.addEventListener('pointerleave',()=>{tooltip.hidden=true});
      chart.addEventListener('focusin',event=>{const point=event.target.closest('[data-channel-point]');if(point)showPoint(point)});
      chart.addEventListener('focusout',event=>{if(!event.relatedTarget?.closest('[data-channel-point]'))tooltip.hidden=true});
      chart.addEventListener('keydown',event=>{
        if(event.key==='Escape'){tooltip.hidden=true;return}
        const point=event.target.closest('[data-channel-point]');if(!point||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        event.preventDefault();const points=[...chart.querySelectorAll('[data-channel-point]')],index=points.indexOf(point),next=event.key==='Home'?0:event.key==='End'?points.length-1:Math.max(0,Math.min(points.length-1,index+(event.key==='ArrowRight'?1:-1)));
        points.forEach((item,slot)=>item.setAttribute('tabindex',slot===next?'0':'-1'));points[next]?.focus({preventScroll:true});points[next]?.scrollIntoView({block:'nearest',inline:'nearest'});
      });
    });
  }
  function renderStackedTrend(data){
    if(!data?.periods?.length)return '<div class="empty-image">图表Sheet暂无可绘制数据</div>';
    const originalImage=DATA.chart_assets?.[data.image_key];

    const trendLine=colors.blue,seriesFill=index=>stackedTrendPalette[index%stackedTrendPalette.length],periods=data.periods,series=data.series||[],totals=data.totals||[],maxTotal=chartMax(totals),labelMax=Math.max(...periods.map(period=>String(period||"").length),1),left=52,bottom=252,plotH=218,step=Math.max(42,Math.min(labelMax*4.8,90)),W=Math.max(380,periods.length*step+50),H=Math.max(310,bottom+Math.min(labelMax*4.2,80)+14),barW=stackedBarWidth(step);
    const annotations=trendAnnotationState.visible
      ? window.TrendAnnotations.render(trendAnnotationsFor(state.subject),periods,state.grain,{left,step,width:W})
      : {height:0,markup:""};
    if(!annotations.height&&window.CHART_RENDER_MODE==="original"&&originalImage)return `<div class="original-chart"><img src="${originalImage}" alt="${esc(data.headline||"Excel原始图表")}"/></div>`;
    const segmentLabelYs=periods.map(()=>[]);
    const bars=periods.map((period,index)=>{const rates=series.map(item=>Math.max(0,Number(item.values[index]||0))),stackHeight=rates.reduce((sum,rate)=>sum+rate,0)*plotH;let y=bottom-stackHeight;const stacks=series.map((item,sIndex)=>{const rate=rates[sIndex],height=rate*plotH,segmentY=y;y+=height;if(!rate)return "";const labelY=avoidLabelY(segmentY+height/2,segmentLabelYs[index],12,bottom-4,12);segmentLabelYs[index].push(labelY);return `<rect x="${left+index*step+(step-barW)/2}" y="${segmentY}" width="${barW}" height="${height}" fill="${seriesFill(sIndex)}"/><text class="chart-data-label stack-segment-label" x="${left+index*step+step/2}" y="${labelY}" text-anchor="middle">${(rate*100).toFixed(0)}%</text>`}).join("");const lx=left+index*step+step-2,ly=bottom+13;return `${stacks}<text x="${lx}" y="${ly}" text-anchor="end" transform="rotate(-40 ${lx} ${ly})" font-size="9" fill="#718396">${esc(period)}</text>`}).join("");
    const points=totals.map((value,index)=>`${left+index*step+step/2},${bottom-Number(value)/maxTotal*plotH}`).join(" ");
    const values=totals.map((value,index)=>{const baseY=bottom-Number(value)/maxTotal*plotH-8,labelY=avoidLabelY(baseY,segmentLabelYs[index],12,bottom-8);return `<text class="chart-data-label total-label" x="${left+index*step+step/2}" y="${labelY}" text-anchor="middle">${fmt(value)}</text>`}).join("");
    const legend=series.map((item,index)=>`<span><i style="background:${seriesFill(index)}"></i>${esc(item.name)}</span>`).join("")+`<span><i class="line-key"></i>总计</span>`;
    const height=H+annotations.height;
    return `<div class="stacked-chart"><svg viewBox="0 0 ${W} ${height}" style="width:${W}px;height:${height}px">${annotations.markup}<g transform="translate(0 ${annotations.height})"><line x1="${left}" y1="${bottom}" x2="${W-20}" y2="${bottom}" stroke="#e6ebf1"/>${bars}<polyline points="${points}" fill="none" stroke="${trendLine}" stroke-width="2.5"/>${values}</g></svg></div><div class="legend trend-legend">${legend}</div>`;
  }
  function renderTable(data){
    if(!data?.columns)return '<div class="empty-image">暂无表格数据</div>';
    const formats=data.formats||[];
    const bodyRows=data.rows.map(row=>`<tr>${row.map((value,index)=>`<td class="${formats[index]&&formats[index]!=="text"?"num":""}">${formatTableCell(value,formats[index])}</td>`).join("")}</tr>`).join("")||`<tr><td class="table-empty" colspan="${data.columns.length}">暂无数据</td></tr>`;
    return `<div class="table-wrap${data.scrollable?' is-scrollable':''}"><table class="data-table"><thead><tr>${data.columns.map((column,index)=>`<th class="${formats[index]&&formats[index]!=="text"?"num":""}">${esc(column)}</th>`).join("")}</tr></thead><tbody>${bodyRows}</tbody></table></div>`;
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
  function formatTableCell(value,type){if(["number","percent","signed_percent"].includes(type)&&(value==null||typeof value==="string"&&!value.trim()))return '—';const number=Number(value);if(type==="percent"&&Number.isFinite(number))return `${(number*100).toFixed(1)}%`;if(type==="signed_percent"&&Number.isFinite(number)){const result=number*100;return `<span class="change ${result>=0?"pos":"neg"}">${result>=0?"+":""}${result.toFixed(1)}%</span>`}if(type==="number"&&Number.isFinite(number))return number.toLocaleString("zh-CN",{maximumFractionDigits:1});return fmt(value)}
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
    const palette=Object.values(colors),rate=value=>Number.isFinite(value)?`${(value*100).toFixed(1)}%`:'—',quantity=value=>Number.isFinite(value)?fmt(value):'—';
    return `<div class="funnel"><div class="funnel-row head"><span>阶段</span><span>规模</span><span>数量</span><span>总占比</span><span>阶段转化</span><span>流失</span></div>${stages.map((stage,index)=>`<div class="funnel-row"><span>${esc(stage.label)}</span><div class="funnel-track">${Number.isFinite(stage.total_rate)?`<div class="funnel-fill" style="width:${Math.max(stage.total_rate*100,1)}%;background:${palette[index%palette.length]}">${rate(stage.total_rate)}</div>`:'<span title="数据缺失或分母为0">—</span>'}</div><b>${quantity(stage.value)}</b><b>${rate(stage.total_rate)}</b><b>${rate(stage.stage_rate)}</b><b>${quantity(stage.loss)}</b></div>`).join("")}</div>`}
  function renderCohortMatrix(cohorts){
    const columns=["大定批次",...cohorts[0].stages.slice(1).map(stage=>stage.label),"大定→锁单","锁单→交付"];
    const rows=cohorts.map(cohort=>[cohort.period,...cohort.stages.slice(1).map(stage=>stage.total_rate),cohort.order_to_lock_days,cohort.lock_to_delivery_days]);
    return `<div class="table-wrap"><table class="data-table"><thead><tr>${columns.map(column=>`<th>${esc(column)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map((value,index)=>index>0&&index<row.length-2?(Number.isFinite(value)?`<td class="heat-cell" style="background:rgba(39,133,232,${.05+Math.pow(value,1.6)*.7})">${(value*100).toFixed(1)}%</td>`:'<td title="数据缺失或分母为0">—</td>'):`<td>${index>=row.length-2?(Number.isFinite(value)?fmt(value)+"天":'—'):esc(value)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }
  function renderRankCards(cards,kind){const directional=kind==='rise'||kind==='drop',directionalClass=directional?` rank-grid-${kind}`:'';return `<div class="rank-grid${directionalClass}">${Object.entries(cards||{}).map(([name,entry])=>{const rows=Array.isArray(entry)?entry:entry.rows||[];if(!rows.length)return `<article class="rank-card"><h3>${esc(name)} · 暂无上榜车型</h3><p class="empty">${esc(entry.empty_reason||"暂无可比排名")}</p></article>`;const maxRate=Math.max(...rows.map(row=>Math.abs(Number(row.rate)||0)),0);return `<article class="rank-card"><h3>${esc(name)} · TOP${rows.length}</h3><ol>${rows.map(row=>{const meta=[row.rate!=null?`${(Number(row.rate)*100).toFixed(1)}%`:"",row.amount!=null?`${fmt(row.amount)}元`:""].filter(Boolean).join(" · ");if(!directional)return `<li><b>${row.rank}</b><span>${esc(row.label)}${meta?`<small>${esc(meta)}</small>`:""}</span></li>`;const rate=Number(row.rate),rateLabel=row.rate!=null&&Number.isFinite(rate)?`${(rate*100).toFixed(1)}%`:'—',width=maxRate>0&&Number.isFinite(rate)?Math.min(Math.abs(rate)/maxRate*100,100):0,amount=row.amount!=null?`${fmt(row.amount)}元`:'';return `<li><b class="rank-index">${row.rank}</b><span class="rank-name">${esc(row.label)}${amount?`<small>${esc(amount)}</small>`:''}</span><div class="rank-bar" aria-hidden="true"><i style="width:${width.toFixed(1)}%"></i></div><strong class="rank-rate">${rateLabel}</strong></li>`}).join("")}</ol></article>`}).join("")}</div>`}
  function renderRights(data){return `<div class="rights"><strong>权益金额 ${fmt(data.amount)} 元</strong><p>${esc(data.text)}</p></div>`}
  function renderFeeBandStructure(data){
    const bands=data?.bands||[],rows=data?.rows||[],palette=["#2859f5","#00C2FF","#00B578","#FFB020","#FF4D6D","#7C3AED","#ED7D31","#70AD47","#4472C4"];
    const legend=`<div class="legend fee-legend">${bands.map((band,index)=>`<span><i style="background:${palette[index%palette.length]}"></i>${esc(band)}</span>`).join("")}</div>`;
    const body=rows.map(row=>{const total=row.values.reduce((sum,value)=>sum+Number(value||0),0),denominator=total||1;return `<div class="fee-band-row"><label title="${esc(row.label)}">${esc(row.label)}</label><div class="fee-band-chart"><div class="fee-band-track">${row.values.map((value,index)=>{const share=Number(value||0)/denominator*100;return `<i style="width:${share}%;background:${palette[index%palette.length]}" title="${esc(bands[index])} ${share.toFixed(1)}%"></i>`}).join("")}</div><div class="segment-data-labels">${row.values.map((value,index)=>{const share=Number(value||0)/denominator*100;return `<span><i style="background:${palette[index%palette.length]}"></i>${share.toFixed(1)}%</span>`}).join("")}</div></div><b>${fmt(total)}单</b></div>`}).join("");
    return `${legend}<div class="fee-band-list">${body}</div>`;
  }
  function renderFeePeriodBands(data){
    const periods=data?.periods||[],series=data?.series||[],palette=[chartPalette.yellow,chartPalette.green,chartPalette.blue,chartPalette.violet,chartPalette.rose];
    const legend=`<div class="legend fee-legend">${series.map((item,index)=>`<span><i style="background:${palette[index%palette.length]}"></i>${esc(item.name)}</span>`).join("")}</div>`;
    const columns=periods.map((period,index)=>{const actual=Object.prototype.hasOwnProperty.call(data,'actual_totals')?data.actual_totals?.[index]:data.actual_total,amount=actual!==null&&actual!==undefined&&typeof actual!=='boolean'&&String(actual).trim()!==''&&Number.isFinite(Number(actual))?fmt(actual):'\u2014';const total=series.reduce((sum,item)=>sum+Number(item.values[index]||0),0)||1;return `<div class="fee-period-col"><div class="fee-period-stack">${series.map((item,sIndex)=>{const share=Number(item.values[index]||0)/total*100;return `<i style="height:${share}%;background:${palette[sIndex%palette.length]}" title="${esc(item.name)} ${share.toFixed(1)}%"><span>${share.toFixed(1)}%</span></i>`}).join("")}</div><b>${esc(period)}</b><small>实际金额总计 ${amount}元</small></div>`}).join("");
    return `${legend}<div class="fee-period-chart" style="--periods:${Math.max(periods.length,1)}">${columns}</div>`;
  }
  function renderFeeHeatmap(data){
    const periods=data?.periods||[],rows=data?.rows||[],columns=Math.max(periods.length,1);
    return `<div class="fee-heatmap"><div class="fee-heat-row" style="--cols:${columns}"><div class="heat-head">选配项</div>${periods.map(period=>`<div class="heat-head">${esc(period)}</div>`).join("")}</div>${rows.map(row=>`<div class="fee-heat-row" style="--cols:${columns}"><div class="heat-label" title="${esc(row.group)} · ${esc(row.label)}"><small>${esc(row.group)}</small>${esc(row.label)}</div>${periods.map((_,index)=>{const value=Number(row.values[index]||0);return `<div class="fee-heat-cell" style="background:rgba(22,119,255,${.08+Math.min(value,1)*.68})">${(value*100).toFixed(1)}%</div>`}).join("")}</div>`).join("")}</div>`;
  }
  function bindSkuHeatmaps(){
    document.querySelectorAll('[data-sku-scroll]').forEach(scroll=>{
      // Hidden combination tabs must wait until their first visible layout.
      // Initialize once so switching tabs does not reset a user's history view.
      if(scroll._skuHeatmapBound||!scroll.clientWidth)return;scroll._skuHeatmapBound=true;
      scroll.scrollLeft=scroll.scrollWidth;
      let drag=null;
      const stop=event=>{
        if(!drag||event.pointerId!==drag.id)return;
        const id=drag.id;drag=null;scroll.classList.remove('is-dragging');
        if(scroll.hasPointerCapture(id))scroll.releasePointerCapture(id);
      };
      scroll.addEventListener('pointerdown',event=>{
        if(event.pointerType!=='mouse'||event.button!==0||scroll.scrollWidth<=scroll.clientWidth+1)return;
        const box=scroll.getBoundingClientRect();
        if(event.clientY>=box.top+scroll.clientHeight||event.clientX>=box.left+scroll.clientWidth)return;
        drag={id:event.pointerId,x:event.clientX,left:scroll.scrollLeft};
        scroll.focus({preventScroll:true});scroll.classList.add('is-dragging');scroll.setPointerCapture(event.pointerId);event.preventDefault();
      });
      scroll.addEventListener('pointermove',event=>{
        if(!drag||event.pointerId!==drag.id)return;
        scroll.scrollLeft=drag.left+drag.x-event.clientX;event.preventDefault();
      });
      ['pointerup','pointercancel','lostpointercapture'].forEach(type=>scroll.addEventListener(type,stop));
      scroll.addEventListener('keydown',event=>{
        if(event.target!==scroll||event.altKey||event.ctrlKey||event.metaKey)return;
        const targets={ArrowLeft:scroll.scrollLeft-75,ArrowRight:scroll.scrollLeft+75,Home:0,End:scroll.scrollWidth};
        if(!Object.hasOwn(targets,event.key))return;
        scroll.scrollLeft=targets[event.key];event.preventDefault();
      });
    });
  }
  function renderSkuHeatmap(data){
    const periods=data?.periods||[],rows=data?.rows||[],columns=Math.max(periods.length,1);
    return `<div class="sku-heatmap-scroll" data-sku-scroll tabindex="0" role="region" aria-label="SKU累计锁单占比历史表，首列固定，可左右拖动或使用左右方向键查看全部周期"><div class="heatmap sku-heatmap"><div class="heatmap-row" style="--cols:${columns}"><div class="heat-head">累计锁单</div>${periods.map(p=>`<div class="heat-head" data-sku-period="${esc(p)}">${esc(p)}</div>`).join("")}</div>${rows.map(row=>`<div class="heatmap-row" style="--cols:${columns}"><div class="heat-label">${esc(row.label)}</div>${periods.map((_,index)=>{const raw=row.values[index];if(raw==null||!Number.isFinite(Number(raw)))return '<div title="该周期未提供累计锁单占比">—</div>';const value=Number(raw);return `<div style="background:rgba(0,181,120,${.12+value*.72})">${(value*100).toFixed(1)}%</div>`}).join("")}</div>`).join("")}</div></div>`;
  }
  function renderComboHeatmap(data){
    const periods=data?.periods||[],rows=data?.rows||[],index=Math.max(periods.length-1,0);
    return `<div class="combo-grid">${rows.map(row=>`<div class="combo-cell"><b>${esc(row.rank)}</b><br>${row.labels.map(esc).join(" × ")}<br><strong>${esc(periods[index]||"总计")} ${(Number(row.values[index]??row.total)*100).toFixed(1)}%</strong></div>`).join("")}</div>`;
  }
  function renderComboMatrix(data){
    const groups=data?.groups||[];
    if(!groups.length)return '<div class="empty-image">组合Sheet暂无可绘制数据</div>';
    const controls=`<div class="combo-controls" role="group" aria-label="配置组合维度">${groups.map((group,index)=>`<button data-combo-switch="${index}" class="${index===0?"active":""}" aria-pressed="${index===0}">${esc(group.name)}</button>`).join("")}</div>`;
    const panels=groups.map((group,groupIndex)=>{const columns=Math.max(group.periods.length,1);const rows=group.rows||[];return `<div class="combo-matrix-panel sku-heatmap-scroll" data-combo-panel="${groupIndex}" data-sku-scroll tabindex="0" role="region" aria-label="${esc(group.name)}配置组合历史表，可左右拖动或使用左右方向键查看全部周期" ${groupIndex?"hidden":""}><div class="combo-matrix-grid" style="--cols:${columns}"><div class="combo-matrix-head">组合</div>${group.periods.map(period=>`<div class="combo-matrix-head" data-sku-period="${esc(period)}">${esc(period)}</div>`).join("")}${rows.map(row=>`<div class="combo-matrix-label" title="${esc(row.rank)} · ${esc(row.label)}"><b>${esc(row.rank)}</b><span>${esc(row.label)}</span></div>${row.values.map(value=>{if(value==null||!Number.isFinite(Number(value)))return '<div class="combo-matrix-cell" title="该周期未提供配置组合占比">—</div>';const number=Number(value),alpha=.04+Math.min(number,1)*.6;return `<div class="combo-matrix-cell" style="background:rgba(0,181,120,${alpha.toFixed(2)})"><b>${(number*100).toFixed(1)}%</b></div>`}).join("")}`).join("")}</div></div>`}).join("");
    return `<div class="combo-matrix">${controls}${panels}</div>`;
  }
  function renderTailDistribution(rows){return renderColumns(rows||[],colors.purple)}
  function renderLaunch(data){
    if(!data?.periods?.length)return '<div class="empty-image">暂无首销期节奏数据</div>';
    const known=rhythmKnown,periods=data.periods,metrics=data.metrics,dailyBig=metrics["当日大定数量"]||[],small=metrics["当日小订转大数量"]||metrics["当日小订转大定数量"]||[];
    const direct=metrics["当日直接大定数量"]||dailyBig.map((value,index)=>known(value)&&known(small[index])?value-small[index]:null),unit=data.grain==='week'?'当周':'当日';
    const smallRate=metrics["累计小订转化率"]||metrics["累计小转大率"]||null,bigRate=metrics["累计直接大定占比"]||null;
    const rows=periods.map((label,index)=>{
      const total=known(small[index])&&known(direct[index])?small[index]+direct[index]:null;
      return {label,total,values:{small:small[index],direct:direct[index]},rates:{smallRate:smallRate?.[index],bigRate:bigRate?.[index]},tooltip:known(total)?`${label} · ${unit}直接大定 ${fmt(direct[index])} · ${unit}小订转大 ${fmt(small[index])} · 来源合计 ${fmt(total)}`:`${label} · ${unit}来源数据尚未更新或不完整，不按0绘制`};
    });
    const lines=[];
    if(Array.isArray(smallRate)&&smallRate.length)lines.push({key:'smallRate',label:'累计小转大率（累计小转大÷总小订）',color:'#A65300',textColor:'#A65300',digits:1});
    if(Array.isArray(bigRate)&&bigRate.length)lines.push({key:'bigRate',label:'累计直接大定占比',color:'#200036',textColor:'#200036',digits:1});
    return renderRhythmChart({kind:'launch-day',title:`首销期${unit}订单来源`,rows,maxValue:chartMax(rows.map(row=>row.total)),series:[{key:'small',label:unit+'小订转大',color:colors.green},{key:'direct',label:unit+'直接大定',color:colors.blue}],lines:[]})+renderLaunchRateTrends(rows,lines);
  }
  function renderSmallOrderRhythm(rows){
    if(!rows?.length)return '<div class="empty-image">暂无小订期节奏数据</div>';
    const data=rows.map(row=>{
      const total=Math.max(Number(row.orders||0),0),retained=Math.max(Number(row.retained||0),0),cancel=Math.max(Number(row.cancel||0),0),retention=Number(row.retention_rate||0);
      return {label:row.period,total,values:{retained,cancel},rates:{retention},tooltip:`${row.period} · 订单 ${fmt(total)} · 留存小订 ${fmt(retained)} · 退订 ${fmt(cancel)} · 留存率 ${(retention*100).toFixed(0)}%`};
    });
    return renderRhythmChart({kind:'small-day',title:'小订期间订单、留存、退订与留存率趋势',rows:data,maxValue:chartMax(rows.flatMap(row=>[row.orders,row.retained,row.cancel])),series:[{key:'retained',label:'留存小订',color:colors.green},{key:'cancel',label:'退订',color:colors.coral}],lines:[{key:'retention',label:'留存率',color:'#0070C0',textColor:'#075fa8',digits:0}]});
  }
  function renderTrend(rows){return renderColumns(rows.map(row=>({label:row.period,value:row.daily||0})),colors.coral)}
  function renderDailyCancel(rows){
    if(!rows?.length)return '<div class="empty-image">暂无日度退订数据</div>';
    const data=rows.map(row=>{
      const small=Math.max(Number(row.daily||0),0),big=Math.max(Number(row.big_daily||0),0),small_rate=row.small_rate==null||row.small_rate===''?null:Number(row.small_rate),big_rate=row.big_rate==null||row.big_rate===''?null:Number(row.big_rate);
      const rateText=value=>rhythmKnown(value)?(value*100).toFixed(1)+'%':'—';
      return {label:row.period,total:small+big,values:{small,big},rates:{small_rate,big_rate},tooltip:`${row.period} · 当日小订退 ${fmt(small)} · 当日大定退 ${fmt(big)} · 退订合计 ${fmt(small+big)} · 小订退率 ${rateText(small_rate)} · 大定退率 ${rateText(big_rate)}`};
    });
    return renderRhythmChart({kind:'cancel-day',title:'日度退订与退订率趋势',rows:data,maxValue:chartMax(rows.map(row=>Number(row.daily||0)+Number(row.big_daily||0))),series:[{key:'small',label:'当日小订退',color:colors.coral},{key:'big',label:'当日大定退',color:colors.orange}],lines:[{key:'small_rate',label:'累计小订退率',color:'#0070C0',textColor:'#075fa8',digits:1},{key:'big_rate',label:'大定退率',color:colors.purple,textColor:'#6930bd',digits:1}]});
  }
  function renderHourlyChart(rows,day){
    const filtered=day==="总计"?(rows||[]):(rows||[]).filter(row=>String(row.period||"")===day);
    const grouped=new Map();filtered.forEach(row=>{const key=String(row.hour),item=grouped.get(key)||{hour:key,count:0,cancel:0};item.count+=Number(row.count||0);item.cancel+=Number(row.cancel||0);grouped.set(key,item)});
    const data=Array.from({length:24},(_,hour)=>grouped.get(String(hour))||{hour:String(hour),count:0,cancel:0});
    const points=data.map(row=>{
      const count=Number(row.count||0),cancel=Number(row.cancel||0),kept=Math.max(count-cancel,0);
      return {label:row.hour+'时',total:count,values:{kept,cancel},tips:{kept:`小订留存 ${fmt(kept)}`,cancel:`退订 ${fmt(cancel)} · 总计 ${fmt(count)}`},tooltip:`${row.hour}时 · 小订留存 ${fmt(kept)} · 退订 ${fmt(cancel)} · 总计 ${fmt(count)}`};
    });
    return renderRhythmChart({kind:'small-hour',title:'分时小订与退订节奏',rows:points,maxValue:chartMax(data.map(row=>row.count)),series:[{key:'kept',label:'留存小订',color:colors.green},{key:'cancel',label:'退订',color:colors.coral}]});
  }
  function renderHourly(rows){
    const days=[...new Set((rows||[]).map(row=>String(row.period||"")).filter(Boolean))];
    const options=["总计",...days].map(day=>`<option value="${esc(day)}">${esc(String(day).replace(/[ T]00:00:00$/, ""))}</option>`).join("");
    return `<div class="hourly-wrap"><div class="hourly-toolbar"><span>分时口径</span><select data-hourly-select aria-label="分时口径" data-hourly-rows="${esc(JSON.stringify(rows||[]))}">${options}</select></div><div data-hourly-body>${renderHourlyChart(rows,"总计")}</div></div>`;
  }
  function renderLaunchHourlyChart(rows,day){
    const filtered=day==="总计"?(rows||[]):(rows||[]).filter(row=>String(row.period||"")===day);
    const grouped=new Map();filtered.forEach(row=>{const key=String(row.hour),item=grouped.get(key)||{hour:key,orders:0,small:0,direct:0};item.orders+=Number(row.orders||0);item.small+=Number(row.small||0);item.direct+=Number(row.direct||0);grouped.set(key,item)});
    const data=Array.from({length:24},(_,hour)=>grouped.get(String(hour))||{hour:String(hour),orders:0,small:0,direct:0});
    const points=data.map(row=>{
      const orders=Number(row.orders||0),small=Number(row.small||0),direct=Number(row.direct||0);
      return {label:row.hour+'时',total:orders,values:{small,direct},tips:{small:`小订转大 ${fmt(small)}`,direct:`直接大定 ${fmt(direct)} · 总计 ${fmt(orders)}`},tooltip:`${row.hour}时 · 小订转大 ${fmt(small)} · 直接大定 ${fmt(direct)} · 总计 ${fmt(orders)}`};
    });
    return renderRhythmChart({kind:'launch-hour',title:'分时首销节奏',rows:points,maxValue:chartMax(data.map(row=>row.orders)),series:[{key:'small',label:'小订转大',color:colors.green},{key:'direct',label:'直接大定',color:colors.blue}]});
  }
  function renderLaunchHourly(rows){
    const days=[...new Set((rows||[]).map(row=>String(row.period||"")).filter(Boolean))];
    const options=["总计",...days].map(day=>`<option value="${esc(day)}">${esc(String(day).replace(/[ T]00:00:00$/, ""))}</option>`).join("");
    return `<div class="hourly-wrap"><div class="hourly-toolbar"><span>分时口径</span><select data-launch-hourly-select aria-label="分时口径" data-launch-hourly-rows="${esc(JSON.stringify(rows||[]))}">${options}</select></div><div data-launch-hourly-body>${renderLaunchHourlyChart(rows,"总计")}</div></div>`;
  }
  function renderColumns(rows,color){const known=row=>row.value!=null&&Number.isFinite(Number(row.value)),max=chartMax(rows.filter(known).map(row=>row.value));return `<div class="trend">${rows.map(row=>`<div class="trend-col"><i style="height:${known(row)?Number(row.value)/max*100:0}%;background:${color}"><b class="column-data-label"${known(row)?'':' title="该周期数据未提供"'}>${known(row)?fmt(row.value):"—"}</b></i><span>${esc(row.label)}</span></div>`).join("")}</div>`}
  function renderCancelCards(groups){return `<div class="cancel-grid">${groups.map((group,index)=>`<section class="structure-card"><h3>${esc(group.name)}</h3>${renderBars({color:["orange","coral","purple","blue","coral","green","orange"][index%7],rows:group.rows})}</section>`).join("")}</div>`}
  function renderUnknown(){return '<div class="empty-image">暂不支持该组件</div>'}

  let rawRowsCache=[],rawRowsKey=null,rawRenderRevision=0,rawSearchTimer=null;
  let pendingRawPage=null;
  const rawPageLimit=200;
  function rawParams(fileIndex=state.rawFile,sheetIndex=state.rawSheet,query=state.rawQuery,offset=state.rawOffset){return {file:fileIndex,sheet:sheetIndex,q:query,offset,limit:rawPageLimit}}
  async function loadRawRows(fileIndex,sheetIndex){
    const key=`${fileIndex}|${sheetIndex}`;
    if(rawRowsKey===key)return rawRowsCache;
    const b64=RAW_BLOCKS[key];
    return b64?((await decompressJson(b64)).rows||[]):[];
  }
  function visibleRawRows(rows,query){const header=rows.length?[rows[0]]:[];return[...header,...filterRawRows(rows.slice(1),query)]}
  async function renderRaw(){
    const revision=++rawRenderRevision,fileIndex=state.rawFile,sheetIndex=state.rawSheet,file=DATA.raw_files[fileIndex]||DATA.raw_files[0],sheet=file?.sheets[sheetIndex]||file?.sheets[0];
    clearTimeout(rawSearchTimer);
    if(DYNAMIC&&$('#rawSearch'))$('#rawSearch').disabled=true;
    const query=state.rawQuery,offset=state.rawOffset;
    let rows,result;
    try{
      if(DYNAMIC){result=pendingRawPage||await apiJson('raw',rawParams(fileIndex,sheetIndex,query,offset));pendingRawPage=null;rows=result.rows;}
      else rows=await loadRawRows(fileIndex,sheetIndex);
    }catch(error){
      if(revision!==rawRenderRevision||state.module!=='raw'||fileIndex!==state.rawFile||sheetIndex!==state.rawSheet)return;
      $('#page').innerHTML=`<div class="empty-page" role="alert"><p>${esc(error.message)}</p><button type="button" data-raw-retry>重新加载底表</button></div>`;
      $('[data-raw-retry]').onclick=()=>renderRaw();return;
    }
    if(revision!==rawRenderRevision||state.module!=="raw"||fileIndex!==state.rawFile||sheetIndex!==state.rawSheet)return;
    // Commit export data only with the matching visible sheet. A stale async
    // read must not replace the current page's cache after its revision check.
    rawRowsCache=rows;rawRowsKey=`${fileIndex}|${sheetIndex}`;
    let visibleRows=DYNAMIC?rows:visibleRawRows(rows,state.rawQuery);
    $("#page").innerHTML=`<div class="raw-layout"><label class="raw-file-picker"><span>选择底表文件</span><select id="rawFile" aria-label="选择底表文件">${DATA.raw_files.map((item,index)=>`<option value="${index}"${index===state.rawFile?" selected":""}>${esc(item.name)}</option>`).join("")}</select></label><aside class="file-list">${DATA.raw_files.map((item,index)=>`<button data-file="${index}" class="${index===state.rawFile?"active":""}" title="${esc(item.name)}">${esc(item.name)}</button>`).join("")}</aside><section class="raw-main"><div class="raw-toolbar"><div class="raw-title"><strong>${esc(file?.name||"")}</strong><small>${sheet?.total_rows||0} 行 × ${sheet?.total_cols||0} 列 · <span id="rawMatchCount" role="status" aria-live="polite">${DYNAMIC?result.total:Math.max(visibleRows.length-1,0)} 条数据（不含表头）</span> · 横向滚动查看其余列</small></div><label><span>Sheet</span><select id="rawSheet">${(file?.sheets||[]).map((item,index)=>`<option value="${index}">${esc(item.name)}</option>`).join("")}</select></label><label><span>表内搜索</span><input id="rawSearch" type="search" value="${esc(state.rawQuery)}" placeholder="在当前 Sheet 中搜索" aria-controls="rawTable" aria-describedby="rawMatchCount"></label><button type="button" id="clearRawSearch" ${state.rawQuery?"":"disabled"}>清空搜索</button><div class="raw-freeze-controls" role="group" aria-label="锁窗格"><label class="raw-freeze-toggle"><input id="rawFreezeRow" type="checkbox" ${state.rawFreezeRow?"checked":""}><span>锁定首行</span></label><label class="raw-freeze-toggle" title="只锁定第一列；与锁定标题列互斥"><input id="rawFreezeFirstColumn" type="checkbox" ${state.rawFreezeFirstColumn?"checked":""}><span>锁定首列</span></label><label class="raw-freeze-toggle" title="自动锁定左侧连续的文字标题列；与锁定首列互斥"><input id="rawFreezeColumn" type="checkbox" ${state.rawFreezeColumn?"checked":""}><span>锁定标题列</span></label></div><button class="export-button" id="exportRaw">导出当前数据</button><button type="button" class="export-button" id="exportRawWorkbook" ${file?.workbook_key?'':'disabled'} title="${file?.workbook_key?'导出该文件的全部 Sheet，保留原文件格式，不受搜索影响':'原始 Excel 文件不可用，请重新生成看板'}">导出整个 Excel</button></div><div class="raw-table ${state.rawFreezeRow?"freeze-row":""} ${state.rawFreezeColumn||state.rawFreezeFirstColumn?"freeze-column":""}" id="rawTable">${renderRawTable(visibleRows)}</div>${DYNAMIC?`<nav class="raw-pagination" aria-label="底表分页"><button type="button" id="rawPrevious">上一页</button><span id="rawPageInfo" role="status"></span><button type="button" id="rawNext">下一页</button></nav>`:""}<div class="raw-empty" id="rawEmpty" ${visibleRows.length>1?"hidden":""}><strong>没有匹配的数据</strong><p>请尝试其他关键词，或清空搜索查看当前 Sheet。</p></div></section></div>`;
    document.querySelectorAll("[data-file]").forEach(button=>button.onclick=async()=>{state.rawFile=Number(button.dataset.file);state.rawSheet=0;state.rawQuery="";state.rawOffset=0;await renderRaw();syncUrl('push')});
    $("#rawFile").onchange=async event=>{state.rawFile=Number(event.target.value);state.rawSheet=0;state.rawQuery="";state.rawOffset=0;await renderRaw();syncUrl('push')};
    $("#rawSheet").value=state.rawSheet;$("#rawSheet").onchange=async event=>{state.rawSheet=Number(event.target.value);state.rawQuery="";state.rawOffset=0;await renderRaw();syncUrl('push')};
    applyRawFrozenColumns(visibleRows);
    const rawRoot=$('#rawTable');
    function pagination(){
      if(!DYNAMIC)return;
      $('#rawPrevious').disabled=state.rawOffset<=0;
      $('#rawNext').disabled=state.rawOffset+rawPageLimit>=result.total;
      $('#rawPageInfo').textContent=`${Math.floor(state.rawOffset/rawPageLimit)+1} / ${Math.max(1,Math.ceil(result.total/rawPageLimit))}`;
    }
    let searchRevision=0;
    function updateRawSearch(){
      const filtered=visibleRawRows(rows,state.rawQuery);visibleRows=filtered;
      $('#rawTable').innerHTML=renderRawTable(filtered);$('#rawMatchCount').textContent=`${Math.max(filtered.length-1,0)} 条数据（不含表头）`;
      $('#rawEmpty').hidden=filtered.length>1;$('#clearRawSearch').disabled=!state.rawQuery;applyRawFrozenColumns(filtered);
    }
    async function fetchRawPage(revision){
      const query=state.rawQuery,offset=state.rawOffset;
      const current=()=>rawRoot.isConnected&&state.module==='raw'&&state.rawFile===fileIndex&&state.rawSheet===sheetIndex&&revision===searchRevision;
      if(!current())return;
      rawRoot.setAttribute('aria-busy','true');$('#exportRaw').disabled=true;$('#rawPrevious').disabled=true;$('#rawNext').disabled=true;
      try{
        const next=await apiJson('raw',rawParams(fileIndex,sheetIndex,query,offset));
        if(!current()||query!==state.rawQuery||offset!==state.rawOffset)return;
        result=next;rows=next.rows;visibleRows=rows;rawRowsCache=rows;$('#exportRaw').disabled=false;
        rawRoot.innerHTML=renderRawTable(rows);rawRoot.scrollTop=0;
        $('#rawMatchCount').textContent=`${next.total} 条数据（不含表头）`;$('#rawEmpty').hidden=next.total>0;
        $('#rawSearchError')?.remove();applyRawFrozenColumns(rows);pagination();syncUrl('replace');
      }catch(error){
        if(!current())return;
        rawRoot.replaceChildren();$('#rawMatchCount').textContent='加载失败';$('#rawEmpty').hidden=true;
        let node=$('#rawSearchError');if(!node){node=document.createElement('div');node.id='rawSearchError';node.className='raw-search-error';node.setAttribute('role','alert');rawRoot.before(node);}
        const message=document.createElement('span'),retry=document.createElement('button');message.textContent=error.message;retry.type='button';retry.textContent='重试';retry.onclick=()=>fetchRawPage(++searchRevision);node.replaceChildren(message,retry);
      }finally{if(current())rawRoot.setAttribute('aria-busy','false');}
    }
    function search(debounce=true){
      state.rawOffset=0;$('#clearRawSearch').disabled=!state.rawQuery;syncUrl('replace');
      if(!DYNAMIC){updateRawSearch();return;}
      $('#exportRaw').disabled=true;
      const revision=++searchRevision;clearTimeout(rawSearchTimer);
      rawSearchTimer=setTimeout(()=>fetchRawPage(revision),debounce?220:0);
    }
    $('#rawSearch').oninput=event=>{state.rawQuery=event.target.value;search()};
    $('#clearRawSearch').onclick=()=>{state.rawQuery='';$('#rawSearch').value='';search(false);$('#rawSearch').focus()};
    if(DYNAMIC){
      pagination();
      $('#rawPrevious').onclick=()=>{state.rawOffset=Math.max(0,state.rawOffset-rawPageLimit);fetchRawPage(++searchRevision)};
      $('#rawNext').onclick=()=>{state.rawOffset+=rawPageLimit;fetchRawPage(++searchRevision)};
    }
    $("#rawFreezeRow").onchange=event=>{state.rawFreezeRow=event.target.checked;$("#rawTable").classList.toggle("freeze-row",state.rawFreezeRow)};
    $("#rawFreezeColumn").onchange=event=>{state.rawFreezeColumn=event.target.checked;if(state.rawFreezeColumn)state.rawFreezeFirstColumn=false;$("#rawFreezeFirstColumn").checked=state.rawFreezeFirstColumn;applyRawFrozenColumns(DYNAMIC?visibleRows:visibleRawRows(rows,state.rawQuery))};
    $("#rawFreezeFirstColumn").onchange=event=>{state.rawFreezeFirstColumn=event.target.checked;if(state.rawFreezeFirstColumn)state.rawFreezeColumn=false;$("#rawFreezeColumn").checked=state.rawFreezeColumn;applyRawFrozenColumns(DYNAMIC?visibleRows:visibleRawRows(rows,state.rawQuery))};
    $("#exportRaw").onclick=event=>exportRaw(file,sheet,event?.currentTarget);
    $("#exportRawWorkbook").onclick=event=>exportRawWorkbook(file,event.currentTarget);
  }
  function filterRawRows(rows,query){const keyword=(query||"").trim().toLowerCase();return keyword?rows.filter(row=>row.some(value=>String(value??"").toLowerCase().includes(keyword))):rows}
  function rawCellIsData(value){
    if(typeof value==="number")return Number.isFinite(value);
    const text=String(value??"").trim();
    if(!text)return false;
    return /^(?:[¥￥$€£]\s*)?[-+]?(?:\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?%?$/.test(text)||/^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+.*)?$/.test(text)||/^\d{1,2}:\d{2}(?::\d{2})?$/.test(text);
  }
  function rawTableWidth(rows){return rows.reduce((width,row)=>Math.max(width,row.length),0)}
  function rawTitleColumnCount(rows){
    const width=rawTableWidth(rows),body=rows.slice(1,101);let count=0;
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
    const revision=root._rawFreezeRevision=(root._rawFreezeRevision||0)+1;
    root.classList.toggle("freeze-column",state.rawFreezeColumn||state.rawFreezeFirstColumn);
    root.querySelectorAll(".raw-frozen-column,.raw-frozen-edge").forEach(cell=>{cell.classList.remove("raw-frozen-column","raw-frozen-edge");cell.style.removeProperty("left")});
    if(!state.rawFreezeColumn&&!state.rawFreezeFirstColumn)return;
    const count=state.rawFreezeFirstColumn?Math.min(1,rawTableWidth(rows)):rawTitleColumnCount(rows);if(!count)return;
    requestAnimationFrame(()=>{
      if(!root.isConnected||root!==$("#rawTable")||root._rawFreezeRevision!==revision)return;
      let left=0;
      for(let col=0;col<count;col+=1){
        const cells=[...root.querySelectorAll(`[data-raw-col="${col}"]`)],measure=cells[0];if(!measure)break;
        cells.forEach(cell=>{cell.classList.add("raw-frozen-column");cell.style.left=`${left}px`;if(col===count-1)cell.classList.add("raw-frozen-edge")});
        left+=measure.getBoundingClientRect().width;
      }
    });
  }
  function renderRawTable(rows){const width=rawTableWidth(rows);return `<table class="data-table"><tbody>${rows.map((row,index)=>`<tr>${Array.from({length:width},(_,col)=>{const cell=row[col]??"";const title=String(cell)!==""?` title="${esc(cell)}"`:"";return `<${index===0?"th":"td"} data-raw-col="${col}"${title}>${fmt(cell)}</${index===0?"th":"td"}>`}).join("")}</tr>`).join("")}</tbody></table>`}
  async function exportRaw(file,sheet,button){
    if(DYNAMIC){
      button.disabled=true;
      try{
        const response=await apiRequest('export/csv',rawParams()),blob=await response.blob();
        const base=(file?.name||'底表').replace(/\.xlsx?$/i,'').replace(/[\\/:*?"<>|]/g,'_');
        downloadBlob(blob,`${base}_${(sheet?.name||'Sheet').replace(/[\\/:*?"<>|]/g,'_')}.csv`);showToast('已导出筛选结果');
      }catch(error){showToast(error.message)}finally{button.disabled=false}
      return;
    }
    const rows=visibleRawRows(rawRowsCache,state.rawQuery),csv="\ufeff"+rows.map(row=>row.map(csvCell).join(",")).join("\r\n"),blob=new Blob([csv],{type:"text/csv;charset=utf-8"}),base=(file?.name||"底表").replace(/\.xlsx?$/i,"").replace(/[\\/:*?\"<>|]/g,"_");
    downloadBlob(blob,`${base}_${(sheet?.name||"Sheet").replace(/[\\/:*?\"<>|]/g,"_")}.csv`);showToast(`已导出 ${rows.length} 行 CSV`);
  }
  async function exportRawWorkbook(file,button){
    button.disabled=true;button.textContent='正在导出…';
    try{
      if(DYNAMIC){const response=await apiRequest('workbook',{file:state.rawFile});downloadBlob(await response.blob(),file.name);showToast('已导出整个 Excel，包含全部 Sheet');return;}
      const b64=RAW_BLOCKS[file?.workbook_key];
      if(!b64)throw new Error('整表文件不可用');
      // Yield before decoding so the loading state is painted. Chunking avoids
      // allocating another full-size binary string for a large workbook.
      await new Promise(resolve=>setTimeout(resolve,0));
      const chunks=[];
      for(let offset=0;offset<b64.length;offset+=65536){
        const binary=atob(b64.slice(offset,offset+65536)),bytes=new Uint8Array(binary.length);
        for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
        chunks.push(bytes);
        if(offset&&offset%4194304===0)await new Promise(resolve=>setTimeout(resolve,0));
      }
      const blob=new Blob(chunks,{type:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
      downloadBlob(blob,(file.name||'底表.xlsx').replace(/[\\/:*?\"<>|]/g,'_'));
      showToast('已导出整个 Excel，包含全部 Sheet');
    }catch(error){showToast('整表导出失败：'+(error.message||'请重试'))}
    finally{button.disabled=false;button.textContent='导出整个 Excel'}
  }
  function downloadBlob(blob,name){
    const url=URL.createObjectURL(blob),link=document.createElement('a');
    try{link.href=url;link.download=name;document.body.appendChild(link);link.click()}
    finally{link.remove();setTimeout(()=>URL.revokeObjectURL(url),500)}
  }
  function csvCell(value){const text=String(value??"");return /[",\r\n]/.test(text)?`"${text.replace(/"/g,'""')}"`:text}
  async function jumpToSource(source){
    if(!source){showToast("当前看板没有独立来源");return}
    const fileIndex=DATA.raw_files.findIndex(item=>item.name===source.file);if(fileIndex<0){showToast("未找到对应底表文件");return}
    const sheetIndex=DATA.raw_files[fileIndex].sheets.findIndex(item=>item.name===source.sheet||item.source_sheet===source.sheet);state.module="raw";state.rawFile=fileIndex;state.rawSheet=Math.max(sheetIndex,0);state.rawQuery="";state.rawOffset=0;await renderAll();syncUrl("push");$("#rawSearch")?.focus({preventScroll:true});$("#page")?.scrollTo({top:0,behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});showToast(`已定位到 ${source.sheet}；浏览器后退可返回分析`)
  }
  function showToast(message){const node=$("#toast");if(!node)return;node.textContent=message;node.classList.add("show");clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>node.classList.remove("show"),4000)}
  let syncBusy=false, interactionRevision=0, lastInteraction=0;
  for(const event of ['click','input','change'])document.addEventListener(event,()=>{interactionRevision++;lastInteraction=performance.now()},true);
  function syncBlocked(){
    return document.hidden||$('#trendAnnotationEditor')?.open||$('#page')?.getAttribute('aria-busy')==='true'
      ||Boolean(document.activeElement?.matches('input,textarea')&&performance.now()-lastInteraction<1500);
  }
  function setSyncStatus(message){
    const node=$('#syncStatus');if(!node)return;
    node.textContent=message;node.hidden=!message;
  }
  async function synchronizeDataset(){
    if(!DYNAMIC||syncBusy||document.hidden)return;
    syncBusy=true;
    try{
      const status=await apiJson('sync');
      setSyncStatus(status.error?'更新失败，当前显示上次数据':'');
      if(!status.dataset_id||status.dataset_id===DATA.dataset_id||syncBlocked())return;
      const original=DATA,previousState=JSON.stringify(state),interaction=interactionRevision;
      const catalog=await apiJson('catalog');
      if(catalog.dataset_id===DATA.dataset_id)return;
      const nextState={...state};
      const nextSubject=catalog.subjects.find(item=>item.id===state.subject)||catalog.subjects[0];
      if(!nextSubject)throw new Error('新数据没有可用主体');
      nextState.subject=nextSubject.id;
      if(!nextSubject.modules.includes(nextState.module))nextState.module=nextSubject.modules[0]||'raw';
      const fileName=DATA.raw_files[state.rawFile]?.name,sheetName=DATA.raw_files[state.rawFile]?.sheets[state.rawSheet]?.name;
      nextState.rawFile=Math.max(0,catalog.raw_files.findIndex(item=>item.name===fileName));
      nextState.rawSheet=Math.max(0,catalog.raw_files[nextState.rawFile]?.sheets.findIndex(item=>item.name===sheetName)??0);
      let board,raw;
      if(nextState.module==='raw'){
        const params={dataset:catalog.dataset_id,file:nextState.rawFile,sheet:nextState.rawSheet,q:nextState.rawQuery,offset:nextState.rawOffset,limit:rawPageLimit};
        raw=await apiJson('raw',params);
        if(params.offset>=raw.total&&params.offset>0){nextState.rawOffset=Math.max(0,Math.ceil(raw.total/rawPageLimit)-1)*rawPageLimit;raw=await apiJson('raw',{...params,offset:nextState.rawOffset});}
      }else{
        board=unpackDashboard(await apiJson('dashboard',{dataset:catalog.dataset_id,subject:nextState.subject,module:nextState.module}));
      }
      // Prepare the complete visible view before changing version. Never erase
      // a usable view because a new request failed or the reader navigated.
      if(DATA!==original||JSON.stringify(state)!==previousState||interactionRevision!==interaction||syncBlocked())return;
      const page=$('#page'),top=page.scrollTop,table=$('#rawTable'),tableTop=table?.scrollTop,tableLeft=table?.scrollLeft;
      const hourly=[...page.querySelectorAll('[data-hourly-select],[data-launch-hourly-select]')].map(node=>node.value);
      const combos=[...page.querySelectorAll('.combo-matrix')].map(node=>node.querySelector('[data-combo-switch].active')?.dataset.comboSwitch);
      ++navigationRevision;++pageRevision;++rawRenderRevision;ensureState.revision=(ensureState.revision||0)+1;
      clearTimeout(rawSearchTimer);rawRowsCache=[];rawRowsKey=null;
      for(const key of Object.keys(boardCache))delete boardCache[key];
      DATA=catalog;window.DASHBOARD_DATA=DATA;moduleLabels=DATA.config.module_labels;
      window.CHART_RENDER_MODE=DATA.config.chart_render_mode||'generated';
      Object.assign(state,nextState);pendingRawPage=raw||null;
      if(board)boardCache[`${DATA.dataset_id}|${state.subject}|${state.module}`]=Promise.resolve(board);
      if(await ensureState()!==false){
        await renderAll();
        page.querySelectorAll('[data-hourly-select],[data-launch-hourly-select]').forEach((node,index)=>{if([...node.options].some(option=>option.value===hourly[index])){node.value=hourly[index];node.dispatchEvent(new Event('change'));}});
        page.querySelectorAll('.combo-matrix').forEach((node,index)=>{[...node.querySelectorAll('[data-combo-switch]')].find(button=>button.dataset.comboSwitch===combos[index])?.click();});
        page.scrollTop=top;const nextTable=$('#rawTable');if(nextTable){nextTable.scrollTop=tableTop||0;nextTable.scrollLeft=tableLeft||0;}
        syncUrl('replace');
      }
    }catch(error){setSyncStatus('同步暂不可用，当前显示上次数据');}
    finally{syncBusy=false;}
  }
  await init();
  if(DYNAMIC){
    const refresh=()=>refreshSharedAnnotations().catch(()=>{});
    refresh();
    setInterval(()=>{if(!document.hidden)refresh()},30000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
    window.addEventListener('focus',refresh);
    setInterval(synchronizeDataset,15000);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)synchronizeDataset()});
    window.addEventListener('focus',synchronizeDataset);
    $('#trendAnnotationEditor')?.addEventListener('close',synchronizeDataset);
    synchronizeDataset();
  }
})().catch(error=>{
  const page=document.querySelector('#page');if(!page)return;
  const message=document.createElement('p'),button=document.createElement('button');
  message.textContent=error.message;button.textContent='重新加载';button.type='button';button.onclick=()=>location.reload();
  page.setAttribute('role','alert');page.replaceChildren(message,button);
});
