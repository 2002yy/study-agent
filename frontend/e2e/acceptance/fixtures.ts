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

/** The page prints two objects; its re-pointed arrow still lands on the first. */
export const J01_PICTURE_LIES = PAGE(`
  <div data-acceptance-declared='{"objectOfA":1,"objectOfB":2}'>b = new Object()</div>
  ${NODES}
  <svg width="420" height="220" viewBox="0 0 420 220">
    <line data-arrow="arrow-a" data-from="node-a" data-to="node-a" x1="60" y1="70" x2="60" y2="40" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b" data-from="node-b" data-to="node-a" x1="100" y1="160" x2="100" y2="70" stroke="#333" stroke-width="2"></line>
  </svg>
  <p>文字说 b 已指向新对象，图上却仍然指向旧对象。</p>`);

/**
 * J01 as a two-step page: the shared phase and the re-pointed phase are read
 * from the same document, so the reference matrix can judge both.
 */
export const J01_STEPS = PAGE(`
  <div data-acceptance-declared='{"objectOfA":1,"objectOfB":1}'></div>
  ${NODES}
  <svg width="420" height="220" viewBox="0 0 420 220">
    <line data-arrow="arrow-a" data-from="node-a" data-to="node-a" x1="60" y1="70" x2="60" y2="40" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b-shared" data-from="node-b" data-to="node-a" x1="60" y1="140" x2="60" y2="70" stroke="#333" stroke-width="2"></line>
    <line data-arrow="arrow-b" data-from="node-b" data-to="node-new-object" x1="100" y1="160" x2="260" y2="50" stroke="#333" stroke-width="2" hidden></line>
  </svg>
  <button type="button" style="position:relative;z-index:10;margin-top:240px">b = new Object()</button>
  <script>
    const declared = document.querySelector('[data-acceptance-declared]');
    const rePointed = document.querySelector('line[data-arrow="arrow-b"]');
    document.querySelector('button').addEventListener('click', () => {
      declared.setAttribute('data-acceptance-declared', JSON.stringify({ objectOfA: 1, objectOfB: 2 }));
      rePointed.removeAttribute('hidden');
    });
  </script>`);

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
      context.arc(x, 60, 30, 0, Math.PI * 2);
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

/**
 * A deterministic phase-position reference: the ball is drawn from the phase,
 * the page prints the matching number, and the amplitude is visible as two
 * tall marks. The observer must recover the position from pixels, not text.
 */
const P01_STEPPED_SCRIPT = (drawnFactor: number) => `
  <canvas data-canvas="p01" width="240" height="120"></canvas>
  <label>相位 <input type="range" min="0" max="6.2832" step="0.01" value="0" data-phase></label>
  <button data-play>播放</button>
  <button data-pause>暂停</button>
  <p>振幅 A = 2</p>
  <p>位移 x = <span data-position>0.00</span></p>
  <div data-acceptance-declared='{"position":0}'></div>
  <script>
    const canvas = document.querySelector('canvas[data-canvas]');
    const context = canvas.getContext('2d');
    const phaseInput = document.querySelector('[data-phase]');
    const declared = document.querySelector('[data-acceptance-declared]');
    const positionText = document.querySelector('[data-position]');
    const CX = 120, CY = 60, AMP = 80, R = 20;
    let phaseValue = 0;
    let playing = false;
    let last = 0;
    function render() {
      const position = 2 * Math.sin(phaseValue);
      declared.setAttribute('data-acceptance-declared', JSON.stringify({ position: Number(position.toFixed(3)) }));
      positionText.textContent = position.toFixed(2);
      context.fillStyle = '#fff';
      context.fillRect(0, 0, 240, 120);
      context.strokeStyle = '#cbd2d9';
      context.lineWidth = 2;
      context.beginPath();
      context.moveTo(10, CY);
      context.lineTo(230, CY);
      context.stroke();
      context.strokeStyle = '#9aa5b1';
      [CX - AMP, CX, CX + AMP].forEach(x => {
        context.beginPath();
        context.moveTo(x, CY - 20);
        context.lineTo(x, CY + 20);
        context.stroke();
      });
      context.fillStyle = '#2680c2';
      context.beginPath();
      context.arc(CX + AMP * ${drawnFactor} * Math.sin(phaseValue), CY, R, 0, Math.PI * 2);
      context.fill();
    }
    phaseInput.addEventListener('input', () => {
      playing = false;
      phaseValue = Number(phaseInput.value);
      render();
    });
    document.querySelector('[data-play]').addEventListener('click', () => {
      if (!playing) { playing = true; last = 0; requestAnimationFrame(tick); }
    });
    document.querySelector('[data-pause]').addEventListener('click', () => { playing = false; });
    function tick(timestamp) {
      if (!playing) return;
      if (!last) last = timestamp;
      const dt = (timestamp - last) / 1000;
      last = timestamp;
      phaseValue = (phaseValue + 2 * dt) % (Math.PI * 2);
      phaseInput.value = String(phaseValue);
      render();
      requestAnimationFrame(tick);
    }
    render();
  </script>`;

