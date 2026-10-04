import { useEffect, useState } from "react";

import { operationRegistry } from "../../app/operationRegistry";
import {
  cancelResearchRun,
  createResearchRun,
  executeResearchRun,
  loadResearchFollowUpCandidate,
  loadResearchRun,
  resumeResearchRun,
  retryResearchRun,
  steerResearchRun,
  type ResearchLookupResponse,
} from "./researchApi";

type WebLookupControllerOptions = {
  query: string;
  setOperationError: (message: string) => void;
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
  activeThreadId?: string;
};

function followUpRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `follow-up-${crypto.randomUUID()}`;
  }
  return `follow-up-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isUsable(response: ResearchLookupResponse): boolean {
  return (
    response.status === "completed" &&
    response.provider_status === "found" &&
    response.news_items.length > 0 &&
    response.selected_sources.length > 0 &&
    Boolean(response.source_block.trim())
  );
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
      let parentRunId: string | undefined;
      let suggestionStatus: "not_checked" | "not_found" | "accepted" | "declined" | "unavailable" =
        options.activeThreadId ? "not_found" : "not_checked";
      if (options.activeThreadId) {
        try {
          const candidate = await loadResearchFollowUpCandidate(
            options.activeThreadId,
            query,
            { signal },
          );
          if (
            candidate.steering_required &&
            candidate.parent_run_id &&
            window.confirm(
              `相关研究仍在进行：\n“${candidate.parent_query}”\n\n` +
                "是否把当前问题作为研究转向加入该 Run？选择取消后将创建独立研究，不会派生 child。",
            )
          ) {
            return steerResearchRun(candidate.parent_run_id, query, { signal });
          }
          if (candidate.available && candidate.parent_run_id) {
            const partialWarning = candidate.requires_explicit_confirmation
              ? "\n注意：上一次研究未完整完成，只会继承已保存的检查点。"
              : "";
            const accepted = window.confirm(
              `发现相关的既有研究：\n“${candidate.parent_query}”\n` +
                `状态 ${candidate.parent_status}，${candidate.source_count} 个来源、${candidate.note_count} 条有界笔记。` +
                `${partialWarning}\n\n是否创建明确关联的后续研究？旧来源仍会重新搜索并读取验证。`,
            );
            if (accepted) {
              parentRunId = candidate.parent_run_id;
              suggestionStatus = "accepted";
            } else {
              suggestionStatus = "declined";
            }
          }
        } catch (error) {
          if (error instanceof DOMException && error.name === "AbortError") throw error;
          suggestionStatus = "unavailable";
        }
      }
      let created: ResearchLookupResponse;
      try {
        created = await createResearchRun(query, 8, {
          signal,
          ownerThreadId: options.activeThreadId,
          parentRunId,
          createRequestId: parentRunId ? followUpRequestId() : undefined,
          suggestionStatus,
        });
      } catch (error) {
        if (
          !parentRunId ||
          !window.confirm(
            "已确认的既有研究当前不再满足继承条件。是否改为创建不继承旧证据的独立研究？",
          )
        ) {
          throw error;
        }
        created = await createResearchRun(query, 8, {
          signal,
          ownerThreadId: options.activeThreadId,
          suggestionStatus: "unavailable",
        });
      }
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
          // A restored durable run remains visible, but using it in chat is a
          // one-shot user choice and must not be inherited across reloads or sessions.
          setUseInChat(false);
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
    if (!runId) return;

    options.setOperationError("");
    setUseInChat(false);
    setIsBusy(true);
    const cancellation = cancelResearchRun(runId);
    operationRegistry.abort("web_lookup");

    void cancellation
      .then((response) => {
        setResult(response);
        setUseInChat(false);
        options.setActiveRunId(response.run_id);
      })
      .catch((error) => {
        options.setOperationError(
          `停止联网研究失败：${error instanceof Error ? error.message : "取消请求失败"}`,
        );
      })
      .finally(() => {
        setIsBusy(false);
      });
  };

  const refreshRun = async (runId: string) => {
    try {
      const response = await loadResearchRun(runId);
      setResult(response);
      // A chat-owned run already supplied this turn's evidence. Refreshing its
      // status must not silently attach it again to the next user question.
      setUseInChat(false);
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
