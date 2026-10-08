import { useId, useState } from "react";
import { ArrowUpRight, Image, MapPin, RotateCcw } from "lucide-react";
import type { AnswerCard } from "./answerUiProtocol";
import { ConsentImage } from "../../components/ConsentImage";
import "./answerUi.css";
import { EvidenceLab, MemoryLab, PerformanceLab } from "./AnswerLabs";

function Plot({ card }: { card: Extract<AnswerCard, { type: "plot" }> }) {
  const [a, setA] = useState(card.a);
  const [b, setB] = useState(card.b);
  const clip = useId().replace(/:/g, "");
  const compute = (x: number) => a * (card.fn === "quadratic" ? x * x : card.fn === "sine" ? Math.sin(x) : x) + b;
  const points = Array.from({ length: 101 }, (_, i) => { const x = -5 + i / 10; return `${40 + (x + 5) * 40},${110 - compute(x) * 3}`; }).join(" ");
  const formula = `y = ${a}${card.fn === "quadratic" ? "x²" : card.fn === "sine" ? "sin(x)" : "x"} ${b < 0 ? "−" : "+"} ${Math.abs(b)}`;
  return <>
    <p className="answer-formula"><output aria-live="polite">{formula}</output><span>数学示意 · x ∈ [−5, 5]，y 显示 [−30, 30]</span></p>
    <svg viewBox="0 0 480 230" role="img" aria-label={`${card.title}：${formula}`}>
      <defs><clipPath id={clip}><rect x="40" y="20" width="400" height="180" /></clipPath></defs>
      {[-30, 0, 30].map(y => <g key={y}><line x1="40" x2="440" y1={110 - y * 3} y2={110 - y * 3} className="answer-grid" /><text x="30" y={114 - y * 3} textAnchor="end">{y}</text></g>)}
      {[-5, 0, 5].map(x => <g key={x}><line x1={40 + (x + 5) * 40} x2={40 + (x + 5) * 40} y1="20" y2="200" className="answer-grid" /><text x={40 + (x + 5) * 40} y="222" textAnchor="middle">{x}</text></g>)}
      <polyline points={points} clipPath={`url(#${clip})`} fill="none" stroke="currentColor" strokeWidth="3" />
    </svg>
    <div className="answer-controls">
      <label>系数 a <output>{a}</output><input aria-label={`${card.title} 系数 a`} type="range" min={-5} max={5} step={0.1} value={a} onChange={e => setA(Number(e.target.value))} /></label>
      <label>偏移 b <output>{b}</output><input aria-label={`${card.title} 偏移 b`} type="range" min={-10} max={10} step={0.5} value={b} onChange={e => setB(Number(e.target.value))} /></label>
      <button type="button" onClick={() => { setA(card.a); setB(card.b); }}><RotateCcw size={14} />恢复初始</button>
    </div>
    <details className="answer-data"><summary>查看采样数值</summary><table><thead><tr><th>x</th><th>y</th></tr></thead><tbody>{[-5, -2, 0, 2, 5].map(x => <tr key={x}><td>{x}</td><td>{Number(compute(x).toFixed(3))}</td></tr>)}</tbody></table></details>
  </>;
}

function Chart({ card }: { card: Extract<AnswerCard, { type: "chart" }> }) {
  const [mode, setMode] = useState<"bar" | "line">("bar");
  const min = Math.min(0, ...card.points.map(p => p.value));
  const max = Math.max(0, ...card.points.map(p => p.value));
  const range = max - min || 1;
  const y = (value: number) => 195 - (value - min) / range * 165;
  const x = (i: number) => 55 + i / (card.points.length - 1) * 360;
  const barWidth = Math.min(28, 300 / card.points.length);
  return <>
    <div className="answer-view-toggle" aria-label={`${card.title} 图表类型`}>
      <button type="button" aria-pressed={mode === "bar"} onClick={() => setMode("bar")}>柱状图</button>
      <button type="button" aria-pressed={mode === "line"} onClick={() => setMode("line")}>折线图</button>
    </div>
    <svg viewBox="0 0 480 230" role="img" aria-label={`${card.title}，${mode === "bar" ? "柱状图" : "折线图"}，${card.points.length} 项；完整数值在下方表格`}>
      <line x1="40" x2="440" y1={y(0)} y2={y(0)} className="answer-grid" />
      <text x="36" y="24">{max.toLocaleString()}</text><text x="36" y="215">{min.toLocaleString()}</text>
      {mode === "line" ? <polyline points={card.points.map((p, i) => `${x(i)},${y(p.value)}`).join(" ")} stroke="currentColor" strokeWidth="3" fill="none" /> : null}
      {card.points.map((p, i) => mode === "bar"
        ? <rect key={i} x={x(i) - barWidth / 2} y={Math.min(y(0), y(p.value))} width={barWidth} height={Math.abs(y(p.value) - y(0))} rx="3" fill="currentColor"><title>{p.label}：{p.value}</title></rect>
        : <circle key={i} cx={x(i)} cy={y(p.value)} r="4" fill="currentColor"><title>{p.label}：{p.value}</title></circle>)}
      <text x="55" y="228" textAnchor="start">{card.points[0].label.slice(0, 10)}</text><text x="415" y="228" textAnchor="end">{card.points[card.points.length - 1].label.slice(0, 10)}</text>
    </svg>
    <details className="answer-data"><summary>查看完整数据</summary><table><thead><tr><th>项目</th><th>数值</th></tr></thead><tbody>{card.points.map((p, i) => <tr key={i}><td>{p.label}</td><td>{p.value.toLocaleString()}</td></tr>)}</tbody></table></details>
  </>;
}

