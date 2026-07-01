import { useEffect, useState } from "react";

import { createRagQueryRun, loadRagRun } from "../../api";
import type { RagQueryResponse, RagRunResponse, RagSettings } from "../../types";

type RagControllerOptions = {
  settings: RagSettings;
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
  setOperationError: (message: string) => void;
};

export function useRagController(options: RagControllerOptions) {
  const [run, setRun] = useState<RagRunResponse | null>(null);
  const [result, setResult] = useState<RagQueryResponse | null>(null);
  const [isSearching, setIsSearching] = useState(false);

  const search = async (query: string) => {
    const normalized = query.trim();
    if (!normalized || isSearching) return;
    setIsSearching(true);
    options.setOperationError("");
    try {
      const created = await createRagQueryRun(normalized, options.settings);
      setRun(created);
      setResult(created.result as unknown as RagQueryResponse);
      options.setActiveRunId(created.id);
    } catch (error) {
      setRun(null);
      setResult(null);
      options.setOperationError(
        `本地资料检索失败：${error instanceof Error ? error.message : "来源检索失败"}`
      );
    } finally {
      setIsSearching(false);
    }
  };

  const clear = () => {
    setRun(null);
    setResult(null);
    options.setActiveRunId(undefined);
  };

  useEffect(() => {
    if (!options.activeRunId || options.activeRunId === run?.id) return;
    let active = true;
    void loadRagRun(options.activeRunId)
      .then((restored) => {
        if (active && restored.kind === "query") {
          setRun(restored);
          setResult(restored.result as unknown as RagQueryResponse);
        }
      })
      .catch((error) => {
        if (active) {
          options.setOperationError(
            `RAG 查询恢复失败：${error instanceof Error ? error.message : "记录不存在"}`
          );
          options.setActiveRunId(undefined);
        }
      });
    return () => {
      active = false;
    };
  }, [options.activeRunId, run?.id]);

  return { run, result, isSearching, search, clear };
}
