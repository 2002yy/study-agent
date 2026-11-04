// Deterministic authored fixture, not evidence of a real model generation.
export const explorer = {
  type: "interactive", id: "order-stock", revision: 1, title: "订单来了，库存去了哪里？",
  summary: "拖动锁定数量，观察可售库存的变化。这里用 37 件商品演示：锁定不等于已经出库。",
  html: `<style>
    .quantity { font-size:44px; font-weight:650; letter-spacing:-2px; line-height:1.2; margin:12px 0 22px; }
    .quantity small { font-size:15px; font-weight:400; letter-spacing:0; color:#666; }
    .label { color:#666; font-size:14px; } input { width:100%; accent-color:#39765d; margin:16px 0; }
    svg { display:block; width:100%; margin:12px 0; } .legend { display:flex; gap:18px; flex-wrap:wrap; font-size:14px; }
    .note { background:#f5f6f5; padding:14px; border-radius:10px; margin-top:22px; font-size:14px; }
    button { border:1px solid #ddd; border-radius:8px; background:white; padding:8px 16px; margin-top:14px; }
  </style>
  <div class="label">可售库存</div><div class="quantity"><output id="available">32</output> <small>/ 37 件</small></div>
  <svg viewBox="0 0 370 24" role="img" aria-label="可售与锁定库存比例"><rect width="370" height="24" rx="5" fill="#eee"/><rect id="free-bar" width="320" height="24" rx="5" fill="#39765d"/></svg>
  <div class="legend"><span>深色：可售</span><span>浅色：锁定，尚未出库</span></div>
  <p><label for="locked">锁定数量 <output id="locked-value">5</output> 件</label><input id="locked" name="locked" aria-label="锁定数量" type="range" min="0" max="37" value="5"></p>
  <div class="note" id="explanation" aria-live="polite">37 − 5 = 32 件可售</div><button id="release">释放所有锁定</button>
  <script>
    const locked = document.getElementById('locked');
    function update() {
      const held = Number(locked.value), free = 37 - held;
      document.getElementById('available').textContent = free;
      document.getElementById('locked-value').textContent = held;
      document.getElementById('free-bar').setAttribute('width', free * 10);
      document.getElementById('explanation').textContent = '37 − ' + held + ' = ' + free + ' 件可售';
      window.studyUI.setState({库存:37, 锁定:held, 可售:free});
    }
    locked.addEventListener('input', update);
    document.getElementById('release').addEventListener('click', () => { locked.value = '0'; update(); });
    update();
  </script>`,
};
