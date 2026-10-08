export type ReadingTarget = {
  scope: "knowledge" | "session" | "web";
  runId?: string;
  url?: string;
  documentId?: string;
  attachmentId?: string;
  threadId?: string;
  revision?: string;
  sourcePath?: string;
  startLine?: number;
  endLine?: number;
  windowLines?: number;
};

export type DocumentReading = {
  schema_version: "document-reading-v1";
  representation: "indexed_text" | "saved_web_text";
  scope: "knowledge" | "session" | "web";
  document_id: string;
  revision_id: string;
  content_hash: string;
  parser_version: string;
  title: string;
  source_path: string;
  file_type: string;
  evidence_status: string;
  start_line: number;
  end_line: number;
  total_lines: number;
  text: string;
  pdf_pages?: number;
  pdf_page_map?: {page:number;line:number}[];
  content_truncated?: boolean;
};

export function readingPath(target: ReadingTarget) {
  if (target.scope === "web") return `/sessions/${encodeURIComponent(target.threadId ?? "")}/research-runs/${encodeURIComponent(target.runId ?? "")}/sources/reading`;
  return target.scope === "session"
    ? `/sessions/${encodeURIComponent(target.threadId ?? "")}/attachments/${encodeURIComponent(target.attachmentId ?? "")}/reading`
    : `/knowledge-base/documents/${encodeURIComponent(target.documentId ?? "")}/reading`;
}

async function checkedFetch(path:string, signal:AbortSignal) {
  const base = import.meta.env.VITE_API_BASE_URL ?? "";
  const token = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";
  const response = await fetch(`${base}${path}`, {signal, headers:token ? {"X-Study-Agent-Token":token} : {}});
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `资料读取失败（${response.status}）`);
  }
  return response;
}

export async function readOriginalPdf(target:ReadingTarget, revision:string, signal:AbortSignal) {
  if(target.scope === "web") throw new Error("网页没有本地 PDF 原件");
  const path=readingPath(target).replace(/\/reading$/, "/original");
  const response=await checkedFetch(`${path}?${new URLSearchParams({expected_revision:revision})}`,signal);
  if (!response.headers.get("content-type")?.includes("application/pdf")) throw new Error("原件类型不一致");
  return new Uint8Array(await response.arrayBuffer());
}

export async function readDocument(
  target: ReadingTarget,
  startLine: number,
  signal: AbortSignal,
): Promise<DocumentReading> {
  const path = readingPath(target);
  const query = new URLSearchParams({start_line: String(startLine), limit: String(target.windowLines ?? 100)});
  if (target.revision) query.set("expected_revision", target.revision);
  if (target.scope === "web" && target.url) query.set("url", target.url);
  const response = await checkedFetch(`${path}?${query}`,signal);
  const data: DocumentReading = await response.json();
  if (
    data.schema_version !== "document-reading-v1" || data.representation !== (target.scope === "web" ? "saved_web_text" : "indexed_text")
    || data.scope !== target.scope || !data.revision_id
    || (target.documentId && data.document_id !== target.documentId)
    || (target.revision && data.revision_id !== target.revision)
    || (target.sourcePath && data.source_path !== target.sourcePath)
    || (target.scope === "web" && data.source_path !== target.url)
    || data.start_line !== startLine || data.end_line < startLine
    || data.end_line > data.total_lines || typeof data.text !== "string"
    || (target.endLine && target.endLine > data.total_lines)
  ) throw new Error("正文与引用定位不一致，请重新选择资料");
  return data;
}
