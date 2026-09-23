"""Offline export safety and metric separation regression tests."""
import importlib.util
import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('web_export_test',Path(__file__).resolve().parents[1] / 'export_html.py')
e=importlib.util.module_from_spec(spec);spec.loader.exec_module(e)


def data():
    return dict(meta={'title':'测试','date_start':date(2021,1,1)},metrics=[],grouping={},
                series=[],results={'weekly':[]},rules=[],forecast={'profiles':[],'backtests':[]})


def templates(folder):
    p=Path(folder)
    (p/'patterns.html').write_text('<!doctype html><html><style>__PATTERNS_CSS__</style><script id="patterns-data" type="application/json">__PATTERNS_DATA__</script><script>__PATTERNS_JS__</script></html>',encoding='utf-8')
    (p/'patterns.css').write_text('body{color:#123}',encoding='utf-8')
    (p/'patterns.js').write_text('window.testData=window.PATTERNS_DATA;',encoding='utf-8')
    return p


class HtmlExportTests(unittest.TestCase):
    def test_data_script_cannot_be_closed_by_source_labels(self):
        payload=data()
        attack='</script><script>throw Error("bad")</script>&__PATTERNS_JS__'
        payload['meta']['title']=attack
        payload['series']=[dict(model=attack,value=-1,metric='留存大定')]
        with tempfile.TemporaryDirectory() as tmp:
            html=e.render_html(payload,templates(tmp))
        embedded=re.search(r'type="application/json">(.*?)</script>',html,re.S)[1]
        self.assertNotIn('<',embedded)
        recovered=json.loads(embedded)
        self.assertEqual(recovered['meta']['title'],attack)
        self.assertEqual(recovered['series'][0]['value'],-1)
        self.assertEqual(recovered['meta']['date_start'],'2021-01-01')
        self.assertEqual(html.count('<script>'),1)

    def test_compaction_is_lossless_for_null_zero_and_repeated_strings(self):
        rows=[dict(model='车型A',value=0 if i%2 else None,date='2024-01-01',metric='留存大定',extra=[1,2]) for i in range(60)]
        packed=e.pack_records(rows)
        self.assertEqual(packed['$table'],1)
        rebuilt=[]
        for row in packed['rows']:
            out={}
            for i,key in enumerate(packed['columns']):
                labels=packed['dictionaries'].get(str(i)); value=row[i]
                out[key]=labels[value] if labels is not None and value is not None else value
            rebuilt.append(out)
        self.assertEqual(rebuilt,rows)
        self.assertLess(len(json.dumps(packed)),len(json.dumps(rows)))
        self.assertEqual(rows[0]['model'],'车型A')

    def test_unknown_nonfinite_numbers_fail_before_output(self):
        payload=data();payload['series']=[dict(value=float('nan'))]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):e.render_html(payload,templates(tmp))

    def test_failed_replace_preserves_old_page_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'report.html';target.write_text('old',encoding='utf-8')
            unrelated=Path(tmp)/'keep.txt';unrelated.write_text('keep',encoding='utf-8')
            with patch.object(e.os,'replace',side_effect=PermissionError('locked')):
                with self.assertRaisesRegex(PermissionError,'上次网页已保留'):
                    e.export_html('<html>patterns-data</html>',target)
            self.assertEqual(target.read_text(encoding='utf-8'),'old')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),['keep.txt','report.html'])

    def test_focus_does_not_replace_missing_net_metric_with_gross_deposits(self):
        results={name:[] for name in ['weekly','monthly','annual','holidays','lifecycle','period_comparisons','period_summary','lock_lags','coverage']}
        results['model_classes']=[dict(model='车型A',brand='品牌',segment='未知',energy='纯电',stages='平销',metrics='大定')]
        results['coverage']=[dict(metric='大定',stage='平销',start=date(2025,1,1),end=date(2025,1,1))]
        panel=[dict(model='车型A',metric='大定',date=date(2025,1,1),value=100,stage='平销')]
        result=e.build_web_data(dict(results=results),panel)
        self.assertEqual(result['series'],[])
        self.assertFalse(any(m['available'] for m in result['metrics']))
        self.assertEqual(result['results']['coverage'],[])
        self.assertEqual(result['meta']['date_start'],None)

if __name__=='__main__':unittest.main()
