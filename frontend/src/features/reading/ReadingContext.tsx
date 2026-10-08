import { createContext, useContext } from "react";
import type { KnowledgeDocument, RagResult, TurnEvidence } from "../../types";
import type { DocumentReading, ReadingTarget } from "./readingApi";

export type ReadingContextValue = {
  documents: KnowledgeDocument[];
  sessionId?: string;
  webCitation: (url:string, evidence:TurnEvidence) => ReadingTarget | null;
  target: ReadingTarget | null;
  document: DocumentReading | null;
  error: string;
  loading: boolean;
  mode: "read" | "chat";
  focused: boolean;
  canAsk: boolean;
  open: (target: ReadingTarget) => void;
  browse: () => void;
  close: () => void;
  showChat: () => void;
  showReader: () => void;
  toggleFocus: () => void;
  goToLine: (line: number) => void;
  retry: () => void;
  shrinkWindow: () => void;
  ask: (quote: string, startLine: number, endLine: number) => void;
  citation: (id: string, source: string, results: RagResult[]) => ReadingTarget | null;
};

export const ReadingContext = createContext<ReadingContextValue | null>(null);
export const useReadingWorkspace = () => useContext(ReadingContext);

/** Resolve exact turn-local identity; filenames and titles cannot authorize a jump. */
export function citationTarget(
  id: string,
  source: string,
  results: RagResult[],
  documents: KnowledgeDocument[],
  sessionId?: string,
): ReadingTarget | null {
  const matches = results.filter(item => item.chunk?.chunk_id === id);
  if (matches.length !== 1) return null;
  const chunk = matches[0].chunk;
  if (!chunk?.document_id || !chunk.revision_id || !source || chunk.source_path !== source
    || !Number.isInteger(chunk.start_line) || !Number.isInteger(chunk.end_line)
    || chunk.start_line! < 1 || chunk.end_line! < chunk.start_line!) return null;
  const common = {documentId:chunk.document_id, revision:chunk.revision_id,
    sourcePath:source, startLine:chunk.start_line, endLine:chunk.end_line};
  const metadata = chunk.metadata;
  if (typeof metadata?.attachment_id === "string") {
    if (!sessionId || metadata.thread_id !== sessionId) return null;
    return {...common, scope:"session", attachmentId:metadata.attachment_id, threadId:sessionId};
  }
  const known = documents.some(doc => doc.document_id === chunk.document_id
    && doc.revision_id === chunk.revision_id && doc.source_path === source);
  return known ? {...common,scope:"knowledge"} : null;
}
