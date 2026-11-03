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

const P01_SCRIPT = `
  <canvas data-canvas="p01" width="240" height="120"></canvas>
  <button data-acceptance-pause>暂停</button>
  <p>相位动画</p>
  <script>
    const canvas = document.querySelector('canvas[data-canvas]');
    const context = canvas.getContext('2d');
    let phase = 0;
    let running = true;
    function draw() {
      context.fillStyle = '#000';
      context.fillRect(0, 0, 240, 120);
      context.fillStyle = '#fff';
      const x = 120 + 80 * Math.sin(phase);
      context.beginPath();
      context.arc(x, 60, 12, 0, Math.PI * 2);
      context.fill();
    }
    function loop() {
      if (!running) return;
      phase += 0.35;
      draw();
      requestAnimationFrame(loop);
    }
    document.querySelector('[data-acceptance-pause]').addEventListener('click', () => { running = false; });
    requestAnimationFrame(loop);
  </script>`;

export const P01_ANIMATED = PAGE(P01_SCRIPT);

/** The button looks like it pauses, but the animation keeps running. */
export const P01_IGNORES_PAUSE = PAGE(`
  <canvas data-canvas="p01" width="240" height="120"></canvas>
  <button data-acceptance-pause>暂停</button>
  <p>相位动画</p>
  <script>
    const canvas = document.querySelector('canvas[data-canvas]');
    const context = canvas.getContext('2d');
    let phase = 0;
    let paused = false;
    function draw() {
      context.fillStyle = '#000';
      context.fillRect(0, 0, 240, 120);
      context.fillStyle = '#fff';
      const x = 120 + 80 * Math.sin(phase);
      context.beginPath();
      context.arc(x, 60, 12, 0, Math.PI * 2);
      context.fill();
    }
    function loop() {
      phase += 0.35;
      draw();
      requestAnimationFrame(loop);
    }
    document.querySelector('[data-acceptance-pause]').addEventListener('click', () => { paused = true; });
    requestAnimationFrame(loop);
  </script>`);

const M01_BODY = `
  <label>x <input type="range" min="-5" max="5" step="1" value="3" data-x></label>
  <output data-y>7</output>
  <canvas data-canvas="m01" width="240" height="120"></canvas>`;

export const M01_CANVAS = PAGE(`
  ${M01_BODY}
  <div data-acceptance-declared='{"y":7}'></div>
  <script>
    const canvas = document.querySelector('canvas[data-canvas]');
    const context = canvas.getContext('2d');
    const input = document.querySelector('input[data-x]');
    const output = document.querySelector('output[data-y]');
    const declared = document.querySelector('[data-acceptance-declared]');
    function draw() {
      const x = Number(input.value);
      const y = 2 * x + 1;
      output.textContent = String(y);
      declared.setAttribute('data-acceptance-declared', JSON.stringify({ y }));
      context.fillStyle = '#fff';
      context.fillRect(0, 0, 240, 120);
      context.strokeStyle = '#888';
      context.beginPath();
      context.moveTo(0, 60);
      context.lineTo(240, 60);
      context.stroke();
      context.fillStyle = '#c33';
      context.beginPath();
      context.arc(120 + x * 20, 60 - y * 10, 6, 0, Math.PI * 2);
      context.fill();
    }
    input.addEventListener('input', draw);
    draw();
  </script>`);

/** The label updates with x, but the canvas never redraws. */
export const M01_FROZEN_CANVAS = PAGE(`
  ${M01_BODY}
  <script>
    const input = document.querySelector('input[data-x]');
    const output = document.querySelector('output[data-y]');
    input.addEventListener('input', () => { output.textContent = String(2 * Number(input.value) + 1); });
  </script>`);
