from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required')
class ForecastWindowSafetyTests(unittest.TestCase):
    def run_js(self, checks):
        subprocess.run(['node', '-e', "const assert=require('assert'),m=require('./templates/forecast-math.js');\n" + checks],
                       cwd=ROOT, check=True, capture_output=True, text=True, encoding='utf-8')

    def test_invalid_large_days_never_throw_or_fabricate_iso_dates(self):
        self.run_js("""
for(const days of [1e20,Number.MAX_SAFE_INTEGER,1e8,Infinity]){
 const windows=m.forecastWindows({launch_date:'2026-09-01',small_start_date:'2026-08-01'},{days,smallDays:days});
 assert.equal(windows.endDate,'');assert.equal(windows.smallEndDate,'');
 assert.equal(m.launchStage({launchDate:'2026-09-01',days},'2026-09-02').key,'unknown');
}
""")

    def test_derived_dates_stay_in_supported_four_digit_year_domain(self):
        self.run_js("""
const w=m.forecastWindows({launch_date:'9999-12-31',small_start_date:'9999-12-31'},{days:2,smallDays:2});
assert.equal(w.endDate,'');assert.equal(w.smallEndDate,'');assert.equal(w.steadyStartDate,'');
assert.equal(m.launchStage({launchDate:'9999-12-31',days:2},'9999-12-31').key,'unknown');
""")

    def test_valid_cross_year_leap_day_and_explicit_window_are_unchanged(self):
        self.run_js("""
assert.equal(m.forecastWindows({launch_date:'2026-12-31',days:2}).endDate,'2027-01-01');
assert.equal(m.forecastWindows({launch_date:'2028-02-28',days:3}).endDate,'2028-03-01');
assert.equal(m.forecastWindows({launch_date:'2026-09-01',days:30,end_date:'2026-09-20'}).endDate,'2026-09-20');
assert.equal(m.launchStage({launchDate:'2026-09-01',endDate:'2026-09-20',days:30},'2026-09-03').days,20);
""")

    def test_empty_invalid_and_zero_days_remain_unavailable(self):
        self.run_js("""
for(const days of ['',null,0,-1,1.5,true,'bad']){
 const windows=m.forecastWindows({launch_date:'2026-09-01'},{days});
 assert.equal(windows.endDate,'');assert.equal(m.launchStage({launchDate:'2026-09-01',days},'2026-09-02').key,'unknown');
}
""")


if __name__ == '__main__':
    unittest.main()
