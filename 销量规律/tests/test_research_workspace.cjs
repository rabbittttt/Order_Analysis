/* Research-workspace regression coverage. Production only needs the offline
   HTML; this file is a development check that injects a small source-shaped
   fixture so UI assertions do not depend on the sample workbook. */
const assert = require("node:assert/strict");
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const reportPath = path.resolve(process.argv[2] || path.join(__dirname, "../../../output_file/鸿蒙智行销量规律分析.html"));
const date = (day) => `2025-02-${String(day).padStart(2, "0")}`;
const models = ["研究车型A", "研究车型B"];
const entries = models.map((model, i) => ({model, category: `研究分类${i + 1}`, metrics: ["小订数量", "留存大定", "交车锁单"], brand: "测试品牌", segment: i ? "SUV" : "轿车", energy: "纯电"}));
const metrics = [
  {key: "小订数量", label: "小订", source_label: "小订数量", available: true},
  {key: "留存大定", label: "留存大定", source_label: "留存大定", available: true},
  {key: "交车锁单", label: "锁单", source_label: "交车锁单", available: true}
];
const series = [];
for (const model of models) {
  [0, 2, 3, 4].forEach((value, i) => series.push({model, metric: "小订数量", date: date(i + 1), stage: "小订阶段", cycle: "小订批次", source: "小订源表", value, life: i + 1}));
  for (let i = 0; i < 6; i++) {
    series.push({model, metric: "留存大定", date: date(i + 1), stage: "首销", cycle: "首销批次", source: "大定源表", value: 20 + i, life: i + 1});
    series.push({model, metric: "交车锁单", date: date(i + 1), stage: "首销", cycle: "锁单批次", source: "锁单源表", value: 10 + i, life: i + 1});
  }
}
const hourly = [];
for (const model of models) {
  for (const [metric, stage, day] of [["小订数量", "小订", 1], ["交车锁单", "首销", 2]]) {
    for (let hour = 0; hour < 24; hour++) hourly.push({
      model, metric, stage, date: date(day), hour, value: 1, share: 1 / 24, total: 24,
      observed_hours: 24, expected_hours: 24, status: "有效", group_status: "有效", source: `${metric}小时源表`, source_sheet: `${metric}by时`
    });
  }
}
const curves = [1, 2, 3].map(day => ({model: models[0], metric: "小订数量", stage: "小订", curve: "小订累计完成度", day, date: date(day), value: day / 3, unit: "比例", source: "小订曲线源表", status: "有效", denominator: 3}));
curves.push({model: models[0], metric: "小订数量", stage: "小订", curve: "小订累计完成度", value: 999, unit: "比例", source: "小订曲线源表", status: "未知"});
const emptyResults = {
  coverage: [], weekly: [], monthly: [], annual: [], holidays: [], lifecycle: [], lock_lags: [], period_comparisons: [], period_summary: [],
  month_progress: [], launch_periods: [], launch_pacing: [], model_classes: entries, period_coverage: []
};
const fixture = {
  meta: {source_name: "UI研究工作台夹具", date_start: date(1), date_end: date(6), analysis_start: date(1), analysis_end: date(6), generated_at: "2025-03-01T09:00:00", calendar_events: []},
  metrics, series, rules: [], grouping: {entries, categories: entries.map(x => x.category), reason: "测试夹具"},
  results: emptyResults, forecast: {profiles: [], backtests: [], notes: []},
  source_insights: {inventory: [], early_launch: [], curves, hourly, notes: []}
};

async function waitFor(page, predicate, timeout = 3000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await predicate()) return; await new Promise(resolve => setTimeout(resolve, 30)); }
  assert.ok(await predicate(), "Expected UI state was not reached");
}

