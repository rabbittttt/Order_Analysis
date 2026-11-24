// Fixed local fixture. Never reads Excel or starts the dashboard's build process.
// PLAYWRIGHT_MODULE=<path> node tests/ui_visual_regression.cjs --output-dir <dir>
// --baseline-ref HEAD (default) compares all visible templates with the working tree.
// After committing CSS/JS/HTML changes, compare against the parent: --baseline-ref HEAD^
// CSS-only mode: --baseline-css-ref HEAD or --baseline-css <saved-css-file>.
// --allow-diff writes differences for intentional changes without failing the run.
// Outputs before/, after/, diff/ PNGs and report.json. Any changed pixel fails.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');

const args = process.argv.slice(2);
if (args.includes('--help')) {
  console.log('node tests/ui_visual_regression.cjs [--baseline-ref HEAD | --baseline-css-ref REF | --baseline-css FILE] [--output-dir DIR] [--allow-diff]');
  process.exit(0);
}
const value = (name, fallback) => {
  const index = args.indexOf(name);
  if (index < 0) return fallback;
  if (!args[index + 1] || args[index + 1].startsWith('--')) throw new Error('Missing value for ' + name);
  return args[index + 1];
};
const allowed = new Set(['--baseline-ref', '--baseline-css-ref', '--baseline-css', '--output-dir', '--allow-diff']);
for (let index = 0; index < args.length; index++) {
  if (!allowed.has(args[index])) throw new Error('Unknown option ' + args[index]);
  if (args[index] !== '--allow-diff') index++;
}
assert(args.filter(arg => ['--baseline-ref', '--baseline-css-ref', '--baseline-css'].includes(arg)).length <= 1, 'Choose one baseline mode');
const root = path.resolve(__dirname, '..');
const project = path.resolve(root, '../..');
const templates = path.join(root, 'templates');
const referenceFile = value('--baseline-css', null);
const cssOnly = Boolean(referenceFile || args.includes('--baseline-css-ref'));
const referenceRef = value(cssOnly ? '--baseline-css-ref' : '--baseline-ref', 'HEAD');
const filenames = ['dashboard.html', 'dashboard.css', 'dashboard.js', 'trend_annotations.js', 'brand-logo.png'];
const currentAssets = Object.fromEntries(filenames.map(name => [name, fs.readFileSync(path.join(templates, name))]));
const baselineAssets = cssOnly ? { ...currentAssets } : Object.fromEntries(filenames.map(name => [
  name, execFileSync('git', ['show', referenceRef + ':generate_html/templates/' + name], { cwd: path.dirname(root) })
]));
if (cssOnly) {
  baselineAssets['dashboard.css'] = referenceFile
    ? fs.readFileSync(path.resolve(referenceFile))
    : execFileSync('git', ['show', referenceRef + ':generate_html/templates/dashboard.css'], { cwd: path.dirname(root) });
}
const outputDirectory = value('--output-dir', null);
const output = path.resolve(outputDirectory || fs.mkdtempSync(path.join(os.tmpdir(), 'order-ui-visual-')));
for (const folder of ['before', 'after', 'diff']) fs.mkdirSync(path.join(output, folder), { recursive: true });
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || path.join(project, '.test_runtime/node_modules/playwright'));
const sha = text => crypto.createHash('sha256').update(text).digest('hex');
const dataset = 'visual-fixture-v1';
const generatedAt = '2026-11-24T09:30:00';
const modelNames = ['问界 M5 2026款', '问界 M6 2026款', '问界 M7 2026款', '问界 M8 2026款', '问界 M9 2026款', '智界 R7 2026款', '智界 S7 2026款', '享界 S9 2026款', '尊界 S800 2026款', '尚界 H5 2026款'];
const subjects = [
  { id: 'g', name: '鸿蒙智行', type: 'group' },
  ...modelNames.map((name, index) => ({ id: 'm' + index, name, type: 'generation', parent: name.slice(0, 2) }))
].map(subject => ({ ...subject, has_lock_orders: true, modules: ['overview', 'raw'] }));
const catalog = {
  dataset_id: dataset, meta: { generated_at: generatedAt }, subjects,
  config: { module_order: ['overview', 'raw'], module_labels: { overview: '订单总览', raw: '底表中心' }, grain_labels: { day: '日', week: '周', month: '月' } },
  raw_files: [{ name: '固定视觉样例.xlsx', sheets: [{ name: '示例数据', total_rows: 5, total_cols: 2 }] }]
};
const view = {
  periods: ['26WK47'], default_period: '26WK47',
  pages: { '26WK47': {
    kpis: [{ label: '大定', value: 240, unit: '单' }, { label: '留存大定', value: 218, unit: '单' }, { label: '交车锁单', value: 186, unit: '单' }, { label: '已交付', value: 155, unit: '单' }],
    sections: [{
      kind: 'stacked_trend', title: '留存大定趋势', meta: '固定视觉样例', width: 'full',
      data: { periods: ['26WK44', '26WK45', '26WK46', '26WK47'], totals: [120, 160, 200, 218], series: [{ name: '增程', values: [.65, .6, .55, .5] }, { name: '纯电', values: [.35, .4, .45, .5] }] },
      source: { file: '固定视觉样例.xlsx', sheet: '示例数据' }
    }]
  } }
};
const annotations = [{ id: 'note', subject: 'g', date: '2026-11-10', text: '权益调整与上市活动，批注完整展示并支持自动换行', version: 1 }];
function shell(assets) {
  const template = assets['dashboard.html'].toString('utf8');
  const css = assets['dashboard.css'].toString('utf8');
  const dashboardJs = assets['dashboard.js'].toString('utf8');
  const annotationsJs = assets['trend_annotations.js'].toString('utf8');
  const logo = 'data:image/png;base64,' + assets['brand-logo.png'].toString('base64');
  const marker = '<script>window.DASHBOARD_DATA_B64="__DASHBOARD_DATA__";</script>';
  assert(template.includes(marker), 'Dynamic fixture entry marker');
  return template.replace(marker, '<script>window.ORDER_DASHBOARD_API_BASE="api/";</script>')
    .replace('__DASHBOARD_RAW__', '{}').replace('__DASHBOARD_BLOCKS__', '{}')
    .replace('__DASHBOARD_CSS__', () => css).replace('__DASHBOARD_JS__', () => dashboardJs)
    .replace('__TREND_ANNOTATIONS_JS__', () => annotationsJs).replace('__BRAND_LOGO__', () => logo)
    .replace('</head>', '<style>*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}</style></head>');
}
const shells = { before: shell(baselineAssets), after: shell(currentAssets) };
const phases = { before: 'idle', after: 'idle' };
const server = http.createServer((request, response) => {
  const url = new URL(request.url, 'http://localhost');
  const [variant, route, resource] = url.pathname.split('/').filter(Boolean);
  const send = (body, status = 200) => {
    response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
    response.end(JSON.stringify(body));
  };
  if (!shells[variant]) return send({ detail: 'Unknown fixture' }, 404);
  if (route !== 'api') {
    response.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' });
    return response.end(shells[variant]);
  }
  if (resource === 'catalog') return send(catalog);
  if (resource === 'dashboard') return send({ views: { week: view }, sources: [] });
  if (resource === 'annotations') return send({ entries: annotations });
  if (resource === 'sync') return send({ dataset_id: dataset, phase: phases[variant], error: phases[variant] === 'error' ? '固定失败样例' : null });
  send({ detail: 'Unsupported fixture request' }, 404);
});

