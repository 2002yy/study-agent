import { useEffect, useMemo, useState, type FormEvent } from "react";

import {
  createNewsRun,
  digestNewsRun,
  discussNewsRun,
  enrichNewsRun,
  getNewsRun,
  searchNewsRun,
} from "../../api";
import { operationRegistry } from "../../app/operationRegistry";
import type { ChatSettings, NewsRunResponse } from "../../types";

type NewsControllerOptions = {
  query: string;
  readArticles: boolean;
  chatSettings: ChatSettings;
  groupThreadId?: string;
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
  onDiscussed: (groupThreadId: string) => void;
};

export function useNewsController(options: NewsControllerOptions) {
  const [run, setRun] = useState<NewsRunResponse | null>(null);
  const [busyStage, setBusyStage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!options.activeRunId) {
      setRun(null);
      setError("");
      return;
    }
    if (run?.id === options.activeRunId) return;
    let cancelled = false;
    void getNewsRun(options.activeRunId)
      .then((restored) => {
        if (!cancelled) setRun(restored);
      })
      .catch((caught) => {
        if (!cancelled) setError(`新闻运行恢复失败：${messageOf(caught)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [options.activeRunId]);

  const queryChanged = Boolean(run && options.query.trim() !== run.query);
  const canSearch = Boolean(options.query.trim()) && !busyStage;
  const canEnrich = run?.stage === "searched" && !busyStage && !queryChanged;
  const canDigest = Boolean(
    run && ["searched", "enriched", "enrich_skipped"].includes(run.stage)
  ) && !busyStage && !queryChanged;
  const canDiscuss = run?.stage === "digested" && !busyStage && !queryChanged;
  const articlesReadCount = useMemo(
    () =>
      (run?.items ?? []).filter(
        (item) =>
          typeof item.article_text === "string" ||
          typeof item.article_excerpt === "string"
      ).length,
    [run?.items]
  );

  const runStage = async (
    stage: string,
    action: (signal: AbortSignal) => Promise<NewsRunResponse>,
    recoveryRunId?: () => string | undefined
  ) => {
    const operation = operationRegistry.start("news", run?.id ?? stage);
    setBusyStage(stage);
    setError("");
    try {
      const result = await action(operation.controller.signal);
      if (!operationRegistry.isCurrent(operation.operationId, operation.generationId)) return null;
      setRun(result);
      options.setActiveRunId(result.id);
      return result;
    } catch (caught) {
      if (
        !operationRegistry.isCurrent(operation.operationId, operation.generationId) ||
        (caught instanceof DOMException && caught.name === "AbortError")
      ) return null;
      const runId = recoveryRunId?.() ?? run?.id;
      if (runId) {
        try {
          const latest = await getNewsRun(runId);
          setRun(latest);
          options.setActiveRunId(latest.id);
        } catch {
          // Preserve the stage error when recovery is unavailable.
        }
      }
      setError(messageOf(caught));
      return null;
    } finally {
      if (operationRegistry.isCurrent(operation.operationId, operation.generationId)) {
        setBusyStage("");
        operationRegistry.complete(operation.operationId);
      }
    }
  };

  const search = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!canSearch) return;
    const query = options.query.trim();
    let createdRunId: string | undefined;
    await runStage(
      "search",
      async (signal) => {
        const created = await createNewsRun(query, { signal });
        createdRunId = created.id;
        setRun(created);
        options.setActiveRunId(created.id);
        return searchNewsRun(created.id, 10, { signal });
      },
      () => createdRunId
    );
  };

  const enrich = async () => {
    if (!run || !canEnrich) return;
    await runStage("enrich", (signal) =>
      enrichNewsRun(run.id, options.readArticles ? 6 : 0, { signal })
    );
  };

  const digest = async () => {
    if (!run || !canDigest) return;
    await runStage("digest", async (signal) => {
      let current = run;
      if (current.stage === "searched") {
        current = await enrichNewsRun(
          current.id,
          options.readArticles ? 6 : 0,
          { signal }
        );
        setRun(current);
        options.setActiveRunId(current.id);
      }
      return digestNewsRun(current.id, options.chatSettings, { signal });
    });
  };

  const discuss = async () => {
    if (!run || !canDiscuss) return;
    const discussed = await runStage("discuss", (signal) =>
      discussNewsRun(run.id, options.groupThreadId, options.chatSettings, { signal })
    );
    if (discussed?.group_thread_id) options.onDiscussed(discussed.group_thread_id);
  };

  const clear = () => {
    operationRegistry.invalidate("news");
    setRun(null);
    setBusyStage("");
    setError("");
    options.setActiveRunId(undefined);
  };

  const cancelWorkspace = () => {
    operationRegistry.invalidate("news");
    setBusyStage("");
  };

  return {
    run,
    busyStage,
    error,
    queryChanged,
    canSearch,
    canEnrich,
    canDigest,
    canDiscuss,
    articlesReadCount,
    search,
    enrich,
    digest,
    discuss,
    clear,
    cancelWorkspace,
  };
}

export type NewsController = ReturnType<typeof useNewsController>;

function messageOf(caught: unknown): string {
  return caught instanceof Error ? caught.message : "新闻阶段执行失败";
}
