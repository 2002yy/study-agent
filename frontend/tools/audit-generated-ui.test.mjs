import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateScenario, applyOfflinePolicy, escapeAttribute } from './audit-generated-ui.mjs';

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
