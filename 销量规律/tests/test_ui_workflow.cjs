/* Optional development audit. Production HTML needs no Node/browser packages.
   PLAYWRIGHT_MODULE and BROWSER_BINARY may point to local installed dependencies. */
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs/promises");
const {pathToFileURL} = require("node:url");
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const reportPath = path.resolve(process.argv[2] || path.join(__dirname, "../../../output_file/鸿蒙智行销量规律分析.html"));
const screenshotDir = process.env.UI_AUDIT_SCREENSHOTS;
const completed = [];
async function check(name, fn) {
  try { await fn(); completed.push(name); }
  catch (error) { error.message = name + ": " + error.message; throw error; }
}
async function until(fn) {
  const end = Date.now() + 4000;
  while (Date.now() < end) { if (await fn()) return; await new Promise(r => setTimeout(r, 40)); }
  assert.ok(await fn(), "Expected state was not reached");
}
async function textMatches(page, selector, regex) {
  await until(async () => regex.test(await page.locator(selector).innerText()));
}
function parseCsv(text) {
  const records = []; let row = [], cell = "", quoted = false;
  text = text.replace(/^\uFEFF/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === '"') { if (quoted && text[i + 1] === '"') { cell += '"'; i++; } else quoted = !quoted; }
    else if (!quoted && c === ',') { row.push(cell); cell = ""; }
    else if (!quoted && (c === '\n' || c === '\r')) { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); records.push(row); row = []; cell = ""; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); records.push(row); }
  return records;
}
async function capture(page, filename) {
  if (!screenshotDir) return;
  await fs.mkdir(screenshotDir, {recursive: true});
  await page.screenshot({path: path.join(screenshotDir, filename), animations: "disabled"});
}
(async () => {
  const browser = await chromium.launch(process.env.BROWSER_BINARY ? {executablePath: process.env.BROWSER_BINARY, headless: true} : {channel: "chrome", headless: true});
  const errors = [], requests = [];
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}, acceptDownloads: true});
  context.on("page", p => { p.on("pageerror", e => errors.push(e.message)); p.on("request", r => { if (/^https?:/.test(r.url())) requests.push(r.url()); }); });
  const page = await context.newPage(), url = pathToFileURL(reportPath).href;
  const reset = async () => { await page.goto(url); await page.locator("#resetFilters").click(); };
  try {
    await page.goto(url);
    await capture(page, "sales-ui-after-desktop.png");
    await check("空白试算不当作零；零值可正常计算", async () => {
      await page.locator("#nav-forecast").click();
      await textMatches(page, "#trialResult", /—/);
      await page.locator("#trialBase").fill("0");
      await textMatches(page, "#trialResult", /\n0 辆/);
      await page.locator("#trialBase").fill("");
      await textMatches(page, "#trialResult", /—/);
    });
    await check("整数天数、负数及超大数的输入反馈", async () => {
      await page.locator("#trialBase").fill("100"); await page.locator("#trialDays").fill("2.5");
      await textMatches(page, "#trialError", /整数/);
      assert.equal(await page.locator("#trialDays").getAttribute("aria-invalid"), "true");
      await page.locator("#trialDays").fill("30"); await page.locator("#trialFactor").fill("-1");
      await textMatches(page, "#trialError", /倍率/);
      await page.locator("#trialFactor").fill("1.2"); await textMatches(page, "#trialResult", /3,600 辆/);
      await page.locator("#trialBase").fill("1e308"); await textMatches(page, "#trialError", /数值过大/);
      await page.locator("#trialBase").fill("100");
      await page.locator('[name="trialMode"][value="period"]').check();
      await textMatches(page, "#trialResult", /120 辆/);
      assert.equal(await page.locator("#trialDaysField").isVisible(), false);
      await page.locator('[name="trialMode"][value="daily"]').check();
    });
    await check("错误日期不会静默改动另一端或改变当前结果", async () => {
      await page.locator("#nav-overview").click();
      const notice = await page.locator("#rangeNotice").innerText(), end = await page.locator("#dateEnd").inputValue();
      await page.locator("#dateStart").fill(""); await page.locator("#dateStart").dispatchEvent("change");
      await textMatches(page, "#dateError", /上次有效范围/);
      assert.equal(await page.locator("#dateEnd").inputValue(), end);
      assert.equal(await page.locator("#rangeNotice").innerText(), notice);
      await page.locator("#resetFilters").click(); assert.equal(await page.locator("#dateError").isVisible(), false);
      await page.locator("#dateStart").fill("2010-01-01"); await page.locator("#dateStart").dispatchEvent("change");
      await textMatches(page, "#dateError", /覆盖范围/);
      await page.locator("#resetFilters").click();
    });
    await check("分类、车型和回测列表共用同一范围", async () => {
      await page.locator("#modelFilter").selectOption({index: 1});
      const model = await page.locator("#modelFilter").inputValue();
      await page.locator("#nav-forecast").click();
      assert.equal(await page.locator("#forecastModel option").count(), 1);
      assert.equal(await page.locator("#forecastModel").inputValue(), model);
      await page.locator("#resetFilters").click();
      await page.locator("#categoryFilter").selectOption({index: 1});
      const valid = await page.evaluate(() => {
        const category = document.getElementById("categoryFilter").value;
        const map = new Map(window.PATTERNS_DATA.grouping.entries.map(x => [x.model, x.category]));
        return [...document.getElementById("forecastModel").options].every(o => !o.value || map.get(o.value) === category);
      });
      assert.equal(valid, true); await page.locator("#resetFilters").click();
    });
    await check("有效回测图表与WAPE评分（测试夹具，与业务数据隔离）", async () => {
      const fixture = await context.newPage();
      await fixture.addInitScript(() => {
        let value;
        Object.defineProperty(window,"PATTERNS_DATA",{configurable:true,get:()=>value,set:incoming=>{
          const model="UI回归测试车型",source="UI回归测试来源（非业务数据）",metric="留存大定",stage="平销",cycle="UI回归夹具";
          const base={model,source,metric,stage,cycle};
          const series=Array.from({length:91},(_,i)=>({...base,date:new Date(Date.UTC(2024,0,i+1)).toISOString().slice(0,10),value:100,life:null}));
          const entry={model,category:"UI测试分类",metrics:[metric],brand:"UI测试品牌",segment:"测试",energy:"测试"};
          const profile={...base,grain:"日",cutoff:"2024-03-31",target_start:"2024-04-01",target_end:"2024-04-01",baseline:100,estimate:120,status:"ok",train_samples:60,method:"仅用于UI回归"};
          const backtests=[{...base,grain:"日",origin:"2024-01-29",target_start:"2024-01-30",target_end:"2024-01-30",actual:100,predicted:120,baseline:90,status:"ok",train_samples:20},{...base,grain:"日",origin:"2024-01-30",target_start:"2024-01-31",target_end:"2024-01-31",actual:150,predicted:130,baseline:140,status:"ok",train_samples:21}];
          value={...incoming,meta:{...incoming.meta,source_name:"UI回归测试夹具",date_start:"2024-01-01",date_end:"2024-03-31"},series,metrics:[{key:metric,label:"净大定",source_label:"留存大定",available:true},{key:"交车锁单",label:"锁单",source_label:"交车锁单",available:false}],grouping:{entries:[entry],categories:[entry.category],reason:"UI测试夹具"},rules:[],results:Object.fromEntries(Object.keys(incoming.results).map(k=>[k,k==="model_classes"?[entry]:[]])),forecast:{profiles:[profile],backtests,notes:[]}};
        }});
      });
      await fixture.goto(url);await fixture.locator("#nav-forecast").click();await fixture.locator("#forecastGrain").selectOption("日");
      assert.equal(await fixture.locator("#backtestChart svg").count(),1);
      assert.equal(await fixture.evaluate(()=>new URLSearchParams(location.hash.slice(1)).get("profileKey")),await fixture.locator("#forecastProfile").inputValue());
      assert.equal(await fixture.locator("#backtestTableWrap tbody tr").count(),2);
      assert.ok((await fixture.locator("#forecastKpis").innerText()).includes("16% / 8%"));
      await fixture.locator(".profile-detail summary").click();assert.ok((await fixture.locator("#forecastSelection").innerText()).includes("非业务数据"));
      await fixture.setViewportSize({width:390,height:844});assert.ok(await fixture.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      assert.equal(await fixture.locator("#backtestChart").getAttribute("tabindex"),"0");
      await fixture.close();await reset();
    });
    await check("刷新和浏览器后退保留页面、规律类别与筛选", async () => {
      await page.locator("#nav-patterns").click(); await page.locator('[data-pattern="week"]').click();
      await page.locator("#modelFilter").selectOption({index: 1});
      const model = await page.locator("#modelFilter").inputValue();
      await page.reload(); assert.equal(await page.locator("#pageTitle").innerText(), "规律探索");
      assert.equal(await page.locator('[data-pattern="week"]').getAttribute("aria-selected"), "true");
      assert.equal(await page.locator("#modelFilter").inputValue(), model);
      await page.locator("#nav-evidence").click(); await page.goBack();
      await until(async () => await page.locator("#pageTitle").innerText() === "规律探索");
      await page.locator(".brand").click(); assert.equal(await page.locator("#pageTitle").innerText(), "销量规律概览");
    });
    await check("键盘导航、快捷跳转和可滚动表格", async () => {
      await page.locator("#nav-overview").focus(); await page.keyboard.press("ArrowRight");
      assert.equal(await page.locator("#nav-patterns").getAttribute("aria-selected"), "true");
      await page.locator('[data-pattern="week"]').focus(); await page.keyboard.press("ArrowRight");
      assert.equal(await page.locator('[data-pattern="holiday"]').getAttribute("aria-selected"), "true");
      await page.locator('.workflow-guide [data-go="evidence"]').click();
      assert.equal(await page.evaluate(() => document.activeElement.id), "pageTitle");
      assert.equal(await page.locator("#evidenceTableWrap").getAttribute("tabindex"), "0");
      await page.locator(".skip-link").focus(); await page.keyboard.press("Enter");
      assert.equal(await page.evaluate(() => document.activeElement.id), "mainContent");
    });
    await reset();
    await check("搜索空状态可恢复且不会导出空文件", async () => {
      await page.locator("#nav-evidence").click(); await page.locator("#evidenceSearch").fill("不存在的车型__audit");
      await until(() => page.locator("#exportCsv").isDisabled());
      await textMatches(page, "#evidenceTableWrap", /清除搜索/);
      await page.locator("#evidenceSearch").fill(""); await until(async () => !await page.locator("#exportCsv").isDisabled());
      if (await page.locator("#nextPage").isEnabled()) await page.locator("#nextPage").click();
      await page.locator("#modelFilter").selectOption({index: 1}); await textMatches(page, "#evidencePageInfo", /第 1 \/ /);
    });
    await reset();
    for (const metric of ["留存大定", "交车锁单"]) {
      await check(metric + " CSV原值与当前筛选一致，且导出不限当前页", async () => {
        const button = page.locator('[data-metric="' + metric + '"]'); if (await button.isDisabled()) return;
        await button.click(); await page.locator("#nav-evidence").click();
        const expected = await page.evaluate(metric => {
          const $ = id => document.getElementById(id).value;
          const category = $("categoryFilter"), model = $("modelFilter"), stage = $("stageFilter"), from = $("dateStart"), to = $("dateEnd");
          const map = new Map(window.PATTERNS_DATA.grouping.entries.map(x => [x.model, x.category]));
          return window.PATTERNS_DATA.series.filter(r => r.metric === metric && r.stage === stage && r.date >= from && r.date <= to && (model === "__ALL__" || r.model === model) && (category === "__ALL__" || map.get(r.model) === category));
        }, metric);
        assert.ok(expected.length > 0);
        const event = page.waitForEvent("download"); await page.locator("#exportCsv").click(); const download = await event;
        assert.equal(await download.failure(), null); const stream = await download.createReadStream(), chunks = [];
        for await (const chunk of stream) chunks.push(chunk);
        const records = parseCsv(Buffer.concat(chunks).toString("utf8")); assert.equal(records.length, expected.length + 1);
        const actual = records.slice(1).map(r => ({date: r[0], model: r[1], value: Number(r[5]), source: r[7]}));
        assert.deepEqual(actual, expected.map(r => ({date: r.date, model: r.model, value: r.value, source: r.source})));
        await textMatches(page, "#actionStatus", /下载已交给浏览器/);
      });
    }
    await check("Excel附件下载入口可用", async () => {
      const event = page.waitForEvent("download"); await page.locator("#excelTopLink").click(); const d = await event;
      assert.equal(await d.failure(), null); assert.equal(d.suggestedFilename(), "鸿蒙智行销量规律分析.xlsx");
    });
    await check("快速连续切换最终状态正确，减少动效后无动画", async () => {
      await page.evaluate(() => ["patterns", "forecast", "evidence", "overview"].forEach(key => document.getElementById("nav-" + key).click()));
      assert.equal(await page.locator("#pageTitle").innerText(), "销量规律概览");
      await page.emulateMedia({reducedMotion: "reduce"});
      await page.locator("#nav-patterns").click(); await page.locator('[data-pattern="week"]').click();
      assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
      const transition = await page.locator("#nav-patterns").evaluate(e => getComputedStyle(e).transitionDuration);
      assert.equal(transition, "0s"); await page.emulateMedia({reducedMotion: "no-preference"});
    });
    const sizes = [[320,740],[375,812],[390,844],[768,1024],[844,390],[1440,1000],[1920,1080]];
    for (const [width,height] of sizes) {
      await check(width + "×" + height + " 四页布局与触摸导航", async () => {
        const p = await context.newPage(); await p.setViewportSize({width,height}); await p.goto(url);
        if (width === 390) await capture(p, "sales-ui-after-mobile.png");
        for (const name of ["overview", "patterns", "forecast", "evidence"]) {
          await p.locator("#nav-" + name).click();
          assert.ok(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), name + " has document overflow");
          assert.equal(await p.locator("#panel-" + name).isVisible(), true);
          const lowContrast = await p.evaluate(() => {
            const rgb = s => (s.match(/[\d.]+/g)||[]).slice(0,3).map(Number);
            const light = c => c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
            return [...document.querySelectorAll(".card-subtitle,.chart-caption,.chart-empty,.table-empty,.page-footer,.pattern-card p,.forecast-kpi span")].filter(e=>e.getClientRects().length).map(e=>{
              const fg=light(rgb(getComputedStyle(e).color));let parent=e,bg="";
              while(parent){bg=getComputedStyle(parent).backgroundColor;if(bg!=="rgba(0, 0, 0, 0)"&&bg!=="transparent")break;parent=parent.parentElement;}
              const b=light(rgb(bg||"rgb(255,255,255)"));return {selector:e.className||e.tagName,ratio:(Math.max(fg,b)+.05)/(Math.min(fg,b)+.05)};
            }).filter(r=>r.ratio<4.5);
          });
          assert.deepEqual(lowContrast, [], name + " has unreadable supporting text");
        }
        if (width <= 850) {
          const bounds = await p.locator(".nav-item").evaluateAll(nodes => nodes.map(e => ({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,right:e.getBoundingClientRect().right,left:e.getBoundingClientRect().left})));
          assert.ok(bounds.every(r => r.width >= 44 && r.height >= 44 && r.left >= 0 && r.right <= width));
          const inputs = await p.locator("#categoryFilter,#modelFilter,#stageFilter,#dateStart,#dateEnd,#exportCsv").evaluateAll(nodes => nodes.map(e => e.getBoundingClientRect().height));
          assert.ok(inputs.every(height => height >= 44));
        }
        await p.close();
      });
    }
    await page.goto(url); await page.locator("#nav-forecast").click(); await page.locator("#trialBase").fill("100");
    await textMatches(page, "#trialResult", /3,000 辆/); await capture(page, "sales-ui-after-forecast.png");
    assert.deepEqual(errors, []); assert.deepEqual(requests, []);
    console.log(JSON.stringify({passed:completed.length,checks:completed,consoleErrors:errors,networkRequests:requests},null,2));
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode = 1;});
