import { BookOpen, ChevronLeft, ChevronRight, MessageSquare, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { KnowledgeDocument } from "../../types";
import { ReadingContext, citationTarget, useReadingWorkspace } from "./ReadingContext";
import { readDocument, type DocumentReading, type ReadingTarget } from "./readingApi";
import "./readingWorkspace.css";

type Request = {target: ReadingTarget; line: number; sessionKey: string; navigationKey: number};

export function ReadingWorkspaceProvider({
  children, sessionId, documents, isSending, onAsk, onOpen, onBrowse, navigationKey=0,
}: {
  children: ReactNode;
  sessionId?: string;
  documents: KnowledgeDocument[];
  isSending: boolean;
  onAsk: (prompt: string) => void;
  onOpen: () => void;
  onBrowse: () => void;
  navigationKey?: number;
}) {
  const [request, setRequest] = useState<Request | null>(null);
  const [result, setResult] = useState<{request: Request; data?: DocumentReading; error?: string} | null>(null);
  const [mode, setMode] = useState<"read" | "chat">("read");
  const [focused, setFocused] = useState(false);
  const sessionKey = sessionId ?? "";
  // A global document opened before the first chat survives that chat's ID
  // allocation. Explicit navigation still clears it via the owner token.
  const active = request && request.navigationKey === navigationKey && (
    request.sessionKey === sessionKey || (request.sessionKey === "" && request.target.scope === "knowledge")
  ) ? request : null;
  const document = active && result?.request === active ? result.data ?? null : null;
  const error = active && result?.request === active ? result.error ?? "" : "";
  useEffect(() => {
    if (!active) {setResult(null);setFocused(false);setMode("read")}
    if (!active) return;
    const controller = new AbortController();
    readDocument(active.target, active.line, controller.signal).then(
      data => {if (!controller.signal.aborted) setResult({request:active,data})},
      cause => {if (!controller.signal.aborted) setResult({request:active,error:cause instanceof Error ? cause.message : "资料读取失败"})},
    );
    return () => controller.abort();
  }, [active]);
  useEffect(() => {
    setRequest(current => current && current.navigationKey === navigationKey && (
      current.sessionKey === sessionKey || (current.sessionKey === "" && current.target.scope === "knowledge")
    ) ? current : null);
  }, [sessionKey,navigationKey]);
  const open = useCallback((target: ReadingTarget) => {
    if (target.scope === "session" && target.threadId !== sessionId) return;
    setRequest({target,line:Math.max(1,(target.startLine ?? 1)-3),sessionKey,navigationKey});
    setMode("read");setFocused(false);onOpen();
  }, [sessionId,sessionKey,onOpen,navigationKey]);
  const close = () => {setRequest(null);setResult(null);setFocused(false)};
  return <ReadingContext.Provider value={{
    target:active?.target ?? null, document, error,
    loading:Boolean(active && result?.request !== active), mode, focused,
    canAsk:!isSending,
    open, close, browse:onBrowse,
    showChat:() => {setMode("chat");setFocused(false)},
    showReader:() => setMode("read"),
    toggleFocus:() => {setFocused(value=>!value);setMode("read")},
    retry:() => {if(active)setRequest({...active})},
    shrinkWindow:() => {
      if(active) setRequest({...active,target:{...active.target,
        windowLines:Math.max(1,Math.floor((active.target.windowLines ?? 100)/5))}});
    },
    goToLine:line => {
      if (active && document) setRequest({...active,line,target:{...active.target,
        revision:document.revision_id,startLine:undefined,endLine:undefined}});
    },
    ask:(quote,startLine,endLine) => {
      if (!document || isSending || !quote.trim() || quote.length>4000
        || !Number.isInteger(startLine) || !Number.isInteger(endLine)
        || startLine<document.start_line || endLine>document.end_line || endLine<startLine) return;
      onAsk(`请解释下面这段资料：\n资料：${document.title}（版本 ${document.revision_id}，L${startLine}–L${endLine}）\n引用：\n${quote}\n\n我的问题：`);
      setMode("chat");setFocused(false);
    },
    citation:(id,source,results) => citationTarget(id,source,results,documents,sessionId),
  }}>{children}</ReadingContext.Provider>;
}

export function ReadingLayout({children}: {children: ReactNode}) {
  const reader = useReadingWorkspace();
  const active = Boolean(reader?.target);
  return <div className={`reading-layout${active ? " has-document" : ""}${active && reader?.focused ? " reading-focused" : ""}${active && reader?.mode === "chat" ? " reading-chat-active" : ""}`}>
    {active ? <>
      <nav className="reading-mobile-tabs" aria-label="阅读工作区">
        <button type="button" aria-pressed={reader?.mode === "read"} onClick={reader?.showReader}><BookOpen size={15}/>资料</button>
        <button type="button" aria-pressed={reader?.mode === "chat"} onClick={reader?.showChat}><MessageSquare size={15}/>对话</button>
      </nav>
      <DocumentReader/>
    </> : null}
    {!active && reader ? <div className="reading-entry"><button type="button" onClick={reader.browse}><BookOpen size={16}/>阅读资料</button><span>选择正文，与对话并排阅读</span></div> : null}
    {children}
  </div>;
}

function DocumentReader() {
  const reader = useReadingWorkspace()!;
  const {document, target} = reader;
  const bodyRef = useRef<HTMLDivElement>(null);
  const [fontSize, setFontSize] = useState(18);
  const [selection, setSelection] = useState<{text:string;start:number;end:number} | null>(null);
  useEffect(() => {
    setSelection(null);
    if (!document) return;
    const line = target?.startLine ?? document.start_line;
    const element = bodyRef.current?.querySelector<HTMLElement>(`[data-line="${line}"]`);
    if (element && target?.startLine) {
      element.scrollIntoView({block:"center"});element.focus({preventScroll:true});
    } else if(bodyRef.current) bodyRef.current.scrollTop = 0;
  }, [document,target]);
  function captureSelection() {
    const selected = window.getSelection();
    if (!selected?.rangeCount || !bodyRef.current) {setSelection(null);return}
    const range = selected.getRangeAt(0);
    const lineOf = (node: Node) => (node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement)?.closest<HTMLElement>("[data-line]");
    const first = lineOf(range.startContainer), last = lineOf(range.endContainer);
    const text = selected.toString().trim();
    if (text && first && last && bodyRef.current.contains(first) && bodyRef.current.contains(last)) {
      setSelection({text,start:Number(first.dataset.line),end:Number(last.dataset.line)});
    } else setSelection(null);
  }
  const filename = document?.source_path.split(/[\\/]/).pop();
  return <section className="document-reader" aria-label="资料正文">
    <header className="document-reader-toolbar">
      <div><strong>{document?.title || "资料阅读"}</strong><small>{document ? `${document.file_type.toUpperCase()} · ${document.file_type === "pdf" || document.file_type === "docx" ? "解析文字版" : "正文文字版"}` : "只读正文"}</small></div>
      <div className="document-reader-actions">
        <button type="button" aria-label="减小阅读字号" disabled={fontSize<=16} onClick={()=>setFontSize(size=>size-1)}>A−</button>
        <button type="button" aria-label="增大阅读字号" disabled={fontSize>=22} onClick={()=>setFontSize(size=>size+1)}>A＋</button>
        <button type="button" className="reading-focus-button" aria-pressed={reader.focused} onClick={reader.toggleFocus}>{reader.focused ? "恢复并排" : "专注"}</button>
        <button type="button" aria-label="关闭资料阅读" onClick={reader.close}><X size={16}/></button>
      </div>
    </header>
    <div className="document-reader-body" ref={bodyRef} onMouseUp={captureSelection} onKeyUp={captureSelection} onTouchEnd={captureSelection} tabIndex={0} aria-label="可滚动资料正文">
      {reader.loading ? <div className="reading-empty" role="status">正在读取资料正文…</div> : null}
      {reader.error ? <div className="reading-empty" role="alert"><strong>{reader.error}</strong><p>资料被删除或版本变化时，请关闭阅读并重新选择资料。</p><button type="button" onClick={reader.retry}>重试</button>{reader.error.includes("正文过长") ? <button type="button" disabled={target?.windowLines===1} onClick={reader.shrinkWindow}>缩小阅读窗口</button> : null}</div> : null}
      {document ? <article className="document-paper" style={{fontSize}}>
        <div className="document-reading-label">{target?.scope === "session" ? "本会话附件" : "长期资料"} · {filename}</div>
        {document.evidence_status !== "active" ? <p className="reading-eligibility-note">{document.evidence_status === "excluded" ? "已排除" : "旧版本"}资料：可阅读，不自动恢复为回答证据。</p> : null}
        {document.text.split("\n").map((text,index) => {
          const line = document.start_line+index;
          const heading = /^(#{1,6})\s+(.+)$/.exec(text);
          const highlighted = Boolean(target?.startLine && line>=target.startLine && line<=(target.endLine ?? target.startLine));
          return <div className={`document-text-line${highlighted ? " citation-located" : ""}${heading ? ` document-heading heading-${heading[1].length}` : ""}${!text ? " blank-line" : ""}`} key={line} data-line={line} tabIndex={-1}>
            <span className="document-line-number" aria-hidden="true">{line}</span>
            <span>{heading ? heading[2] : text || "\u00a0"}</span>
          </div>;
        })}
      </article> : null}
    </div>
    <div className="document-reader-selection">
      <span>{selection ? selection.text.length>4000 ? "选段过长，请缩小到4000字符以内" : `已选 L${selection.start}–L${selection.end}` : "选中正文后，可带着原文提问"}</span>
      <button type="button" disabled={!selection || selection.text.length>4000 || !reader.canAsk || reader.loading} onClick={()=>{if(selection)reader.ask(selection.text,selection.start,selection.end)}}>解释选中文字</button>
    </div>
    <footer className="document-reader-footer">
      <span>{document ? `L${document.start_line}–L${document.end_line} / ${document.total_lines} 行` : "解析正文 · 非 PDF 页码"}</span>
      <div><button type="button" aria-label="上一段正文" disabled={!document || document.start_line===1} onClick={()=>reader.goToLine(Math.max(1,(document?.start_line ?? 1)-(target?.windowLines ?? 100)))}><ChevronLeft size={15}/></button><button type="button" aria-label="下一段正文" disabled={!document || document.end_line===document.total_lines} onClick={()=>reader.goToLine((document?.end_line ?? 0)+1)}><ChevronRight size={15}/></button></div>
    </footer>
  </section>;
}
