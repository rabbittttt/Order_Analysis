"""Shared display components must not change prediction values or DOM bindings."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastStudioTests(unittest.TestCase):
    def js(self, body):
        setup = r'''
const fs=require('fs'),source=fs.readFileSync('templates/dashboard.js','utf8');
const esc=value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
const fmt=value=>Number(value).toLocaleString('zh-CN');
const section=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
eval(section('  function renderForecastQuantityChart(', '  function renderForecastWeeklyV2('));
eval(section('  function renderLifecycleBars(', '  function renderForecastEvidenceLines('));
eval(section('  function renderForecastScenarioCard(', '  function renderSmallOrderWorkspace('));
'''
        result = subprocess.run(['node', '-e', setup+body], cwd=ROOT,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_three_stages_share_chart_and_table_without_mutating_rows(self):
        result = self.js(r'''
const rows=[{label:'D1',day:'D1',date:'2026-09-01',actual:true,orders:100,lock:100,daily_gross:100,cumulative_gross:100},
 {label:'D2',day:'D2',date:'2026-09-02',actual:false,orders:0,lock:0,daily_gross:0,cumulative_gross:100}];
const original=JSON.stringify(rows),target={innerHTML:''};
renderForecastDecisionChartV2({querySelector:()=>target},rows);
const charts=[renderLifecycleBars(rows,'orders'),target.innerHTML,renderLifecycleBars(rows,'lock')];
console.log(JSON.stringify({unchanged:JSON.stringify(rows)===original,
 valid:charts.map(html=>html.includes('forecast-decision-svg')&&html.includes('forecast-result-values')&&html.includes('查看图表数值')&&html.includes('stroke-dasharray="4 2"')),
 zero:charts[0].includes('<td>0</td>'),escaped:renderLifecycleBars([{...rows[0],label:'<script>'}],'orders').includes('&lt;script>')}));
''')
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['valid'], [True, True, True])
        self.assertTrue(result['zero'])
        self.assertTrue(result['escaped'])

    def test_missing_display_value_is_not_rendered_as_zero(self):
        result = self.js(r'''
const html=renderLifecycleBars([{label:'D1',actual:true,orders:null}],'orders');
console.log(JSON.stringify({missing:html.includes('<td>—</td>'),zero:html.includes('<td>0</td>'),empty:renderLifecycleBars([],'orders').includes('暂无可绘制数据'),historical:renderLifecycleBars([{label:'D1',orders:8,past_missing:true}],'orders').includes('<td>历史缺失估算</td>')}));
''')
        self.assertTrue(result['missing'])
        self.assertFalse(result['zero'])
        self.assertTrue(result['empty'])
        self.assertTrue(result['historical'])

    def test_shared_metric_strip_preserves_existing_update_selectors(self):
        result = self.js(r'''
const small=renderLifecycleConclusion('small','小订','说明',[{key:'total',label:'总量',unit:'单'},{key:'d1',label:'D1',unit:'单'}]);
const steady=renderLifecycleConclusion('steady','平销','说明',[{key:'total',label:'总量',unit:'单'},{key:'basis',label:'依据'}]);
const launch=renderForecastScenarioCard({title:'方法一',note:'说明',status:'data-forecast-method-status="progress"',metrics:[{label:'大定',attribute:'data-forecast-value="progress-gross"',unit:'单',noteAttribute:'data-forecast-kpi-note="progress-gross"'}]});
console.log(JSON.stringify({strips:[small,launch,steady].every(html=>html.includes('forecast-metric-strip')),
 selectors:[small.includes('data-small-kpi="total"'),small.includes('data-small-confidence'),steady.includes('data-steady-kpi="basis"'),launch.includes('data-forecast-value="progress-gross"'),launch.includes('data-forecast-kpi-note="progress-gross"')]}));
''')
        self.assertTrue(result['strips'])
        self.assertTrue(all(result['selectors']))
