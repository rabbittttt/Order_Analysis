from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from openpyxl import Workbook

from core.discovery import discover_subjects
from core.excel import WorkbookItem, WorkbookStore
from core.model_identity import stage_records, stage_name, parent_generation, generation_records
from core.models import Subject
from core.models import Dashboard, SourceRef
from core.components import kpi
from modules.cancellation import CancellationModule
from modules.launch_rhythm import LaunchRhythmModule


PARENT = '问界 M7 2024款'
ULTRA, PRO = PARENT + ' Ultra版', PARENT + ' Pro版'


def records():
    return [dict(代际名=PARENT, 二级代际名=name, 小订开始日期=datetime(2024, month, 1),
                 小订结束日期=datetime(2024, month, 2), 开始大定日期=datetime(2024, month, 3),
                 小转大结束日期=datetime(2024, month, 4), 首销期天数=2)
            for name, month in ((ULTRA, 5), (PRO, 8))]


class GenerationCampaignTests(TestCase):
    def test_explicit_small_publication_synonym_does_not_borrow_launch_period(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from openpyxl import Workbook
        from core.model_identity import stage_records
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'source.xlsx'
            book = Workbook()
            book.active.append(['代际名', '小订发布时间', '首销发布时段', '发布时段'])
            book.active.append(['测试A', '下午', '晚上', '上午'])
            book.active.append(['测试B', None, '晚上', '上午'])
            book.save(path)
            book.close()
            rows = stage_records(path)
            self.assertEqual(rows[0]['小订发布时段'], '下午')
            self.assertIsNone(rows[1]['小订发布时段'])

    def test_small_all_phases_preserves_individuals_and_weights_retention(self):
        rs = records()
        source = SourceRef('原表.xlsx', '小订分时')
        def board(orders, retained):
            page = {'kpis': [kpi('小订', orders), kpi('留存', retained),
                            kpi('退订', orders-retained), kpi('留存率', retained/orders*100)],
                    'sections': []}
            return Dashboard('cancellation', 'm7', {'day': {'pages': {'日期':page}}}, [source])
        with patch('modules.cancellation.generation_records', return_value=rs), \
             patch.object(CancellationModule, '_build_campaign', side_effect=[board(100,90),board(300,150)]):
            result = CancellationModule().build(WorkbookStore(Path('.')), Subject('m7', PARENT, 'generation'))
        view = result.views['day']
        self.assertEqual(len(view['pages']), 3)
        self.assertIn('全部阶段', view['periods'])
        self.assertNotEqual(view['default_period'], '全部阶段')
        values = [c['value'] for c in view['pages']['全部阶段']['kpis']]
        self.assertEqual(values, [400,240,160,60])
        self.assertEqual(len(result.sources), 1)
        with patch('modules.cancellation.generation_records', return_value=rs[:1]), \
             patch.object(CancellationModule, '_build_campaign', return_value=board(100,90)):
            single = CancellationModule().build(WorkbookStore(Path('.')), Subject('m7', PARENT, 'generation'))
        self.assertNotIn('全部阶段', single.views['day']['periods'])


    def test_small_all_phases_with_real_secondary_sheet_names(self):
        mix = Workbook(); mix.active.title=PARENT+'by天'
        mix.active.append(['指标','统计类型','分类',date(2024,5,1),date(2024,8,1)])
        mix.active.append(['小订','数量','数量',100,300])
        cancel = Workbook(); cancel.remove(cancel.active)
        for name,month,quantity in ((ULTRA,5,10),(PRO,8,150)):
            sheet = cancel.create_sheet(name+'_日度退订')
            sheet.append(['日期','当日小订退','累计小订退','当日退订数','小转大率','小订退订率','大定退订率'])
            sheet.append([date(2024,month,1),quantity,quantity,0,0,quantity/1000,0])
            selection = cancel.create_sheet(name + '_选配退订')
            selection.append(['版本退订比例'])
            selection.append(['版本', '小订数', '总退订数', '小订后退订比例', '大定后退订比例', '总退订比例'])
            selection.append(['标准版', 1000, quantity, quantity / 1000, 0, quantity / 1000])
        store = WorkbookStore(Path('.'))
        store.items = [WorkbookItem(Path('小订选配比例分析.xlsx'),mix),WorkbookItem(Path('小订退订分析.xlsx'),cancel)]
        with patch('modules.cancellation.generation_records',return_value=records()), \
             patch('core.model_identity.generation_records',return_value=records()):
            board = CancellationModule().build(store,Subject('m7',PARENT,'generation'))
        self.assertIsNotNone(board)
        view = board.views['day']
        self.assertEqual(len(view['pages']),3)
        self.assertEqual([k['value'] for k in view['pages']['全部阶段']['kpis']],[400,240,160,60])
        self.assertEqual(
            [s['title'] for s in view['pages']['全部阶段']['sections']],
            ['小订阶段对比', 'Ultra版 · 小订期订单节奏', 'Pro版 · 小订期订单节奏'],
        )
        for period in view['periods'][1:]:
            with self.subTest(period=period):
                self.assertEqual(
                    [s['title'] for s in view['pages'][period]['sections']],
                    ['小订期订单节奏', '日度退订趋势', '选配退订率排行'],
                )
        mix.close();cancel.close()


    def make_source(self, root):
        source = root / '小订及首销数据整理.xlsx'
        book = Workbook(); book.active.title = '任意首Sheet名称'
        rows = records(); headers = list(rows[0])
        book.active.append(headers)
        for record in rows: book.active.append([record[k] for k in headers])
        book.save(source); book.close()
        return source


    def test_stage_identity_uses_the_selected_workbook_directory(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            self.make_source(Path(first))
            self.assertEqual([stage_name(row) for row in generation_records(Path(first))], [ULTRA, PRO])
            self.assertEqual(generation_records(Path(second)), [])

    def test_published_database_and_batch_pin(self):
        import json
        import sqlite3
        from contextlib import closing
        from core.model_identity import CampaignNotPublished, PINNED_CAMPAIGN, campaign_batch
        from core.sync import source_signature, copy_stable_inputs, refresh_key
        with TemporaryDirectory() as folder:
            root = Path(folder)
            shared, batch = root / "shared/订单汇总", root / "batch"
            database = root / "database/vehicle-config/campaigns/campaigns.sqlite3"
            shared.mkdir(parents=True)
            database.parent.mkdir(parents=True)
            batch.mkdir()
            # Neither the old workbook nor a stale derived snapshot is a default source.
            self.make_source(shared)
            database.with_name("published.json").write_text("stale", encoding="utf-8")
            env = {"PLANHUB_DATA_ROOT": str(root), "SHARED_DATA_ROOT": str(root / "shared"),
                   "VEHICLE_CONFIG_CAMPAIGN_SNAPSHOT": "", "VEHICLE_CONFIG_CAMPAIGN_DB": ""}
            with patch.dict("os.environ", env):
                with self.assertRaisesRegex(CampaignNotPublished, "请先.*发布"):
                    source_signature(shared)
                self.assertFalse(database.exists())
                with closing(sqlite3.connect(database)) as db:
                    db.executescript("""
                        CREATE TABLE draft(id INTEGER PRIMARY KEY, published_revision INTEGER, data TEXT);
                        CREATE TABLE publications(revision INTEGER PRIMARY KEY, data TEXT);
                        INSERT INTO draft VALUES(1,0,'unpublished');
                    """)
                    with self.assertRaisesRegex(CampaignNotPublished, "请先.*发布"):
                        generation_records(shared)
                    headers = ["代际名", "二级代际名", "开始大定日期"]
                    for revision, stage in [(1, ULTRA), (2, PRO)]:
                        rows = [headers, [PARENT, stage, "2024-05-03"]]
                        data = {"sheets": [{"name": "车型汇总", "rows": rows}]}
                        db.execute("INSERT INTO publications VALUES(?,?)", (revision, json.dumps(data)))
                    db.execute("UPDATE draft SET published_revision=1")
                    db.commit()
                    sig = source_signature(shared)
                    copy_stable_inputs(shared, batch, sig)
                    self.assertEqual(json.loads((batch / PINNED_CAMPAIGN).read_bytes())["revision"], 1)
                    self.assertFalse((batch / "小订及首销数据整理.xlsx").exists())
                    with campaign_batch(shared):
                        db.execute("UPDATE draft SET published_revision=2")
                        db.commit()
                        self.assertEqual(source_signature(shared), sig)
                        self.assertEqual(stage_name(generation_records(shared)[0]), ULTRA)
                    next_sig = source_signature(shared)
                    self.assertNotEqual(refresh_key(next_sig), refresh_key(sig))
                    self.assertEqual(stage_name(generation_records(shared)[0]), PRO)
                    db.execute("UPDATE draft SET data='new draft'")
                    db.commit()
                    self.assertEqual(source_signature(shared), next_sig)
                    with self.assertRaisesRegex(RuntimeError, "已变化"):
                        copy_stable_inputs(shared, batch, sig)
                relocated = database.rename(root / "custom.sqlite3")
                with patch.dict("os.environ", {"VEHICLE_CONFIG_CAMPAIGN_DB": str(relocated)}):
                    self.assertEqual(stage_name(generation_records(shared)[0]), PRO)
                result = generation_records(batch)
                self.assertEqual(stage_name(result[0]), ULTRA)
                self.assertEqual(result[0]["开始大定日期"], datetime(2024, 5, 3))
                with patch.dict("os.environ", {"VEHICLE_CONFIG_CAMPAIGN_SNAPSHOT": str(batch / PINNED_CAMPAIGN)}):
                    self.assertEqual(generation_records(shared), result)

    def test_primary_selector_and_exact_secondary_sheet_pairing(self):
        book = Workbook(); book.remove(book.active)
        # Deliberately reverse file order: hourly sheets must pair by edition.
        for name, month, quantity in ((PRO, 8, 20), (ULTRA, 5, 10)):
            day = book.create_sheet(name + 'by天')
            day.append(['周期', 'D1']); day.append(['时间', datetime(2024, month, 3)])
            day.append(['当日大定数量', quantity])
            hourly = book.create_sheet(name + 'by时')
            hourly.append(['日期', datetime(2024, month, 3)])
            hourly.append(['时刻', 20]); hourly.append(['当日大定数量', quantity])
        store = WorkbookStore(Path('.')); store.items = [WorkbookItem(Path('首销期订单节奏.xlsx'), book)]
        with patch('core.discovery.generation_records', return_value=records()), patch('core.model_identity.generation_records', return_value=records()):
            subjects = discover_subjects(store)
            self.assertEqual([s.name for s in subjects if s.type == 'generation'], [PARENT])
            self.assertEqual(len(store.find_subject_sheets('首销期订单节奏', PARENT, 'day')), 2)
            self.assertEqual(len(store.find_subject_sheets('首销期订单节奏', ULTRA, 'day')), 1)
            board = LaunchRhythmModule().build(store, Subject('m7', PARENT, 'generation', '问界'))
        self.assertTrue(board.views['day']['default_period'].startswith('Pro版 · '))
        self.assertTrue(any(label.startswith('Ultra版 · ') for label in board.views['day']['periods']))
