#!/usr/bin/env node
/**
 * Offline black-box checks for standalone model-generated HTML/SVG/Canvas.
 * Usage (from frontend/):
 *   node tools/audit-generated-ui.mjs --html fixture.html --scenario steps.json --report result.json
 * Does not call a model, use app credentials, or modify production state.
 */
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const POLICY = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; connect-src 'none'; font-src 'none'; frame-src 'none'; object-src 'none'; form-action 'none'; base-uri 'none'";
const OPS = new Set(['click', 'set', 'expectText', 'expectAbsent', 'expectCount', 'expectEquation', 'expectLineAnchored', 'expectNoOverflow', 'wait']);
const selector = s => typeof s === 'string' && s.length > 0 && s.length <= 300;

export function validateScenario(s) {
  if (!s || typeof s !== 'object' || Array.isArray(s) || s.version !== 1 || typeof s.name !== 'string' || !s.name.trim()) throw Error('Invalid scenario header');
  if (!Array.isArray(s.viewports) || s.viewports.length < 1 || s.viewports.length > 4) throw Error('Expected 1–4 viewports');
  for (const v of s.viewports) {
    if (!Number.isInteger(v.width) || v.width < 320 || v.width > 1920 || !Number.isInteger(v.height) || v.height < 320 || v.height > 1200) throw Error('Invalid viewport');
  }
  if (!Array.isArray(s.steps) || s.steps.length < 1 || s.steps.length > 100) throw Error('Expected 1–100 steps');
  for (const [i, step] of s.steps.entries()) {
    if (!step || !OPS.has(step.op)) throw Error('Invalid operation at step ' + i);
    if (step.op !== 'expectNoOverflow' && !selector(step.selector)) throw Error('Invalid selector at step ' + i);
    if (step.op === 'set' && !['string', 'number'].includes(typeof step.value)) throw Error('Invalid value at step ' + i);
    if (step.op === 'expectText' && typeof step.equals !== 'string' && typeof step.includes !== 'string') throw Error('Missing text expectation at step ' + i);
    if (step.op === 'expectCount' && (!Number.isInteger(step.count) || step.count < 0)) throw Error('Invalid count at step ' + i);
    if (step.op === 'expectEquation' && (!selector(step.total) || !selector(step.locked) || !selector(step.available))) throw Error('Invalid equation selectors at step ' + i);
    if (step.op === 'expectLineAnchored' && (!selector(step.from) || !selector(step.to) || (step.tolerancePx !== undefined && (!Number.isFinite(step.tolerancePx) || step.tolerancePx < 0 || step.tolerancePx > 100)))) throw Error('Invalid line endpoints at step ' + i);
    if (step.op === 'wait' && (!Number.isInteger(step.ms) || step.ms < 0 || step.ms > 1500)) throw Error('Invalid wait at step ' + i);
  }
  return s;
}

