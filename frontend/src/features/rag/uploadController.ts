import { useEffect, useState } from "react";

import {
  createRagWriteRun,
  deleteKnowledgeDocument,
  loadKnowledgeDocuments,
  loadRagRun,
} from "../../api";
import type {
  RagIndexResponse,
  RagRunResponse,
} from "../../types";
import {
  setKnowledgeDocumentEvidenceStatus,
  type EvidenceKnowledgeDocumentListResponse,
  type EvidenceStatus,
} from "./evidenceEligibilityApi";

type UploadControllerOptions = {
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
  setOperationError: (message: string) => void;
  onChanged: () => Promise<void> | void;
};

export type UploadFlowPhase = "idle" | "processing" | "ready" | "failed";

export function describeRagWriteResult(result: RagIndexResponse): string {
  const base = `已索引 ${result.documents} 个文档、${result.chunks} 个片段`;
  const failedStages = (result.stages ?? []).filter((stage) => stage.status === "failed");
  const version = result.index_version ? ` · 索引版本 v${result.index_version}` : "";
  return failedStages.length
    ? `${base}${version}；${failedStages.map((stage) => `${stage.name} 阶段失败：${stage.detail ?? "未知错误"}`).join("；")}`
    : `${base}${version}`;
}

function hasFailedStage(result: RagIndexResponse): boolean {
  return (result.stages ?? []).some((stage) => stage.status === "failed");
}

export function useUploadController(options: UploadControllerOptions) {
  const [mode, setMode] = useState<"upload" | "rebuild">("upload");
  const [run, setRun] = useState<RagRunResponse | null>(null);
  const [status, setStatus] = useState("");
  const [detail, setDetail] = useState("");
  const [flowPhase, setFlowPhase] = useState<UploadFlowPhase>("idle");
  const [lastUploadCount, setLastUploadCount] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [documents, setDocuments] = useState<EvidenceKnowledgeDocumentListResponse | null>(null);

  const refreshDocuments = async () => {
    try {
      setDocuments(
        (await loadKnowledgeDocuments()) as EvidenceKnowledgeDocumentListResponse,
      );
    } catch (error) {
      options.setOperationError(
        `知识库文档读取失败：${error instanceof Error ? error.message : "读取失败"}`,
      );
    }
  };

  const upload = async (files: File[]) => {
    if (!files.length || isUploading) return;
    setIsUploading(true);
    setLastUploadCount(files.length);
    setFlowPhase("processing");
    setStatus(`正在解析 ${files.length} 份资料…`);
    setDetail("");
    options.setOperationError("");
    try {
      const created = await createRagWriteRun(files, mode);
      const result = created.result as unknown as RagIndexResponse;
      setRun(created);
      options.setActiveRunId(created.id);
      setDetail(describeRagWriteResult(result));
      if (hasFailedStage(result)) {
        setFlowPhase("failed");
        setStatus("资料处理没有完整完成，请查看错误后重试。");
      } else {
        setFlowPhase("ready");
        setStatus(`${files.length} 份资料已准备好`);
      }
      await refreshDocuments();
      await options.onChanged();
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      setFlowPhase("failed");
      setStatus("资料处理失败，请重试。");
      setDetail(message);
      options.setOperationError(`资料上传失败：${message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const dismissFlow = () => {
    setFlowPhase("idle");
    setStatus("");
    setDetail("");
    setLastUploadCount(0);
  };

  const removeDocument = async (documentId: string) => {
    options.setOperationError("");
    try {
      await deleteKnowledgeDocument(documentId);
      await refreshDocuments();
      await options.onChanged();
    } catch (error) {
      options.setOperationError(
        `文档删除失败：${error instanceof Error ? error.message : "删除失败"}`,
      );
    }
  };

  const setDocumentEvidenceStatus = async (
    documentId: string,
    evidenceStatus: EvidenceStatus,
    supersededByDocumentId = "",
  ) => {
    options.setOperationError("");
    try {
      await setKnowledgeDocumentEvidenceStatus(
        documentId,
        evidenceStatus,
        supersededByDocumentId,
      );
      await refreshDocuments();
      await options.onChanged();
    } catch (error) {
      options.setOperationError(
        `资料状态更新失败：${error instanceof Error ? error.message : "更新失败"}`,
      );
    }
  };

  useEffect(() => {
    void refreshDocuments();
  }, []);

  useEffect(() => {
    if (!options.activeRunId || options.activeRunId === run?.id) return;
    let active = true;
    void loadRagRun(options.activeRunId)
      .then((restored) => {
        if (active && (restored.kind === "upload" || restored.kind === "rebuild")) {
          const result = restored.result as unknown as RagIndexResponse;
          setRun(restored);
          setMode(restored.kind);
          setDetail(describeRagWriteResult(result));
          setFlowPhase(hasFailedStage(result) ? "failed" : "ready");
          setStatus(hasFailedStage(result) ? "资料处理没有完整完成，请查看错误后重试。" : "资料已准备好");
        }
      })
      .catch((error) => {
        if (active) {
          options.setOperationError(
            `RAG 写入恢复失败：${error instanceof Error ? error.message : "记录不存在"}`,
          );
          options.setActiveRunId(undefined);
        }
      });
    return () => {
      active = false;
    };
  }, [options.activeRunId, run?.id]);

  return {
    mode,
    setMode,
    run,
    status,
    detail,
    flowPhase,
    lastUploadCount,
    isUploading,
    documents,
    upload,
    dismissFlow,
    removeDocument,
    setDocumentEvidenceStatus,
    refreshDocuments,
  };
}
