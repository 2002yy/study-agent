import { useState } from "react";
import type { AnswerCard } from "./answerUiProtocol";

type Memory = { a: number | null; b: number | null; objects: { id: number; name: string }[]; code: string; explanation: string };
export function MemoryLab({ card }: { card: Extract<AnswerCard, { type: "memory_lab" }> }) {
  const initial = (): Memory => ({ a: 1, b: 1, objects: [{ id: 1, name: card.initialName }], code: "Student b = a;", explanation: "a 与 b 引用同一个对象；两个变量不是两个对象。" });
  const [state, setState] = useState(initial);
  const apply = (op: "mutate" | "assign" | "clear" | "clearAll") => setState(s => {
    const literal = JSON.stringify(card.updatedName);
    if (op === "mutate") return s.b === null ? { ...s, code: `b.name = ${literal};`, explanation: "b 为 null；访问属性会触发 NullPointerException，引用和对象均未改变。" }
      : { ...s, objects: s.objects.map(o => o.id === s.b ? { ...o, name: card.updatedName } : o), code: `b.name = ${literal};`, explanation: s.a === s.b ? "a 与 b 指向同一对象；改变的是对象属性，a.name 也会读到新值。" : "只改变 b 当前引用的对象；a 的引用和它指向的对象没有变化。" };
    if (op === "assign") { const id = Math.max(...s.objects.map(o => o.id)) + 1; return { ...s, b: id, objects: [...s.objects, { id, name: card.updatedName }], code: `b = new Student(${literal});`, explanation: "创建新对象，并让 b 指向它；重新赋值没有改变 a。" }; }
    if (op === "clear") return { ...s, b: null, code: "b = null;", explanation: "只移除 b 的引用；对象是否仍可达取决于 a，置空不等于立即回收。" };
    return { ...s, a: null, b: null, code: "a = null;\nb = null;", explanation: "在此模型中，对象已无法经 a、b 到达，符合回收条件；这不意味着 GC 已实际发生。" };
  });
  return <>
    <p className="answer-lab-note">Java 概念模拟 · 只考虑 a、b 两个引用，不执行代码或预测 GC 时机。</p>
    <pre><code>{`Student a = new Student(${JSON.stringify(card.initialName)});\nStudent b = a;`}</code></pre>
    <div className="answer-controls" aria-label="选择内存操作"><button type="button" onClick={() => apply("mutate")}>修改属性</button><button type="button" disabled={state.objects.length >= 12} onClick={() => apply("assign")}>重新赋值</button><button type="button" onClick={() => apply("clear")}>置空 b</button><button type="button" onClick={() => apply("clearAll")}>全部置空</button></div>
    <p className="answer-lab-label">最近执行</p><pre><code>{state.code}</code></pre>
    <div className="answer-lab-grid">
      <section aria-label="局部变量与引用"><h4>局部变量 / 引用</h4>{(["a", "b"] as const).map(ref => <p key={ref}><code>{ref}</code><span>→ {state[ref] === null ? "null" : `#${state[ref]}`}</span></p>)}</section>
      <section aria-label="堆上的对象"><h4>堆上的对象</h4>{state.objects.map(o => <div key={o.id} className="answer-heap-object"><strong>对象 #{o.id}</strong><span>name = {JSON.stringify(o.name)}</span>{sUnreachable(state, o.id) ? <small>不可达 · 可被回收</small> : <small>仍可达</small>}</div>)}</section>
    </div>
    <p className="answer-lab-result" role="status">{state.explanation}</p>
    {state.objects.length >= 12 ? <small>已达本次实验的12个对象上限，可重置后继续。</small> : null}
    <div className="answer-controls"><button type="button" onClick={() => setState(initial())}>重置实验</button></div>
  </>;
}
const sUnreachable = (s: Memory, id: number) => s.a !== id && s.b !== id;

export function PerformanceLab({ card }: { card: Extract<AnswerCard, { type: "performance_lab" }> }) {
  const initial = { pages: card.pages, concurrency: card.concurrency, readSeconds: card.readSeconds, summarySeconds: card.summarySeconds };
  const [params, setParams] = useState(initial);
  const batches = Math.ceil(params.pages / params.concurrency);
  const serial = params.pages * params.readSeconds + params.summarySeconds;
  const parallel = batches * params.readSeconds + params.summarySeconds;
  const saved = serial - parallel;
  const controls = [["pages", "需要读取的网页数", 1, 40, 1, "个"], ["concurrency", "允许同时读取的网页数", 1, 12, 1, "个"], ["readSeconds", "每个网页的读取耗时", 1, 20, .5, "秒"], ["summarySeconds", "最终模型总结耗时", 0, 30, .5, "秒"]] as const;
  return <>
    <p className="answer-lab-note">简化模型预测 · 参数是演示假设，不是真实压测数据。</p>
    <div className="answer-lab-sliders">{controls.map(([key, label, min, max, step, unit]) => <label key={key}><span>{label}</span><output>{params[key]} {unit}</output><input type="range" aria-label={label} min={min} max={max} step={step} value={params[key]} onChange={e => setParams({ ...params, [key]: Number(e.target.value) })} /></label>)}</div>
    <div className="answer-lab-grid answer-lab-metrics"><section><span>串行读取总耗时</span><output aria-label="串行读取总耗时">{serial}s</output></section><section><span>并发读取总耗时</span><output aria-label="并发读取总耗时">{parallel}s</output></section></div>
    <svg role="img" aria-label={`模拟耗时：串行${serial}秒，并发${parallel}秒`} viewBox="0 0 420 160"><line x1="30" x2="390" y1="130" y2="130" className="answer-grid" /><rect x="70" y={130 - 100} width="90" height="100" rx="5" fill="#527896" /><rect x="260" y={130 - parallel / serial * 100} width="90" height={parallel / serial * 100} rx="5" fill="#859d87" /><text x="115" y="150" textAnchor="middle">串行 {serial}s</text><text x="305" y="150" textAnchor="middle">并发 {parallel}s</text></svg>
    <p className="answer-lab-result" role="status" aria-label="性能预测结论">分成 {batches} 批 · 节省 {saved} 秒 · 耗时降低 {Math.round(saved / serial * 100)}%</p>
    <p>当前 {params.pages} 个网页需要 {batches} 批，每批最多 {params.concurrency} 个；总结仍需等待最后一批完成。</p>
    <details className="answer-data"><summary>计算方法与实验边界</summary><p>串行 = 网页数 × 单页耗时 + 总结耗时；并发 = ceil(网页数 / 并发数) × 单页耗时 + 总结耗时。假设各页等时长，无并发开销、限流、失败重试。真实系统还受尾延迟、CPU和模型队列影响。</p></details>
    <div className="answer-controls"><button type="button" onClick={() => setParams(initial)}>恢复默认参数</button></div>
  </>;
}

export function EvidenceLab({ card }: { card: Extract<AnswerCard, { type: "evidence_lab" }> }) {
  const [selected, setSelected] = useState<number[]>([0]);
  const measured = selected.map(i => card.sources[i]).filter(p => p.kind === "measurement");
  const counter = measured.some(p => p.aSeconds >= p.bSeconds);
  const verdict = counter ? "发现反例：原命题不成立" : measured.length ? "仅支持已选任务，不能证明所有任务" : "证据不足：暂不下结论";
  return <>
    <p className="answer-lab-note">虚构演示数据 · 本地推演，不改变正式研究的来源选择或发布结论。</p>
    <p>检验命题：模型 A 在所有任务中都比模型 B 更快。</p>
    <div className="answer-evidence-list">{card.sources.map((source, i) => <label key={i} className="answer-evidence-item"><input type="checkbox" checked={selected.includes(i)} onChange={() => setSelected(selected.includes(i) ? selected.filter(n => n !== i) : [...selected, i])} /><div><strong>{source.label}</strong>{source.kind === "measurement" ? <><div className="answer-lab-grid"><span>模型 A：{source.aSeconds}s</span><span>模型 B：{source.bSeconds}s</span></div><small>{source.aSeconds < source.bSeconds ? "支持此任务中 A 更快，不能推广到所有任务。" : "A 在此任务未比 B 更快，构成原命题反例。"}</small></> : <><p>{source.text}</p><small>主观观点，没有可复核测量，不能作为计时证据。</small></>}</div></label>)}</div>
    <div className="answer-lab-result" role="status"><span>已纳入 {selected.length}/{card.sources.length} 个来源</span><strong>{verdict}</strong><p>{counter ? "存在已纳入的测量反例；增加主观评论不能消除这个反例。" : measured.length ? "已选测量仅覆盖有限任务；没有发现反例，不等于证明所有任务都更快。" : "当前没有可用的计时证据。增加主观评论不会提高测量证据的充分性。"}</p></div>
    <div className="answer-controls"><button type="button" onClick={() => setSelected([0])}>重置选择</button><button type="button" onClick={() => setSelected(card.sources.map((_, i) => i))}>纳入全部来源</button></div>
  </>;
}
