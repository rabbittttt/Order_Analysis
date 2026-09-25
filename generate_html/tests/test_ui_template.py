from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

from core.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class DashboardTemplateTests(unittest.TestCase):
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
        self.assertIn("rawFreezeRow:true,rawFreezeColumn:true", script)
        self.assertIn('aria-label="锁窗格"', script)
        self.assertIn('id="rawFreezeRow"', script)
        self.assertIn('id="rawFreezeColumn"', script)
        self.assertIn("锁定标题列", script)
        self.assertIn('classList.toggle("freeze-row",state.rawFreezeRow)', script)
        self.assertIn('classList.toggle("freeze-column",state.rawFreezeColumn)', script)
        self.assertIn("function rawCellIsData(value)", script)
        self.assertIn("function rawTitleColumnCount(rows)", script)
        self.assertIn("function applyRawFrozenColumns(rows)", script)
        self.assertIn('data-raw-col="${col}"', script)
        self.assertIn("applyRawFrozenColumns(filtered)", script)
        self.assertIn(".raw-table.freeze-row .data-table th", css)
        self.assertIn(".raw-table.freeze-column .data-table .raw-frozen-column", css)
        self.assertIn(".raw-table.freeze-row.freeze-column .data-table th.raw-frozen-column", css)

    def test_sales_forecast_has_three_lifecycle_stages(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('{id:"small",label:"小订预测"}', script)
        self.assertIn('{id:"launch",label:"首销预测"}', script)
        self.assertIn('{id:"steady",label:"平销预测"}', script)
        self.assertNotIn("data-forecast-stage-nav", script)
        self.assertNotIn("forecastNavExpanded", script)
        self.assertIn('data-forecast-stage-switch="${stage.id}"', script)
        self.assertIn('button.dataset.module===state.module', script)
        self.assertIn('请选择具体车型（代际）后查看', script)
        self.assertNotIn('class="module-subnav"', script)
        self.assertNotIn('class="forecast-lifecycle-tabs"', script)
        self.assertIn('if(target?.stage==="ended")return "steady"', script)
        self.assertIn('if(target?.stage==="active")return "launch"', script)
        self.assertIn('if(target?.stage==="before")return "small"', script)
        self.assertIn("state.forecastStageAuto=false", script)
        self.assertIn("activateForecastStage(button.dataset.forecastStageSwitch)", script)
        self.assertIn("const root=document.querySelector('.forecast-workspace.forecast-v2');showForecastStageSummary(root,id);applyForecastView(root,state.forecastView||\"result\")", script)
        self.assertIn("setForecastStageSummary(root,'small',stageLabel,source.textContent)", script)
        self.assertIn("setForecastStageSummary(root,'launch',stageBadge,stageSource)", script)
        self.assertIn("setForecastStageSummary(root,'steady',stageLabel,sourceText)", script)
        self.assertIn("findStageActual(target.name,'before')", script)
        self.assertIn("transitionTotal||current?.total", script)
        self.assertIn("与首销未开始共用", script)
        self.assertNotIn("findStageActual(target.name,'ended')", script)
        self.assertIn("const targetSteady=target=>history.find", script)
        self.assertIn("actualWeeks=[...(own?.weeks||[])]", script)
        self.assertIn('data-forecast-current-day aria-live="polite"', script)
        self.assertNotIn("data-small-stage", script)
        self.assertNotIn("data-steady-stage", script)
        self.assertIn('class="forecast-tabs forecast-target-tabs"', script)
        self.assertLess(script.index('class="forecast-tabs forecast-target-tabs"'), script.index('class="forecast-target-sources"'))
        self.assertNotIn('class="forecast-tab-row"', script)
        self.assertIn('data-forecast-target="smallStartDate"', script)
        self.assertNotIn('data-forecast-target="weekday"', script)
        self.assertIn("function applyForecastView", script)
        self.assertIn("applyForecastView(root,state.forecastView||\"result\")", script)
        self.assertIn("const forecastDrafts=new Map()", script)
        self.assertIn("forecastDrafts.set(root._forecastSubjectId||state.subject", script)
        self.assertIn("window.addEventListener(\"popstate\"", script)
        self.assertIn('history[`${mode}State`]', script)
        self.assertIn("scheduleForecastUpdate", script)
        self.assertIn("scrollIntoView({block:'start'", script)
        self.assertIn("button.setAttribute('aria-controls',`${prefix}-pane-${button.dataset.forecastTab}`)", script)
        self.assertIn("平销预测指标 = 交车锁单", script)
        self.assertNotIn("平销期大定 = 平销期直接大定", script)
        self.assertIn("不再预测平销大定", script)
        self.assertIn("bindForecastLifecycleNavigation", script)
        self.assertIn("ArrowRight", script)
        self.assertIn(".module-bar .module-subnav", css)
        self.assertIn("box-shadow:none;", css[css.index(".module-bar .module-nav .module-subnav button.active"):css.index(".workspace", css.index(".module-bar .module-nav .module-subnav button.active"))])
        self.assertIn(".forecast-stage-pane.active", css)
        self.assertIn(".forecast-steady .forecast-lifecycle-kpis article{border-top-color:#2f7fd2}", css)
        self.assertIn(".forecast-steady .forecast-lifecycle-bars article.actual .forecast-lifecycle-bar i{background:#56a1e9}", css)
        self.assertIn(".forecast-target-meta{grid-column:1/-1;display:grid", css)
        self.assertIn("overflow:visible;padding-right:2px", css)
        self.assertIn("height:auto;\n  min-height:100%;\n  overflow:visible;", css)
        self.assertIn(".forecast-scroll-body{display:flex;flex:0 0 auto", css)
        self.assertIn(".page-workspace.forecast-page{\n  height:auto;", css)
        self.assertIn(".page-workspace.forecast-page>.page-workspace-body{\n  flex:0 0 auto;\n  overflow:visible;", css)
        self.assertIn("min-height:44px", css)

    def test_forecast_calendar_is_automatic(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertNotIn('data-forecast-allocation="holidays"', script)
        self.assertIn("adjustedWorkdays", script)
        self.assertIn("周末调休按工作日处理", script)

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

    def test_non_temporal_modules_keep_static_time_filter_placeholders(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('$("#grainSelect").closest(".filter-group").style.display=""', script)
        self.assertNotIn('$("#grainSelect").closest("label")', script)
        self.assertIn('["sales_forecast","generic","raw"].includes(state.module)', script)
        self.assertIn("Object.entries(DATA.config.grain_labels)", script)
        self.assertIn("按预测阶段窗口", script)
        self.assertIn("按所选表格范围", script)
        self.assertIn('$("#periodSelect").disabled=true', script)
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
        self.assertGreaterEqual(script.count("chart-data-label"), 8)
        self.assertIn("segment-data-labels", script)
        self.assertIn("column-data-label", script)
        self.assertIn("hourly-bars", script)
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
        self.assertGreaterEqual(script.count("avoidLabelY("), 5)
        self.assertIn("max=chartMax(data.map(row=>row.count))", script)
        self.assertIn("max=chartMax(data.map(row=>row.orders))", script)
        self.assertIn("padding:34px 12px 26px", css)
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
        self.assertGreaterEqual(script.count("bw=stackedBarWidth(step)"), 2)
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
            ("function renderStackedTrend", "function renderTable"),
            ("function renderLaunch", "function renderSmallOrderRhythm"),
            ("function renderSmallOrderRhythm", "function renderTrend"),
            ("function renderDailyCancel", "function renderHourlyChart"),
        ]
        for start, end in renderers:
            renderer = script[script.index(start):script.index(end)]
            self.assertNotRegex(renderer, r"<rect[^>]*\brx=", msg=f"rounded corner in {start}")

    def test_sales_forecast_uses_and_syncs_the_top_subject_selector(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('moduleId==="sales_forecast"', script)
        self.assertIn('?item.type==="generation"&&DATA.subjects.some', script)
        self.assertNotIn('state.module==="sales_forecast"&&item.type!=="generation"', script)
        self.assertIn('const workspace=state.module==="sales_forecast"?{...page.workspace,data:linkedForecastData(page.workspace.data)}', script)
        self.assertNotIn('data-forecast-target="name"', script)
        self.assertIn("const targetState=()=>{const name=data.target?.name||''", script)
        self.assertIn('$("#subjectSelect").onchange=async event=>{captureForecastDraft();state.subject=event.target.value;if(state.module==="sales_forecast")state.forecastStageAuto=true;await ensureState();await renderAll();syncUrl("push")}', script)
        self.assertIn('[["generation","预测代际"]]', script)

    def test_sales_forecast_vehicle_and_launch_settings_are_always_visible(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertNotIn('forecast-target-editor', script)
        self.assertIn('<div class="forecast-target-form">', script)
        self.assertIn('.forecast-workspace.forecast-v2 .forecast-target>.forecast-target-form{grid-template-columns:repeat(7', css)

    def test_sales_forecast_frontend_uses_backend_vehicle_mapping(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        self.assertIn("modelAliases=data.model_aliases||{}", script)
        self.assertIn("const forecastModelAliases=()=>", script)
        self.assertIn("forecastModelKey=(value,aliases=forecastModelAliases())", script)
        self.assertIn("sameForecastModel(a,b,modelAliases)", script)
        self.assertNotIn("const rawModelKey=value=>", script)
        self.assertIn("model_mapping = _read_model_mapping()", module)
        self.assertIn('"model_aliases": model_mapping', module)
        self.assertNotIn("问界|智界|享界|尊界|尚界", script.split("const rawForecastModelKey=", 1)[1].split(";", 1)[0])

    def test_sales_forecast_never_inherits_another_targets_parameters(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        linked = script.split("function linkedForecastData(data)", 1)[1].split("function linkedForecastSource", 1)[0]
        self.assertNotIn("original.total_small", linked)
        self.assertNotIn("original.conversion", linked)
        self.assertNotIn("original.direct_share", linked)
        self.assertIn("total_small:Number(option.small??0)", linked)

    def test_sales_forecast_separates_observable_structure_from_reference_completion(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        refresh = (ROOT / "tools" / "refresh_sales_forecast_data.py").read_text(encoding="utf-8")
        self.assertIn("结构、斜率和累计曲线只比较已经真实发生的部分", script)
        self.assertIn("参考车型同期小转大完成率", script)
        self.assertIn("不预先计算自身完成率", script)
        self.assertIn("D2可观测小转大斜率", script)
        self.assertIn("D2订单来源斜率", script)
        self.assertIn("早期退订质量", script)
        self.assertIn("D1小转大/D1大定", refresh)
        self.assertIn("D1+D2小转大/D1+D2大定", refresh)
        self.assertIn("未映射·暂按传播名", refresh)
        self.assertIn("不计算未知的当前车型自身完成率", module)
        self.assertIn("大定：${d1FieldSource('gross')}", script)
        self.assertIn("D1大定按阶段顺序逐字段回退后仍缺失", script)

    def test_sales_forecast_combines_progress_curves_and_uses_parameter_lines(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("参考确认后的小转大预测完成度", script)
        self.assertIn("参考确认后的直接大定预测完成度", script)
        self.assertIn("截至各日真实累计量÷方法一预测终局", script)
        self.assertIn("当前真实日不会提前归一到100%", script)
        self.assertIn("只有首销结束日达到100%", script)
        self.assertIn("const terminal=rows.reduce", script)
        self.assertIn("return terminal>0?running/terminal:null", script)
        self.assertIn("const rows=spec.observableShape?(comparison.progressRows||[]):(comparison.rows||[])", script)
        self.assertNotIn("renderCompletionMini", script)
        self.assertIn('aria-label="${title}折线图"', script)
        self.assertIn("方法二 · 小订转化率 by天", script)
        self.assertIn("方法二 · 直接大定占比 by天", script)
        self.assertIn("逐日累计小转大 ÷ 总小订", script)
        self.assertIn("逐日累计直接大定 ÷ 逐日累计总大定", script)

    def test_sales_forecast_attribute_dropdowns_only_use_vehicle_master_values(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        self.assertIn("const tierValues=[...new Set([target.tier,...(data.tiers||[])", script)
        self.assertIn("const nodeValues=[...new Set([target.launch_node,...(data.nodes||[])", script)
        self.assertNotIn("'标准发布','年度换代','年度改款','品牌首发','衍生款发布'", script)
        self.assertIn('"tiers": _master_values(model_master, "产品档位")', module)
        self.assertIn('"nodes": _master_values(model_master, "发布类型")', module)

    def test_sales_forecast_has_a_scoring_tab_backed_by_the_real_score_function(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('data-forecast-tab="score">预测打分</button>', script)
        self.assertIn('data-forecast-pane="score"', script)
        self.assertIn("const scoreSpecs=", script)
        self.assertIn("const renderScoreDashboard=target=>", script)
        self.assertIn("页面直接调用实际排序函数与同一份权重配置，不另算展示分", script)
        self.assertIn("part.value*part.weight/effectiveWeight*100", script)
        self.assertIn("单项相似度", script)
        self.assertIn("折算贡献", script)
        self.assertIn("const scoreRuleText=", script)
        self.assertIn("const scoreRuleFor=", script)
        self.assertIn("为什么这样打分", script)
        self.assertIn("相似度计算规则", script)
        self.assertIn("缺失处理", script)
        self.assertIn("实际对比、评分规则与贡献", script)
        self.assertIn('.forecast-pane[data-forecast-pane="score"].active', css)
        self.assertIn(".forecast-score-rule-box", css)
        self.assertIn(".forecast-score-detail-table th:nth-child(2),.forecast-score-detail-table td:nth-child(2){width:132px;min-width:132px;max-width:132px;white-space:normal;overflow-wrap:anywhere}", css)

    def test_small_and_steady_score_pages_explain_the_actual_ranking(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        self.assertIn("function renderLifecycleScorePage", script)
        self.assertIn("const smallScoreRules=", script)
        self.assertIn("smallReferenceScore(item,target,current,minimumEvidence)", script)
        self.assertIn("const steadyScoreRules=", script)
        self.assertIn("steadyReferenceScore(item,target,targetLaunch(target)||{},minimumEvidence)", script)
        self.assertIn("有效单项相似度之和", script)
        self.assertIn("实际对比、评分规则与贡献", script)
        self.assertIn("排序与本页明细直接调用同一个逐项评分结果", script)
        self.assertIn("主辅权重只影响后续预测加权，不反向改变候选车型得分", script)
        self.assertIn("产品档位、能源类型、发布类型和首销期大定到锁单率共同决定参考", script)
        self.assertIn("证据不足的车型仍可人工选择", script)
        self.assertIn("event_id||item.model", script)
        self.assertNotIn("小订转化率、小转大占比仅参与相似度", script)
        self.assertIn("基线优先本车型已有平销真实日", module)
        self.assertIn("所有平销KPI、图表、周合计和来源说明均为交车锁单口径", module)
        self.assertNotIn("最近2至4周稳健周均", module)

    def test_small_and_steady_evidence_use_the_prediction_curves(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn("function renderLifecycleLineChart", script)
        self.assertIn("data-small-reference-chart", script)
        self.assertIn("data-steady-reference-chart", script)
        self.assertIn("rebasedForecastCompletionCurve(item,field,days)", script)
        self.assertIn("const lockValues=item=>", script)
        self.assertIn("const recentRatio=item=>", script)
        self.assertIn("当前与主辅参考的平销交车锁单", script)
        self.assertIn("仅展示首销截止后完整自然周的交车锁单", script)
        self.assertIn(".forecast-lifecycle-reference-chart{grid-column:1/-1", css)
        self.assertIn(".forecast-lifecycle-line-scroll svg{height:300px}", css)

    def test_sales_forecast_result_layout_stays_expanded_and_uses_horizontal_space(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        scenarios = script.index('<div class="forecast-scenarios">')
        parameters = script.index('<aside class="forecast-parameter-rail">')
        charts = script.index('<div class="forecast-decision-grid">')
        common = script.index('<section class="forecast-common-controls">')
        scale = script.index('<section class="forecast-scale-check">')
        self.assertLess(scenarios, parameters)
        self.assertLess(parameters, charts)
        self.assertLess(charts, common)
        self.assertLess(common, scale)
        self.assertLess(charts, scale)
        self.assertIn(".forecast-workspace.forecast-v2 .forecast-control-grid{grid-column:1/-1;display:grid;grid-template-columns:repeat(2,minmax(0,1fr))", css)
        self.assertIn(".forecast-result-main>.forecast-common-controls{grid-column:1/-1", css)
        self.assertIn(".forecast-decision-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px", css)
        self.assertIn(".forecast-decision-card .forecast-svg-scroll svg{height:280px}", css)
        self.assertIn(".forecast-decision-card .forecast-decision-svg{width:100%;max-width:100%;min-width:0}", css)
        self.assertIn('class="forecast-decision-svg"', script)
        self.assertNotIn('class="forecast-decision-svg" viewBox="0 0 ${W} ${H}" style="width:${W}px"', script)
        self.assertIn("@media(max-width:1500px)", css)
        self.assertIn(".forecast-workspace.forecast-v2 .forecast-control-grid{grid-template-columns:repeat(2,minmax(0,1fr))}", css)
        self.assertIn(".forecast-workspace.forecast-v2 .forecast-control-grid{grid-template-columns:1fr}", css)
        self.assertNotIn('<details class="forecast-parameter-rail">', script)

    def test_forecast_stage_errors_are_top_aligned_and_bridge_controls_are_bottom_aligned(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        small = script[script.index("function renderSmallOrderWorkspace"):script.index("function renderSteadyWorkspace")]
        steady = script[script.index("function renderSteadyWorkspace"):script.index("function renderForecastWorkspaceV2")]
        launch = script[script.index("data-forecast-data-error"):script.index("data-forecast-pane=\"evidence\"")]
        self.assertLess(small.index('data-small-error'), small.index('id="small-forecast-pane-result"'))
        self.assertLess(steady.index('data-steady-error'), steady.index('id="steady-forecast-pane-result"'))
        self.assertLess(steady.index('data-steady-chart'), steady.index('data-forecast-import-anchor="steady"'))
        self.assertLess(steady.index('data-forecast-import-anchor="steady"'), steady.index("renderStageCommonControls('steady')"))
        self.assertLess(launch.index('data-forecast-data-error'), launch.index('id="forecast-pane-result"'))
        self.assertLess(launch.index('data-forecast-decision-chart="parameter"'), launch.index('data-forecast-import-anchor="launch"'))
        self.assertLess(launch.index('data-forecast-import-anchor="launch"'), launch.index('<section class="forecast-common-controls">'))
        self.assertLess(launch.index('data-forecast-allocation-note'), launch.index("renderBridgeControls('launch')"))
        self.assertLess(launch.index("renderBridgeControls('launch')"), launch.index('<section class="forecast-scale-check">'))

    def test_bridge_controls_use_a_compact_parameter_layout(self):
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("[data-bridge-stage] .forecast-day-allocation{margin-top:0;padding:8px 10px", css)
        self.assertIn("[data-bridge-stage] .forecast-allocation-inputs{grid-template-columns:repeat(3", css)
        self.assertIn("[data-bridge-stage]>label{display:grid;grid-template-columns:minmax(150px,.38fr)", css)
        self.assertIn(".forecast-common-controls [data-bridge-stage]{display:grid", css)
        self.assertIn("function renderStageCommonControls(stage)", script)
        self.assertIn("min-height:29px", css)

    def test_steady_missing_lock_days_cover_the_full_steady_period(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("expectedSteadyDates=steadyElapsedDays?Array.from", script)
        self.assertIn("const compactMissingRanges=dates=>", script)
        self.assertIn("平销开始以来已结束日锁单缺失或异常（共${missing.length}天）：${compactMissingRanges(missing)}", script)
        self.assertIn("steadyNotStarted=!!target.steadyStartDate&&target.steadyStartDate>today", script)
        self.assertIn("if(!message){", script)
        self.assertIn("const blocked=!!message", script)
        self.assertIn("平销尚未开始", script)
        self.assertNotIn("当前周已结束日锁单缺失或异常", script)

    def test_daily_base_curve_explanation_matches_allocation_logic(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        self.assertIn("首销每日大定相对D1（基础曲线）", script)
        self.assertIn("root._forecastDailyEvidence={adaptedDailyOrders,historicalFactor}", script)
        self.assertIn("root._forecastDailyEvidence.historicalFactor(item,day)", script)
        self.assertIn("root._forecastDailyEvidence.targetFactor=index=>", script)
        self.assertIn("D1=100%，用于未来余量的基础形状", script)
        self.assertIn("剔除原日期类型系数", module)
        self.assertIn("两种方法均用主辅加权后的基础曲线衔接前一真实日", module)

    def test_sales_forecast_evidence_uses_compact_reference_comparison_table(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn("参与打分参数", script)
        self.assertIn("当前 · ${esc(target.name)}", script)
        self.assertIn("主参考 · ${esc(name(selected[0],'未选择'))}", script)
        self.assertIn("辅助参考 · ${esc(name(selected[1],'未选择'))}", script)
        self.assertIn("单项打分", script)
        self.assertIn("综合得分", script)
        self.assertIn('<details class="forecast-ref-score-details"><summary>查看评分对比表</summary>', script)
        self.assertNotIn('<details class="forecast-ref-score-details" open>', script)
        self.assertIn(".forecast-ref-comparison table", css)
        self.assertIn(".forecast-ref-score-details>.forecast-ref-comparison", css)
        self.assertNotIn("reason.textContent=selected.length", script)

    def test_sales_forecast_score_explanations_match_the_components_used(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("D2小转大/D2大定", script)
        self.assertIn("D1小转大占前两日", script)
        self.assertIn("D1直接大占前两日", script)
        self.assertIn("D2单日退订率", script)
        self.assertIn("/2项可用（留存大定率、大定到锁单率）", script)
        self.assertNotIn("lockData*3", script)
        self.assertNotIn("得分${Math.round(part.value*100)}", script)

    def test_sales_forecast_six_logic_fixes_are_observable(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        refresh = (ROOT / "tools" / "refresh_sales_forecast_data.py").read_text(encoding="utf-8")
        self.assertIn("parameterRawSmall", script)
        self.assertIn("KPI与未来剩余量已同步到真实下限", script)
        self.assertIn("curveShapeCloseness", script)
        self.assertIn("D1～当前Dn归一化斜率", script)
        self.assertIn("不参与参考车型评分", script)

    def test_sales_forecast_has_one_interactive_calculation_owner(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        self.assertNotIn("def _match_score", module)
        self.assertNotIn("def _recommendations", module)
        self.assertNotIn("window_profile", module)
        self.assertNotIn("function renderForecastWorkspace(data)", script)
        self.assertNotIn("function bindForecastWorkspace()", script)
        self.assertEqual(script.count("const scoreParts="), 1)

    def test_sales_forecast_rebases_horizon_and_separates_past_gaps(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        forecast_math = (ROOT / "templates" / "forecast-math.js").read_text(encoding="utf-8")
        self.assertIn("const rebasedForecastCompletion=", script)
        self.assertIn("const extendForecastCurve=", script)
        self.assertIn("const rebasedForecastCompletionCurve=", script)
        self.assertIn("comparison?.progressRows?.length", script)
        self.assertNotIn("values=cumulativeNormalized(values.slice(0,count))", script)
        self.assertIn("由${sourceDays}天外推至${targetDays}天", script)
        self.assertIn("const adaptedDailyOrders=", script)
        self.assertIn("past_missing", script)
        self.assertIn("过期缺失补估", script)
        self.assertIn("quotas.map(Math.floor)", forecast_math)
        self.assertIn("参数实时生效", script)
        self.assertIn('data-forecast-feedback role="status" aria-live="polite"', script)
        self.assertNotIn("data-forecast-confirm", script)
        self.assertNotIn("confirmedReferenceSnapshot", script)

    def test_sales_forecast_excludes_delivery_metrics(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        module = (ROOT / "modules" / "sales_forecast.py").read_text(encoding="utf-8")
        refresh = (ROOT / "tools" / "refresh_sales_forecast_data.py").read_text(encoding="utf-8")
        for text in (script, module, refresh):
            self.assertNotIn("首销期交付", text)
            self.assertNotIn("交付/锁单", text)
            self.assertNotIn("delivery_rate", text)
        self.assertIn("item?.d1_valid===false", script)
        self.assertIn('calculated_lock_rate = safe_div(lock, gross)', refresh)
        self.assertNotIn('calculated_lock_rate = safe_div(lock, net)', refresh)
        self.assertNotIn('write_rows(workbook, "人工校准参数"', refresh)
        self.assertNotIn('record.get("参考锁单率")', module)

    def test_sales_forecast_uses_shared_lock_parameter_and_compact_layout(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        refresh = (ROOT / "tools" / "refresh_sales_forecast_data.py").read_text(encoding="utf-8")
        parameter_block = script.split('forecast-parameter-controls', 1)[1].split('forecast-common-controls', 1)[0]
        self.assertNotIn('data-forecast-input="lock"', parameter_block)
        self.assertIn('class="forecast-common-lock">大定到锁单率', script)
        self.assertIn('首销期锁单 ÷ 总大定', script)
        self.assertIn('"首销期锁单", "大定到锁单率"', refresh)
        self.assertIn('.forecast-v2 .forecast-ref-grid{grid-template-columns:repeat(2,minmax(0,1fr))', css)
        self.assertIn('.forecast-common-controls{grid-column:1/-1', css)
        self.assertLess(script.index('forecast-progress-controls'), script.index('forecast-d1-card'))

    def test_history_tables_follow_the_top_grain_without_local_selector(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("const current=options[state.grain]?state.grain", script)
        self.assertNotIn("data-history-select", script)
        self.assertNotIn("history-toolbar", script)

    def test_sales_forecast_blocks_both_methods_on_raw_data_errors(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('data-forecast-data-error role="alert" aria-live="assertive"', script)
        self.assertIn("rawDataError", script)
        self.assertIn("parameterAvailable=!rawDataError", script)
        self.assertIn("progressAvailable=!rawDataError", script)
        self.assertIn("原始数据错误，当前对象已停止预测", script)
        self.assertIn(".forecast-data-error", css)


    def test_forecast_workflow_is_discoverable_and_details_remain_available(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('class="forecast-target-settings"', script)
        self.assertIn('class="forecast-source-details"', script)
        self.assertIn('data-forecast-stage-switch=', script)
        self.assertIn('data-forecast-jump="curve"', script)
        self.assertIn('data-forecast-jump="import"', script)
        self.assertIn('class="forecast-quick-actions forecast-result-actions"', script)
        self.assertIn("pane.querySelector('.forecast-scenarios,.forecast-lifecycle-kpis')", script)
        header = script.split('<section class="forecast-target">', 1)[1].split('</section>', 1)[0]
        self.assertNotIn("data-forecast-jump", header)

    def test_raw_search_has_live_count_empty_state_and_mobile_picker(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('id="rawMatchCount" role="status" aria-live="polite"', script)
        self.assertIn('id="rawEmpty"', script)
        self.assertIn('id="clearRawSearch"', script)
        self.assertIn('id="rawFile" aria-label="选择底表文件"', script)
        self.assertIn('$("#rawEmpty").hidden=filtered.length>1', script)

    def test_import_boundary_dates_follow_the_selected_stage(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('return windows[preferred]?preferred:', script)
        self.assertIn('stage:stageFor(row.date,target,stage)', script)
        self.assertIn('stageFor(row.date,target,row.stage)===stage', script)
        self.assertIn("status.dataset.state='error'", script)

    def test_navigation_discards_stale_pages_and_source_jump_preserves_back_path(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('revision!==pageRevision||moduleId!==state.module', script)
        self.assertIn('revision!==rawRenderRevision||state.module!=="raw"', script)
        source_jump = script.split('async function jumpToSource(source)', 1)[1].split('function showToast', 1)[0]
        self.assertIn('captureForecastDraft()', source_jump)
        self.assertIn('await renderAll();syncUrl("push")', source_jump)

    def test_forecast_manual_drafts_and_imports_are_saved_locally(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("const forecastStorageKey='harmony-forecast-v1:'+location.pathname", script)
        self.assertIn("localStorage.setItem(forecastStorageKey", script)
        self.assertIn("localStorage.getItem(forecastStorageKey)", script)
        self.assertIn("root._forecastTouched?.has(forecastDraftControlKey(control))", script)
        self.assertIn("root._forecastRestoreDraft?.(draft.meta||{})", script)
        self.assertIn("data-forecast-reset", script)
        self.assertIn("本机保存失败", script)

    def test_import_merge_identity_includes_stage_and_explicit_replace_is_confirmed(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn('<option value="merge">合并（同阶段同日更新）</option>', script)
        self.assertIn("mode==='replace'&&previous?.rows.length&&!window.confirm(", script)
        self.assertIn("const key=row.stage+'|'+row.date", script)
        self.assertIn("source:file.name", script)

    def test_vehicle_parameters_stay_expanded_at_all_widths(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn('<div class="forecast-target-settings" role="group" aria-label="车型与时间参数">', script)
        self.assertNotIn('<details class="forecast-target-settings">', script)
        self.assertIn('grid-template-columns:repeat(7,minmax(0,1fr))', css)
        self.assertIn('grid-template-columns:repeat(4,minmax(0,1fr))!important;gap:5px 7px', css)
        self.assertIn('grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:5px 6px', css)


    def test_forecast_source_brief_stays_outside_collapsible_details(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        header = script.split('<section class="forecast-target">', 1)[1].split('</section>', 1)[0]
        for marker in ('data-forecast-source-brief', 'data-forecast-time-brief'):
            self.assertLess(header.index(marker), header.index('<details class="forecast-source-details">'))
        self.assertIn('<summary>来源与时间详情</summary>', header)
        self.assertIn('data-forecast-day-source', header)
        self.assertIn('data-forecast-time-summary', header)
        self.assertGreaterEqual(script.count('refreshForecastHeaderBrief(root)'), 3)

    def test_forecast_secondary_tabs_are_lightweight_and_keyboard_visible(self):
        css = (ROOT / "templates" / "dashboard.css").read_text(encoding="utf-8")
        block = css.split('/* One stage entry point, followed by an aligned content-view switcher. */', 1)[1]
        primary = re.search(r'\.forecast-stage-switcher button\[aria-pressed=true\]\{([^}]+)\}', block).group(1)
        secondary = re.search(r'\.forecast-target-tabs button\[aria-selected=true\]\{([^}]+)\}', block).group(1)
        self.assertIn('background:#0d63ce', primary)
        self.assertIn('background:transparent', secondary)
        self.assertIn('border-bottom-color:#0d63ce', secondary)
        self.assertIn('border-left:1px solid #ccdae8', block)
        self.assertIn('.forecast-target-tabs button:focus-visible', block)
        self.assertIn('display:flex;flex-wrap:wrap;align-items:center', block)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for display formatter checks")
    def test_forecast_source_brief_preserves_mixed_sources_errors_and_judgement_date(self):
        script = (ROOT / "templates" / "dashboard.js").read_text(encoding="utf-8")
        helpers = script[script.index("  function forecastSourceBrief(text){"):
                         script.index("  function showForecastStageSummary(")]
        checks = r"""
const assert=require('node:assert/strict');
assert.equal(forecastSourceBrief('首销期已结束；主来源小订及首销数据整理（预测基准总表）；字段来源：首销日明细：小订及首销数据整理；总小订：小订及首销数据整理；分时进度：首销期订单节奏'),
  '混合来源：整理表＋首销节奏');
assert.equal(forecastSourceBrief('主来源小订及首销数据整理（预测基准总表）；字段来源：总小订：小订及首销数据整理'),
  '来源：整理表');
assert.equal(forecastSourceBrief('最终总小订取自小订及首销数据整理。逐日形状使用“小订by天”真实曲线。'),
  '总小订：整理表');
assert.equal(forecastSourceBrief('已发生4个完整日；分时累计仅作参考'), '实绩：4个完整日');
assert.equal(forecastSourceBrief('主辅参考车型测算'), '参考测算');
assert.equal(forecastSourceBrief('已结束日锁单缺失或异常（共490天）'), '数据缺失/异常');
const source={textContent:'已结束日锁单缺失或异常（共490天）'},
      time={textContent:'判定日期2026-09-23（数据生成于2026-09-22 09:57）；首销窗口2025-03-20 ~ 2025-05-06'},
      brief={dataset:{}},date={};
const nodes={'[data-forecast-day-source]':source,'[data-forecast-time-summary]':time,
 '[data-forecast-source-brief]':brief,'[data-forecast-time-brief]':date};
const root={querySelector:selector=>nodes[selector]};
refreshForecastHeaderBrief(root);
assert.equal(date.textContent,'判定日 2026-09-23');
assert.equal(date.title,time.textContent);
assert.equal(brief.title,source.textContent);
assert.equal(brief.dataset.warning,'true');
source.textContent='主辅参考车型测算';
refreshForecastHeaderBrief(root);
assert.equal(brief.dataset.warning,'false');
assert.equal(brief.textContent,'参考测算');
assert.equal(source.textContent,'主辅参考车型测算');
assert.doesNotThrow(()=>refreshForecastHeaderBrief({querySelector:()=>null}));
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", helpers + checks],
            capture_output=True, text=True, encoding="utf-8", timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

if __name__ == "__main__":
    unittest.main()
