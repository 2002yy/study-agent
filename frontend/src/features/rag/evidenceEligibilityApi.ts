import type { KnowledgeDocument, KnowledgeDocumentListResponse } from "../../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API_TOKEN = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";

export type EvidenceStatus = "active" | "superseded" | "excluded";

export type EvidenceKnowledgeDocument = KnowledgeDocument & {
  evidence_status?: EvidenceStatus;
  superseded_by_document_id?: string;
};

export type EvidenceKnowledgeDocumentListResponse = Omit<
  KnowledgeDocumentListResponse,
  "documents"
> & {
  documents: EvidenceKnowledgeDocument[];
  retrievable_documents?: number;
  retrievable_chunks?: number;
};

export type EvidenceStatusUpdateResponse = {
  document_id: string;
  evidence_status: EvidenceStatus;
  superseded_by_document_id: string;
  documents: number;
  chunks: number;
  retrievable_documents: number;
  retrievable_chunks: number;
  index_path: string;
  index_version: number;
  stages: Array<Record<string, unknown>>;
};

function authHeaders(): HeadersInit {
  return API_TOKEN ? { "X-Study-Agent-Token": API_TOKEN } : {};
}

export async function setKnowledgeDocumentEvidenceStatus(
  documentId: string,
  evidenceStatus: EvidenceStatus,
  supersededByDocumentId = "",
): Promise<EvidenceStatusUpdateResponse> {
  const response = await fetch(
    `${API_BASE_URL}/knowledge-base/documents/${encodeURIComponent(documentId)}/evidence-status`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
      },
      body: JSON.stringify({
        evidence_status: evidenceStatus,
        superseded_by_document_id: supersededByDocumentId,
      }),
    },
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}${body ? `: ${body}` : ""}`);
  }
  return (await response.json()) as EvidenceStatusUpdateResponse;
}
