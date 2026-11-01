"""Bad hourly source rows must not be laundered into valid forecast evidence."""
import inspect
import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
from core.forecast_summary import DAILY_SHEET, SMALL_HOURLY_SHEET, table_records
from modules.sales_forecast import _attach_small_hourly_curves, _read_actual_profiles
from tests import test_forecast_source_backfill_e2e as fixtures
from tests import test_audit_20261026_small_snapshot as runtime

DAY = date(2026, 8, 30)
BAD = {'duplicate':(19,999), 'hour':(24,0), 'negative_hour':(-1,0),
       'fraction_hour':(18.5,0), 'quantity':(20,'待更新'), 'negative':(20,-1), 'boolean':(20,True)}


def populate(book, model, defect=None, only_bad=False):
    sheet = book.create_sheet(model+'_小订分时退订')
    sheet.append(['小订日期','小订小时','小订数'])
    if not only_bad:
        sheet.append([DAY,18,30]); sheet.append([DAY,19,10])
    if defect:
        sheet.append([DAY,*BAD[defect]])
    sheet.append([date(2026,8,31),18,60])


def attach(profile, model):
    item = {'model':model,'small_start_date':DAY.isoformat(),'dates':[DAY.isoformat()],
            'daily_orders':[40],'daily_actual':True}
    with patch('modules.sales_forecast._read_model_mapping',return_value={}):
        _attach_small_hourly_curves([item],[profile],today=date(2026,9,5))
    return item['small_hourly_curve']


class SmallHourQualityTests(TestCase):
    def read(self, defect=None, only_bad=False):
        book=Workbook();model='测试车';populate(book,model,defect,only_bad);self.addCleanup(book.close)
        item=SimpleNamespace(path=Path('小订退订分析.xlsx'),workbook=book)
        store=SimpleNamespace(find=lambda key:item if key=='小订退订分析' else None)
        with patch('modules.sales_forecast._read_model_mapping',return_value={}):
            profiles,_=_read_actual_profiles(store)
        return profiles[0],model

    def test_invalid_points_cannot_become_valid_reference_after_filtering(self):
        for defect in BAD:
            with self.subTest(defect=defect):
                profile,model=self.read(defect);bucket=profile['small_hourly_days'][0]
                self.assertFalse(bucket.get('hourly_valid',True))
                self.assertIsNone(bucket['orders'])
                self.assertEqual([(r['hour'],r['orders']) for r in bucket['hours']],[(18,30),(19,10)])
                profile['small_daily_days'][0]['orders']=40
                self.assertEqual(attach(profile,model),[])

    def test_entirely_invalid_date_remains_explicitly_unusable(self):
        profile,_=self.read('hour',True)
        bucket=next(r for r in profile['small_hourly_days'] if r['date']==DAY.isoformat())
        self.assertFalse(bucket['hourly_valid']);self.assertEqual(bucket['hours'],[])
        self.assertIsNone(bucket['orders'])

    def test_other_date_and_independent_real_zero_are_preserved(self):
        profile,model=self.read('duplicate');valid=profile['small_hourly_days'][1]
        self.assertTrue(valid.get('hourly_valid',True));self.assertEqual(valid['orders'],60)
        profile['small_daily_days'][0]['orders']=0
        self.assertEqual(attach(profile,model),[])
        self.assertEqual(profile['small_daily_days'][0]['orders'],0)

    def test_normal_sparse_hours_keep_current_results(self):
        profile,model=self.read()
        self.assertEqual(attach(profile,model)[18:20],[.75,1])
        self.assertEqual(profile['small_hourly_days'][0]['orders'],40)

    def test_supported_integer_hour_formats_remain_valid(self):
        for value in (18,18.0,'18','18.0','18时','18:00','18:00:00'):
            with self.subTest(value=value):
                book=Workbook();model='测试车';sheet=book.active
                sheet.title=model+'_小订分时退订';sheet.append(['小订日期','小订小时','小订数'])
                sheet.append([DAY,value,40]);item=SimpleNamespace(path=Path('小订退订分析.xlsx'),workbook=book)
                store=SimpleNamespace(find=lambda key:item if key=='小订退订分析' else None)
                with patch('modules.sales_forecast._read_model_mapping',return_value={}):
                    profiles,_=_read_actual_profiles(store)
                self.assertEqual(attach(profiles[0],model)[18],1)
                book.close()