export const P01_STEPPED = PAGE(P01_STEPPED_SCRIPT(1));

/** The number says 2, but the drawn marker only reaches half the amplitude. */
export const P01_STEPPED_LIES = PAGE(P01_STEPPED_SCRIPT(0.5));

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
      context.arc(x, 60, 30, 0, Math.PI * 2);
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
  <span data-value="y">7</span>
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
    const observedY = document.querySelector('[data-value="y"]');
    function draw() {
      const x = Number(input.value);
      const y = 2 * x + 1;
      output.textContent = String(y);
      observedY.textContent = String(y);
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

/** Remaining task references: each phase section carries its own declared and
 *  structured values, so the matrix can judge every task from real DOM. */

export const J02_PAGE = PAGE(`
  <div data-phase="call" data-acceptance-declared='{"dispatchedImplementations":1}'>
    <p>Animal a = new Dog(); a.sound() 执行 Dog 的实现</p>
    <span data-value="dispatchedImplementations">1</span>
  </div>`);

export const A01_PAGE = PAGE(`
  <div data-phase="found" data-acceptance-declared='{"firstChecked":2,"secondChecked":3}'>
    <p>先检查索引 2（值 5），再检查索引 3（值 7），找到 7</p>
    <span data-value="firstChecked">2</span>
    <span data-value="secondChecked">3</span>
  </div>`);

export const A02_PAGE = PAGE(`
  <div data-phase="result" data-acceptance-declared='{"distance":6}'>
    <p>最短路径 A-B-C-D，距离 6</p>
    <span data-value="distance">6</span>
  </div>`);

export const D01_PAGES = PAGE(`
  <section data-phase="committed" data-acceptance-declared='{"A":70,"B":70}'>
    <p>转账完成</p>
    <span data-value="A">70</span><span data-value="B">70</span>
  </section>
  <section data-phase="rolled_back" data-acceptance-declared='{"A":100,"B":40}'>
    <p>事务回滚，A=100，B=40</p>
    <span data-value="A">100</span><span data-value="B">40</span>
  </section>`);

export const D02_PAGES = PAGE(`
  <section data-phase="interleaved" data-acceptance-declared='{"stock":9}'>
    <p>交错执行</p><span data-value="stock">9</span>
  </section>
  <section data-phase="serialized" data-acceptance-declared='{"stock":8}'>
    <p>串行执行</p><span data-value="stock">8</span>
  </section>`);

export const C01_PAGE = PAGE(`
  <div data-phase="running" data-acceptance-declared='{"running":2,"waiting":1}'>
    <p>两个任务运行，一个任务等待</p>
    <span data-value="running">2</span><span data-value="waiting">1</span>
  </div>`);

export const M02_PAGES = PAGE(`
  <section data-phase="base" data-acceptance-declared='{"zero1":-2,"zero2":2,"vertexY":-4}'>
    <p>零点 -2 与 2，顶点 (0,-4)</p>
    <span data-value="zero1">-2</span><span data-value="zero2">2</span><span data-value="vertexY">-4</span>
  </section>
  <section data-phase="adjusted" data-acceptance-declared='{"zero1":-1,"zero2":1}'>
    <p>零点 -1 与 1</p>
    <span data-value="zero1">-1</span><span data-value="zero2">1</span>
  </section>`);

export const S01_PAGE = PAGE(`
  <div data-phase="metrics" data-acceptance-declared='{"precision":0.8,"recall":0.6667}'>
    <p>TP=40 FP=10 FN=20 TN=30</p>
    <span data-value="precision" id="precision">0.8</span>
    <span data-value="recall" id="recall">0.6667</span>
    <script>
      const tp = 40, fp = 10, fn = 20;
      document.getElementById("precision").textContent = String(tp / (tp + fp));
      document.getElementById("recall").textContent = String(tp / (tp + fn));
    </script>
  </div>`);

export const N01_PAGE = PAGE(`
  <div data-phase="complete" data-acceptance-declared='{"syn":1,"synAck":2,"ack":3}'>
    <p>SYN → SYN-ACK → ACK</p>
    <span data-value="syn">1</span><span data-value="synAck">2</span><span data-value="ack">3</span>
    <svg width="420" height="220" viewBox="0 0 420 220">
      <rect data-node="node-server" x="300" y="0" width="60" height="40" fill="#eef"></rect>
      <line data-arrow="arrow-ack" data-from="node-client" data-to="node-server" x1="20" y1="60" x2="310" y2="20" stroke="#333" stroke-width="2"></line>
    </svg>
  </div>`);
