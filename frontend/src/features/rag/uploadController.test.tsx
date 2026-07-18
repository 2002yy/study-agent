import React from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUploadController } from "./uploadController";

const apiMocks = vi.hoisted(() => ({
  createRagWriteRun: vi.fn(),
  deleteKnowledgeDocument: vi.fn(),
  loadKnowledgeDocuments: vi.fn(),
  loadRagRun: vi.fn(),
}));
vi.mock("../../api", () => apiMocks);

const writeRun = {
  id: "rag_upload_1",
  kind: "upload" as const,
  status: "completed" as const,
  request: {},
  result: { documents: 1, chunks: 2, index_version: 3, stages: [] },
  error: "",
  index_version: 3,
  version: 2,
  created_at: "now",
  updated_at: "now",
};
const documents = {
  index_path: "rag.json",
  index_exists: true,
  index_version: 3,
  documents: [
    {
      document_id: "hash",
      title: "Doc",
      source_path: "doc.md",
      file_type: "md",
      content_hash: "hash",
      chunks: 2,
      metadata: {},
    },
  ],
  chunks: 2,
};

describe("useUploadController", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.loadKnowledgeDocuments.mockResolvedValue(documents);
  });

  it("owns upload state, durable run id, and learner-facing readiness", async () => {
    apiMocks.createRagWriteRun.mockResolvedValue(writeRun);
    const setActiveRunId = vi.fn();
    let controller: ReturnType<typeof useUploadController> | undefined;
    function Harness() {
      controller = useUploadController({
        setActiveRunId,
        setOperationError: vi.fn(),
        onChanged: vi.fn(),
      });
      return null;
    }
    await act(async () => {
      create(<Harness />);
    });
    await act(async () => {
      await controller?.upload([new File(["doc"], "doc.md")]);
    });

    expect(setActiveRunId).toHaveBeenCalledWith("rag_upload_1");
    expect(controller?.flowPhase).toBe("ready");
    expect(controller?.status).toBe("1 份资料已准备好");
    expect(controller?.detail).toContain("索引版本 v3");
    expect(controller?.documents?.documents[0].document_id).toBe("hash");
  });

  it("deletes a document and refreshes the server list", async () => {
    apiMocks.deleteKnowledgeDocument.mockResolvedValue({ deleted_document_id: "hash" });
    let controller: ReturnType<typeof useUploadController> | undefined;
    function Harness() {
      controller = useUploadController({
        setActiveRunId: vi.fn(),
        setOperationError: vi.fn(),
        onChanged: vi.fn(),
      });
      return null;
    }
    await act(async () => {
      create(<Harness />);
    });
    await act(async () => {
      await controller?.removeDocument("hash");
    });
    expect(apiMocks.deleteKnowledgeDocument).toHaveBeenCalledWith("hash");
    expect(apiMocks.loadKnowledgeDocuments).toHaveBeenCalled();
  });
});
