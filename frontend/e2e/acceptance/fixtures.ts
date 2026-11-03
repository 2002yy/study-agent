/**
 * Reference pages for the observer. They are deliberately small: each one is a
 * real page with real SVG geometry, so the observer measures the page instead
 * of trusting a hand-written observation.
 */

const PAGE = (body: string) => `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>body { margin: 0; padding: 16px; font: 16px/1.6 system-ui, sans-serif; }
svg { position: absolute; left: 0; top: 0; }
</style></head><body>${body}</body></html>`;

const NODES = `
  <svg width="420" height="220" viewBox="0 0 420 220" aria-hidden="true">
    <rect data-node="node-a" x="20" y="30" width="80" height="40" fill="#e8f0ff"></rect>
    <rect data-node="node-b" x="20" y="140" width="80" height="40" fill="#fff0f4"></rect>
    <rect data-node="node-new-object" x="260" y="30" width="100" height="40" fill="#eaf7ee"></rect>
  </svg>`;

export const J01_CORRECT = PAGE(`
  <div data-acceptance-declared='{"objectOfA":1,"objectOfB":2}'>b = new Object()</div>
  ${NODES}
  <svg width="420" height="220" viewBox="0 0 420 220">
    <line data-arrow="arrow-a" data-from="node-a" data-to="node-a" x1="60" y1="70" x2="60" y2="40" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b-shared" data-from="node-b" data-to="node-a" x1="60" y1="140" x2="60" y2="70" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b" data-from="node-b" data-to="node-new-object" x1="100" y1="160" x2="260" y2="50" stroke="#333" stroke-width="2"></line>
  </svg>
  <p>a 与 b 共享对象；b = new 之后分成两个对象。</p>`);

export const J01_WRONG_ARROW = PAGE(`
  <div data-acceptance-declared='{"objectOfA":1,"objectOfB":2}'>b = new Object()</div>
  ${NODES}
  <svg width="420" height="220" viewBox="0 0 420 220">
    <line data-arrow="arrow-a" data-from="node-a" data-to="node-a" x1="60" y1="70" x2="60" y2="40" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b-shared" data-from="node-b" data-to="node-a" x1="60" y1="140" x2="60" y2="70" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b" data-from="node-b" data-to="node-new-object" x1="100" y1="160" x2="180" y2="205" stroke="#333" stroke-width="2"></line>
  </svg>
  <p>箭头画到了空白处。</p>`);

/** The page prints the right counts; its picture shows only one target for b. */
export const J01_PICTURE_LIES = PAGE(`
  <div data-acceptance-declared='{"objectOfA":1,"objectOfB":2}'>b = new Object()</div>
  ${NODES}
  <svg width="420" height="220" viewBox="0 0 420 220">
    <line data-arrow="arrow-a" data-from="node-a" data-to="node-a" x1="60" y1="70" x2="60" y2="40" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b" data-from="node-b" data-to="node-new-object" x1="100" y1="160" x2="260" y2="50" stroke="#333" stroke-width="2"></line>
  </svg>
  <p>文字说有两个对象，图上只有一条来自 b 的箭头。</p>`);

export const RUNTIME_ERROR = PAGE(`
  <p>正在加载…</p>
  <script>throw new Error("boom: init failed");</script>`);

export const TINY_FONT = PAGE(`
  <div data-acceptance-declared='{}'>
    <p style="font-size:12px">坐标轴说明文字</p>
  </div>`);

export const OVERFLOW = PAGE(`
  <div data-acceptance-declared='{}' style="width:2000px">很宽的时间线</div>`);

export const NO_EVIDENCE = PAGE(`<p>只有一段说明文字，没有任何可核对的数据。</p>`);
