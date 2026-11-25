from __future__ import annotations

import unittest
from pathlib import Path

from openpyxl import Workbook

from core.excel import WorkbookItem, WorkbookStore, parse_metric_sheet
from core.models import Subject
from modules.order_mix import MixModule, OrderMixModule


class MetricBlockOrderTests(unittest.TestCase):
    def sheet(self, rows):
        book = Workbook()
        self.addCleanup(book.close)
        sheet = book.active
        sheet.title = '问界 M9 2026款 by周'
        sheet.append(['指标', '统计类型', '分类', '26WK42', '26WK43'])
        for row in rows:
            sheet.append(row)
        return book, sheet

    def test_count_before_share_preserves_original_counts_and_shares(self):
        _, sheet = self.sheet([['版本', '数量', 'A', 30, 0], [None, None, 'B', 70, 100],
                               [None, '占比', 'A', .3, 0], [None, None, 'B', .7, 1]])
        parsed = parse_metric_sheet(sheet)
        self.assertEqual(parsed['26WK42']['structures']['版本'],
                         [{'label': 'A', 'share': .3, 'count': 30}, {'label': 'B', 'share': .7, 'count': 70}])
        self.assertEqual(parsed['26WK43']['structures']['版本'][0]['count'], 0)

    def test_share_first_and_count_first_have_identical_result(self):
        share = ['版本', '占比', 'A', .3, .4]
        count = ['版本', '数量', 'A', 30, 40]
        _, first = self.sheet([share, count])
        _, second = self.sheet([count, share])
        self.assertEqual(parse_metric_sheet(first), parse_metric_sheet(second))

    def test_interleaved_metrics_and_contributing_stores_do_not_mix_counts(self):
        _, sheet = self.sheet([['版本', '数量', 'A', 30, 40], ['门店类型', '数量', 'A', 3, 4],
                               [None, '贡献门店数', 'A', 1, 2],
                               ['版本', '占比', 'A', .3, .4], ['门店类型', '占比', 'A', .03, .04]])
        result = parse_metric_sheet(sheet)['26WK43']['structures']
        self.assertEqual(result['版本'][0]['count'], 40)
        self.assertEqual(result['门店类型'][0]['count'], 4)

    def test_share_only_keeps_unknown_count_and_count_only_adds_no_fake_share(self):
        _, sheet = self.sheet([['版本', '占比', 'A', .3, .4], ['外观', '数量', '白', 30, 40]])
        result = parse_metric_sheet(sheet)['26WK43']['structures']
        self.assertIsNone(result['版本'][0]['count'])
        self.assertEqual(result.get('外观', []), [])

    def test_scalar_metrics_remain_separate(self):
        _, sheet = self.sheet([['大定', '数量', '数量', 100, 200], ['版本', '数量', 'A', 30, 40],
                               [None, '占比', 'A', .3, .2]])
        result = parse_metric_sheet(sheet)['26WK43']
        self.assertEqual(result['metrics'], {'大定': 200})
        self.assertEqual(result['structures']['版本'][0]['count'], 40)

    def test_battery_trend_is_full_width_and_keeps_counts_and_shares(self):
        book, _ = self.sheet([
            ['电池包', '占比', '100度', .6, .4], [None, None, '80度', .4, .6],
            ['电池包', '数量', '100度', 6, 4], [None, None, '80度', None, 0],
            ['内饰', '数量', '米色', 0, 12], [None, '占比', '米色', 0, .3],
            [None, None, '黑色', .2, .1],
        ])
        store = WorkbookStore(Path('.'))
        store.items = [WorkbookItem(Path('鸿蒙智行大定选配比例分析.xlsx'), book)]
        subject = Subject(id='test', name='问界 M9 2026款', type='generation', parent='问界')
        page = OrderMixModule().build(store, subject).views['week']['pages']['26WK43']
        battery, structures = page['sections'][:2]
        self.assertEqual([s['kind'] for s in page['sections']].count('mix_combo_trend'), 1)
        self.assertEqual(battery['title'], '电池包度数 · 数量与占比')
        self.assertEqual(battery['width'], 'full')
        self.assertEqual(battery['data']['periods'], ['26WK42', '26WK43'])
        self.assertEqual(battery['data']['series'], [
            {'name': '80度', 'shares': [.4, .6], 'counts': [None, 0]},
            {'name': '100度', 'shares': [.6, .4], 'counts': [6, 4]},
        ])
        self.assertEqual(structures['kind'], 'structure_cards')
        self.assertIn('内饰', [group['name'] for group in structures['data']])

    def test_order_mix_page_keeps_count_in_ranking(self):
        book, _ = self.sheet([['版本', '数量', 'A', 30, 40], [None, '占比', 'A', .3, .4]])
        store = WorkbookStore(Path('.'))
        store.items = [WorkbookItem(Path('鸿蒙智行大定选配比例分析.xlsx'), book)]
        subject = Subject(id='test', name='问界 M9 2026款', type='generation', parent='问界')
        board = OrderMixModule().build(store, subject).to_dict()
        page = board['views']['week']['pages']['26WK43']
        ranking = next(section for section in page['sections'] if section['title'] == '选配偏好变化排行')
        self.assertEqual(ranking['data']['rows'][0][-1], 40)

    def test_zero_battery_option_hidden_only_in_its_zero_period(self):
        book, _ = self.sheet([['电池包', '占比', '80度', .7, 1], [None, None, '100度', .3, 0]])
        subject = Subject(id='test', name='问界 M9 2026款', type='generation', parent='问界')
        for kind in ('order', 'lock', 'small'):
            with self.subTest(kind=kind):
                module = MixModule(kind)
                store = WorkbookStore(Path('.'))
                store.items = [WorkbookItem(Path(f'鸿蒙智行{module.keyword}分析.xlsx'), book)]
                pages = module.build(store, subject).views['week']['pages']
                for period, labels in [('26WK42', {'80度', '100度'}), ('26WK43', {'80度'})]:
                    sections = {part['kind']: part['data'] for part in pages[period]['sections']}
                    self.assertEqual({row['label'] for row in sections['structure_cards'][0]['rows']}, labels)
                    self.assertEqual({row[1] for row in sections['table']['rows']}, labels)


if __name__ == '__main__':
    unittest.main()
