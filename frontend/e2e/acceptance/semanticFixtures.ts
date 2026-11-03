/**
 * Minimal J01-shaped pages for the semantic locator test.
 *
 * They deliberately carry no `data-acceptance-*` attributes: the locator must
 * find variables, objects and arrows the way it does on a saved real answer.
 * Three layouts mirror what the saved documents actually used: SVG groups,
 * correctly positioned HTML boxes, and HTML boxes whose `left/top` have no
 * effect because `position` is missing.
 */
export type J01Layout = "svg" | "html" | "broken";

export function j01Page(layout: J01Layout): string {
  const objectCss =
    layout === "broken"
      ? ".obj{width:180px;border:1px solid #3f8f5f;box-sizing:border-box;padding:4px 8px}"
      : ".obj{position:absolute;width:180px;height:70px;border:1px solid #3f8f5f;box-sizing:border-box;padding:4px 8px}";

  return `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
  body{font:16px/1.6 system-ui,sans-serif;margin:16px;color:#1f2933}
  .diagram{position:relative;width:460px;height:300px;border:1px solid #e1e7ec}
  .arrows{position:absolute;left:0;top:0;width:460px;height:300px}
  .box{position:absolute;width:110px;height:44px;border:1px solid #7fb2e5;box-sizing:border-box;padding:2px 8px;font-family:monospace}
  ${objectCss}
  button{min-height:40px;padding:8px 16px;margin-right:8px}
</style></head><body>
  <div class="diagram" id="diagram">
    <svg class="arrows" id="arrows" viewBox="0 0 460 300"></svg>
  </div>
  <div id="values"></div>
  <div class="controls">
    <button id="prev" type="button">上一步</button>
    <button id="next" type="button">下一步</button>
    <button id="reset" type="button">重置</button>
  </div>
  <div id="stepLabel"></div>
<script>
(function(){
  var step = 0;
  var LAYOUT = ${JSON.stringify(layout)};
  var NS = "http://www.w3.org/2000/svg";
  function state(){
    return {
      a: step >= 1,
      b: step >= 2,
      obj1: step >= 1,
      obj2: step >= 4,
      bNew: step >= 4,
      hits1: step >= 3 ? 3 : 0,
      hits2: step >= 5 ? 7 : 0
    };
  }
  function addNode(kind, label, sub, x, y, w, h){
    if (LAYOUT === "svg") {
      var svg = document.getElementById("arrows");
      var g = document.createElementNS(NS, "g");
      var rect = document.createElementNS(NS, "rect");
      rect.setAttribute("x", x); rect.setAttribute("y", y);
      rect.setAttribute("width", w); rect.setAttribute("height", h);
      rect.setAttribute("fill", "none"); rect.setAttribute("stroke", "#888");
      var first = document.createElementNS(NS, "text");
      first.setAttribute("x", x + 8); first.setAttribute("y", y + 20);
      first.textContent = label;
      var second = document.createElementNS(NS, "text");
      second.setAttribute("x", x + 8); second.setAttribute("y", y + 38);
      second.textContent = kind === "obj" ? ("hits = " + sub) : sub;
      g.appendChild(rect); g.appendChild(first); g.appendChild(second);
      svg.appendChild(g);
      return;
    }
    var diagram = document.getElementById("diagram");
    var element = document.createElement("div");
    element.className = kind === "obj" ? "obj" : "box";
    element.setAttribute("style", "left:" + x + "px;top:" + y + "px");
    element.innerHTML = kind === "obj"
      ? '<div class="title">' + label + '</div><div>hits = ' + sub + '</div>'
      : label + '<br><span>' + sub + '</span>';
    diagram.appendChild(element);
  }
  function render(){
    var svg = document.getElementById("arrows");
    Array.prototype.slice.call(svg.querySelectorAll("g")).forEach(function(g){ g.remove(); });
    Array.prototype.slice.call(document.querySelectorAll(".box,.obj")).forEach(function(e){ e.remove(); });
    var s = state();
    var lines = [];
    if (s.a) lines.push([130, 62, 248, 75]);
    if (s.b) lines.push([130, 152, 248, s.bNew ? 205 : 75]);
    svg.innerHTML = lines.map(function(line){
      return '<line x1="' + line[0] + '" y1="' + line[1] + '" x2="' + line[2] + '" y2="' + line[3] + '" stroke="#2f6fb0" stroke-width="2"/>';
    }).join("");

    addNode("var", "a", s.a ? "→ 对象1" : "未赋值", 20, 40, 110, 44);
    addNode("var", "b", s.b ? (s.bNew ? "→ 对象2" : "→ 对象1") : "未赋值", 20, 130, 110, 44);
    if (s.obj1) addNode("obj", "对象1 CacheEntry", s.hits1, 250, 40, 180, 70);
    if (s.obj2) addNode("obj", "对象2 CacheEntry", s.hits2, 250, 170, 180, 70);

    document.getElementById("values").textContent =
      "a: " + (s.a ? "指向对象1" : "未赋值") + "\\n" +
      "b: " + (s.b ? (s.bNew ? "指向对象2" : "指向对象1") : "未赋值");
    document.getElementById("stepLabel").textContent =
      step === 0 ? "当前：执行前，此时没有任何对象" : ("当前：执行完第 " + step + " 行");
    document.getElementById("prev").disabled = step === 0;
    document.getElementById("next").disabled = step === 5;
  }
  document.getElementById("next").addEventListener("click", function(){ if (step < 5) { step++; render(); } });
  document.getElementById("prev").addEventListener("click", function(){ if (step > 0) { step--; render(); } });
  document.getElementById("reset").addEventListener("click", function(){ step = 0; render(); });
  render();
})();
</script></body></html>`;
}
