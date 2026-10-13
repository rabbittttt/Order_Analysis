"""Early cancellation scores must compare the same launch-day quantities."""
import json
from datetime import date
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from core.forecast_summary import D12_SHEET, read_public_forecast, table_records
from modules.sales_forecast import _package_summary_profiles
from tests import test_forecast_reference_backfill as backfill

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class EarlyCancellationScoreTests(unittest.TestCase):
    def score(self, days, reference=(.05, .05, .1), total=20):
        script = r'''
const fs=require('fs'),math=require('./templates/forecast-math.js');
const lines=fs.readFileSync('templates/dashboard.js','utf8').split('\n');
const line=marker=>lines.find(text=>text.includes(marker));
const code=[line('const closeness=(a,b'),line('const averageCloseness='),
  line('const targetD1CancelRate='),line('values.earlyCancel=d1?')].join('\n');
const calculate=new Function('d1','d2','target','item','observed','ratio',
  'const values={};'+code+';return {rates:[targetD1CancelRate,targetD2CancelRate,targetD12CancelRate],score:values.earlyCancel};');
const [d1,d2]=DAYS,ref=REFERENCE;
console.log(JSON.stringify(calculate(d1,d2,{small:TOTAL},
 {d1_cancel_rate:ref[0],d2_cancel_rate:ref[1],d12_cancel_rate:ref[2]},
 math.observedQuantity,math.observedRatio)));
'''.replace('DAYS', json.dumps(days)).replace('REFERENCE', json.dumps(reference)).replace('TOTAL', json.dumps(total))
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_public_summary_carries_daily_and_cumulative_without_recalculation(self):
        fixture = backfill.ForecastReferenceBackfillTests()
        self.addCleanup(fixture.doCleanups)
        book = fixture.build(daily=fixture.quantities(), cancel=[
            {'date': '2026-01-02', 'cancel': 2},
            {'date': '2026-01-03', 'daily_cancel': 1, 'cancel': 3},
            {'date': '2026-01-04', 'daily_cancel': 1, 'cancel': 4},
            {'date': '2026-01-05', 'daily_cancel': 1, 'cancel': 5}])
        with patch('modules.sales_forecast._read_model_mapping', return_value={}), \
             patch('modules.sales_forecast._read_model_master', return_value={}):
            profiles, _, _, _ = read_public_forecast(book, [], today=date(2026, 1, 6))
        profile = _package_summary_profiles(profiles, [{'name': '测试车', 'stage': 'ended'}])[0]
        self.assertEqual([r.get('daily_cancel') for r in profile['days']], [1, 1, 1])
        self.assertEqual([r['cancel'] for r in profile['days']], [3, 4, 5])
        reference = table_records(book, D12_SHEET)[0]
        rates = [reference[k] for k in ('D1退订率', 'D2退订率', 'D1+D2退订率')]
        for stage in ('before', 'active', 'ended', 'unknown'):
            result = self.score(profile['stage_profiles'][stage]['days'][:2], rates)
            self.assertEqual(result, {'rates': rates, 'score': 1})

    def test_prelaunch_baseline_does_not_change_same_daily_evidence(self):
        for baseline in (0, 2, 10, 1000):
            with self.subTest(baseline=baseline):
                result = self.score([{'cancel': baseline+1, 'daily_cancel': 1},
                                     {'cancel': baseline+2, 'daily_cancel': 1}])
                self.assertEqual(result, {'rates': [.05, .05, .1], 'score': 1})

    def test_cumulative_only_is_not_a_daily_observation(self):
        self.assertEqual(self.score([{'cancel': 3}, {'cancel': 4}]),
                         {'rates': [None, None, None], 'score': None})

    def test_missing_d1_does_not_hide_known_d2_or_invent_two_day_total(self):
        result = self.score([{'cancel': None, 'daily_cancel': None},
                             {'cancel': None, 'daily_cancel': 1}])
        self.assertEqual(result, {'rates': [None, .05, None], 'score': 1})

    def test_real_zero_is_valid_without_a_cumulative_snapshot(self):
        result = self.score([{'daily_cancel': 0}, {'daily_cancel': 0}], (0, 0, 0))
        self.assertEqual(result, {'rates': [0, 0, 0], 'score': 1})

    def test_no_terminal_denominator_means_no_rate_not_zero(self):
        for total in (None, 0):
            self.assertEqual(self.score([{'daily_cancel': 1}, {'daily_cancel': 1}], total=total),
                             {'rates': [None, None, None], 'score': None})

    def test_unknown_or_invalid_daily_values_do_not_use_cumulative_fallback(self):
        for value in (None, '', True, -1):
            result = self.score([{'daily_cancel': value, 'cancel': 1},
                                 {'daily_cancel': value, 'cancel': 2}])
            self.assertEqual(result, {'rates': [None, None, None], 'score': None})

    def test_d2_not_completed_keeps_d1_only(self):
        result = self.score([{'daily_cancel': 1, 'cancel': 3}, None])
        self.assertEqual(result, {'rates': [.05, None, None], 'score': 1})
