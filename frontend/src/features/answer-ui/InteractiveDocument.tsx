import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ArrowUpRight, History, Maximize2, Minimize2, RotateCcw, Square, Play } from "lucide-react";
import { interactiveFollowup, makeInteractiveDocument, stateText, type InteractiveCard } from "./interactiveRuntime";
import { loadInteractiveState, saveInteractiveState } from "../../api";
import "./interactiveDocument.css";

export function InteractiveDocument({ card, onDraft, onRestoreBase, sessionId }: { card: InteractiveCard; onDraft?: (prompt: string) => void; onRestoreBase?: (target: { id: string; revision: number; title: string }) => void; sessionId?: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const instance = useId();
  const [generation, setGeneration] = useState(0);
  const [running, setRunning] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [height, setHeight] = useState(360);
  const [status, setStatus] = useState("正在准备交互…");
  const [error, setError] = useState("");
  const [state, setState] = useState<string | null>(null);
  const [savedState, setSavedState] = useState<{ state: Record<string, unknown>; revision: number } | null>(null);
  const [restoreNote, setRestoreNote] = useState("");
  const initialRef = useRef<string | null>(null);
  const saveTimer = useRef<number | null>(null);
  const channel = `${instance}:${generation}`;
  const document = useMemo(() => makeInteractiveDocument(card.html, channel), [card.html, channel]);
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    loadInteractiveState(sessionId, card.id)
      .then(snapshot => { if (!cancelled) setSavedState({ state: snapshot.state, revision: snapshot.revision }); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId, card.id]);
  useEffect(() => () => { if (saveTimer.current !== null) window.clearTimeout(saveTimer.current); }, []);
  useEffect(() => {
    if (!running) return;
    const receive = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow || event.origin !== "null") return;
      const data: unknown = event.data;
      if (!data || typeof data !== "object" || !("channel" in data) || data.channel !== channel || !("type" in data) || !("value" in data)) return;
      if (data.type === "state") {
        const text = stateText(data.value);
        if (text) {
          setState(text);
          // The first publish is the document's own initial state; saving it
          // would overwrite a real snapshot just by re-rendering an old answer.
          if (initialRef.current === null) initialRef.current = text;
          else if (sessionId && text !== initialRef.current) {
            if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
            const snapshot = JSON.parse(text) as Record<string, unknown>;
            saveTimer.current = window.setTimeout(() => {
              saveInteractiveState(sessionId, card.id, card.revision, snapshot).catch(() => {});
            }, 800);
          }
        }
      }
      if (data.type === "height" && typeof data.value === "number" && Number.isFinite(data.value)) setHeight(Math.min(720, Math.max(180, data.value + 2)));
      if (data.type === "ready") setStatus("可交互");
      if (data.type === "restore_unavailable") setRestoreNote("这个版本没有实现状态恢复，只能从初始状态重新操作。");
      if (data.type === "error" && typeof data.value === "string") { setError(data.value.slice(0, 500)); setStatus("部分交互未能运行"); }
    };
    window.addEventListener("message", receive);
    const timer = window.setTimeout(() => setStatus(current => current === "正在准备交互…" ? "界面未就绪，可重新运行或请模型修复" : current), 8000);
    return () => { window.removeEventListener("message", receive); window.clearTimeout(timer); };
  }, [channel, running, sessionId, card.id, card.revision]);
  const restart = () => { setState(null); setError(""); setStatus("正在准备交互…"); setRunning(true); setGeneration(n => n + 1); };
  const restoreSavedState = () => {
    if (!savedState) return;
    frame.current?.contentWindow?.postMessage({ channel, type: "restore", value: savedState.state }, "*");
    setRestoreNote("");
  };
  return <div className={`interactive-document${expanded ? " is-expanded" : ""}`}>
    <p className="interactive-summary">{card.summary}</p>
    <div className="interactive-toolbar">
      <span className="interactive-version">版本 {card.revision} <span role="status">{error ? "部分交互未能运行" : running ? status : "已停止"}</span></span>
      <div className="interactive-tools">
        <button type="button" onClick={restart} title="恢复初始状态"><RotateCcw size={15} /><span>重置</span></button>
        <button type="button" onClick={() => { if (running) setRunning(false); else restart(); }}><span aria-hidden="true">{running ? <Square size={14} /> : <Play size={14} />}</span><span>{running ? "停止" : "运行"}</span></button>
        <button type="button" aria-pressed={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}<span>{expanded ? "收起" : "展开"}</span></button>
      </div>
    </div>
    {running ? <iframe key={channel} ref={frame} title={`${card.title}，版本 ${card.revision}，交互画布`} sandbox="allow-scripts" referrerPolicy="no-referrer" allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'" srcDoc={document} style={{ height: expanded ? "min(78vh, 1000px)" : height }} />
      : <p className="interactive-stopped">交互已停止。文字说明和当前状态仍然保留。</p>}
    {error ? <p className="interactive-error" role="alert">{error}</p> : null}
    <div className="interactive-footer">
      <button type="button" className="interactive-continue" disabled={!onDraft} onClick={() => onDraft?.(interactiveFollowup(card, state, error))}>{error ? "请模型修复" : "带着当前状态继续问"}<ArrowUpRight size={16} /></button>
      <button type="button" className="interactive-restore" disabled={!onRestoreBase} onClick={() => onRestoreBase?.({ id: card.id, revision: card.revision, title: card.title })} title="从这一版的源码重新开始，而不是最近一版">以此版本为基础继续</button>
      {savedState && savedState.revision === card.revision ? (
        <button type="button" className="interactive-restore" onClick={restoreSavedState}><History size={14} /><span>恢复上次状态</span></button>
      ) : null}
      {savedState && savedState.revision !== card.revision ? (
        <span className="interactive-restore-note" role="status">上次状态属于版本 {savedState.revision}，不能直接恢复到版本 {card.revision}。</span>
      ) : null}
      {restoreNote ? <span className="interactive-restore-note" role="status">{restoreNote}</span> : null}
      <span>生成式交互 · 结果需结合原理核对</span>
    </div>
    <details className="interactive-source"><summary>查看内容与当前状态</summary><p>当前参数可随追问发送；刷新后从初始状态开始。</p><pre>{state ? JSON.stringify(JSON.parse(state), null, 2) : "尚未提供状态"}</pre><details><summary>界面源码</summary><pre>{card.html}</pre></details></details>
  </div>;
}
