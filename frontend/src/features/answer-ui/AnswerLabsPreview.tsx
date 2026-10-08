import { useState } from "react";
import { createRoot } from "react-dom/client";
import { AnswerCardView } from "./AnswerCardView";
import type { AnswerCard } from "./answerUiProtocol";
import "./answerLabsPreview.css";

// Dev-only, deterministic visual acceptance page. The ordinary app still renders these inside replies.
const examples: AnswerCard[] = [
  { type: "memory_lab", title: "Java 内存实验室", initialName: "甲", updatedName: "乙" },
  { type: "evidence_lab", title: "证据与结论工作台", mode: "simulation", sources: [
    { kind: "measurement", label: "来源 A：编码任务的计时结果", aSeconds: 1.4, bSeconds: 2 },
    { kind: "measurement", label: "来源 B：检索任务的计时结果", aSeconds: 2.6, bSeconds: 2.1 },
    { kind: "opinion", label: "来源 C：没有测试数据的主观评论", text: "我感觉 A 的响应更加迅速。没有任务定义、计时方式或可复核数据。" },
  ] },
  { type: "performance_lab", title: "研究任务性能实验台", pages: 8, concurrency: 3, readSeconds: 4, summarySeconds: 6 },
];
function Preview() {
  const [selected, setSelected] = useState(0);
  return <main className="answer-labs-preview"><header><span>操作 · 观察 · 验证</span><h1>把回答变成一个小实验</h1><p>使用演示数据，操作只影响当前实验，不写入会话或研究结果。</p></header>
    <nav aria-label="选择学习实验">{["Java 引用", "证据审查", "并发性能"].map((label, i) => <button type="button" key={i} aria-pressed={selected === i} onClick={() => setSelected(i)}>{label}</button>)}</nav>
    {examples.map((card, i) => <div hidden={selected !== i} key={card.type}><AnswerCardView card={card} /></div>)}
  </main>;
}
if (import.meta.env.DEV) createRoot(document.getElementById("answer-labs")!).render(<Preview />);
