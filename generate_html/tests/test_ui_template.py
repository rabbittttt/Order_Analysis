from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from core.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class DashboardTemplateTests(unittest.TestCase):
    def test_reused_number_formatter_preserves_existing_display(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        script = (ROOT / 'templates/dashboard.js').read_text(encoding='utf-8')
        formatter = script[script.index('  const displayText ='):script.index('  const colors =')]
        checks = r'''
const assert=require('assert');
const values=[0,-0,NaN,Infinity,-Infinity,1.05,-1.05,1234567.89,Number.MAX_VALUE,Number.MIN_VALUE];
for(let i=-1000;i<=1000;i++)values.push(i/13);
for(const value of values)assert.strictEqual(fmt(value),value.toLocaleString('zh-CN',{maximumFractionDigits:1}));
assert.strictEqual(fmt('<净大定>'),'&lt;留存大定&gt;');
assert.strictEqual(fmt(null),'');
'''
        subprocess.run([node, '-e', formatter + checks], check=True, capture_output=True)

    def test_sku_unknown_values_are_distinct_from_real_zero(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable")
        script = (ROOT / "templates/dashboard.js").read_text(encoding="utf-8")
        runtime = script[script.index("  const displayText ="):script.index("  const RHYTHM_LAYOUT=")]
        runtime += script[script.index("  function renderSkuHeatmap("):script.index("  function renderComboHeatmap(")]
        runtime += script[script.index("  function renderComboMatrix("):script.index("  function renderColumns(")]
        runtime += script[script.index("  function renderColumns("):script.index("  function renderCancelCards(")]
        checks = r'''
const assert=require('assert'),values=[null,0,.25,NaN,Infinity,undefined],original=[...values],periods=values.map((_,index)=>'W'+index);
const data={groups:[{name:'外饰组合',periods,rows:[{rank:'TOP1',label:'黑色',values}]}]},matrix=renderComboMatrix(data);
const cells=[...matrix.matchAll(/<div class="combo-matrix-cell"([^>]*)>(.*?)<\/div>/g)];
assert.equal(cells.length,values.length);
assert.deepEqual(cells.map(cell=>cell[2].replace(/<[^>]*>/g,'')),['—','0.0%','25.0%','—','—','—']);
for(const index of [0,3,4,5])assert(!cells[index][1].includes('background'),'unknown ratio must not receive a numeric heat color');
assert(cells[1][1].includes('background'),'real zero remains a known heatmap value');
const heat=renderSkuHeatmap({periods,rows:[{label:'TOP1',values}]});
assert.equal((heat.match(/>—<\/div>/g)||[]).length,4);assert(heat.includes('>0.0%</div>'));
const tailRows=[{label:'未知',value:null},{label:'真实零',value:0},{label:'已知',value:5},{label:'非有限',value:Infinity}],tail=renderTailDistribution(tailRows);
assert.deepEqual([...tail.matchAll(/class="column-data-label"[^>]*>([^<]*)<\/b>/g)].map(match=>match[1]),['—','0','5','—']);
const positiveHeight=html=>[...html.matchAll(/height:([\d.]+)%/g)].map(match=>Number(match[1])).filter(height=>height>0);
assert.deepEqual(positiveHeight(tail),positiveHeight(renderTailDistribution([{label:'已知',value:5}])),'unknown counts must not alter the numeric scale');
assert.deepEqual(values,original);assert.equal(tailRows[0].value,null);assert.equal(tailRows[1].value,0);
assert(!matrix.includes('NaN')&&!matrix.includes('Infinity')&&!tail.includes('NaN')&&!tail.includes('Infinity'));
'''
        subprocess.run([node, "-e", runtime + checks], check=True, capture_output=True)

    @staticmethod
    def rhythm_runtime():
        script = (ROOT / "templates/dashboard.js").read_text(encoding="utf-8")
        helpers = script[script.index("  const displayText ="):script.index("  function avoidLabelY(")]
        adapters = script[script.index("  function renderLaunch(data){"):script.index("  function renderColumns(rows,color){")]
        return helpers + adapters

    def test_launch_chart_keeps_blank_gaps_and_real_zero(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        data = "{periods:['D1','D2','D3','D4'],metrics:{'当日小订转大定数量':[20,null,40,0],'当日直接大定数量':[60,null,160,0],'累计小订转大定数量':[999,999,999,999],'累计直接大定数量':[9999,9999,9999,9999],'累计小订转化率':[.1,null,.2,0]}}"
        result = subprocess.run([node, '-e', self.rhythm_runtime() + 'process.stdout.write(renderLaunch(' + data + '));'],
                                text=True, encoding='utf-8', capture_output=True, check=True)
        self.assertEqual(result.stdout.count('<circle'), 3)
        self.assertEqual(result.stdout.count('<rect data-rhythm-bar='), 6)
        self.assertIn('>0</text>', result.stdout)
        self.assertIn('尚未更新或不完整', result.stdout)
        self.assertIn('D3 · 当日直接大定 160 · 当日小订转大 40 · 来源合计 200', result.stdout)
        self.assertIn('累计小转大率（累计小转大÷总小订）', result.stdout)
        self.assertIn('>20.0%</text>', result.stdout)
        self.assertNotIn('>999</text>', result.stdout)
        self.assertNotIn('>9999</text>', result.stdout)
        path = re.search(r'<path[^>]*\bd="([^"]*)"', result.stdout)[1]
        self.assertEqual(path.count('M'), 2)
        self.assertEqual(path.count('L'), 1)
        self.assertNotIn('NaN', result.stdout)

    def test_launch_sources_only_use_current_period_and_do_not_fill_unknown_with_zero(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        checks = r'''
const assert=require('assert');
const metrics={'当日大定数量':[100,50,30],'当日小订转大数量':[40,null,10]},original=JSON.stringify(metrics);
const html=renderLaunch({periods:['D1','D2','D3'],metrics});
assert(html.includes('D1 · 当日直接大定 60 · 当日小订转大 40 · 来源合计 100'));
assert(html.includes('D3 · 当日直接大定 20 · 当日小订转大 10 · 来源合计 30'));
assert.equal((html.match(/<rect data-rhythm-bar=/g)||[]).length,4);
assert.equal((html.match(/<title>[^<]*尚未更新或不完整/g)||[]).length,1);
assert.equal(JSON.stringify(metrics),original,'display renderer must not change metrics');
for(const missing of [{'累计直接大定数量':[100],'累计小订转大数量':[40]}, {'当日大定数量':[100]}]){
 const unavailable=renderLaunch({periods:['D1'],metrics:missing});
 assert(!unavailable.includes('<rect data-rhythm-bar='));assert(unavailable.includes('尚未更新或不完整'));
}
const week=renderLaunch({periods:['W1','W2','W3'],metrics,grain:'week'});
assert(week.includes('当周直接大定'));assert(!week.includes('当日'));assert(!week.includes('累计直接大定</span>'));
const rates=renderLaunch({periods:['D1','D2'],metrics:{'当日小订转大数量':[10,10],'当日直接大定数量':[30,20],'累计小订转化率':[.1,.2],'累计直接大定占比':[.75,50/70],'累计直接大定进度':[.6,1]}});
assert(rates.includes('>20.0%</text>'));assert(rates.includes('71.4%'));assert(!rates.includes('100.0%'));
assert(rates.includes('D2 · 当日直接大定 20 · 当日小订转大 10 · 来源合计 30'));
'''
        subprocess.run([node, '-e', self.rhythm_runtime() + checks], check=True, capture_output=True)

    def test_rhythm_charts_use_shared_compact_presentation(self):
        script = (ROOT / "templates/dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates/dashboard.css").read_text(encoding="utf-8")
        adapters = script[script.index('  function renderLaunch(data){'):script.index('  function renderColumns(rows,color){')]
        self.assertEqual(adapters.count('return renderRhythmChart('), 5)
        self.assertNotIn('<svg', adapters)
        self.assertNotIn('<rect', adapters)
        self.assertNotIn('hourlyPlotHeight', script)
        self.assertNotIn('rhythmLineLabelY', script)
        self.assertIn('bindRhythmCharts();', script)
        self.assertIn('rhythmObserver?.disconnect()', script)
        self.assertNotIn('.hourly-bars', css)
        self.assertNotIn('.hourly-chart', css)
        self.assertNotIn('.rhythm-hourly-chart', css)
        self.assertNotIn('.launch-chart', css)
        self.assertNotIn('rhythm-label-background', script + css)
        self.assertNotIn('rhythm-grid-line', script + css)
        self.assertEqual(css.count('.rhythm-chart {'), 1)
        self.assertIn('height:var(--rhythm-frame-height)', css)
        self.assertIn('overflow-x:auto', css)

    def test_rhythm_geometry_is_fixed_pixel_and_labels_cannot_drift(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        checks = r'''
const assert=require('assert');
for(const count of [1,14,24,100])for(const width of [320,768,1440]){
 const g=rhythmGeometry(count,width);assert.equal(g.barWidth,28);assert.equal(g.height,224);assert.equal(g.frameHeight,240);
 assert.equal(g.plotHeight,160);assert.equal(g.step,40);assert.equal(g.left,g.right);
 assert.equal(g.width,60+count*40,'wide screens must not stretch the column gaps');
}
const point={x:100,y:100},geometry=rhythmGeometry(2,500),occupied=[],points=[point],original=JSON.stringify([occupied,points]);
const placed=rhythmLineLabel(point,'40.0%',occupied,points,[],geometry);
assert(placed&&Math.abs(placed.y-point.y)<=24);assert.equal(JSON.stringify([occupied,points]),original);
const completed={x:100,y:geometry.top};
assert(rhythmLineLabel(completed,'100.0%',[],[completed],[],geometry),'100% endpoint needs space above the plot');
assert.equal(rhythmLineLabel(point,'40.0%',[{left:0,right:500,top:0,bottom:260}],points,[],geometry),null,'hide instead of moving away from its point');
const close=renderDailyCancel(Array.from({length:14},(_,i)=>({period:'D'+(i+1),daily:10,big_daily:10,small_rate:.06,big_rate:.02})));
const labelled=[...close.matchAll(/data-rhythm-label="line"[^>]*data-series="([^"]+)"/g)].map(match=>match[1]);
assert.equal(labelled.filter(key=>key==='small_rate').length,14);assert.equal(labelled.filter(key=>key==='big_rate').length,14,'nearby curves must retain every label');
const scenarios=[[0,0],[1,1],[.5,.5],[.06,.02],[.00001,.0001],[null,0],['0','0.7'],[undefined,''],['invalid',null]];
for(const values of scenarios){
 const rows=Array.from({length:100},(_,i)=>({period:'D'+(i+1),daily:i%3?10:0,big_daily:i%2?10:0,small_rate:values[0],big_rate:values[1]})),before=JSON.stringify(rows),html=renderDailyCancel(rows);
 const known=values.filter(value=>value!=null&&value!==''&&Number.isFinite(Number(value))).length,nonzero=values.filter(value=>value!=null&&value!==''&&Number.isFinite(Number(value))&&Number(value)!==0).length;
 assert.equal((html.match(/data-rhythm-point=/g)||[]).length,100*known);
 assert.equal((html.match(/data-rhythm-label="line"/g)||[]).length,100*nonzero,'only exact-zero rates omit labels; rounded nonzero rates retain labels');
 assert.equal(JSON.stringify(rows),before,'display must not modify source values');
}
const missing=renderDailyCancel([{period:'D1',daily:1,big_daily:2,small_rate:null,big_rate:0},{period:'D2',daily:1,big_daily:2,small_rate:.1,big_rate:null},{period:'D3',daily:1,big_daily:2,small_rate:null,big_rate:1}]);
assert(missing.includes('小订退率 — · 大定退率 0.0%'));
assert.equal((missing.match(/data-rhythm-label="line"/g)||[]).length,2);
assert.equal((missing.match(/>0.0%<\/text>/g)||[]).length,0);
const rounded=renderDailyCancel([{period:'D1',daily:1,big_daily:2,small_rate:.00001,big_rate:0}]);
assert.equal((rounded.match(/>0.0%<\/text>/g)||[]).length,1,'a nonzero value rounded to 0.0% must stay visible');
const other=renderSmallOrderRhythm([{period:'D1',orders:10,retained:0,cancel:10,retention_rate:0}]);
assert.equal((other.match(/data-rhythm-label="line"/g)||[]).length,1,'other rhythm charts retain their zero labels');
'''
        subprocess.run([node, '-e', self.rhythm_runtime() + checks], check=True, capture_output=True)

    def test_rhythm_line_labels_keep_series_colors_over_bars(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        checks = r'''
const assert=require('assert');
const spec={title:'color',rows:[{label:'D1',total:100,values:{bar:100},rates:{rate:.5}}],maxValue:120,series:[{key:'bar',label:'bar',color:'#1677FF'}],lines:[{key:'rate',label:'rate',color:'#00B578',textColor:'#102238',digits:1}]};
const html=renderRhythmSvg(spec,320),lineLabel=html.match(/<text class="rhythm-value-label rhythm-line-label"[^>]*>/)?.[0];
assert(lineLabel,'line percentage label should render');
assert(lineLabel.includes('data-series="rate"'));
assert(lineLabel.includes('fill:#00B578'),'line label must use its series color');
assert(!lineLabel.includes('fill:#102238'),'bar overlap must not neutralize line label color');
'''
        subprocess.run([node, '-e', self.rhythm_runtime() + checks], check=True, capture_output=True)

    def test_rhythm_preserves_every_total_before_allocating_rate_labels(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable')
        checks = r'''
const assert=require('assert');
const rows=Array.from({length:24},(_,i)=>({label:'2026-10-'+String(i+1).padStart(2,'0'),total:i===0?null:i*35,values:{orders:i*35},rates:{rate:i/24}}));
const spec={title:'test',rows,maxValue:chartMax(rows.map(row=>row.total)),series:[{key:'orders',label:'orders',color:'#1677ff'}],lines:[{key:'rate',label:'rate',color:'#0070c0'}]},before=JSON.stringify(spec);
for(const width of [320,768,1440,1920]){
 const html=renderRhythmSvg(spec,width),labels=[...html.matchAll(/data-rhythm-label="total" data-index="(\d+)"[^>]*>([^<]*)<\/text>/g)];
 assert.equal(labels.length,24,'every column has its total, even beside a rate curve');
 labels.forEach((match,index)=>{assert.equal(Number(match[1]),index);assert.equal(match[2],index===0?'—':fmt(index*35));});
 assert(!html.includes('rhythm-label-background')&&!html.includes('rhythm-grid-line'));
 assert(html.includes('>10-01<title>2026-10-01</title>'),'short axis date preserves full date');
}
assert.equal(JSON.stringify(spec),before);
assert.equal(rhythmAxisText('D1'),'D1');assert.equal(rhythmAxisText('23时'),'23时');
const larger=rhythmLabelBox('12345',50,50,10),smaller=rhythmLabelBox('12345',50,50,9);
assert(smaller.right-smaller.left<larger.right-larger.left,'collision measurement must honor the smaller font');
'''
        subprocess.run([node, '-e', self.rhythm_runtime() + checks], check=True, capture_output=True)

    def test_rhythm_labels_avoid_points_and_keep_hourly_tooltip_values(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable")
        checks = r'''
const assert=require('assert');
const smallRows=[{period:'D1',hour:'0',count:1,cancel:0},{period:'D1',hour:'19',count:10000,cancel:1},{period:'D2',hour:'0',count:2,cancel:1}],before=JSON.stringify(smallRows);
const smallHtml=renderHourlyChart(smallRows,'总计');
assert.equal((smallHtml.match(/data-rhythm-row=/g)||[]).length,24);
assert(smallHtml.includes('小订留存 9,999')&&smallHtml.includes('退订 1 · 总计 10,000'));
assert(smallHtml.includes('退订 1 · 总计 3'));
assert(!renderHourlyChart(smallRows,'D1').includes('总计 3</title>'));
assert.equal(JSON.stringify(smallRows),before);
const launchHtml=renderLaunchHourlyChart([{period:'D1',hour:'19',orders:10000,small:9999,direct:1}],'D1');
assert.equal((launchHtml.match(/data-rhythm-row=/g)||[]).length,24);
assert(launchHtml.includes('小订转大 9,999')&&launchHtml.includes('直接大定 1 · 总计 10,000'));
assert(!/data-rhythm-label="segment"[^>]*>1<\/text>/.test(launchHtml),'too-small segment cannot force a label outside the bar');
'''
        subprocess.run([node, "-e", self.rhythm_runtime() + checks], check=True, capture_output=True)

    def test_day_period_selector_uses_chronological_order(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        sorter = script[script.index("function sortPeriods"):script.index("async function renderFilters")]
        self.assertIn("return pa-pb;", sorter)
        self.assertNotIn("return pb-pa;", sorter)

    def test_runtime_logs_use_a_flat_timestamped_generate_html_file(self):
        main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('log_dir = output_dir / "log"', main)
        self.assertIn('log_dir.mkdir(parents=True, exist_ok=True)', main)
        self.assertIn('strftime("%Y%m%d_%H%M%S")', main)
        self.assertIn('f"generate_html_{timestamp}.log"', main)
        self.assertNotIn('output_dir / "generation.log"', main)
        self.assertNotIn('write_text("\\n".join(warnings)', main)
        self.assertIn('legacy_warning_file.unlink()', main)

    def test_raw_table_supports_freezing_first_row_and_title_columns(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn("rawFreezeRow:true,rawFreezeColumn:false,rawFreezeFirstColumn:true", script)
        self.assertIn('aria-label="锁窗格"', script)
        self.assertIn('id="rawFreezeRow"', script)
        self.assertIn('id="rawFreezeColumn"', script)
        self.assertIn('id="rawFreezeFirstColumn"', script)
        self.assertIn("锁定标题列", script)
        self.assertIn('classList.toggle("freeze-row",state.rawFreezeRow)', script)
        self.assertIn('classList.toggle("freeze-column",state.rawFreezeColumn||state.rawFreezeFirstColumn)', script)
        self.assertIn("function rawCellIsData(value)", script)
        self.assertIn("function rawTitleColumnCount(rows)", script)
        self.assertIn("function applyRawFrozenColumns(rows)", script)
        self.assertIn('data-raw-col="${col}"', script)
        self.assertIn("applyRawFrozenColumns(filtered)", script)
        self.assertIn(".raw-table.freeze-row .data-table th", css)
        self.assertIn(".raw-table.freeze-column .data-table .raw-frozen-column", css)
        self.assertIn(".raw-table.freeze-row.freeze-column .data-table th.raw-frozen-column", css)
        node = shutil.which("node")
        if not node:
            self.skipTest("Node unavailable")
        runtime = script[script.index("  function rawCellIsData"):script.index("  function renderRawTable")]
        checks = r'''
const assert=require('assert'),state={rawFreezeColumn:true,rawFreezeFirstColumn:false},frames=[];
const classes=()=>({values:new Set(),add(...names){names.forEach(name=>this.values.add(name))},remove(...names){names.forEach(name=>this.values.delete(name))},toggle(name,on){on?this.values.add(name):this.values.delete(name)}});
const cells=Array.from({length:4},(_,col)=>({col,classList:classes(),style:{removeProperty(name){delete this[name]}},getBoundingClientRect(){return {width:100}}}));
const root={isConnected:true,classList:classes(),querySelectorAll(selector){return selector.startsWith('[data-raw-col=')?cells.filter(cell=>cell.col===Number(selector.match(/"(\d+)"/)[1])):cells.filter(cell=>cell.classList.values.has('raw-frozen-column'))}};
const $=()=>root,requestAnimationFrame=callback=>frames.push(callback),flush=()=>{while(frames.length)frames.shift()()},frozen=()=>cells.filter(cell=>cell.classList.values.has('raw-frozen-column')).map(cell=>cell.col);
const rows=[['品牌','车型','数量','占比'],['问界','M9',12,.5]],before=JSON.stringify(rows);
applyRawFrozenColumns(rows);flush();assert.deepEqual(frozen(),[0,1],'title mode preserves multiple title columns');
state.rawFreezeColumn=false;state.rawFreezeFirstColumn=true;applyRawFrozenColumns(rows);flush();assert.deepEqual(frozen(),[0]);
applyRawFrozenColumns([['编号','名称'],[1,'门店']]);flush();assert.deepEqual(frozen(),[0],'first column freezes even when numeric');
state.rawFreezeColumn=true;state.rawFreezeFirstColumn=false;applyRawFrozenColumns(rows);
state.rawFreezeColumn=false;state.rawFreezeFirstColumn=true;applyRawFrozenColumns(rows);flush();assert.deepEqual(frozen(),[0],'stale animation frame must not restore title columns');
applyRawFrozenColumns(rows);state.rawFreezeFirstColumn=false;applyRawFrozenColumns(rows);flush();assert.deepEqual(frozen(),[],'turning off before paint stays off');
state.rawFreezeFirstColumn=true;applyRawFrozenColumns([]);flush();assert.deepEqual(frozen(),[],'empty tables are safe');
assert.equal(JSON.stringify(rows),before,'freezing does not modify cell values');
'''
        subprocess.run([node, "-e", runtime + checks], check=True, capture_output=True)



    def test_filters_are_the_last_control_group_in_the_topbar(self):
        template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        topbar = template.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
        self.assertIn('class="topbar-main"', topbar)
        self.assertIn('<section class="filters" id="filters"', topbar)
        self.assertLess(topbar.index('class="top-actions"'), topbar.index('id="filters"'))
        self.assertIn('id="quickGenerationList"', topbar)
        self.assertGreater(topbar.index('id="quickGenerations"'), topbar.index('</section>'))
        self.assertIn("latestQuickGenerations", script)
        self.assertIn("syncTopbarQuickLayout", script)
        self.assertIn("quick-generation-wrapped", script)
        self.assertIn("generationShortName", script)
        self.assertIn('data-quick-generation', script)
        self.assertIn("replace(/\\s+Ultimate\\b/ig,'U')", script)
        self.assertIn("replace(/\\s+典藏大观\\b/g,'大观')", script)
        self.assertIn("const generationAggregate=name=>", script)
        self.assertIn("const candidates=DATA.subjects.filter(item=>item.type==='generation')", script)
        self.assertIn("yearLabel=year?` ${String(year).slice(-2)}`:''", script)
        self.assertIn(".quick-generation-list", css)
        self.assertIn(".topbar.quick-generation-wrapped>.quick-generation-filter", css)
        self.assertIn("flex-wrap:wrap", css)
        self.assertNotIn("overflow-x:auto", css[css.index(".quick-generation-list"):css.index(".quick-generation-button")])
        module_bar = template.split('<aside class="module-bar">', 1)[1].split("</aside>", 1)[0]
        self.assertNotIn('id="filters"', module_bar)

    def test_topbar_keeps_generated_time_and_compacts_small_screen_filters(self):
        template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        topbar = template.split('<header class="topbar">', 1)[1].split("</header>", 1)[0]
        self.assertIn('id="updatedAt"', topbar)
        self.assertIn('select id="subjectSelect" aria-label="分析主体"', topbar)
        self.assertIn('id="grainSelect"', topbar)
        self.assertIn('select id="periodSelect" aria-label="分析周期"', topbar)
        self.assertIn('$("#updatedAt").textContent=', script)
        self.assertIn(".topbar .top-actions #updatedAt {\n  display:inline-flex;", css)
        self.assertIn(".topbar .top-actions>span { display:inline-flex; }", css)
        self.assertIn(".topbar-end {\n    display:grid;\n    grid-template-columns:auto minmax(0,1fr);", css)
        self.assertIn(".topbar .filters {\n    width:auto;\n    flex:none;\n    min-width:0;\n    grid-template-columns:minmax(0,1.2fr) 140px minmax(100px,1fr);", css)
        self.assertIn(".topbar .filters {\n    width:100%;\n    grid-template-columns:140px minmax(0,1fr);", css)
        self.assertIn(".topbar .filters select { height:32px; padding:0 7px; font-size:11px; }", css)
        self.assertIn(".topbar .top-actions { display:flex; min-width:0; max-width:100%; }", css)
        self.assertIn(".topbar .filters label,.topbar .filters .filter-group { min-width:0; }", css)
        self.assertIn(".topbar .filters select { width:100%; min-width:0; max-width:100%; }", css)
        self.assertIn("grid-template-columns:minmax(0,1.2fr) 140px minmax(100px,1fr);", css)
        self.assertIn("grid-template-columns:140px minmax(0,1fr);", css)
        self.assertNotIn(".topbar .top-actions #updatedAt {\n    display:none;", css)
        self.assertNotIn(".topbar .top-actions {\n    display:none;", css)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for quick-generation filtering")
    def test_quick_generations_hide_special_and_outdated_variants(self):
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "quick_generations.cjs")],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_temporal_modules_keep_static_time_filter_placeholders(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('$("#grainSelect").closest(".filter-group").style.display=""', script)
        self.assertNotIn('$("#grainSelect").closest("label")', script)
        self.assertIn('["generic","raw"].includes(state.module)', script)
        self.assertIn("Object.entries(DATA.config.grain_labels)", script)
        self.assertIn("按所选表格范围", script)
        self.assertIn('period.disabled=true', script)
        self.assertIn('$("#periodSelect").disabled=false', script)
        self.assertIn(".topbar .filters select:disabled", css)
        self.assertIn("cursor:not-allowed", css)

    def test_navigation_is_a_single_left_sidebar(self):
        template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('<div class="app-shell">', template)
        self.assertIn('<aside class="module-bar">', template)
        self.assertIn("grid-template-columns:120px minmax(0,1fr)", css)
        self.assertIn("grid-template-columns:minmax(0,1fr)", css)
        self.assertIn("flex-direction:column", css)
        self.assertIn("flex:1 1 0", css)

    def test_brand_logo_is_embedded_as_an_accessible_decorative_image(self):
        template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn('class="brand-mark" src="__BRAND_LOGO__" alt="" aria-hidden="true"', template)
        self.assertTrue((ROOT / "templates" / "brand-logo.png").exists())

    def test_config_supports_either_chart_source_and_requested_module_order(self):
        config = load_config(ROOT / "config.json")
        self.assertIn(config["chart_render_mode"], {"original", "generated"})
        self.assertEqual(config["chart_render_mode"], "generated")
        self.assertLess(
            config["module_order"].index("cancellation"),
            config["module_order"].index("launch_rhythm"),
        )

    def test_generated_chart_renderers_include_visible_data_labels(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('class="rhythm-value-label rhythm-', script)
        self.assertIn('data-rhythm-label', script)
        self.assertIn("segment-data-labels", script)
        self.assertIn("column-data-label", script)
        self.assertIn("data-rhythm-bar", script)
        self.assertIn("data-launch-hourly-select", script)
        self.assertIn("renderLaunchHourlyChart", script)
        self.assertIn('<span>分时口径</span><select data-hourly-select', script)
        self.assertIn('<span>分时口径</span><select data-launch-hourly-select', script)
        self.assertIn('["总计",...days]', script)
        self.assertIn('replace(/[ T]00:00:00$/, "")', script)

    def test_pie_charts_show_direct_percentage_labels(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        renderer = script[script.index("function renderPieChart"):script.index("function renderStructureCards")]
        self.assertIn("const sliceLabels=source.map", renderer)
        self.assertIn('class="pie-slice-label"', renderer)
        self.assertIn("percent.toFixed(1)", renderer)
        self.assertIn(".pie-slice-label", css)
        self.assertIn("dominant-baseline:middle", css)
        self.assertIn("donut:renderPieChart", script)
        self.assertIn('aria-label="占比圆环图"', renderer)

    def test_chart_labels_use_requested_colors_without_halo(self):
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        label = re.search(r"\.chart-data-label\s*\{([^}]*)\}", css, re.S)
        on_color = re.search(r"\.chart-data-label\.on-color\s*\{([^}]*)\}", css, re.S)
        total = re.search(r"\.chart-data-label\.total-label\s*\{([^}]*)\}", css, re.S)
        self.assertIsNotNone(label)
        self.assertIsNotNone(on_color)
        self.assertIsNotNone(total)
        self.assertIn("fill:#334155", label.group(1))
        self.assertIn("stroke:none", label.group(1))
        self.assertNotIn("paint-order", label.group(1))
        self.assertIn("fill:#334155", on_color.group(1))
        self.assertIn("fill:#C00000", total.group(1))
        self.assertNotRegex(script, r'class="chart-data-label[^\n>]*"[^>]*\sfill=')

    def test_chart_labels_have_headroom_and_collision_avoidance(self):
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("const LABEL_SCALE_HEADROOM=1.18", script)
        self.assertIn("function avoidLabelY", script)
        self.assertIn("maxValue:chartMax(data.map(row=>row.count))", script)
        self.assertIn("maxValue:chartMax(data.map(row=>row.orders))", script)
        self.assertIn("lineLabelMaxOffset:24", script)
        self.assertIn("rhythmLabelClear(box,occupied,points,segments)", script)
        self.assertIn("color:var(--ink-2)", css)

    def test_stacked_trend_uses_requested_palette_in_series_order(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        palette = '["#FFF2CC","#E2F0D9","#C8E8E8","#A8D8EA","#A0C1E8","#DCC5ED","#F0C8C8","#F8D8B0"]'
        self.assertIn(f"const stackedTrendPalette={palette}", script)
        self.assertIn("seriesFill=index=>stackedTrendPalette[index%stackedTrendPalette.length]", script)
        self.assertNotRegex(script, r"seriesFill=.*增程")
        self.assertNotRegex(script, r"seriesFill=.*纯电")

    def test_stacked_trend_places_series_from_top_to_bottom(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("const rates=series.map(item=>Math.max(0,Number(item.values[index]||0)))", script)
        self.assertIn("let y=bottom-stackHeight", script)
        self.assertIn("segmentY=y;y+=height", script)
        self.assertIn('y="${segmentY}"', script)

    def test_stacked_trend_uses_plain_segment_labels_and_no_line_markers(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        renderer = script[script.index("function renderStackedTrend"):script.index("function renderTable")]
        self.assertIn('class="chart-data-label stack-segment-label"', renderer)
        self.assertIn('(rate*100).toFixed(0)', renderer)
        self.assertNotIn('(rate*100).toFixed(1)', renderer)
        self.assertIn("const stackedBarWidth=step=>Math.min(42,step*.58)", script)
        self.assertIn("barW=stackedBarWidth(step)", renderer)
        self.assertNotIn("<circle", renderer)
        segment_label = re.search(r"\.chart-data-label\.stack-segment-label\s*\{([^}]*)\}", css, re.S)
        self.assertIsNotNone(segment_label)
        self.assertIn("font-size:8px", segment_label.group(1))
        self.assertIn("font-weight:400", segment_label.group(1))
        self.assertIn("fill:#404040", segment_label.group(1))
        self.assertIn(".stacked-chart .chart-data-label {\n  font-size:10px;", css)
        self.assertIn(".stacked-chart .chart-data-label.stack-segment-label {\n  font-size:9px;", css)

    def test_overview_stacked_trends_default_to_latest_period(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("function alignOverviewChartScrollbars()", script)
        self.assertIn('if(state.module!=="overview")return;', script)
        self.assertIn('document.querySelectorAll("#page .stacked-chart")', script)
        self.assertIn("chart.scrollLeft=Math.max(0,chart.scrollWidth-chart.clientWidth)", script)
        self.assertIn("requestAnimationFrame(align)", script)
        self.assertIn("alignOverviewChartScrollbars();", script)

    def test_svg_stacked_bars_use_square_corners(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        renderers = [
            ("function renderRhythmSvg", "function renderRhythmChart"),
            ("function renderStackedTrend", "function renderTable"),
            ("function renderLaunch", "function renderSmallOrderRhythm"),
            ("function renderSmallOrderRhythm", "function renderTrend"),
            ("function renderDailyCancel", "function renderHourlyChart"),
        ]
        for start, end in renderers:
            renderer = script[script.index(start):script.index(end)]
            self.assertNotRegex(renderer, r"<rect[^>]*\brx=", msg=f"rounded corner in {start}")




























    def test_history_tables_follow_the_top_grain_without_local_selector(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("const current=options[state.grain]?state.grain", script)
        self.assertNotIn("data-history-select", script)
        self.assertNotIn("history-toolbar", script)




    def test_raw_search_has_live_count_empty_state_and_mobile_picker(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('id="rawMatchCount" role="status" aria-live="polite"', script)
        self.assertIn('id="rawEmpty"', script)
        self.assertIn('id="clearRawSearch"', script)
        self.assertIn('id="rawFile" aria-label="选择底表文件"', script)
        self.assertIn("$('#rawEmpty').hidden=filtered.length>1", script)
        self.assertIn("$('#rawEmpty').hidden=next.total>0", script)


    def test_navigation_discards_stale_pages_and_source_jump_preserves_back_path(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('revision!==pageRevision||moduleId!==state.module', script)
        self.assertIn('revision!==rawRenderRevision||state.module!=="raw"', script)
        source_jump = script.split('async function jumpToSource(source)', 1)[1].split('function showToast', 1)[0]
        self.assertIn('await renderAll();syncUrl("push")', source_jump)








if __name__ == "__main__":
    unittest.main()
