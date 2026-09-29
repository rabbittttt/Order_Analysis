const assert = require('assert');
const fs = require('fs');
const path = require('path');

const script = fs.readFileSync(path.join(__dirname, '../templates/dashboard.js'), 'utf8');
const start = script.indexOf('const quickBrandOrder=');
const end = script.indexOf('function syncTopbarQuickLayout()', start);
assert(start >= 0 && end > start, 'quick-generation selector not found');
const select = new Function('DATA', `${script.slice(start, end)}\nreturn latestQuickGenerations().map(item=>item.name);`);

const names = [
  '问界 F2N 2026款汇总',
  '问界 M5 2025款', '问界 M5 增程 2022款', '问界 M5 增程智驾版 2023款',
  '问界 M5 增程标准版 2023款', '问界 M5 纯电 2022款',
  '问界 M5 纯电智驾版 2023款', '问界 M5 纯电标准版 2023款',
  '问界 M8 2025款', '问界 M9 2026款', '问界 M9 Ultimate 2026款',
  '问界 M9 直订 2026款', '问界 M9 Ultimate 直订 2026款',
  '享界 S9 2026款', '享界 S9 Beta',
  '尊界 S800 2025款', '尊界 S800 典藏大观 2026款',
  '尊界 S800 典藏大观 直订 2026款',
  '尊界 V680 2026款', '尊界 V680 直订 2026款',
  '尊界 V800 2026款', '尊界 V800 Beta 2026款', '尊界 V800 直订 2026款',
  '尚界 X6M 2026款汇总', '尚界 SHB 2026款汇总',
  '尚界 Z7 2026款', '尚界 Z7 Beta 2025款',
  '尚界 Z7T 2026款', '尚界 Z7T Beta 2025款',
  '智界 RX 盲订 2027款', '智界 RX 2027款盲订', '智界 RX 2027款',
];
const subjects = names.map((name, index) => ({id: String(index), name, parent: name.slice(0, 2), type: 'generation'}));
const actual = select({subjects});
const expected = [
  '问界 F2N 2026款汇总', '尚界 X6M 2026款汇总', '尚界 SHB 2026款汇总',
  '问界 M5 2025款', '问界 M8 2025款', '问界 M9 2026款',
  '问界 M9 Ultimate 2026款', '享界 S9 2026款',
  '尊界 S800 2025款', '尊界 S800 典藏大观 2026款',
  '尊界 V680 2026款', '尊界 V800 2026款',
  '尚界 Z7 2026款', '尚界 Z7T 2026款',
  '智界 RX 2027款',
];
assert.deepStrictEqual([...actual].sort(), [...expected].sort());
assert.strictEqual(subjects.length, names.length, 'source subjects must remain untouched');

const coexist=select({subjects:['问界 M5 2026款','问界 M5 2026款汇总','问界 M5 2025款汇总'].map(name=>({name,type:'generation',parent:'问界'}))});
assert.deepStrictEqual(coexist.sort(),['问界 M5 2026款','问界 M5 2026款汇总'].sort());
