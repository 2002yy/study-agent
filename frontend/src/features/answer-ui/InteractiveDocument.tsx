import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ArrowUpRight, History, Maximize2, Minimize2, RotateCcw, Square, Play } from "lucide-react";
import { interactiveFollowup, makeInteractiveDocument, stateText, type InteractiveCard } from "./interactiveRuntime";
import { parseLayoutDiagnostics } from "./layoutDiagnostics";
import { formatRepairFeedback, type RepairIssue } from "./repairFeedback";
import { loadInteractiveState, saveInteractiveState } from "../../api";
import { loadThreeSource } from "./threeSource";
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
  const [diagnostics, setDiagnostics] = useState<RepairIssue[] | null>(null);
  const [diagnosticStatus, setDiagnosticStatus] = useState("");
  const diagnosticTimer = useRef<number | null>(null);
  const [state, setState] = useState<string | null>(null);
  const [savedState, setSavedState] = useState<{ state: Record<string, unknown>; revision: number } | null>(null);
  const [restoreNote, setRestoreNote] = useState("");
  const seenInitialRef = useRef(false);
  const generationRef = useRef(0);
  const saveTimerRef = useRef<number | null>(null);
  const saveInFlightRef = useRef(false);
  const queuedSaveRef = useRef<{ snapshot: Record<string, unknown>; generation: number } | null>(null);
  const restorePendingRef = useRef(false);
  const restoreTimerRef = useRef<number | null>(null);
  const channel = `${instance}:${generation}`;
  const needsThree = card.capabilities?.includes("three") === true;
  const [threeSource, setThreeSource] = useState<string | null>(null);
  useEffect(() => {
    if (!needsThree) { setThreeSource(null); return; }
    let cancelled = false;
    loadThreeSource().then(source => { if (!cancelled) setThreeSource(source); })
      .catch(() => { if (!cancelled) { setError("本地 Three.js 能力加载失败，请重新运行。"); setStatus("交互未能运行"); } });
    return () => { cancelled = true; };
  }, [needsThree, generation]);
  const document = useMemo(() => needsThree && !threeSource ? null : makeInteractiveDocument(card.html, channel, needsThree ? ["three"] : undefined, threeSource ?? undefined), [card.html, channel, needsThree, threeSource]);
  const cancelPendingSave = () => {
    if (saveTimerRef.current !== null) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = null;
  };
  const writeSnapshot = (snapshot: Record<string, unknown>, generation: number) => {
    if (!sessionId || generationRef.current !== generation) return;
    saveInFlightRef.current = true;
    saveInteractiveState(sessionId!, card.id, card.revision, snapshot)
      .then(result => setSavedState({ state: result.state, revision: result.revision }))
      .catch(() => {})
      .finally(() => {
        saveInFlightRef.current = false;
        const queued = queuedSaveRef.current;
        queuedSaveRef.current = null;
        // One write at a time, latest wins: an older request finishing late can
        // never land after a newer value has already been captured.
        if (queued) writeSnapshot(queued.snapshot, queued.generation);
      });
  };
  const cancelRestoreWait = () => {
    if (restoreTimerRef.current !== null) window.clearTimeout(restoreTimerRef.current);
    restoreTimerRef.current = null;
    restorePendingRef.current = false;
  };
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    loadInteractiveState(sessionId, card.id, card.revision)
      .then(snapshot => { if (!cancelled) setSavedState({ state: snapshot.state, revision: snapshot.revision }); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId, card.id, card.revision]);
  useEffect(() => () => { cancelPendingSave(); cancelRestoreWait(); if (diagnosticTimer.current !== null) window.clearTimeout(diagnosticTimer.current); }, []);
  useEffect(() => {
    if (!running || !document) return;
    const receive = (event: MessageEvent) => {
      if (!frame.current || event.source !== frame.current.contentWindow || event.origin !== "null") return;
      const data: unknown = event.data;
      if (!data || typeof data !== "object" || !("channel" in data) || data.channel !== channel || !("type" in data) || !("value" in data)) return;
      if (data.type === "state") {
        const text = stateText(data.value);
        if (text) {
          setState(text);
          if (restorePendingRef.current) {
            restorePendingRef.current = false;
            if (restoreTimerRef.current !== null) window.clearTimeout(restoreTimerRef.current);
            restoreTimerRef.current = null;
            setRestoreNote("已恢复上次状态。");
          }
          if (!seenInitialRef.current) {
            // Only the first publish after mount/restart is the document's own
            // initial state. Later publishes are user actions even when the
            // value happens to equal the initial one again.
            seenInitialRef.current = true;
            return;
          }
          if (sessionId) {
            const scheduledFor = generationRef.current;
            const snapshot = JSON.parse(text) as Record<string, unknown>;
            cancelPendingSave();
            saveTimerRef.current = window.setTimeout(() => {
              saveTimerRef.current = null;
              if (generationRef.current !== scheduledFor) return;
              if (saveInFlightRef.current) {
                queuedSaveRef.current = { snapshot, generation: scheduledFor };
                return;
              }
              writeSnapshot(snapshot, scheduledFor);
            }, 800);
          }
          if (restorePendingRef.current) {
            restorePendingRef.current = false;
            if (restoreTimerRef.current !== null) window.clearTimeout(restoreTimerRef.current);
            restoreTimerRef.current = null;
            setRestoreNote("已恢复上次状态。");
          }
        }
      }
      if (data.type === "height" && typeof data.value === "number" && Number.isFinite(data.value)) setHeight(Math.min(720, Math.max(180, data.value + 2)));
      if (data.type === "ready") setStatus("可交互");
      if (data.type === "restore_unavailable") {
        cancelRestoreWait();
        setRestoreNote("这个版本没有实现状态恢复，只能从初始状态重新操作。");
      }
      if (data.type === "error" && typeof data.value === "string") { setError(data.value.slice(0, 500)); setStatus("部分交互未能运行"); }
      if (data.type === "diagnostics") {
        if (diagnosticTimer.current !== null) window.clearTimeout(diagnosticTimer.current);
        const measured = parseLayoutDiagnostics(data.value);
        setDiagnostics(measured);
        setDiagnosticStatus(measured ? "已检查" : "读取排版数据失败，请重新检查。");
      }
    };
    window.addEventListener("message", receive);
    const timer = window.setTimeout(() => setStatus(current => current === "正在准备交互…" ? "界面未就绪，可重新运行或请模型修复" : current), 8000);
    return () => { window.removeEventListener("message", receive); window.clearTimeout(timer); };
  }, [channel, running, sessionId, card.id, card.revision, document]);
  const restart = () => {
    // A rebuilt document is a new generation: drop pending writes for the old
    // one and let its first publish count as initial state again.
    cancelPendingSave();
    cancelRestoreWait();
    queuedSaveRef.current = null;
    seenInitialRef.current = false;
    generationRef.current += 1;
    setRestoreNote("");
    setState(null);
    setError("");
    if (diagnosticTimer.current !== null) window.clearTimeout(diagnosticTimer.current);
    setDiagnostics(null); setDiagnosticStatus("");
    setStatus("正在准备交互…");
    setRunning(true);
    setGeneration(n => n + 1);
  };
  const restoreSavedState = () => {
    if (!savedState) return;
    cancelRestoreWait();
    restorePendingRef.current = true;
    restoreTimerRef.current = window.setTimeout(() => {
      restoreTimerRef.current = null;
      if (!restorePendingRef.current) return;
      restorePendingRef.current = false;
      setRestoreNote("已发送恢复请求，但界面没有回报状态。");
    }, 1500);
    setRestoreNote("");
    frame.current?.contentWindow?.postMessage({ channel, type: "restore", value: savedState.state }, "*");
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
    {running ? document ? <iframe key={channel} ref={frame} title={`${card.title}，版本 ${card.revision}，交互画布`} sandbox="allow-scripts" referrerPolicy="no-referrer" allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'" srcDoc={document} style={{ height: expanded ? "min(78vh, 1000px)" : height }} /> : <p role="status">{error ? "本地 3D 能力未就绪。" : "正在加载本地 3D 能力…"}</p>
      : <p className="interactive-stopped">交互已停止。文字说明和当前状态仍然保留。</p>}
    {error ? <p className="interactive-error" role="alert">{error}</p> : null}
    <section aria-label="界面排版检查">
      <button type="button" disabled={!running || !document} onClick={() => {
        setDiagnostics(null); setDiagnosticStatus("正在检查…");
        if (diagnosticTimer.current !== null) window.clearTimeout(diagnosticTimer.current);
        diagnosticTimer.current = window.setTimeout(() => {
          setDiagnostics(null); setDiagnosticStatus("未收到排版测量结果，请重新检查。");
        }, 3000);
        frame.current?.contentWindow?.postMessage({ channel, type: "diagnose" }, "*");
      }}>检查排版</button>
      {diagnosticStatus ? <p role="status">{diagnosticStatus}</p> : null}
      {diagnostics ? diagnostics.length ? <>
        <p>发现 {diagnostics.length} 项排版问题：</p>
        <ul>{diagnostics.map((issue, index) => <li key={index}>{issue.elementId} · {issue.checkId}：实测 {issue.measured?.toFixed(1)} {issue.unit}，阈值 {issue.threshold} {issue.unit}</li>)}</ul>
        <button type="button" disabled={!onDraft || card.revision >= 999} onClick={() => onDraft?.(formatRepairFeedback(card, diagnostics) + "\n测量时的参数与观察：" + (state ?? "尚未提供，请保留原始参数。"))}>生成修复草稿</button>
      </> : <p>已覆盖的排版项目未发现问题；这不代表内容或交互逻辑正确。</p> : null}
    </section>
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
