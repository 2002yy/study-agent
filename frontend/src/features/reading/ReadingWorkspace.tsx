import { BookOpen, MessageSquare } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import type { KnowledgeDocument } from "../../types";
import { ReadingContext, citationTarget, useReadingWorkspace } from "./ReadingContext";
import { readDocument, type DocumentReading, type ReadingTarget } from "./readingApi";
import { DocumentReader } from "./DocumentReader";
import "./readingWorkspace.css";
import "./workspaceInterior.css";
import "./chatAppearance.css";
import "./workspacePolish.css";
import { PanelResizeHandle } from "./PanelResizeHandle";

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
    if (target.scope !== "knowledge" && target.threadId !== sessionId) return;
    setRequest({target,line:Math.max(1,(target.startLine ?? 1)-3),sessionKey,navigationKey});
    setMode("read");setFocused(false);onOpen();
  }, [sessionId,sessionKey,onOpen,navigationKey]);
  const close = () => {setRequest(null);setResult(null);setFocused(false)};
  return <ReadingContext.Provider value={{
    documents, sessionId,
    webCitation:(url,evidence) => {
      const runId=evidence.rag?.web_tools?.run_id || evidence.rag?.web_context?.run_id;
      return sessionId && runId && /^https?:\/\//i.test(url)
        ? {scope:"web",threadId:sessionId,runId,url,sourcePath:url} : null;
    },
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
      {!reader?.focused ? <PanelResizeHandle panel="reading" /> : null}
    </> : null}
    {children}
  </div>;
}
