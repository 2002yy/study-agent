import { BookOpen, ChevronLeft, ChevronRight, List, MessageSquare, X } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useReadingWorkspace } from "./ReadingContext";

const PdfReader=lazy(()=>import("./PdfReader"));

export function DocumentReader() {
  const reader = useReadingWorkspace()!;
  const {document, target} = reader;
  const bodyRef = useRef<HTMLDivElement>(null);
  const [fontSize, setFontSize] = useState(18);
  const [outlineOpen, setOutlineOpen] = useState(false);
  const [jumpLine, setJumpLine] = useState("1");
  const [selection, setSelection] = useState<{text:string;start:number;end:number} | null>(null);
  const [pdfMode,setPdfMode]=useState(true);
  useEffect(()=>{setPdfMode(true);setSelection(null)},[target?.scope,target?.documentId,target?.attachmentId,target?.runId,target?.url]);
  useEffect(()=>{if(document && target?.startLine && !document.pdf_page_map?.length)setPdfMode(false)},[document,target]);
  useEffect(() => {
    setSelection(null);
    setJumpLine(String(document?.start_line ?? 1));
    if (!document) return;
    const line = target?.startLine ?? document.start_line;
    const element = bodyRef.current?.querySelector<HTMLElement>(`[data-line="${line}"]`);
    if (element && target?.startLine) {
      element.scrollIntoView({block:"center"});element.focus({preventScroll:true});
    } else if(bodyRef.current) bodyRef.current.scrollTop = 0;
  }, [document,target,pdfMode]);
  // The outline describes only this loaded window, never an invented full TOC.
  const headings: {line:number;level:number;text:string}[] = [];
  let fence: string | null = null;
  document?.text.split("\n").forEach((text,index) => {
    const marker = /^\s{0,3}(`{3,}|~{3,})/.exec(text);
    if (marker) {
      if (!fence) fence = marker[1];
      else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
      return;
    }
    const heading = !fence && /^(#{1,6})\s+(.+)$/.exec(text);
    if (heading) headings.push({line:document!.start_line+index,level:heading[1].length,text:heading[2]});
  });
  function locateLine(line: number) {
    const element = bodyRef.current?.querySelector<HTMLElement>(`[data-line="${line}"]`);
    element?.scrollIntoView({block:"start",behavior:"instant"});
    element?.focus({preventScroll:true});
  }
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
  const nativePdf=Boolean(pdfMode && document?.file_type === "pdf" && target);
  const locatedPage=document?.pdf_page_map?.reduce((page,item)=>item.line<=(target?.startLine ?? document.start_line)?item.page:page,1) ?? 1;
  return <section className="document-reader" aria-label="资料正文">
    <header className="document-reader-toolbar">
      <div className="document-reader-title"><BookOpen size={18} aria-hidden="true"/><div><strong>{document?.title || "资料阅读"}</strong><small>{document ? document.scope === "web" ? "网页 · 已保存阅读正文" : `${document.file_type.toUpperCase()} · ${nativePdf ? "原始页面" : document.file_type === "pdf" || document.file_type === "docx" ? "解析文字版" : "正文文字版"}` : "只读正文"}</small></div></div>
      <div className="document-reader-actions">
        <button type="button" aria-label="减小阅读字号" disabled={fontSize<=16} onClick={()=>setFontSize(size=>size-1)}>A−</button>
        <button type="button" aria-label="增大阅读字号" disabled={fontSize>=22} onClick={()=>setFontSize(size=>size+1)}>A＋</button>
        <button type="button" className="reading-focus-button" aria-pressed={reader.focused} onClick={reader.toggleFocus}>{reader.focused ? "恢复并排" : "专注"}</button>
        <button type="button" aria-label="关闭资料阅读" onClick={reader.close}><X size={16}/></button>
      </div>
    </header>
    <div className="document-reader-navigation">
      {document?.file_type === "pdf" ? <div className="reading-view-tabs"><button type="button" aria-pressed={pdfMode} onClick={()=>{setPdfMode(true);setSelection(null)}}>PDF 原页</button><button type="button" aria-pressed={!pdfMode} onClick={()=>setPdfMode(false)}>解析文字</button></div> : <button type="button" aria-expanded={outlineOpen} aria-controls="reading-window-outline" disabled={!document} onClick={()=>setOutlineOpen(value=>!value)}><List size={16} aria-hidden="true"/>本段目录</button>}
      <button type="button" onClick={reader.browse}>切换资料<ChevronRight size={14} aria-hidden="true"/></button>
    </div>
    {outlineOpen && document ? <nav className="document-outline" id="reading-window-outline" aria-label="当前正文窗口目录">
      <p>当前已载入正文的标题 · L{document.start_line}–L{document.end_line}</p>
      {headings.length ? <ol>{headings.map(heading => <li key={heading.line} className={heading.level>1 ? "outline-subheading" : ""}><button type="button" onClick={()=>locateLine(heading.line)}>{heading.text}<small>L{heading.line}</small></button></li>)}</ol> : <p>这一段没有章节标题，可按行号定位。</p>}
    </nav> : null}
    {nativePdf && document && target ? <Suspense fallback={<div className="reading-empty" role="status">正在载入阅读器…</div>}><PdfReader target={target} revision={document.revision_id} initialPage={locatedPage} onText={()=>setPdfMode(false)}/></Suspense> : null}
    <div className="document-reader-body" hidden={nativePdf} ref={bodyRef} onMouseUp={captureSelection} onKeyUp={captureSelection} onTouchEnd={captureSelection} tabIndex={0} aria-label="可滚动资料正文">
      {reader.loading ? <div className="reading-empty" role="status">正在读取资料正文…</div> : null}
      {reader.error ? <div className="reading-empty" role="alert"><strong>{reader.error}</strong><p>资料被删除或版本变化时，请关闭阅读并重新选择资料。</p><button type="button" onClick={reader.retry}>重试</button>{reader.error.includes("正文过长") ? <button type="button" disabled={target?.windowLines===1} onClick={reader.shrinkWindow}>缩小阅读窗口</button> : null}</div> : null}
      {document ? <article className="document-paper" style={{fontSize}}>
        <div className="document-reading-label"><span>{target?.scope === "session" ? "本会话附件" : target?.scope === "web" ? "网页阅读记录" : "长期资料"}</span><span>{filename}</span></div>
        {document.scope === "web" ? <p className="reading-source-note">{document.content_truncated ? "阅读时保存的部分正文，内容有截断。" : "阅读时保存的正文快照。"} <a href={document.source_path} target="_blank" rel="noreferrer">打开原网站</a></p> : null}
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
    <div hidden={nativePdf} className={`document-reader-selection${selection ? " has-selection" : ""}`}>
      <div><strong>{selection ? selection.text.length>4000 ? "选段过长，请缩小到4000字符以内" : `已选 L${selection.start}–L${selection.end}` : "带着原文，一起讨论"}</strong><span>{selection ? "选段将加入草稿，写好问题后再发送" : "选中正文，将这一段带入对话草稿"}</span></div>
      {selection ? <button type="button" className="reading-clear-selection" aria-label="取消正文选段" onClick={()=>{window.getSelection()?.removeAllRanges();setSelection(null)}}><X size={16}/></button> : null}
      <button type="button" disabled={!selection || selection.text.length>4000 || !reader.canAsk || reader.loading} onClick={()=>{if(selection)reader.ask(selection.text,selection.start,selection.end)}}><MessageSquare size={15} aria-hidden="true"/>解释选中文字</button>
    </div>
    <footer hidden={nativePdf} className="document-reader-footer">
      <span>{document ? `L${document.start_line}–L${document.end_line} / ${document.total_lines} 行` : "解析正文 · 非 PDF 页码"}</span>
      {document ? <form className="reading-line-jump" onSubmit={event=>{
        event.preventDefault();const line=Number(jumpLine);
        if(!Number.isInteger(line) || line<1 || line>document.total_lines)return;
        if(line>=document.start_line && line<=document.end_line)locateLine(line);
        else reader.goToLine(line);
      }}><input type="number" aria-label="跳转到正文行号" min={1} max={document.total_lines} step={1} required value={jumpLine} onChange={event=>setJumpLine(event.target.value)}/><button type="submit">跳转</button></form> : null}
      <div><button type="button" aria-label="上一段正文" disabled={!document || document.start_line===1} onClick={()=>reader.goToLine(Math.max(1,(document?.start_line ?? 1)-(target?.windowLines ?? 100)))}><ChevronLeft size={15}/></button><button type="button" aria-label="下一段正文" disabled={!document || document.end_line===document.total_lines} onClick={()=>reader.goToLine((document?.end_line ?? 0)+1)}><ChevronRight size={15}/></button></div>
    </footer>
  </section>;
}
