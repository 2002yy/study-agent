import { useEffect, useState } from "react";

import { operationRegistry } from "../../app/operationRegistry";
import {
  createResearchRun,
  loadResearchRun,
  retryResearchRun,
  searchResearchRun,
  type ResearchLookupResponse,
} from "./researchApi";

type WebLookupControllerOptions = {
  query: string;
  setOperationError: (message: string) => void;
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
};

const RETRYABLE_STATUSES = new Set(["pending", "empty", "failed", "running"]);

export function useWebLookupController(options: WebLookupControllerOptions) {
  const [result, setResult] = useState<ResearchLookupResponse | null>(null);
  const [useInChat, setUseInChat] = useState(true);
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
      setUseInChat(response.status === "completed");
      if (response.status === "failed") {
        options.setOperationError(`联网研究失败，可重试：${response.error || "搜索服务不可用"}`);
      }
    } catch (error) {
      if (
        !operationRegistry.isCurrent(operation.operationId, operation.generationId) ||
        (error instanceof DOMException && error.name === "AbortError")
      ) return;
      options.setOperationError(
        `${errorPrefix}：${error instanceof Error ? error.message : errorPrefix}`
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

  const lookup = async () => {
    const query = options.query.trim();
    if (!query || isBusy) return;
    if (result && RETRYABLE_STATUSES.has(result.status)) {
      await retry();
      return;
    }
    await runOperation(async (signal) => {
      const created = await createResearchRun(query, 8, { signal });
      setResult(created);
      options.setActiveRunId(created.run_id);
      return searchResearchRun(created.run_id, { signal });
    }, "联网搜索失败");
  };

  useEffect(() => {
    if (!options.activeRunId || options.activeRunId === result?.run_id) return;
    let active = true;
    void loadResearchRun(options.activeRunId)
      .then((response) => {
        if (active) {
          setResult(response);
          setUseInChat(response.status === "completed");
        }
      })
      .catch((error) => {
        if (active) {
          options.setOperationError(
            `联网结果恢复失败：${error instanceof Error ? error.message : "记录不存在"}`
          );
          options.setActiveRunId(undefined);
        }
      });
    return () => {
      active = false;
    };
  }, [options.activeRunId, result?.run_id]);

  const cancel = () => {
    operationRegistry.invalidate("web_lookup");
    setIsBusy(false);
  };

  return {
    result,
    useInChat,
    setUseInChat,
    isBusy,
    canRetry: Boolean(result && RETRYABLE_STATUSES.has(result.status)),
    lookup,
    retry,
    cancel,
  };
}