(async () => {
  const browser = await chromium.launch(process.env.BROWSER_BINARY ? {executablePath: process.env.BROWSER_BINARY, headless: true} : {channel: "chrome", headless: true});
  const requests = [], errors = [];
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  context.on("request", request => { if (/^https?:/i.test(request.url())) requests.push(request.url()); });
  context.on("page", page => page.on("pageerror", error => errors.push(error.message)));
  const page = await context.newPage();
  const url = pathToFileURL(reportPath).href;
  await page.addInitScript(({fixture}) => {
    let current;
    Object.defineProperty(window, "PATTERNS_DATA", {
      configurable: true,
      get: () => current,
      set: () => { current = fixture; }
    });
  }, {fixture});
  try {
    await page.goto(url);
    await waitFor(page, () => page.locator("#resetFilters").count().then(Boolean));

    assert.equal(await page.locator("[data-metric]").count(), 3);
    assert.deepEqual(await page.locator("[data-metric]").allTextContents(), ["小订", "留存大定", "锁单"]);

    await page.locator('[data-metric="小订数量"]').click();
    assert.equal(await page.locator("#stageFilter").inputValue(), "小订阶段");
    assert.deepEqual(await page.locator("#stageFilter option").allTextContents(), ["小订期"]);
    assert.ok((await page.locator("#evidenceMeta").count()) >= 1);
    const sameDayStages = await page.evaluate(() => {
      const rows = window.PATTERNS_DATA.series.filter(r => r.date === "2025-02-01");
      return Object.fromEntries(rows.map(r => [r.metric, r.stage]));
    });
    assert.equal(sameDayStages["小订数量"], "小订阶段");
    assert.equal(sameDayStages["留存大定"], "首销");
    assert.equal(await page.evaluate(() => window.PATTERNS_DATA.series.some(r => r.metric === "小订数量" && r.value === 0)), true);

    await page.locator("#nav-evidence").click();
    const smallDailyRows = await page.locator("#evidenceTableWrap .data-table tbody tr").evaluateAll(rows => rows.map(row => [...row.cells].map(cell => cell.innerText)));
    assert.ok(smallDailyRows.some(row => row[0] === date(1) && row[5] === "0"), "真实0应在逐日证据中保留");
    await page.locator('[data-evidence="library"]').click();
    await page.locator("#libraryTable").selectOption("sourceCurves");
    assert.match(await page.locator("#evidenceTableWrap").innerText(), /日期未知，仅保留核对，不参与当前日期窗统计/);
    await page.locator("#nav-overview").click();

    await page.locator('[data-metric="留存大定"]').click();
    assert.ok((await page.locator("#stageFilter option").allTextContents()).includes("首销"));
    await page.locator("#modelFilter").selectOption("研究车型B");
    await page.locator('[data-metric="小订数量"]').click();
    assert.equal(await page.locator("#modelFilter").inputValue(), "研究车型B");

    await page.locator("#nav-patterns").click();
    assert.equal(await page.locator("#domain-orders").isDisabled(), true);
    await page.locator("#domain-calendar").click();
    await page.locator("#domain-lifecycle").click();
    assert.equal(await page.locator("#domain-lifecycle").getAttribute("aria-selected"), "true");
    assert.equal(await page.locator("#pattern-lags").isHidden(), true);
    await page.locator("#pattern-hourly").click();
    assert.equal(new URLSearchParams(new URL(page.url()).hash.slice(1)).get("pattern"), "hourly");
    await page.reload();
    assert.equal(await page.locator("#pattern-hourly").getAttribute("aria-selected"), "true");
    await page.locator('[data-metric="留存大定"]').click();
    await page.locator("#domain-orders").click();
    await page.locator("#pattern-lags").click();
    assert.equal(await page.locator("#pattern-lags").getAttribute("aria-selected"), "true");

    await page.locator("#nav-overview").click();
    for (const id of ["overviewInsight", "ratioSummary", "modelCompare", "overviewSignals"]) assert.equal(await page.locator("#" + id).count(), 0, id + " should not be on the homepage");
    assert.match(await page.locator("#overviewRuleCard").innerText(), /当前范围发现了什么/);

    await page.locator('[data-metric="留存大定"]').click();
    await page.locator("#modelFilter").selectOption("研究车型A");
    await page.locator("#dateStart").fill(date(1)); await page.locator("#dateStart").dispatchEvent("change");
    await page.locator("#dateEnd").fill(date(4)); await page.locator("#dateEnd").dispatchEvent("change");
    await page.locator("#nav-patterns").click(); await page.locator("#domain-calendar").click(); await page.locator("#pattern-months").click();
    const beforeEvidence = [await page.locator("#modelFilter").inputValue(), await page.locator("#dateStart").inputValue(), await page.locator("#dateEnd").inputValue()];
    await page.getByRole("button", {name: "核对本专题证据"}).click();
    assert.equal(await page.locator("#nav-evidence").getAttribute("aria-selected"), "true");
    assert.deepEqual([await page.locator("#modelFilter").inputValue(), await page.locator("#dateStart").inputValue(), await page.locator("#dateEnd").inputValue()], beforeEvidence);

    await page.locator("#nav-patterns").click(); await page.locator("#domain-lifecycle").click();
    await page.locator('[data-metric="小订数量"]').click();
    await page.locator("#pattern-structure").click();
    assert.doesNotMatch(await page.locator("#patternPanels").innerText(), /999/, "未知日期曲线不能进入图表统计");
    await page.locator("#pattern-hourly").click();
    await page.locator('[data-metric="交车锁单"]').click();
    assert.equal(await page.locator("#patternPanels .pattern-card").first().locator(".data-table tbody tr").count(), 24);
    await page.locator('[data-metric="留存大定"]').click();
    assert.match(await page.locator("#patternPanels").innerText(), /源表没有.*留存大定|不会使用.*替代/);
    await page.locator('[data-metric="交车锁单"]').click();
    await page.locator("#dateStart").fill(date(1)); await page.locator("#dateStart").dispatchEvent("change");
    await page.locator("#dateEnd").fill(date(1)); await page.locator("#dateEnd").dispatchEvent("change");
    assert.equal(await page.locator("#patternPanels .data-table").count(), 0);
    assert.match(await page.locator("#patternPanels").innerText(), /没有完整有效的24小时记录|没有完整分时样本|源表没有|源表未提供/);

    const hourlyCoverage = await page.evaluate(() => {
      const groups = new Map();
      for (const r of window.PATTERNS_DATA.source_insights.hourly) {
        const key = [r.metric, r.model, r.date].join("|");
        groups.set(key, (groups.get(key) || 0) + 1);
      }
      return [...groups.entries()];
    });
    assert.ok(hourlyCoverage.some(([key, count]) => key.startsWith("小订数量|") && count === 24));
    assert.ok(hourlyCoverage.some(([key, count]) => key.startsWith("交车锁单|") && count === 24));

    await page.locator("#resetFilters").click();
    for (const width of [1366, 1920, 2560, 390]) {
      await page.setViewportSize({width, height: 900});
      await page.locator("#nav-overview").click();
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), `horizontal overflow at ${width}px`);
    }
    await page.locator("#nav-forecast").click();
    await page.waitForTimeout(30);
    for (const width of [1366, 1920, 2560, 390]) {
      await page.setViewportSize({width, height: 900});
      const forecastOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      assert.equal(forecastOverflow, false, `forecast page overflows at ${width}px`);
    }
    assert.deepEqual(requests, []);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({passed: true, checks: 18, widths: [1366, 1920, 2560, 390]}));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
