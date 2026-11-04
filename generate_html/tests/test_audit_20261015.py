"""Calendar positions and raw-table reads must survive real user workflows."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
PARENT = '测试车 2026款'


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class BrowserDataWorkflowTests(unittest.TestCase):
    def js(self, script):
        prelude = "const fs=require('fs'),source=fs.readFileSync('templates/dashboard.js','utf8');\n"
        result = subprocess.run(['node', '-e', prelude+script], cwd=ROOT,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


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
