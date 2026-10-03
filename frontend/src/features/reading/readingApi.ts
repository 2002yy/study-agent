export type ReadingTarget = {
  scope: "knowledge" | "session";
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
  representation: "indexed_text";
  scope: "knowledge" | "session";
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
};

export async function readDocument(
  target: ReadingTarget,
  startLine: number,
  signal: AbortSignal,
): Promise<DocumentReading> {
  const base = import.meta.env.VITE_API_BASE_URL ?? "";
  const path = target.scope === "session"
    ? `/sessions/${encodeURIComponent(target.threadId ?? "")}/attachments/${encodeURIComponent(target.attachmentId ?? "")}/reading`
    : `/knowledge-base/documents/${encodeURIComponent(target.documentId ?? "")}/reading`;
  const query = new URLSearchParams({start_line: String(startLine), limit: String(target.windowLines ?? 100)});
  if (target.revision) query.set("expected_revision", target.revision);
  const token = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";
  const response = await fetch(`${base}${path}?${query}`, {
    signal, headers:token ? {"X-Study-Agent-Token":token} : {},
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === "string" ? body.detail : `资料读取失败（${response.status}）`);
  }
  const data: DocumentReading = await response.json();
  if (
    data.schema_version !== "document-reading-v1" || data.representation !== "indexed_text"
    || data.scope !== target.scope || !data.revision_id
    || (target.documentId && data.document_id !== target.documentId)
    || (target.revision && data.revision_id !== target.revision)
    || (target.sourcePath && data.source_path !== target.sourcePath)
    || data.start_line !== startLine || data.end_line < startLine
    || data.end_line > data.total_lines || typeof data.text !== "string"
    || (target.endLine && target.endLine > data.total_lines)
  ) throw new Error("正文与引用定位不一致，请重新选择资料");
  return data;
}
