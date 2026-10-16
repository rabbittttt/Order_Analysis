"""Exercise the production Excel importer, including transactional UI failures."""
import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
from unittest import TestCase, skipUnless
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[1]


def prediction_zip(cell, small=None):
    """Minimal OOXML bytes let tests control formula-cache states exactly."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('xl/workbook.xml',
            '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="预测" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels',
            '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml',
            '<worksheet><sheetData><row r="1">'
            '<c r="A1" t="inlineStr"><is><t>车型（代际）</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>日期</t></is></c>'
            '<c r="C1" t="inlineStr"><is><t>预测大定</t></is></c>'
            '<c r="D1" t="inlineStr"><is><t>预测小订</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>问界 M9 2026款</t></is></c>'
            '<c r="B2" t="inlineStr"><is><t>2026-10-17</t></is></c>'
            + cell + (f'<c r="D2"><v>{small}</v></c>' if small is not None else '')
            + '</row></sheetData></worksheet>')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


@skipUnless(shutil.which('node') and (PROJECT/'.test_runtime/node_modules/playwright').exists(),
            'Node.js and project browser test runtime required')
class ExternalExcelQuantityTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cases = {
            'uncached': prediction_zip('<c r="C2"><f>1+2</f><v></v></c>'),
            'no_cache_element': prediction_zip('<c r="C2"><f>1+2</f></c>'),
            'empty_numeric': prediction_zip('<c r="C2" t="n"><v> </v></c>'),
            'formula_zero': prediction_zip('<c r="C2"><f>1-1</f><v>0</v></c>'),
            'literal_zero': prediction_zip('<c r="C2"><v>0</v></c>'),
            'positive': prediction_zip('<c r="C2"><f>1+2</f><v>3</v></c>'),
            'boolean_true': prediction_zip('<c r="C2" t="b"><v>1</v></c>'),
            'boolean_false': prediction_zip('<c r="C2" t="b"><v>0</v></c>'),
            'mixed': prediction_zip('<c r="C2"><f>1+2</f><v/></c>', small=10),
            'excel_error': prediction_zip('<c r="C2" t="e"><v>#DIV/0!</v></c>'),
        }
        script = r"""
const fs=require('fs'),path=require('path'),{pathToFileURL}=require('url');
const project=path.resolve('../..'),{chromium}=require(path.join(project,'.test_runtime/node_modules/playwright'));
(async()=>{
 const cases=JSON.parse(fs.readFileSync(0,'utf8')),browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  const url=pathToFileURL(path.join(project,'output_file/鸿蒙智行订单分析汇总.html'));
  url.search=new URLSearchParams({subject:'问界 M9 2026款',module:'sales_forecast'});
  await page.goto(url.href);await page.waitForSelector('.forecast-workspace');
  await page.addScriptTag({path:path.resolve('templates/forecast-import.js')});
  const results=await page.evaluate(async cases=>{
   const result={};
   for(const [key,value] of Object.entries(cases)){
    try{result[key]={rows:await ForecastImport.read(new File([Uint8Array.from(atob(value),c=>c.charCodeAt(0))],'test.xlsx'))}}
    catch(e){result[key]={error:e.message}}
   }
   result.normalize_boolean=[true,false].map(value=>{try{return ForecastImport.normalize([['车型','日期','预测数量'],['测试','2026-10-17',value]])}catch(e){return {error:e.message}}});
   return result;
  },cases);
  await page.locator('[data-forecast-stage-switch="launch"]').click();
  const card=page.locator('[data-forecast-import="launch"]'),input=card.locator('[data-forecast-import-file]');
  await input.setInputFiles({name:'valid.csv',mimeType:'text/csv',buffer:Buffer.from('车型（代际）,日期,预测大定\n问界 M9 2026款,2026-10-17,21')});
  await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"] [data-forecast-import-status]')?.textContent.includes('导入成功'));
  const storage=()=>page.evaluate(()=>Object.fromEntries(Object.entries(localStorage).filter(([,v])=>{try{return JSON.parse(v)?.version===1&&Array.isArray(JSON.parse(v).imports)}catch{return false}})));
  const before=await storage();
  await input.setInputFiles({name:'uncached.xlsx',mimeType:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',buffer:Buffer.from(cases.uncached,'base64')});
  await page.waitForFunction(()=>document.querySelector('[data-forecast-import="launch"]')?.getAttribute('aria-busy')==='false');
  results.transaction={before,after:await storage(),status:await card.locator('[data-forecast-import-status]').textContent(),state:await card.locator('[data-forecast-import-status]').getAttribute('data-state')};
  results.errors=errors;console.log(JSON.stringify(results));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
"""
        result = subprocess.run(['node', '-e', script], input=json.dumps(cases), cwd=ROOT,
                                capture_output=True, encoding='utf-8', timeout=90)
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.results = json.loads(result.stdout)

    def test_missing_cache_is_not_a_zero_prediction(self):
        for key in ('uncached', 'no_cache_element', 'empty_numeric'):
            with self.subTest(cache=key):
                self.assertIn('error', self.results[key])

    def test_real_zero_and_cached_formula_result_survive(self):
        for key, expected in (('formula_zero', 0), ('literal_zero', 0), ('positive', 3)):
            with self.subTest(value=key):
                self.assertEqual(self.results[key]['rows'][0]['gross'], expected)

    def test_excel_booleans_cannot_be_order_quantities(self):
        for key in ('boolean_true', 'boolean_false'):
            with self.subTest(value=key):
                self.assertIn('error', self.results[key])

    def test_shared_normalizer_also_rejects_boolean_quantities(self):
        for result in self.results['normalize_boolean']:
            self.assertIn('error', result)

    def test_other_known_metric_is_retained_without_inventing_missing_metric(self):
        row = self.results['mixed']['rows'][0]
        self.assertEqual(row['small'], 10)
        self.assertNotIn('gross', row)

    def test_excel_formula_errors_are_not_quantities(self):
        self.assertIn('error', self.results['excel_error'])

    def test_failed_excel_import_preserves_previous_saved_prediction(self):
        result = self.results['transaction']
        self.assertEqual(result['state'], 'error')
        self.assertIn('原导入数据保持不变', result['status'])
        self.assertEqual(result['before'], result['after'])
        self.assertTrue(result['before'])
        self.assertEqual(self.results['errors'], [])