async function comparePng(page, before, after) {
  return page.evaluate(async ({ before, after }) => {
    async function decode(bytes) {
      const image = new Image();
      image.src = 'data:image/png;base64,' + bytes;
      await image.decode();
      const canvas = document.createElement('canvas');
      canvas.width = image.width; canvas.height = image.height;
      const context = canvas.getContext('2d');
      context.drawImage(image, 0, 0);
      return { width: image.width, height: image.height, data: context.getImageData(0, 0, image.width, image.height).data };
    }
    const first = await decode(before), second = await decode(after);
    const width = Math.max(first.width, second.width), height = Math.max(first.height, second.height);
    const canvas = document.createElement('canvas');
    canvas.width = width; canvas.height = height;
    const context = canvas.getContext('2d'), diff = context.createImageData(width, height);
    let changedPixels = 0;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      const target = (y * width + x) * 4;
      const presentA = x < first.width && y < first.height, presentB = x < second.width && y < second.height;
      const indexA = (y * first.width + x) * 4, indexB = (y * second.width + x) * 4;
      let changed = presentA !== presentB;
      for (let channel = 0; channel < 4; channel++) {
        const a = presentA ? first.data[indexA + channel] : 0, b = presentB ? second.data[indexB + channel] : 0;
        if (a !== b) changed = true;
      }
      if (changed) {
        changedPixels++;
        diff.data.set([224, 0, 110, 255], target);
      } else {
        const gray = presentB ? Math.round((second.data[indexB] + second.data[indexB + 1] + second.data[indexB + 2]) / 3 * .25 + 255 * .75) : 255;
        diff.data.set([gray, gray, gray, 255], target);
      }
    }
    context.putImageData(diff, 0, 0);
    return { width, height, beforeSize: [first.width, first.height], afterSize: [second.width, second.height], changedPixels, totalPixels: width * height, png: canvas.toDataURL('image/png').split(',')[1] };
  }, { before: before.toString('base64'), after: after.toString('base64') });
}

