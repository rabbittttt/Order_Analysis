from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for forecast math numeric tests")
class ForecastMathTests(unittest.TestCase):
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
        self.assertTrue(eligible["eligible"])


if __name__ == "__main__":
    unittest.main()