class SmallHourPublicTests(TestCase):
    def build(self, defect=None, only_bad=False):
        fixture=fixtures.SourceBackfillEndToEndTests();self.addCleanup(fixture.doCleanups)
        def add(folder):
            path=folder/'鸿蒙智行小订退订分析.xlsx';book=load_workbook(path)
            populate(book,fixture.model,defect,only_bad);book.save(path);book.close()
        book=fixture.build(add_sources=add)
        _,profiles,_,_,_=fixture.web_inputs(book,date(2026,9,5))
        return fixture,book,next(r for r in profiles if r['model']==fixture.model)

    def test_saved_quality_and_daily_priority_survive_public_read(self):
        for defect in ('duplicate','hour','quantity'):
            with self.subTest(defect=defect):
                fixture,book,profile=self.build(defect)
                bad=[r for r in table_records(book,SMALL_HOURLY_SHEET) if str(r['日期'])[:10]==DAY.isoformat()]
                self.assertTrue(bad)
                self.assertTrue(all(r.get('分时口径状态') and r['分时口径状态']!='有效' for r in bad))
                self.assertEqual([r['小时小订'] for r in bad],[30,10])
                bucket=next(r for r in profile['small_hourly_days'] if r['date']==DAY.isoformat())
                self.assertFalse(bucket.get('hourly_valid',True));self.assertIsNone(bucket['orders'])
                self.assertEqual(attach(profile,fixture.model),[])
                daily={str(r['日期'])[:10]:r for r in table_records(book,DAILY_SHEET)}
                self.assertEqual(daily[DAY.isoformat()]['小订数量'],40)
                self.assertIn('小订及首销数据整理.xlsx',daily[DAY.isoformat()]['字段来源'])
                self.assertEqual(next(r for r in profile['small_daily_days'] if r['date']==DAY.isoformat())['orders'],40)

    def test_quality_only_date_survives_public_read(self):
        _,book,profile=self.build('hour',True)
        bucket=next(r for r in profile['small_hourly_days'] if r['date']==DAY.isoformat())
        self.assertFalse(bucket['hourly_valid']);self.assertEqual(bucket['hours'],[])
        self.assertIsNone(bucket['orders'])

    def test_valid_public_and_legacy_no_quality_column_stay_compatible(self):
        fixture,book,profile=self.build()
        self.assertEqual(attach(profile,fixture.model)[18:20],[.75,1])
        sheet=book[SMALL_HOURLY_SHEET];headers=[c.value for c in sheet[1]]
        if '分时口径状态' in headers:sheet.delete_cols(headers.index('分时口径状态')+1)
        _,profiles,_,_,_=fixture.web_inputs(book,date(2026,9,5))
        self.assertEqual(attach(next(r for r in profiles if r['model']==fixture.model),fixture.model)[18:20],[.75,1])

    @skipUnless(shutil.which('node'),'Node.js required')
    def test_public_quality_reaches_current_d1_runtime(self):
        _,_,profile=self.build('duplicate')
        bucket=next(r for r in profile['small_hourly_days'] if r['date']==DAY.isoformat())
        # Reuse the existing production-binder harness, only extending fixture
        # transport with the quality fields; no production logic is mocked.
        source=inspect.getsource(runtime.SmallOrderSnapshotFloorTests.run_cases).lstrip()
        source=source.replace('hours:input.hours??[]','hours:input.hours??[],hourly_valid:input.hourly_valid,hourly_status:input.hourly_status')
        namespace=dict(vars(runtime));exec(source,namespace)
        cases=[{'today':'2026-09-01','fixed':[],'day':daily,'hour':400,
                'hours':bucket['hours'],'hourly_valid':bucket.get('hourly_valid'),
                'hourly_status':bucket.get('hourly_status')} for daily in (40,0,None)]
        results=namespace['run_cases'](self,cases)
        for result,actual in zip(results,('40','0','—')):
            self.assertIn('分时',result['error']);self.assertEqual(result['actual'],actual)
            self.assertFalse(any(row['actual'] is False for row in result['rows']))