async function main() {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
  const errors = [], snapshots = new Map();
  const devices = [
    { name: 'desktop', viewport: { width: 1440, height: 1000 }, isMobile: false, hasTouch: false },
    { name: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }
  ];
  try {
    for (const variant of ['before', 'after']) for (const device of devices) {
      phases[variant] = 'idle';
      const context = await browser.newContext({ viewport: device.viewport, isMobile: device.isMobile, hasTouch: device.hasTouch, deviceScaleFactor: 1, locale: 'zh-CN', timezoneId: 'Asia/Shanghai', colorScheme: 'light', reducedMotion: 'reduce' });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(variant + '/' + device.name + ': ' + error.message));
      await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
      const annotationResponse = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/api/annotations'));
      await page.goto(origin + '/' + variant + '/?subject=m2&grain=week');
      await page.waitForFunction(() => document.querySelector('#page')?.getAttribute('aria-busy') === 'false' && document.querySelector('[data-section-kind="stacked_trend"]'));
      await annotationResponse;
      await page.evaluate(() => document.fonts.ready.then(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))));
      const capture = async (name, locator) => {
        const filename = device.name + '-' + name + '.png';
        const png = await locator.screenshot({ path: path.join(output, variant, filename), animations: 'disabled', caret: 'hide' });
        if (!snapshots.has(filename)) snapshots.set(filename, {});
        snapshots.get(filename)[variant] = png;
      };
      const status = page.locator('#syncStatus'), header = page.locator('.topbar');
      await capture('header-idle', header);
      for (const phase of ['building', 'error', 'idle']) {
        phases[variant] = phase;
        const response = page.waitForResponse(reply => reply.url().includes('/api/sync'));
        await page.evaluate(() => window.dispatchEvent(new Event('focus')));
        await response;
        await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
        if (phase !== 'idle') await capture('header-' + phase, header);
      }
      const card = page.locator('[data-section-kind="stacked_trend"]').first();
      await page.mouse.move(1, 1);
      await capture('trend-default', card);
      const source = card.locator('[data-panel-source]');
      await source.hover();
      await capture('trend-source-hover', card);
      await page.mouse.move(1, 1);
      await source.focus();
      await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab');
      assert(await source.evaluate(node => node === document.activeElement), 'Source button focused');
      await capture('trend-source-focus', card);
      await status.evaluate(node => { node.hidden = true; });
      assert(await status.isHidden(), 'Hidden generation status remains hidden');
      await context.close();
    }
    const comparison = await browser.newPage();
    const records = [];
    for (const [filename, images] of snapshots) {
      const { png, ...result } = await comparePng(comparison, images.before, images.after);
      fs.writeFileSync(path.join(output, 'diff', filename), Buffer.from(png, 'base64'));
      records.push({ filename, ...result });
    }
    const report = {
      fixture: dataset, fixtureHash: sha(JSON.stringify({ catalog, view, annotations })),
      mode: cssOnly ? 'css-only' : 'complete-templates',
      reference: referenceFile ? path.resolve(referenceFile) : referenceRef,
      beforeHashes: Object.fromEntries(filenames.map(name => [name, sha(baselineAssets[name])])),
      afterHashes: Object.fromEntries(filenames.map(name => [name, sha(currentAssets[name])])),
      browser: browser.version(), platform: process.platform, devices, errors, snapshots: records
    };
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2) + '\n');
    const changed = records.filter(record => record.changedPixels > 0);
    console.log(JSON.stringify({ output, snapshots: records.length, changed: changed.map(record => ({ filename: record.filename, changedPixels: record.changedPixels })), errors }, null, 2));
    if (errors.length || (changed.length && !args.includes('--allow-diff'))) process.exitCode = 1;
  } finally {
    await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(error => { console.error(error); server.close(); process.exitCode = 1; });