function Picture({ card }: { card: Extract<AnswerCard, { type: "image" }> }) {
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);
  return <figure className={`answer-picture${expanded ? " is-expanded" : ""}`}>
    {failed ? <p><Image size={18} />图片暂时无法显示：{card.alt}</p> : <ConsentImage src={card.src} alt={card.alt} onFailure={() => setFailed(true)} />}
    {card.caption ? <figcaption>{card.caption}</figcaption> : null}
    <div className="answer-controls">{!failed ? <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>{expanded ? "收起图片" : "放大图片"}</button> : null}<a href={card.src} target="_blank" rel="noreferrer noopener">打开原图<ArrowUpRight size={14} /></a></div>
  </figure>;
}

function Places({ card }: { card: Extract<AnswerCard, { type: "map" }> }) {
  const [selected, setSelected] = useState(0);
  const [open, setOpen] = useState(false);
  const point = card.points[selected];
  const lon = point.lon;
  const lat = point.lat;
  const query = new URLSearchParams({ bbox: `${Math.max(-180, lon - .08)},${Math.max(-85, lat - .05)},${Math.min(180, lon + .08)},${Math.min(85, lat + .05)}`, layer: "mapnik", marker: `${lat},${lon}` });
  const link = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=12/${lat}/${lon}`;
  return <>
    <div className="answer-places">{card.points.map((p, i) => <button type="button" key={i} aria-pressed={selected === i} onClick={() => setSelected(i)}><MapPin size={14} />{p.label}</button>)}</div>
    <p className="answer-coordinate">{point.label} · {lat.toFixed(4)}°, {lon.toFixed(4)}°</p>
    {open ? <iframe src={`https://www.openstreetmap.org/export/embed.html?${query}`} title={`${point.label} 地图`} loading="lazy" referrerPolicy="no-referrer" sandbox="allow-scripts allow-same-origin" /> : null}
    <div className="answer-controls"><button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "收起地图" : "显示地图"}</button><a href={link} target="_blank" rel="noreferrer noopener">在 OpenStreetMap 中打开<ArrowUpRight size={14} /></a></div>
    <small>地图由 OpenStreetMap 提供，加载需要联网。</small>
  </>;
}

export function AnswerCardView({ card, onDraft }: { card: AnswerCard; onDraft?: (prompt: string) => void }) {
  return <section className={`answer-card answer-card-${card.type}`} aria-label={card.title}>
    <h3>{card.title}</h3>
    {card.type === "memory_lab" ? <MemoryLab card={card} /> : card.type === "performance_lab" ? <PerformanceLab card={card} /> : card.type === "evidence_lab" ? <EvidenceLab card={card} />
      : card.type === "plot" ? <Plot card={card} /> : card.type === "chart" ? <Chart card={card} /> : card.type === "image" ? <Picture card={card} /> : card.type === "map" ? <Places card={card} />
      : <><div className="answer-followups">{card.items.map((item, i) => <button type="button" key={i} disabled={!onDraft} onClick={() => onDraft?.(item.prompt)}>{item.label}<ArrowUpRight size={14} /></button>)}</div><small>选择后放入输入框，由你决定发送。</small></>}
  </section>;
}
