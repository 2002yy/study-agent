export type AnswerCard =
  | { type: "image"; title: string; src: string; alt: string; caption?: string }
  | { type: "plot"; title: string; fn: "linear" | "quadratic" | "sine"; a: number; b: number }
  | { type: "chart"; title: string; points: { label: string; value: number }[] }
  | { type: "actions"; title: string; items: { label: string; prompt: string }[] }
  | { type: "map"; title: string; points: { label: string; lat: number; lon: number }[] };

const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const text = (v: unknown, max = 100): v is string => typeof v === "string" && !!v.trim() && v.length <= max;
const number = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v) && Math.abs(v) <= 1e12;
export function safeImageUrl(value: unknown): value is string {
  if (!text(value, 2048) || /[\x00-\x20\\]/.test(value)) return false;
  if (value.startsWith("/assets/") && !value.includes("..")) return true;
  try { const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password; } catch { return false; }
}

export function parseAnswerCard(raw: string): AnswerCard | null {
  if (raw.length > 24000) return null;
  try {
    const c: unknown = JSON.parse(raw);
    if (!record(c) || !text(c.title)) return null;
    // Copy only recognized data. Model-supplied HTML, script, styles and callbacks never reach the renderer.
    const title = c.title;
    if (c.type === "image" && safeImageUrl(c.src) && text(c.alt, 300)
      && (c.caption === undefined || text(c.caption, 600))) return { type: "image", title, src: c.src, alt: c.alt, caption: c.caption };
    if (c.type === "plot" && ["linear", "quadratic", "sine"].includes(String(c.fn))
      && number(c.a) && Math.abs(c.a) <= 5 && number(c.b) && Math.abs(c.b) <= 10)
      return { type: "plot", title, fn: c.fn as "linear" | "quadratic" | "sine", a: c.a, b: c.b };
    if (c.type === "chart" && Array.isArray(c.points) && c.points.length >= 2 && c.points.length <= 40
      && c.points.every(p => record(p) && text(p.label, 60) && number(p.value)))
      return { type: "chart", title, points: c.points.map(p => ({ label: p.label, value: p.value })) };
    if (c.type === "actions" && Array.isArray(c.items) && c.items.length >= 1 && c.items.length <= 4
      && c.items.every(p => record(p) && text(p.label, 40) && text(p.prompt, 600)))
      return { type: "actions", title, items: c.items.map(p => ({ label: p.label, prompt: p.prompt })) };
    if (c.type === "map" && Array.isArray(c.points) && c.points.length >= 1 && c.points.length <= 12
      && c.points.every(p => record(p) && text(p.label, 60) && number(p.lat) && Math.abs(p.lat) <= 85
        && number(p.lon) && Math.abs(p.lon) <= 180))
      return { type: "map", title, points: c.points.map(p => ({ label: p.label, lat: p.lat, lon: p.lon })) };
  } catch { /* Incomplete or unsupported data remains ordinary readable Markdown. */ }
  return null;
}

export type AnswerPart = { kind: "markdown"; content: string; key: number }
  | { kind: "card"; card: AnswerCard; key: number } | { kind: "pending"; key: number };

export function splitAnswerContent(content: string, streaming = false): AnswerPart[] {
  const parts: AnswerPart[] = [];
  const lines = content.split("\n");
  let start = 0;
  let cards = 0;
  for (let i = 0; i < lines.length; i++) {
    const open = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(lines[i]);
    if (!open) continue;
    const marker = open[1];
    const ui = open[2].trim() === "study-ui";
    let end = i + 1;
    while (end < lines.length && !new RegExp(`^ {0,3}${marker[0]}{${marker.length},}\\s*$`).test(lines[end])) end++;
    if (!ui) { i = end; continue; }
    if (end === lines.length && !streaming) break;
    const card = end < lines.length && cards < 4 ? parseAnswerCard(lines.slice(i + 1, end).join("\n")) : null;
    if (card || end === lines.length) {
      if (i > start) parts.push({ kind: "markdown", content: lines.slice(start, i).join("\n"), key: start });
      parts.push(card ? { kind: "card", card, key: i } : { kind: "pending", key: i });
      if (card) cards++;
      start = Math.min(end + 1, lines.length);
    }
    i = end;
  }
  if (start < lines.length) parts.push({ kind: "markdown", content: lines.slice(start).join("\n"), key: start });
  return parts;
}

export const ANSWER_UI_CONTEXT = `【回答中的学习交互组件 v1；仅本轮界面能力，不是学习事实】
优先给出简洁文字，只有确实帮助理解时才添加组件。遵守当前教学策略、引用与证据发布约束；不要输出内部思维链，不要宣称尚未核验的事实。正文继续使用 Markdown，组件放在独立的 study-ui fenced JSON 代码块中，每块仅一个对象，完整关闭后即可显示。最多4块。支持以下格式：
{"type":"plot","title":"探索函数","fn":"quadratic","a":1,"b":0}：fn只能linear/quadratic/sine，分别y=a*x+b、y=a*x*x+b、y=a*sin(x)+b；a在[-5,5]、b在[-10,10]，x固定[-5,5]，控件可调a/b。适合说明，不是实测数据。
{"type":"chart","title":"数据比较","points":[{"label":"甲","value":2},{"label":"乙","value":3}]}：2到40项，只用有依据的数据；示例必须在正文标注。原有引用写在相邻正文中。
{"type":"image","title":"示意图","src":"https://...","alt":"图像描述","caption":"来源与说明"}：仅用已知可访问的真实图片URL或/assets/路径，不编造URL、不使用代码或data URL。
{"type":"actions","title":"继续探索","items":[{"label":"练习一下","prompt":"给我一道相关练习题"}]}：1到4个按钮，仅将问题放入输入框由用户决定发送，不执行外部操作。
{"type":"map","title":"地点","points":[{"label":"地点名","lat":30,"lon":120}]}：只用有依据的坐标，lat在[-85,85]、lon在[-180,180]；地点选择可打开OpenStreetMap底图，没有坐标时改用文字。
不要生成HTML/JavaScript/自定义公式或调用外部操作；现有文本回答始终可用。`;

export function packAnswerUiContext(instruction: string, lesson: string): string {
  // Reuse the server's existing transient envelope; UI guidance is never saved as a user's instruction.
  return "__STUDY_AGENT_TURN_CONTEXT_V1__" + JSON.stringify({
    conversation_instruction: instruction,
    turn_context: [ANSWER_UI_CONTEXT, lesson.trim()].filter(Boolean).join("\n\n"),
  });
}

export function answerCopyText(content: string): string {
  return splitAnswerContent(content).map(part => {
    if (part.kind === "markdown") return part.content.trimEnd();
    if (part.kind === "pending") return "";
    const c = part.card;
    const detail = c.type === "chart" ? c.points.map(p => `${p.label}：${p.value}`).join("\n")
      : c.type === "image" ? [c.alt, c.caption, c.src].filter(Boolean).join("\n")
      : c.type === "map" ? c.points.map(p => `${p.label}：${p.lat}°, ${p.lon}°`).join("\n")
      : c.type === "actions" ? c.items.map(p => `${p.label}：${p.prompt}`).join("\n")
      : `y = ${c.a}${c.fn === "quadratic" ? "x²" : c.fn === "sine" ? "sin(x)" : "x"} + (${c.b})（数学示意，可调参数）`;
    return `${c.title}\n${detail}`;
  }).join("\n\n").trim();
}