export function applyOfflinePolicy(html) {
  const tag = '<meta http-equiv="Content-Security-Policy" content="' + POLICY + '">';
  const dt = /^\s*<!doctype[^>]*>/i.exec(html);
  return dt ? html.slice(0, dt[0].length) + tag + html.slice(dt[0].length) : tag + html;
}
export function escapeAttribute(s) {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function check(frame, step) {
  const el = step.selector ? frame.locator(step.selector) : null;
  switch (step.op) {
    case 'click': await el.click(); return;
    case 'set':
      await el.fill(String(step.value));
      await el.dispatchEvent('input');
      await el.dispatchEvent('change');
      return;
    case 'wait': await new Promise(resolve => setTimeout(resolve, step.ms)); return;
    case 'expectText': {
      const got = (await el.innerText()).trim();
      if (step.equals !== undefined ? got !== step.equals : !got.includes(step.includes)) throw Error('Unexpected text ' + step.selector + ': ' + JSON.stringify(got));
      return;
    }
    case 'expectAbsent': {
      const nodes = await el.all();
      for (const node of nodes) if (await node.isVisible()) throw Error('Unexpected visible node ' + step.selector);
      return;
    }
    case 'expectCount': {
      const got = await el.count();
      if (got !== step.count) throw Error('Unexpected count ' + step.selector + ': ' + got + ', expected ' + step.count);
      return;
    }
    case 'expectNoOverflow': {
      const r = await frame.evaluate(() => ({ width: innerWidth, root: document.documentElement.scrollWidth, body: document.body?.scrollWidth ?? 0 }));
      if (Math.max(r.root, r.body) > r.width + 1) throw Error('Horizontal overflow: ' + JSON.stringify(r));
      return;
    }
    case 'expectEquation': {
      const fields = [step.total, step.locked, step.available];
      const values = await Promise.all(fields.map(async sel => {
        const node = frame.locator(sel);
        const raw = (await node.inputValue().catch(() => node.innerText())).trim();
        const m = raw.match(/-?\d+(?:\.\d+)?/g);
        if (!m || m.length !== 1) throw Error('Expected one number at ' + sel + ', got ' + raw);
        return Number(m[0]);
      }));
      if (Math.abs(values[0] - values[1] - values[2]) > 1e-8) throw Error('Inconsistent inventory invariant: ' + values.join(', '));
      return;
    }
    case 'expectLineAnchored': {
      const r = await frame.evaluate(s => {
        const line = document.querySelector(s.selector);
        const from = document.querySelector(s.from), to = document.querySelector(s.to);
        if (!(line instanceof SVGLineElement) || !from || !to) return { error: 'Missing SVG line or nodes' };
        const matrix = line.getScreenCTM();
        if (!matrix) return { error: 'Missing SVG transform' };
        const transform = (x, y) => new DOMPoint(x, y).matrixTransform(matrix);
        const a = transform(line.x1.baseVal.value, line.y1.baseVal.value);
        const b = transform(line.x2.baseVal.value, line.y2.baseVal.value);
        const edgeDistance = (p, rect) => {
          const dx = Math.max(rect.left - p.x, 0, p.x - rect.right);
          const dy = Math.max(rect.top - p.y, 0, p.y - rect.bottom);
          if (dx || dy) return Math.hypot(dx, dy);
          return Math.min(p.x - rect.left, rect.right - p.x, p.y - rect.top, rect.bottom - p.y);
        };
        return { start: edgeDistance(a, from.getBoundingClientRect()), end: edgeDistance(b, to.getBoundingClientRect()) };
      }, step);
      const tolerance = step.tolerancePx ?? 14;
      if (r.error || r.start > tolerance || r.end > tolerance) throw Error('Misaligned SVG arrow: ' + JSON.stringify(r));
      return;
    }
  }
}

export async function auditHtml({ html, scenario, browserName = 'chromium', reportPath }) {
  validateScenario(scenario);
  if (typeof html !== 'string' || !html.trim() || Buffer.byteLength(html) > 256000) throw Error('HTML must be nonempty and <=256KB');
  if (!['chromium', 'firefox', 'webkit'].includes(browserName)) throw Error('Unsupported browser');
  const { chromium, firefox, webkit } = await import('@playwright/test');
  const browser = await ({ chromium, firefox, webkit })[browserName].launch({ headless: true });
  const report = { name: scenario.name, passed: true, viewports: [], blockedRequests: [] };
  try {
    for (const viewport of scenario.viewports) {
      const context = await browser.newContext({ viewport, serviceWorkers: 'block', acceptDownloads: false });
      const page = await context.newPage();
      const runtimeErrors = [];
      page.setDefaultTimeout(3000);
      page.on('pageerror', e => runtimeErrors.push(e.message));
      page.on('console', msg => { if (msg.type() === 'error') runtimeErrors.push(msg.text()); });
      await page.route('**/*', route => { report.blockedRequests.push(route.request().url()); return route.abort(); });
      const body = '<iframe id="generated" sandbox="allow-scripts" referrerpolicy="no-referrer" style="width:100%;height:100%;border:0" srcdoc="' + escapeAttribute(applyOfflinePolicy(html)) + '"></iframe>';
      await page.setContent('<!doctype html><style>html,body{width:100%;height:100%;margin:0}</style>' + body);
      const handle = await page.locator('#generated').elementHandle();
      const frame = await handle.contentFrame();
      await frame.locator('body').waitFor({ state: 'attached' });
      const current = { ...viewport, passed: true, steps: [] };
      for (const [index, step] of scenario.steps.entries()) {
        try {
          await check(frame, step);
          current.steps.push({ index, op: step.op, passed: true });
        } catch (e) {
          current.steps.push({ index, op: step.op, passed: false, error: String(e?.message ?? e) });
          current.passed = false;
          break;
        }
      }
      if (runtimeErrors.length) { current.runtimeErrors = runtimeErrors; current.passed = false; }
      report.viewports.push(current);
      await context.close();
    }
    report.passed = report.viewports.every(v => v.passed) && report.blockedRequests.length === 0;
    if (reportPath) await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n');
    return report;
  } finally { await browser.close(); }
}

async function main() {
  const options = {}, args = process.argv.slice(2);
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i], value = args[i + 1];
    if (!['--html', '--scenario', '--report', '--browser'].includes(key) || !value) throw Error('Usage: --html file.html --scenario checks.json [--report result.json] [--browser chromium|firefox|webkit]');
    options[key.slice(2)] = value;
  }
  if (!options.html || !options.scenario) throw Error('Both --html and --scenario are required');
  const html = await readFile(options.html, 'utf8'), raw = await readFile(options.scenario, 'utf8');
  if (Buffer.byteLength(raw) > 100000) throw Error('Scenario exceeds 100KB');
  const result = await auditHtml({ html, scenario: JSON.parse(raw), browserName: options.browser, reportPath: options.report });
  console.log(JSON.stringify({ name: result.name, passed: result.passed, viewports: result.viewports, blockedRequests: result.blockedRequests }, null, 2));
  if (!result.passed) process.exitCode = 1;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch(e => { console.error(e); process.exitCode = 1; });
