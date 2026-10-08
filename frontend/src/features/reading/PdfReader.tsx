import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { readOriginalPdf, type ReadingTarget } from "./readingApi";

export default function PdfReader({target,revision,initialPage,onText}: {
  target:ReadingTarget;revision:string;initialPage:number;onText:()=>void;
}) {
  const [pdf,setPdf]=useState<PDFDocumentProxy | null>(null);
  const [page,setPage]=useState(initialPage);
  const [zoom,setZoom]=useState(1);
  const [width,setWidth]=useState(600);
  const [error,setError]=useState("");
  const [rendering,setRendering]=useState(true);
  const canvasRef=useRef<HTMLCanvasElement>(null);
  const frameRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const controller=new AbortController();
    let task:ReturnType<typeof import("pdfjs-dist").getDocument> | undefined;
    setPdf(null);setError("");setPage(initialPage);setRendering(true);
    void (async()=>{
      try {
        const [data,library]=await Promise.all([readOriginalPdf(target,revision,controller.signal),import("pdfjs-dist")]);
        if(controller.signal.aborted)return;
        library.GlobalWorkerOptions.workerSrc=workerUrl;
        task=library.getDocument({data,enableXfa:false});
        const document=await task.promise;
        if(!controller.signal.aborted) {setPdf(document);setPage(Math.min(initialPage,document.numPages))}
      } catch(cause) {if(!controller.signal.aborted)setError(cause instanceof Error?cause.message:"PDF 原件读取失败")}
    })();
    return ()=>{controller.abort();void task?.destroy()};
  },[target,revision,initialPage]);
  useEffect(()=>{
    if(!frameRef.current)return;
    const observer=new ResizeObserver(entries=>setWidth(entries[0].contentRect.width));
    observer.observe(frameRef.current);
    return ()=>observer.disconnect();
  },[]);
  useEffect(()=>{
    if(!pdf || !canvasRef.current)return;
    let cancelled=false;
    let render:ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["render"]> | undefined;
    setRendering(true);setError("");
    void (async()=>{
      try {
        const sheet=await pdf.getPage(page);
        if(cancelled || !canvasRef.current)return;
        const natural=sheet.getViewport({scale:1});
        const viewport=sheet.getViewport({scale:Math.max(.1,(width-32)/natural.width)*zoom});
        const canvas=canvasRef.current;
        const pixelRatio=Math.min(window.devicePixelRatio || 1,2);
        canvas.width=Math.floor(viewport.width*pixelRatio);canvas.height=Math.floor(viewport.height*pixelRatio);
        canvas.style.width=`${viewport.width}px`;canvas.style.height=`${viewport.height}px`;
        render=sheet.render({canvas,viewport,transform:pixelRatio===1?undefined:[pixelRatio,0,0,pixelRatio,0,0]});
        await render.promise;
        if(!cancelled)setRendering(false);
      } catch(cause) {if(!cancelled)setError(cause instanceof Error?cause.message:"PDF 页渲染失败")}
    })();
    return ()=>{cancelled=true;render?.cancel()};
  },[pdf,page,width,zoom]);
  return <div className="pdf-reader">
    <div className="pdf-page-controls">
      <button type="button" aria-label="上一页 PDF" disabled={!pdf || page<=1} onClick={()=>setPage(value=>value-1)}><ChevronLeft size={16}/></button>
      <form onSubmit={event=>event.preventDefault()}><input aria-label="PDF 页码" type="number" min={1} max={pdf?.numPages ?? 1} value={page} onChange={event=>{const value=Number(event.target.value);if(pdf && Number.isInteger(value) && value>=1 && value<=pdf.numPages)setPage(value)}}/><span>/ {pdf?.numPages ?? "…"} 页</span></form>
      <button type="button" aria-label="下一页 PDF" disabled={!pdf || page>=pdf.numPages} onClick={()=>setPage(value=>value+1)}><ChevronRight size={16}/></button>
      <button type="button" aria-label="缩小 PDF" disabled={zoom<=.75} onClick={()=>setZoom(value=>Math.max(.75,value-.25))}><ZoomOut size={16}/></button>
      <button type="button" aria-label="放大 PDF" disabled={zoom>=2} onClick={()=>setZoom(value=>Math.min(2,value+.25))}><ZoomIn size={16}/></button>
      <button type="button" onClick={onText}>在解析文字中引用</button>
    </div>
    <div className="pdf-page-frame" ref={frameRef} tabIndex={0} aria-label="可滚动 PDF 原页">
      {error?<div className="reading-empty" role="alert"><strong>{error}</strong><p>解析文字仍可阅读。</p><button type="button" onClick={onText}>阅读解析文字</button></div>:null}
      {!error && rendering?<p className="pdf-loading" role="status">正在载入 PDF 原页…</p>:null}
      <canvas ref={canvasRef} role="img" aria-label={`PDF 原始第 ${page} 页`} style={{visibility:error || rendering?"hidden":"visible"}}/>
    </div>
  </div>;
}
