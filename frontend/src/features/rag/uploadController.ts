import { useEffect, useState } from "react";

import {
  createRagWriteRun,
  deleteKnowledgeDocument,
  loadKnowledgeDocuments,
  loadRagRun
} from "../../api";
import type {
  KnowledgeDocumentListResponse,
  RagIndexResponse,
  RagRunResponse
} from "../../types";

type UploadControllerOptions = {
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
  setOperationError: (message: string) => void;
  onChanged: () => Promise<void> | void;
};

export function describeRagWriteResult(result: RagIndexResponse): string {
  const base = `已索引 ${result.documents} 个文档、${result.chunks} 个片段`;
  const failedStages = (result.stages ?? []).filter((stage) => stage.status === "failed");
  const version = result.index_version ? ` · 索引版本 v${result.index_version}` : "";
  return failedStages.length
    ? `${base}${version}；${failedStages.map((stage) => `${stage.name} 阶段失败：${stage.detail ?? "未知错误"}`).join("；")}`
    : `${base}${version}`;
}

export function useUploadController(options: UploadControllerOptions) {
  const [mode, setMode] = useState<"upload" | "rebuild">("upload");
  const [run, setRun] = useState<RagRunResponse | null>(null);
  const [status, setStatus] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [documents, setDocuments] = useState<KnowledgeDocumentListResponse | null>(null);

  const refreshDocuments = async () => {
    try {
      setDocuments(await loadKnowledgeDocuments());
    } catch (error) {
      options.setOperationError(
        `知识库文档读取失败：${error instanceof Error ? error.message : "读取失败"}`
      );
    }
  };

  const upload = async (files: File[]) => {
    if (!files.length || isUploading) return;
    setIsUploading(true);
    setStatus(`${mode === "upload" ? "正在追加索引" : "正在重建索引"} ${files.length} 个文件...`);
    options.setOperationError("");
    try {
      const created = await createRagWriteRun(files, mode);
      setRun(created);
      options.setActiveRunId(created.id);
      setStatus(describeRagWriteResult(created.result as unknown as RagIndexResponse));
      await refreshDocuments();
      await options.onChanged();
    } catch (error) {
      const message = error instanceof Error ? error.message : "未知错误";
      setStatus(`上传失败：${message}`);
      options.setOperationError(`资料上传失败：${message}`);
    } finally {
      setIsUploading(false);
    }
  };

  const removeDocument = async (documentId: string) => {
    options.setOperationError("");
    try {
      await deleteKnowledgeDocument(documentId);
      await refreshDocuments();
      await options.onChanged();
    } catch (error) {
      options.setOperationError(
        `文档删除失败：${error instanceof Error ? error.message : "删除失败"}`
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
          setRun(restored);
          setMode(restored.kind);
          setStatus(describeRagWriteResult(restored.result as unknown as RagIndexResponse));
        }
      })
      .catch((error) => {
        if (active) {
          options.setOperationError(
            `RAG 写入恢复失败：${error instanceof Error ? error.message : "记录不存在"}`
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
    isUploading,
    documents,
    upload,
    removeDocument,
    refreshDocuments
  };
}
