from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for forecast math numeric tests")
class ForecastMathTests(unittest.TestCase):
    def test_missing_primary_conversion_does_not_dilute_valid_auxiliary(self):
        from modules.sales_forecast import _history_item
        primary = _history_item({'传播名':'X6M', '小订转化率':None}, True)
        auxiliary = _history_item({'传播名':'V9', '小订转化率':.413}, True)
        rows = [{'item':primary, 'weight':70}, {'item':auxiliary, 'weight':30}]
        result = self.run_node(f"m.referenceParameter({json.dumps(rows)}, 'conversion')")
        self.assertAlmostEqual(result['value'], .413)
        self.assertEqual(result['used'][0]['effectiveWeight'], 1)
        self.assertEqual(result['excluded'][0]['item']['model'], 'X6M')

    def test_reference_rates_skip_missing_and_invalid_without_discarding_zero(self):
        for field in ('conversion', 'direct_share', 'lock_rate', 'net_rate', 'cancel_rate'):
            for missing in ('null', 'undefined', "''", 'NaN', '-1', '1.1'):
                expression = f"m.referenceParameter([{{item:{{{field}:{missing}}},weight:70}},{{item:{{{field}:.6}},weight:30}}],'{field}').value"
                self.assertAlmostEqual(self.run_node(expression), .6)
        self.assertAlmostEqual(self.run_node("m.referenceParameter([{item:{conversion:0},weight:70},{item:{conversion:.4},weight:30}],'conversion').value"), .12)
        self.assertIsNone(self.run_node("m.referenceParameter([{item:{conversion:null},weight:70}],'conversion',.5).value"))
        self.assertAlmostEqual(self.run_node("m.referenceParameter([{item:{conversion:.4,quality_issues:'小订转化率不一致'},weight:70},{item:{conversion:.6},weight:30}],'conversion').value"), .6)
        self.assertAlmostEqual(self.run_node("m.referenceParameter([{item:{direct_share:.98},weight:70},{item:{direct_share:.96},weight:30}],'direct_share').value"), .974)
        self.assertIsNone(self.run_node("m.referenceParameter([{item:{direct_share:1},weight:70}],'direct_share').value"))

    def test_weighted_observations_distinguish_blank_and_zero(self):
        self.assertEqual(self.run_node("m.weightedObserved([{value:null,weight:70},{value:10,weight:30}])"), 10)
        self.assertEqual(self.run_node("m.weightedObserved([{value:0,weight:70},{value:10,weight:30}])"), 3)

    def test_editable_windows_derive_ends_and_keep_unmodified_explicit_dates(self):
        configured = {'launch_date':'2026-09-01', 'days':30, 'end_date':'2026-09-30',
                      'small_start_date':'2026-08-01', 'small_days':20, 'small_end_date':'2026-08-20'}
        original = self.run_node(f'm.forecastWindows({json.dumps(configured)})')
        self.assertEqual(original['endDate'], '2026-09-30')
        self.assertFalse(original['launchChanged'])
        edited = self.run_node(f'm.forecastWindows({json.dumps(configured)},{{days:10,smallStartDate:"2026-08-02",smallDays:5}})')
        self.assertEqual(edited['endDate'], '2026-09-10')
        self.assertEqual(edited['steadyStartDate'], '2026-09-11')
        self.assertEqual(edited['smallEndDate'], '2026-08-06')
        self.assertTrue(edited['launchChanged'])
        self.assertTrue(edited['smallChanged'])
        empty = self.run_node(f'm.forecastWindows({json.dumps(configured)},{{days:""}})')
        self.assertEqual(empty['endDate'], '')
        self.assertEqual(empty['steadyStartDate'], '')

    def test_later_publication_time_never_discards_real_observations(self):
        result = self.run_node("m.smallHourlyForecast({hours:[{hour:18,orders:40},{hour:19,orders:40}],startHour:20,references:[{item:{small_start_hour:18,small_hourly_curve:[...Array(18).fill(null),.2,.4,.6,.8,.9,1]},weight:100}]})")
        self.assertEqual(result['observed'], 80)
        self.assertEqual(result['total'], 200)

    def test_completion_stretch_preserves_four_edge_days_and_middle_mass(self):
        source = [.2, .3, .35, .42, .5, .58, .65, .75, .85, 1]
        for length in (5, 8, 10, 18, 90):
            result = self.run_node(f"m.stretchCompletion({json.dumps(source)},{length})")
            self.assertEqual(len(result), length)
            self.assertEqual(result[:2], source[:2])
            self.assertAlmostEqual(result[-2], .85)
            self.assertAlmostEqual(result[-1], 1)
            self.assertAlmostEqual(result[-3], .75)
            self.assertTrue(all(a <= b for a, b in zip(result, result[1:])))

    def test_completion_stretch_rejects_incompatible_short_or_missing_curves(self):
        self.assertEqual(self.run_node("m.stretchCompletion([.2,.4,.8,1],8)"), [])
        self.assertEqual(self.run_node("m.stretchCompletion([.2,.4,.8,1],4)"), [.2,.4,.8,1])
        self.assertEqual(self.run_node("m.stretchCompletion([.1,.2,null,.8,1],10)"), [])
        self.assertEqual(self.run_node("m.stretchCompletion([.1,.4,.3,.8,1],10)"), [])

    def test_full_launch_baseline_retains_early_and_middle_observations(self):
        result = self.run_node("(()=>{const rows=Array.from({length:30},(_,i)=>({date:'2026-09-'+String(i+1).padStart(2,'0'),direct:i===0?300:30,gross:500,lock:400}));const args={rows,launchDate:'2026-09-01',endDate:'2026-09-30',today:'2026-10-01'};const a=m.launchDirectLockBaseline(args);rows[10].direct=400;return [a,m.launchDirectLockBaseline(args)];})()")
        self.assertEqual(result[0]['days'], 30)
        self.assertNotEqual(result[0]['level'], result[1]['level'])
        self.assertNotEqual(result[0]['ratio'], result[1]['ratio'])

    def test_steady_reference_compares_shape_not_absolute_sales(self):
        result = self.run_node("(()=>{const base={tier:'SUV',energy:'增程',node:'新车',lock_rate:.8,direct_curve:[10,8,6,4,2],steady_curve:[5,4,3]};const target={tier:'SUV',energy:'增程',node:'新车'},current={...base,launch_days:5};return [m.steadyReferenceScore(base,target,current),m.steadyReferenceScore({...base,direct_curve:base.direct_curve.map(v=>v*100),steady_curve:base.steady_curve.map(v=>v*100)},target,current),m.steadyReferenceScore({...base,direct_curve:[2,4,6,8,10]},target,current)];})()")
        self.assertTrue(result[0]['eligible'])
        self.assertAlmostEqual(result[0]['score'], result[1]['score'])
        self.assertGreater(result[0]['score'], result[2]['score'])

    def test_launch_hourly_adapter_preserves_release_hour_and_absolute_invariance(self):
        result = self.run_node("(()=>{const hours=[{hour:18,orders:40},{hour:19,orders:40}],curve=[...Array(18).fill(0),.2,.4,.6,.8,.9,1];return [100,100000].map(d1_gross=>m.smallHourlyForecast({hours,references:[{item:m.launchHourlyItem({hourly_curve:curve,d1_gross}),weight:100}]}));})()")
        self.assertEqual(result[0], result[1])
        self.assertEqual(result[0]['total'], 200)
        self.assertTrue(all(v is None for v in result[0]['actual'][:18]))

    def test_shared_import_keeps_separate_small_and_gross_columns(self):
        importer = json.dumps(str(ROOT / "templates" / "forecast-import.js"))
        result = self.run_node(f"require({importer}).normalize([['车型','日期','预测小订','预测大定'],['A','2026-09-01',0,120],['A','2026-09-02','',150]])")
        self.assertEqual(result, [{'model':'A','date':'2026-09-01','small':0,'gross':120},{'model':'A','date':'2026-09-02','gross':150}])


    def test_small_hourly_prediction_uses_shape_and_freezes_observations(self):
        expression = "(()=>{const item={small_start_hour:18,small_hourly_curve:[...Array(18).fill(null),.2,.4,.6,.8,.9,1]},hours=[{hour:18,orders:40},{hour:19,orders:40}];return [100,100000].map(total=>m.smallHourlyForecast({hours,references:[{item:{...item,total,d1_gross:total},weight:100}]}))})()"
        low, high = self.run_node(expression)
        self.assertEqual(low, high)
        self.assertEqual(low['observed'], 80)
        self.assertEqual(low['total'], 200)
        self.assertEqual(low['remaining'], 120)
        self.assertEqual(sum(value or 0 for value in low['predictedHours']), 120)
        self.assertTrue(all(value is None for value in low['actual'][:18]))
        self.assertEqual(low['forecast'][-1], 1)

    def test_small_hourly_score_ignores_absolute_size_and_prefers_shape_time(self):
        result = self.run_node("(()=>{const curve=[...Array(18).fill(null),.2,.4,.6,.8,.9,1],current={hours:[{hour:18,orders:40},{hour:19,orders:40}],startHour:18};return {same:m.smallHourlyReferenceScore({total:1,small_start_hour:18,small_hourly_curve:curve},current),huge:m.smallHourlyReferenceScore({total:100000,small_start_hour:18,small_hourly_curve:curve},current),different:m.smallHourlyReferenceScore({small_start_hour:8,small_hourly_curve:[...Array(8).fill(null),.8,...Array(15).fill(1)]},current)}})()")
        self.assertEqual(result['same']['score'], result['huge']['score'])
        self.assertGreater(result['same']['score'], result['different']['score'])
        self.assertEqual({part['key'] for part in result['same']['parts']}, {'release_hour', 'hour_slope', 'hour_progress'})

    def test_intraday_missing_components_conserve_observed_gross(self):
        for snapshot in ("{gross:100}", "{gross:100,small_to_big:0,direct:0}", "{gross:100,small_to_big:60,direct:40}"):
            result = self.run_node(f"m.intradayComponents({snapshot},.5,.6)")
            self.assertEqual(result['gross'], 200)
            self.assertEqual(result['small'] + result['direct'], 200)
            self.assertEqual(result['observedSmall'] + result['observedDirect'], 100)
        result = self.run_node("m.intradayComponents({gross:100,small_to_big:0},.5,.6)")
        self.assertEqual(result['observedSmall'], 0)
        self.assertEqual(result['observedDirect'], 100)
        self.assertEqual(self.run_node("m.intradayComponents(null,1,.6).gross"), 0)

    def test_hourly_same_day_denominator_and_duplicate_hours(self):
        result = self.run_node("m.hourlyComparison({date:'2026-09-01',hours:[{hour:8,gross:20},{hour:8,gross:30},{hour:9,gross:50}]},{today:'2026-09-02',dailyTotal:200})")
        self.assertEqual(result['actual'][8], .25)
        self.assertEqual(result['actual'][9], .5)
        self.assertIsNone(result['actual'][23])
        self.assertTrue(all(value is None for value in result['forecast']))
        future = self.run_node("m.hourlyComparison({date:'2026-09-03',hours:[{hour:8,gross:100}]},{today:'2026-09-02'})")
        self.assertTrue(all(value is None for value in future['actual']))

    def test_intraday_estimates_never_replace_observed_components(self):
        for snapshot, known_small, known_direct, observed in (
            ('{gross:100,small_to_big:70,direct:20}', 70, 20, 100),
            ('{gross:100,small_to_big:70,direct:40}', 70, 40, 110),
            ('{small_to_big:70,direct:20}', 70, 20, 90),
        ):
            with self.subTest(snapshot=snapshot):
                result = self.run_node(f'm.intradayComponents({snapshot},.9,.1)')
                self.assertGreaterEqual(result['observedSmall'], known_small)
                self.assertGreaterEqual(result['observedDirect'], known_direct)
                self.assertGreaterEqual(result['small'], known_small)
                self.assertGreaterEqual(result['direct'], known_direct)
                self.assertEqual(result['observedSmall'] + result['observedDirect'], observed)
                self.assertEqual(result['small'] + result['direct'], result['gross'])

    def test_intraday_floor_conserves_remaining_or_raises_to_actual(self):
        result = self.run_node("m.applyObservedFloor([10,20,30],40)")
        self.assertEqual(result['values'][0], 40)
        self.assertEqual(sum(result['values']), 60)
        self.assertEqual(result['raised'], 0)
        self.assertEqual(self.run_node("m.applyObservedFloor([10,20,30],90)"), {'values':[90,0,0], 'raised':30})

    def test_intraday_reference_uses_completed_non_d1_same_calendar_days(self):
        result = self.run_node("m.intradayReference({today:'2026-09-05',launchDate:'2026-09-01',dayType:d=>['2026-09-03','2026-09-05'].includes(d)?'holiday':'workday',days:[1,2,3,4,5].map(n=>({date:'2026-09-0'+n,gross:100})),buckets:[1,2,3,4,5].map(n=>({date:'2026-09-0'+n,hours:[{hour:n,gross:100}]}))})")
        self.assertEqual(result['days'], 1)
        self.assertTrue(result['sameType'])
        self.assertEqual(result['curve'][:5], [0,0,0,1,1])
        self.assertEqual(result['curve'][-1], 1)

    def run_node(self, expression: str):
        module = json.dumps(str(ROOT / "templates" / "forecast-math.js"))
        result = subprocess.run(
            ["node", "-e", f"const m=require({module});console.log(JSON.stringify({expression}))"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return json.loads(result.stdout)

    def test_default_bridge_weights_are_bounded_for_any_horizon(self):
        self.assertEqual(self.run_node("m.defaultBridgeWeights(0)"), [])
        self.assertEqual(self.run_node("m.defaultBridgeWeights(1)"), [0])
        self.assertEqual(self.run_node("m.defaultBridgeWeights(2)"), [0, .5])
        self.assertEqual(self.run_node("m.defaultBridgeWeights(30)"), [0, .5] + [1] * 28)

    def test_launch_direct_lock_uses_completed_days_and_same_window_rate(self):
        result = self.run_node("m.launchDirectLockBaseline({launchDate:'2026-09-01',endDate:'2026-09-03',today:'2026-09-03',rows:[{date:'2026-09-01',direct:40,gross:100,lock:80},{date:'2026-09-02',direct:60,gross:100,lock:80},{date:'2026-09-03',direct:999,gross:999,lock:999}]})")
        self.assertTrue(result['available'])
        self.assertEqual(result['days'], 2)
        self.assertAlmostEqual(result['level'], 40)
        self.assertEqual(result['ratio'], 1)

    def test_launch_direct_lock_missing_is_not_zero_or_historical(self):
        result = self.run_node("m.launchDirectLockBaseline({launchDate:'2026-09-01',endDate:'2026-09-03',today:'2026-09-02',rows:[{date:'2026-09-01',direct:null,gross:100,lock:80}]})")
        self.assertFalse(result['available'])
        self.assertIsNone(result['level'])

    def test_steady_daily_uses_even_one_actual_day_and_keeps_zero(self):
        for value in (0, 150):
            result = self.run_node("m.recentSteadyBaseline({startDate:'2026-09-01',today:'2026-09-02',factor:()=>1.5,rows:[{date:'2026-09-01',lock:" + str(value) + "},{date:'2026-09-02',lock:999}]})")
            self.assertTrue(result['available'])
            self.assertEqual(result['level'], value / 1.5)
            self.assertEqual(result['days'], 1)

    def test_steady_daily_does_not_bridge_missing_yesterday(self):
        result = self.run_node("m.recentSteadyBaseline({startDate:'2026-09-01',today:'2026-09-03',rows:[{date:'2026-09-01',lock:100},{date:'2026-09-02',lock:null}]})")
        self.assertFalse(result['available'])

    def test_daily_slope_is_adjacent_change_and_preserves_gaps(self):
        result = self.run_node("m.dailySlope([100,80,0,50,null,60,90])")
        self.assertIsNone(result[0])
        self.assertAlmostEqual(result[1], -.2)
        self.assertEqual(result[2], -1)
        self.assertEqual(result[3:6], [None, None, None])
        self.assertEqual(result[6], .5)

    def test_bounded_bridge_matches_example_and_keeps_tail_shape(self):
        result = self.run_node("m.anchoredAllocate({remaining:350,anchor:100,shapes:[1,.8,.6,.4],factors:[1,1,1,1],weights:m.defaultBridgeWeights(4)})")
        self.assertEqual(result['values'], [100,100,90,60])
        self.assertEqual(sum(result['values']), 350)

    def test_small_days_need_only_completed_dates_not_final_total(self):
        result = self.run_node("m.completedSmallOrderDays('2026-09-01','2026-09-10','2026-09-03',[{date:'2026-09-01',orders:100},{date:'2026-09-02',orders:0},{date:'2026-09-03',orders:999}])")
        self.assertEqual(result['expected'], 2)
        self.assertEqual(result['missing'], [])
        self.assertEqual([row['orders'] for row in result['rows']], [100, 0])

    def test_small_days_do_not_compress_gaps_or_turn_null_into_zero(self):
        result = self.run_node("m.completedSmallOrderDays('2026-09-01','2026-09-10','2026-09-04',[{date:'2026-09-01',orders:null},{date:'2026-09-03',orders:30}])")
        self.assertEqual(result['missing'], ['D1', 'D2'])
        self.assertEqual(result['rows'][0]['label'], 'D3')

    def test_small_days_fallback_is_by_absolute_date(self):
        result = self.run_node("m.completedSmallOrderDays('2026-09-01','2026-09-10','2026-09-03',[{date:'2026-09-01',orders:100}],[{date:'2026-09-01',orders:900},{date:'2026-09-02',orders:200}])")
        self.assertEqual([row['orders'] for row in result['rows']], [100, 200])
        self.assertEqual(result['missing'], [])

    def test_small_d1_does_not_require_completed_days(self):
        result = self.run_node("m.completedSmallOrderDays('2026-09-01','2026-09-10','2026-09-01',[])")
        self.assertEqual(result['expected'], 0)
        self.assertEqual(result['missing'], [])

    def test_bridge_preserves_first_day_and_total(self):
        result = self.run_node("m.anchoredAllocate({remaining:3600,anchor:1000,anchorShape:1,shapes:[.9,.8,.7,.6],factors:[1,1,1,1],weights:[0,20,35,45]})")
        self.assertEqual(result['values'][0],900)
        self.assertEqual(sum(result['values']),3600)
        self.assertEqual(result['error'],'')

    def test_bridge_calendar_removes_anchor_factor_before_applying_future_factor(self):
        result = self.run_node("m.anchoredAllocate({remaining:1900,anchor:1200,anchorFactor:1.2,anchorShape:1,shapes:[.9,.8],factors:[1.2,1],weights:[0,1]})")
        self.assertEqual(result['values'],[1080,820])

    def test_bridge_negative_difference_never_creates_negative_days(self):
        result = self.run_node("m.anchoredAllocate({remaining:200,anchor:1000,shapes:[.9,.8,.7],factors:[1,1,1],weights:[0,1,2]})")
        self.assertEqual(sum(result['values']),200)
        self.assertTrue(all(value>=0 for value in result['values']))
        self.assertTrue(result['warnings'])

    def test_manual_bridge_weights_change_distribution_not_total(self):
        a = self.run_node("m.anchoredAllocate({remaining:2000,anchor:1000,shapes:[.9,.8],factors:[1,1],weights:[0,1]})")
        b = self.run_node("m.anchoredAllocate({remaining:2000,anchor:1000,shapes:[.9,.8],factors:[1,1],weights:[1,0]})")
        self.assertEqual(a['values'],[900,1100])
        self.assertEqual(b['values'],[1200,800])

    def test_bridge_rejects_all_zero_adjustment_weights(self):
        result = self.run_node("m.anchoredAllocate({remaining:2000,anchor:1000,shapes:[.9,.8],factors:[1,1],weights:[0,0]})")
        self.assertTrue(result['error'])

    def test_bridge_last_day_absorbs_remaining_with_warning(self):
        result = self.run_node("m.anchoredAllocate({remaining:300,anchor:1000,shapes:[.9],factors:[1],weights:[0]})")
        self.assertEqual(result['values'],[300])
        self.assertTrue(result['warnings'])

    def test_completion_floor_is_transparent(self):
        result = self.run_node("m.protectCompletion(0.002)")
        self.assertTrue(result["valid"])
        self.assertTrue(result["clamped"])
        self.assertEqual(result["raw"], 0.002)
        self.assertEqual(result["applied"], 0.005)

    def test_normal_completion_is_not_modified(self):
        result = self.run_node("m.protectCompletion(0.35)")
        self.assertFalse(result["clamped"])
        self.assertEqual(result["applied"], 0.35)

    def test_integer_distribution_preserves_total(self):
        result = self.run_node("m.distributeInteger(101,[1,2,3])")
        self.assertEqual(sum(result), 101)
        self.assertEqual(len(result), 3)

    def test_unmaintained_attributes_are_not_valid_evidence(self):
        result = self.run_node("[m.isKnownAttribute('未维护'),m.isKnownAttribute('待维护'),m.isKnownAttribute('SUV')]")
        self.assertEqual(result, [False, False, True])

    def test_small_reference_requires_three_valid_evidence_items(self):
        insufficient = self.run_node(
            "m.smallReferenceScore({tier:'SUV',energy:'增程',total:100},"
            "{tier:'SUV',energy:'增程',node:'未维护',smallDays:0},{total:0},3)"
        )
        eligible = self.run_node(
            "m.smallReferenceScore({tier:'SUV',energy:'增程',node:'年度换代',total:100},"
            "{tier:'SUV',energy:'增程',node:'年度换代',smallDays:0},{total:0},3)"
        )
        self.assertEqual(insufficient["evidenceCount"], 2)
        self.assertFalse(insufficient["eligible"])
        self.assertEqual(eligible["evidenceCount"], 3)
        self.assertTrue(eligible["eligible"])

    def test_steady_reference_requires_three_valid_evidence_items(self):
        insufficient = self.run_node(
            "m.steadyReferenceScore({tier:'SUV',energy:'增程'},"
            "{tier:'SUV',energy:'增程',node:'未维护'},{},3)"
        )
        eligible = self.run_node(
            "m.steadyReferenceScore({tier:'SUV',energy:'增程',node:'年度换代'},"
            "{tier:'SUV',energy:'增程',node:'年度换代'},{},3)"
        )
        self.assertEqual(insufficient["evidenceCount"], 2)
        self.assertFalse(insufficient["eligible"])
        self.assertEqual(eligible["evidenceCount"], 3)
        self.assertFalse(eligible["eligible"])  # Metadata alone cannot establish a trend match.


    def launch_daily(self, expression, values=None):
        item = {'days': 40, 'launch_date': '2026-09-01', 'end_date': '2026-10-10',
                'daily_orders': [100]+[10]*39}
        item.update(values or {})
        return self.run_node(expression.replace('ITEM', json.dumps(item)))

    def test_partial_launch_daily_curve_is_not_stretched_into_full_cycle(self):
        result = self.launch_daily("m.launchDailyReference(ITEM,'2026-10-11')", {'daily_orders':[100]+[10]*19})
        self.assertFalse(result['available'])
        self.assertEqual(len(result['observed']), 20)
        self.assertEqual(result['orders'], [])
        self.assertEqual(self.launch_daily("m.adaptLaunchDailyOrders(ITEM,40,'2026-10-11')", {'daily_orders':[100]+[10]*19}), [])

    def test_ongoing_launch_is_excluded_even_if_future_cells_have_values(self):
        result = self.launch_daily("m.launchDailyReference(ITEM,'2026-09-21')")
        self.assertFalse(result['available'])
        self.assertEqual(result['reason'], '首销期尚未结束')
        self.assertEqual(len(result['observed']), 20)
        self.assertEqual(self.launch_daily("m.adaptLaunchDailyOrders(ITEM,40,'2026-09-21')"), [])

    def test_launch_final_day_is_not_yet_a_completed_reference(self):
        result = self.launch_daily("m.launchDailyReference(ITEM,'2026-10-10')")
        self.assertFalse(result['available'])
        self.assertEqual(len(result['observed']), 39)
        self.assertTrue(self.launch_daily("m.launchDailyReference(ITEM,'2026-10-11')")['available'])

    def test_complete_daily_reference_preserves_edge_days_mass_and_zeros(self):
        item = {'days':8, 'launch_date':'2026-09-01', 'end_date':'2026-09-08', 'daily_orders':[100,20,0,10,15,5,25,35]}
        same = self.launch_daily("m.adaptLaunchDailyOrders(ITEM,8,'2026-09-09')", item)
        for value, expected in zip(same, item['daily_orders']):
            self.assertAlmostEqual(value, expected)
        stretched = self.launch_daily("m.adaptLaunchDailyOrders(ITEM,12,'2026-09-09')", item)
        self.assertAlmostEqual(sum(stretched), sum(item['daily_orders']))
        for actual, expected in zip(stretched[:2]+stretched[-2:], [100,20,25,35]):
            self.assertAlmostEqual(actual, expected)

    def test_daily_reference_rejects_gaps_invalid_counts_and_bad_windows(self):
        for value in (None, '', -1, True):
            with self.subTest(value=value):
                self.assertFalse(self.launch_daily("m.launchDailyReference(ITEM,'2026-10-11')", {'daily_orders':[100,value]+[10]*38})['available'])
        for change in ({'days':0}, {'days':39}, {'launch_date':''}, {'end_date':''}, {'end_date':'2026-02-30'}):
            self.assertFalse(self.launch_daily("m.launchDailyReference(ITEM,'2026-10-11')", change)['available'])

    def daily_runtime(self, expression):
        script = (ROOT / 'templates' / 'dashboard.js').read_text(encoding='utf-8')
        declarations = [next(line.strip() for line in script.splitlines() if line.strip().startswith('const '+name+'='))
                        for name in ('adaptedDailyOrders', 'dailyUnavailable', 'rankedForTask', 'dailyShape')]
        valid = {'model':'完整参考', 'days':40, 'launch_date':'2026-09-01', 'end_date':'2026-10-10',
                 'daily_orders':[100]+[10]*39}
        partial = dict(valid, model='未收齐参考', daily_orders=[100]+[10]*19)
        return self.run_node("(()=>{const window={ForecastMath:m},todayIso=()=> '2026-10-11',minimumScoreCoverage=.45;"
            + 'const valid='+json.dumps(valid)+',partial='+json.dumps(partial)+';'
            + "const historyList=[partial,valid],scoredForTask=()=>historyList.map(item=>({item,summary:{coverage:1}}));"
            + "const historicalFactor=()=>1,slotWeight=index=>index===0?.7:.3,genericDailyShape=m.genericDailyShape;"
            + ''.join(declarations) + 'return '+expression+';})()')

    def test_page_recommendation_excludes_partial_daily_reference(self):
        result = self.daily_runtime("rankedForTask('daily',{days:40}).map(row=>row.item.model)")
        self.assertEqual(result, ['完整参考'])

    def test_stale_manual_partial_reference_does_not_dilute_valid_daily_shape(self):
        result = self.daily_runtime("[dailyShape([partial,valid],5,40),dailyShape([valid],5,40),adaptedDailyOrders(partial,40)]")
        self.assertAlmostEqual(result[0], result[1])
        self.assertEqual(result[2], [])


if __name__ == "__main__":
    unittest.main()
