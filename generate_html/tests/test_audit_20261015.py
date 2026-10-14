"""Calendar positions and raw-table reads must survive real user workflows."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from modules.sales_forecast import _combined_steady_inputs


ROOT = Path(__file__).resolve().parents[1]
PARENT = '测试车 2026款'


class CampaignCalendarTests(unittest.TestCase):
    def combined(self, windows):
        targets, profiles = [], []
        for edition, start, end, values in windows:
            name = PARENT + ' ' + edition
            targets.append(dict(name=name, primary_generation=PARENT,
                                secondary_generation=name, launch_date=start, end_date=end))
            profiles.append(dict(model=name, days=[dict(date=day, gross=quantity,
                small_to_big=0, direct=quantity, lock=quantity/2, net=quantity)
                for day, quantity in values]))
        return _combined_steady_inputs(targets, profiles, [])

    def test_gap_keeps_calendar_span_without_inventing_actual_orders(self):
        targets, profiles, history = self.combined([
            ('A', '2026-05-01', '2026-05-01', [('2026-05-01', 100)]),
            ('B', '2026-05-03', '2026-05-03', [('2026-05-03', 200)])])
        self.assertEqual(targets[0]['days'], 3)
        self.assertEqual(targets[0]['steady_start_date'], '2026-05-04')
        self.assertEqual([r['date'] for r in profiles[0]['days']], ['2026-05-01', '2026-05-03'])
        self.assertEqual([r['day'] for r in profiles[0]['days']], ['D1', 'D3'])
        self.assertEqual(history[0]['daily_direct'], [100, None, 200])
        self.assertEqual(history[0]['daily_orders'], [100, None, 200])
        self.assertEqual(history[0]['daily_small'], [0, None, 0])
        self.assertEqual(history[0]['gross'], 300)
        self.assertEqual(history[0]['lock_rate'], .5)

    def test_overlapping_editions_still_sum_once_per_calendar_day(self):
        targets, profiles, history = self.combined([
            ('A', '2026-05-01', '2026-05-02', [('2026-05-01', 10), ('2026-05-02', 20)]),
            ('B', '2026-05-02', '2026-05-03', [('2026-05-02', 30), ('2026-05-03', 40)])])
        self.assertEqual(targets[0]['days'], 3)
        self.assertEqual(history[0]['daily_direct'], [10, 50, 40])
        self.assertEqual([r['direct'] for r in profiles[0]['days']], [10, 50, 40])
        self.assertEqual(history[0]['direct'], 100)


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class BrowserDataWorkflowTests(unittest.TestCase):
    def js(self, script):
        prelude = "const fs=require('fs'),source=fs.readFileSync('templates/dashboard.js','utf8'),math=require('./templates/forecast-math.js');\n"
        result = subprocess.run(['node', '-e', prelude+script], cwd=ROOT,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def reference(self, values, today):
        return self.js(r'''
const begin=source.indexOf('    const directFeature='),end=source.indexOf('    const scoreResult=',begin);
const launch={model:'测试车',launch_date:'2026-05-01',end_date:'2026-05-03',days:3,lock_rate:.5,daily_direct:VALUES};
const context={factors:()=>({workday:1,holiday:2}),todayIso:()=>TODAY,
 calendarType:(start,index)=>({date:new Date(Date.parse(start+'T00:00:00Z')+index*86400000).toISOString().slice(0,10),type:index===1?'holiday':'workday'})};
const feature=new Function('window','context','targetLaunch','launchHistory','sameModel','observedDailyPrefix',
 source.slice(begin,end)+';return directFeature;')({ForecastMath:math},context,()=>launch,[launch],(a,b)=>a===b,
 values=>{const out=[];for(const v of values){if(v==null||!Number.isFinite(v)||v<0)break;out.push(v)}return out});
const result=feature({model:'测试车',daily:[]});
console.log(JSON.stringify({curve:result.direct_curve,days:result.launch_days}));
'''.replace('VALUES', json.dumps(values)).replace('TODAY', json.dumps(today)))

    def test_reference_gap_does_not_hide_or_recalendar_later_actual(self):
        self.assertEqual(self.reference([100, None, 200], '2026-05-04'),
                         {'curve': [100, None, 200], 'days': 3})

    def test_reference_excludes_current_and_future_days(self):
        self.assertEqual(self.reference([100, 150, 200], '2026-05-03'),
                         {'curve': [100, 75], 'days': 3})

    def test_complete_reference_calendar_values_are_unchanged(self):
        self.assertEqual(self.reference([100, 150, 200], '2026-05-04'),
                         {'curve': [100, 75, 200], 'days': 3})

    def test_incomplete_calendar_curve_is_not_an_eligible_trend_reference(self):
        result = self.js(r'''
const attrs={tier:'SUV',energy:'纯电',node:'发布'};
console.log(JSON.stringify(math.steadyReferenceScore({...attrs,launch_days:5,direct_curve:[100,null,200,150,100]},
 attrs,{launch_days:5,direct_curve:[100,80,60,40,20]},3)));
''')
        self.assertFalse(result['eligible'])

    def raw_switch(self, reverse=False, leave=False):
        return self.js(r'''
const begin=source.indexOf('  let rawRowsCache='),end=source.indexOf('  function filterRawRows',begin);
const filter=source.split('\n').find(line=>line.startsWith('  function filterRawRows'));
const exportBegin=source.indexOf('  function exportRaw('),exportEnd=source.indexOf('  async function jumpToSource',exportBegin);
const elements={},downloads=[],blobs=new Map(),pending={};
const $=selector=>elements[selector]??=({innerHTML:'',classList:{toggle(){}},value:'',focus(){}});
const state={module:'raw',rawFile:0,rawSheet:0,rawQuery:''};
const DATA={raw_files:['旧文件','当前文件'].map(name=>({name:name+'.xlsx',sheets:[{name:'by天'}]}))};
const doc={querySelectorAll:()=>[],body:{appendChild(){}},createElement:()=>({click(){downloads.push({name:this.download,csv:blobs.get(this.href).parts.join('')})},remove(){}})};
class FakeBlob{constructor(parts){this.parts=parts}}
const urls={createObjectURL:blob=>{const key='url'+blobs.size;blobs.set(key,blob);return key},revokeObjectURL(){}};
const api=new Function('$','document','state','DATA','RAW_BLOCKS','decompressJson','esc','renderRawTable',
 'applyRawFrozenColumns','syncUrl','Blob','URL','showToast','setTimeout',
 source.slice(begin,end)+filter+'\n'+source.slice(exportBegin,exportEnd)+
 ';return {renderRaw,cache:()=>({rows:rawRowsCache,key:rawRowsKey})};')($,doc,state,DATA,
 {'0|0':'old','1|0':'new'},name=>new Promise(resolve=>pending[name]=resolve),String,JSON.stringify,
 ()=>{},()=>{},FakeBlob,urls,()=>{},()=>{});
(async()=>{
 const old=api.renderRaw();state.rawFile=1;const current=api.renderRaw();
 if(REVERSE){pending.old({rows:[['标题'],['OLD']]});await old;pending.new({rows:[['标题'],['NEW']]});await current;}
 else{pending.new({rows:[['标题'],['NEW']]});await current;if(LEAVE)state.module='overview';pending.old({rows:[['标题'],['OLD']]});await old;}
 elements['#exportRaw'].onclick();
 console.log(JSON.stringify({cache:api.cache(),display:elements['#page'].innerHTML,downloads}));
})().catch(error=>{console.error(error);process.exitCode=1});
'''.replace('REVERSE', json.dumps(reverse)).replace('LEAVE', json.dumps(leave)))

    def test_late_old_read_cannot_change_current_sheet_export(self):
        result = self.raw_switch()
        self.assertEqual(result['cache']['key'], '1|0')
        self.assertIn('NEW', result['downloads'][0]['csv'])
        self.assertNotIn('OLD', result['downloads'][0]['csv'])
        self.assertEqual(result['downloads'][0]['name'], '当前文件_by天.csv')
        self.assertIn('当前文件', result['display'])

    def test_read_completion_in_request_order_still_exports_current_sheet(self):
        result = self.raw_switch(reverse=True)
        self.assertEqual(result['cache']['rows'], [['标题'], ['NEW']])
        self.assertIn('NEW', result['downloads'][0]['csv'])

    def test_leaving_raw_view_does_not_let_stale_read_replace_cache(self):
        result = self.raw_switch(leave=True)
        self.assertEqual(result['cache']['key'], '1|0')
        self.assertIn('NEW', result['downloads'][0]['csv'])

    def test_large_raw_sheet_width_and_render_do_not_spread_rows_as_arguments(self):
        result = self.js(r'''
const begin=source.indexOf('  function rawCellIsData'),end=source.indexOf('  function applyRawFrozenColumns',begin);
const render=source.split('\n').find(line=>line.startsWith('  function renderRawTable'));
const api=new Function('fmt','esc',source.slice(begin,end)+render+';return {rawTitleColumnCount,renderRawTable};')(String,String);
const rows=Array.from({length:150000},()=>['测试车',12]);rows[rows.length-1]=['尾行',3,0];
const count=api.rawTitleColumnCount(rows),html=api.renderRawTable(rows);
console.log(JSON.stringify({titleColumns:count,rows:(html.match(/<tr>/g)||[]).length,lastColumn:html.includes('data-raw-col="2"')}));
''')
        self.assertEqual(result, {'titleColumns': 1, 'rows': 150000, 'lastColumn': True})

    def test_empty_raw_table_is_still_renderable(self):
        result = self.js(r'''
const begin=source.indexOf('  function rawCellIsData'),end=source.indexOf('  function applyRawFrozenColumns',begin);
const render=source.split('\n').find(line=>line.startsWith('  function renderRawTable'));
const api=new Function('fmt','esc',source.slice(begin,end)+render+';return {rawTitleColumnCount,renderRawTable};')(String,String);
console.log(JSON.stringify({width:api.rawTitleColumnCount([]),html:api.renderRawTable([])}));
''')
        self.assertEqual(result, {'width': 0, 'html': '<table class="data-table"><tbody></tbody></table>'})
