import { useEffect, useState } from "react";

import { operationRegistry } from "../../app/operationRegistry";
import {
  cancelResearchRun,
  createResearchRun,
  executeResearchRun,
  loadResearchRun,
  resumeResearchRun,
  retryResearchRun,
  type ResearchLookupResponse,
} from "./researchApi";

type WebLookupControllerOptions = {
  query: string;
  setOperationError: (message: string) => void;
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
};

function isUsable(response: ResearchLookupResponse): boolean {
  return ["completed", "partial"].includes(response.status) && response.news_items.length > 0;
}

function isRetryable(response: ResearchLookupResponse | null): boolean {
  if (!response) return false;
  if (["failed", "cancelled", "partial"].includes(response.status)) return true;
  return response.status === "completed" && ["empty", "partial", "insufficient"].includes(response.provider_status);
}

function isResumable(response: ResearchLookupResponse | null): boolean {
  return Boolean(response && ["pending", "running"].includes(response.status));
}

export function useWebLookupController(options: WebLookupControllerOptions) {
  const [result, setResult] = useState<ResearchLookupResponse | null>(null);
  const [useInChat, setUseInChat] = useState(false);
  const [isBusy, setIsBusy] = useState(false);

  const runOperation = async (
    task: (signal: AbortSignal) => Promise<ResearchLookupResponse>,
    errorPrefix: string,
  ) => {
    const operation = operationRegistry.start("web_lookup");
    setIsBusy(true);
    options.setOperationError("");
    try {
      const response = await task(operation.controller.signal);
      if (!operationRegistry.isCurrent(operation.operationId, operation.generationId)) return;
      setResult(response);
      options.setActiveRunId(response.run_id);
      setUseInChat(isUsable(response));
      if (response.status === "failed") {
        options.setOperationError(
          `联网研究失败，可重试：${response.error || "研究服务不可用"}`,
        );
      }
    } catch (error) {
      if (
        !operationRegistry.isCurrent(operation.operationId, operation.generationId) ||
        (error instanceof DOMException && error.name === "AbortError")
      ) return;
      options.setOperationError(
        `${errorPrefix}：${error instanceof Error ? error.message : errorPrefix}`,
      );
    } finally {
      if (operationRegistry.isCurrent(operation.operationId, operation.generationId)) {
        setIsBusy(false);
      }
      operationRegistry.complete(operation.operationId);
    }
  };

  const retry = async () => {
    const runId = result?.run_id ?? options.activeRunId;
    if (!runId || isBusy) return;
    await runOperation(
      (signal) => retryResearchRun(runId, { signal }),
      "联网研究重试失败",
    );
  };

  const resume = async () => {
    const runId = result?.run_id ?? options.activeRunId;
    if (!runId || isBusy) return;
    await runOperation(
      (signal) => resumeResearchRun(runId, { signal }),
      "联网研究恢复失败",
    );
  };

  const lookup = async () => {
    const query = options.query.trim();
    if (!query || isBusy) return;
    const sameQuery = result?.query_text.trim() === query;
    if (sameQuery && isResumable(result)) {
      await resume();
      return;
    }
    if (sameQuery && isRetryable(result)) {
      await retry();
      return;
    }
    if (sameQuery && result?.status === "completed" && result.provider_status === "found") {
      setUseInChat(true);
      return;
    }

    setUseInChat(false);
    await runOperation(async (signal) => {
      const created = await createResearchRun(query, 8, { signal });
      setResult(created);
      options.setActiveRunId(created.run_id);
      return executeResearchRun(created.run_id, { signal });
    }, "联网搜索失败");
  };

  useEffect(() => {
    if (!options.activeRunId || options.activeRunId === result?.run_id) return;
    let active = true;
    void loadResearchRun(options.activeRunId)
      .then((response) => {
        if (active) {
          setResult(response);
          setUseInChat(isUsable(response));
        }
      })
      .catch((error) => {
        if (active) {
          options.setOperationError(
            `联网结果恢复失败：${error instanceof Error ? error.message : "记录不存在"}`,
          );
          options.setActiveRunId(undefined);
        }
      });
    return () => {
      active = false;
    };
  }, [options.activeRunId, result?.run_id]);

  const cancel = () => {
    const runId = result?.run_id ?? options.activeRunId;
    if (runId) {
      void cancelResearchRun(runId)
        .then((response) => {
          setResult(response);
          setUseInChat(false);
          options.setActiveRunId(response.run_id);
        })
        .catch((error) => {
          options.setOperationError(
            `停止联网研究失败：${error instanceof Error ? error.message : "取消请求失败"}`,
          );
        });
    }
    operationRegistry.invalidate("web_lookup");
    setIsBusy(false);
  };

  const refreshRun = async (runId: string) => {
    try {
      const response = await loadResearchRun(runId);
      setResult(response);
      setUseInChat(isUsable(response));
      options.setActiveRunId(response.run_id);
    } catch (error) {
      options.setOperationError(
        `联网研究状态刷新失败：${error instanceof Error ? error.message : "记录不存在"}`,
      );
    }
  };

  return {
    result,
    useInChat,
    setUseInChat,
    isBusy,
    canRetry: isRetryable(result),
    canResume: isResumable(result),
    lookup,
    retry,
    resume,
    cancel,
    refreshRun,
  };
}
