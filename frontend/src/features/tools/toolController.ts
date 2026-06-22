import { useEffect, useMemo, useState } from "react";

import {
  callToolRun,
  createToolRun,
  getToolRun,
  type LocalKnowledgeInvocation,
} from "../../api";
import { operationRegistry } from "../../app/operationRegistry";
import type { ToolRunResponse } from "../../types";

type ToolControllerOptions = {
  invocation: LocalKnowledgeInvocation;
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
  onCalled?: (runId: string) => Promise<void> | void;
};

export function useToolController(options: ToolControllerOptions) {
  const [run, setRun] = useState<ToolRunResponse | null>(null);
  const [busyStage, setBusyStage] = useState<"" | "preview" | "call">("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!options.activeRunId) {
      setRun(null);
      setError("");
      return;
    }
    if (run?.id === options.activeRunId) return;
    let cancelled = false;
    void getToolRun(options.activeRunId)
      .then((restored) => {
        if (!cancelled) setRun(restored);
      })
      .catch((caught) => {
        if (!cancelled) setError(messageOf(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [options.activeRunId]);

  const invocationChanged = Boolean(run && !matchesInvocation(run, options.invocation));
  const canCall = run?.status === "previewed" && !busyStage && !invocationChanged;
  const invocationLabel = useMemo(() => {
    if (!run) return "";
    return `${String(run.args.query ?? "")} · ${String(run.args.retrieval_mode ?? "")} · top_k=${String(run.args.top_k ?? "")} · min_score=${String(run.args.min_score ?? "")}`;
  }, [run]);

  const preview = async () => {
    if (!options.invocation.query.trim() || busyStage) return;
    const operation = operationRegistry.start("tool", "preview");
    setBusyStage("preview");
    setError("");
    try {
      const created = await createToolRun(options.invocation, {
        signal: operation.controller.signal,
      });
      if (!operationRegistry.isCurrent(operation.operationId, operation.generationId)) return;
      setRun(created);
      options.setActiveRunId(created.id);
    } catch (caught) {
      if (
        operationRegistry.isCurrent(operation.operationId, operation.generationId) &&
        !(caught instanceof DOMException && caught.name === "AbortError")
      ) {
        setError(messageOf(caught));
      }
    } finally {
      if (operationRegistry.isCurrent(operation.operationId, operation.generationId)) {
        setBusyStage("");
        operationRegistry.complete(operation.operationId);
      }
    }
  };

  const call = async () => {
    if (!run || !canCall) return;
    const operation = operationRegistry.start("tool", run.id);
    setBusyStage("call");
    setError("");
    try {
      const completed = await callToolRun(run.id, {
        signal: operation.controller.signal,
      });
      if (!operationRegistry.isCurrent(operation.operationId, operation.generationId)) return;
      setRun(completed);
      await options.onCalled?.(completed.id);
    } catch (caught) {
      if (
        !operationRegistry.isCurrent(operation.operationId, operation.generationId) ||
        (caught instanceof DOMException && caught.name === "AbortError")
      ) return;
      try {
        setRun(await getToolRun(run.id));
      } catch {
        // Keep the call error when server recovery is unavailable.
      }
      setError(messageOf(caught));
    } finally {
      if (operationRegistry.isCurrent(operation.operationId, operation.generationId)) {
        setBusyStage("");
        operationRegistry.complete(operation.operationId);
      }
    }
  };

  const clear = () => {
    operationRegistry.invalidate("tool");
    setRun(null);
    setBusyStage("");
    setError("");
    options.setActiveRunId(undefined);
  };

  const cancelWorkspace = () => {
    operationRegistry.invalidate("tool");
    setBusyStage("");
  };

  return {
    run,
    error,
    isPreviewing: busyStage === "preview",
    isCalling: busyStage === "call",
    canCall,
    callBlockedReason: run && invocationChanged
      ? "输入或 RAG 参数已变化，请重新预览后再调用。"
      : "",
    invocationLabel,
    preview,
    call,
    clear,
    cancelWorkspace,
  };
}

export type ToolController = ReturnType<typeof useToolController>;

function matchesInvocation(
  run: ToolRunResponse,
  invocation: LocalKnowledgeInvocation
): boolean {
  return (
    run.args.query === invocation.query &&
    run.args.retrieval_mode === invocation.retrievalMode &&
    run.args.top_k === invocation.topK &&
    run.args.min_score === invocation.minScore
  );
}

function messageOf(caught: unknown): string {
  return caught instanceof Error ? caught.message : "工具运行失败";
}
