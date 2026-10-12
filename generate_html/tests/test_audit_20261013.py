"""Regression: estimated splits conserve orders; unavailable periods are not zero."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from datetime import date
from openpyxl import Workbook

from core.excel import WorkbookItem, WorkbookStore
from modules.overview import _drop_rankings, _rise_rankings_with_empty, _group_model_series

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class IntradayIntegerTests(unittest.TestCase):
    def evaluate(self, expression):
        result = subprocess.run(['node', '-e',
            "const m=require('./templates/forecast-math.js');console.log(JSON.stringify(" + expression + '))'],
            cwd=ROOT, capture_output=True, text=True, encoding='utf-8', check=True)
        return json.loads(result.stdout)

    def test_fractional_estimated_share_cannot_create_an_order(self):
        result = self.evaluate('m.intradayComponents({gross:100},1,1/3)')
        self.assertEqual(result['gross'], 100)
        self.assertEqual(result['small'] + result['direct'], 100)
        self.assertEqual(result['observedSmall'] + result['observedDirect'], 100)

    def test_estimated_component_floors_cannot_raise_d1_terminal(self):
        result = self.evaluate('''(()=>{const r=m.intradayComponents({gross:100},1,1/3);
          return m.applyObservedFloor([33,0],r.observedSmall).raised+
                 m.applyObservedFloor([67,0],r.observedDirect).raised;})()''')
        self.assertEqual(result, 0)

    def test_rounding_preserves_observed_components_and_total_for_all_shares(self):
        failures = self.evaluate('''(()=>{const failures=[];
          for(let gross=1;gross<=50;gross++)for(const completion of [1,.99,.7,.2])for(const share of [.001,1/3,.5,.999]){
            for(const extra of [{},{small_to_big:0},{direct:0},{small_to_big:Math.floor(gross*.4),direct:Math.floor(gross*.3)}]){
              const r=m.intradayComponents({gross,...extra},completion,share);
              if(r.gross!==Math.round(gross/completion)||r.small+r.direct!==r.gross||
                 r.small<(extra.small_to_big||0)||r.direct<(extra.direct||0)||
                 !Number.isInteger(r.observedSmall)||!Number.isInteger(r.observedDirect)){
                failures.push({gross,completion,share,extra,r});if(failures.length>=3)return failures;
              }
            }
          }return failures;})()''')
        self.assertEqual(failures, [])

    def test_known_components_remain_unchanged(self):
        result = self.evaluate('m.intradayComponents({gross:100,small_to_big:70,direct:30},1,1/3)')
        self.assertEqual((result['small'], result['direct']), (70, 30))


class RankingMissingEvidenceTests(unittest.TestCase):
    def series(self, current):
        return {'测试车': {metric: {'上期': {'metrics': {metric: 100}}, **current(metric)}
                          for metric in ('留存大定', '交车锁单')}}

    def test_unupdated_period_is_not_a_full_decline(self):
        series = self.series(lambda metric: {})
        self.assertEqual(_drop_rankings(series, '本期', '上期'), {})
        self.assertIn('暂无可比数据', _rise_rankings_with_empty(series, '本期', '上期')['交车锁单']['empty_reason'])

    def test_missing_metric_is_not_a_full_decline(self):
        series = self.series(lambda metric: {'本期': {'metrics': {'其他指标': 5}}})
        self.assertEqual(_drop_rankings(series, '本期', '上期'), {})

    def test_real_zero_remains_a_full_decline(self):
        series = self.series(lambda metric: {'本期': {'metrics': {metric: 0}}})
        for metric in ('留存大定', '交车锁单'):
            self.assertEqual(_drop_rankings(series, '本期', '上期')[metric][0]['rate'], 1)
        self.assertEqual(_rise_rankings_with_empty(series, '本期', '上期')['交车锁单']['empty_reason'], '本期暂无环比上涨车型')

    def test_invalid_quantity_is_not_comparable(self):
        for value in (None, -1, float('nan'), float('inf'), True):
            with self.subTest(value=value):
                series = self.series(lambda metric: {'本期': {'metrics': {metric: value}}})
                self.assertEqual(_drop_rankings(series, '本期', '上期'), {})
                self.assertIn('暂无可比数据', _rise_rankings_with_empty(series, '本期', '上期')['交车锁单']['empty_reason'])

    def test_sparse_daily_zero_uses_physical_file_coverage_not_model_last_sale(self):
        store = WorkbookStore(Path('.'))
        for kind, metric in (('大定', '净大定'), ('锁单', '交车锁单')):
            book = Workbook()
            group = book.active
            group.title = '鸿蒙智行by天'
            group.append(['指标', '统计类型', '分类', '2026-01-01', '2026-01-03'])
            group.append([metric, '数量', '数量', 200, 100])
            model = book.create_sheet('问界 M9 2026款by天')
            model.append(['指标', '统计类型', '分类', '2026-01-01'])
            model.append([metric, '数量', '数量', 100])
            store.items.append(WorkbookItem(Path('鸿蒙智行' + kind + '选配比例分析.xlsx'), book))
        try:
            series = _group_model_series(store, 'day')
            for day in ('2026-01-02', '2026-01-03'):
                self.assertEqual(_drop_rankings(series, day, '2026-01-01')['交车锁单'][0]['rate'], 1)
            self.assertEqual(_drop_rankings(series, '2026-01-04', '2026-01-01'), {})
        finally:
            store.close()

    def test_gaps_between_exports_are_not_zero(self):
        series = self.series(lambda metric: {})
        series['测试车']['_daily_coverage'] = {metric: [(date(2026,1,1), date(2026,1,2)),
            (date(2026,1,4), date(2026,1,5))] for metric in ('留存大定', '交车锁单')}
        self.assertEqual(_drop_rankings(series, '2026-01-03', '上期'), {})
        self.assertEqual(_drop_rankings(series, '2026-01-04', '上期')['交车锁单'][0]['rate'], 1)
