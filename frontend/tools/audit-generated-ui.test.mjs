import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateScenario, applyOfflinePolicy, escapeAttribute, htmlFromInteractiveCard } from './audit-generated-ui.mjs';

const spec = {
  version: 1, name: '库存演示',
  viewports: [{ width: 390, height: 844 }],
  steps: [{ op: 'expectNoOverflow' }],
};

test('accepts bounded independent checks', () => {
  assert.equal(validateScenario(spec), spec);
});
test('rejects arbitrary execution, oversized waits and invalid viewports', () => {
  assert.throws(() => validateScenario({ ...spec, steps: [{ op: 'eval', selector: 'body' }] }), /Invalid operation/);
  assert.throws(() => validateScenario({ ...spec, steps: [{ op: 'wait', selector: 'body', ms: 99999 }] }), /Invalid wait/);
  assert.throws(() => validateScenario({ ...spec, viewports: [{ width: 90000, height: 844 }] }), /Invalid viewport/);
});
test('rejects malformed equation and SVG endpoint specifications', () => {
  assert.throws(() => validateScenario({ ...spec, steps: [{ op: 'expectEquation', selector: '#a', total: '#a', locked: '#b' }] }), /equation/);
  assert.throws(() => validateScenario({ ...spec, steps: [{ op: 'expectLineAnchored', selector: '#line', from: '#left', to: '#right', tolerancePx: 500 }] }), /line endpoints/);
});
test('places restrictive CSP before generated scripts', () => {
  const html = applyOfflinePolicy('<!doctype html><script>window.x=1</script>');
  assert.ok(html.indexOf('Content-Security-Policy') < html.indexOf('<script>'));
  assert.match(html, /connect-src 'none'/);
  assert.match(html, /form-action 'none'/);
});
test('escapes malicious srcdoc attribute termination', () => {
  assert.equal(escapeAttribute('" onload="alert(1)<script>&'), '&quot; onload=&quot;alert(1)&lt;script&gt;&amp;');
});

test('accepts published state assertions and blocks unsafe or invalid paths', () => {
  const sample = { ...spec, steps: [{ op: 'expectState', path: 'controls.锁定', equals: 12 }] };
  assert.equal(validateScenario(sample), sample);
  for (const bad of [
    { op: 'expectState', path: '__proto__.evil', equals: 2 },
    { op: 'expectState', path: 'stock..locked', equals: 2 },
    { op: 'expectState', path: 'inventory', equals: { stock: 2 } },
  ]) assert.throws(() => validateScenario({ ...spec, steps: [bad] }), /Invalid state assertion/);
});

test('loads a bounded saved real-model card directly for replay', () => {
  const card = { type: 'interactive', id: 'stock', revision: 1, title: '库存', summary: '测试模型结果', html: '<button>操作</button>' };
  assert.equal(htmlFromInteractiveCard(JSON.stringify(card)), card.html);
  for (const bad of [{ ...card, type: 'chart' }, { ...card, id: '../escape' }, { ...card, revision: 0 }, { ...card, html: '' }]) {
    assert.throws(() => htmlFromInteractiveCard(JSON.stringify(bad)), /bounded interactive card/);
  }
  assert.throws(() => htmlFromInteractiveCard('{incomplete'), /Invalid interactive card/);
});
