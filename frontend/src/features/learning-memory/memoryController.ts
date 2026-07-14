import { useEffect, useMemo, useState } from "react";

import { commitMemoryRun, createMemoryRun, loadMemoryRun } from "../../api";
import type { MemoryCommitResponse, MemoryRunResponse, MemoryUpdate } from "../../types";
import {
  cancelLearningClosure,
  commitLearningClosure,
  createLearningClosure,
  loadLearningClosure,
  retryLearningClosure,
} from "./closureApi";
import type { LearningClosureRunResponse } from "./closureTypes";

export type MemoryDraft = {
  id?: string;
  target: string;
  content: string;
  replaceCurrentFocus: boolean;
  learnerPending: boolean;
  enabled?: boolean;
};

export const createMemoryDraft = (index: number): MemoryDraft => ({
  id: `draft-${Date.now()}-${index}`,
  target: index === 0 ? "progress" : "summary",
  content: "",
  replaceCurrentFocus: false,
  learnerPending: false,
  enabled: true
});

export function buildMemoryUpdatePayload(draft: MemoryDraft): MemoryUpdate | null {
  if (draft.enabled === false) return null;
  const content = draft.content.trim();
  if (!content) return null;
  return {
    target: draft.target,
    content,
    append: draft.target === "current_focus" ? !draft.replaceCurrentFocus : true,
    learner_pending: draft.learnerPending
  };
}

export function buildMemoryUpdatePayloads(drafts: MemoryDraft[]): MemoryUpdate[] {
  return drafts.flatMap((draft) => {
    const payload = buildMemoryUpdatePayload(draft);
    return payload ? [payload] : [];
  });
}

function draftsFromRun(memoryRun: MemoryRunResponse, prefix: string): MemoryDraft[] {
  return memoryRun.updates.map((update, index) => ({
    id: `${prefix}-${memoryRun.id}-${index}`,
    target: update.target,
    content: update.content,
    replaceCurrentFocus: update.target === "current_focus" && update.append === false,
    learnerPending: Boolean(update.learner_pending),
    enabled: true,
  }));
}

type MemoryControllerOptions = {
  activeRunId?: string;
  setActiveRunId: (runId?: string) => void;
  activeClosureRunId?: string;
  setActiveClosureRunId: (runId?: string) => void;
  onMemoryChanged?: () => Promise<void> | void;
};

export function useMemoryController(options: MemoryControllerOptions) {
  const [drafts, setDrafts] = useState<MemoryDraft[]>([createMemoryDraft(0)]);
  const [run, setRun] = useState<MemoryRunResponse | null>(null);
  const [closureRun, setClosureRun] = useState<LearningClosureRunResponse | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isCommitting, setIsCommitting] = useState(false);
  const [error, setError] = useState("");
  const updates = useMemo(() => buildMemoryUpdatePayloads(drafts), [drafts]);
  const isClosurePreview = Boolean(
    closureRun &&
      closureRun.status === "preview_ready" &&
      closureRun.memory_run?.id === run?.id
  );

  const applyClosure = (closure: LearningClosureRunResponse) => {
    setClosureRun(closure);
    options.setActiveClosureRunId(closure.id);
    if (closure.memory_run) {
      setRun(closure.memory_run);
      options.setActiveRunId(closure.memory_run.id);
      setDrafts(draftsFromRun(closure.memory_run, "closure"));
    } else if (closure.status === "cancelled") {
      setRun(null);
      options.setActiveRunId(undefined);
      setDrafts([createMemoryDraft(0)]);
    }
    if (closure.status === "failed") {
      setError(closure.error || closure.reason || "学习整理失败");
    }
  };

  const invalidatePreview = () => {
    setRun(null);
    options.setActiveRunId(undefined);
  };

  const rejectClosureEdit = () => {
    setError("学习整理候选已由闭包流程锁定；请确认写入、取消，或失败后重试。");
  };

  const updateDraft = <K extends keyof MemoryDraft>(
    id: string | undefined,
    key: K,
    value: MemoryDraft[K]
  ) => {
    if (isClosurePreview) {
      rejectClosureEdit();
      return;
    }
    setDrafts((current) =>
      current.map((draft) => (draft.id === id ? { ...draft, [key]: value } : draft))
    );
    setError("");
    invalidatePreview();
  };

  const addDraft = () => {
    if (isClosurePreview) {
      rejectClosureEdit();
      return;
    }
    setDrafts((current) => [...current, createMemoryDraft(current.length)]);
    setError("");
    invalidatePreview();
  };

  const removeDraft = (id: string | undefined) => {
    if (isClosurePreview) {
      rejectClosureEdit();
      return;
    }
    setDrafts((current) =>
      current.length === 1 ? current : current.filter((draft) => draft.id !== id)
    );
    setError("");
    invalidatePreview();
  };

  const preview = async () => {
    if (isClosurePreview) return;
    if (!updates.length) {
      setError("请先填写至少一条启用的记忆候选。");
      return;
    }
    setIsPreviewing(true);
    setError("");
    try {
      const created = await createMemoryRun(updates);
      setRun(created);
      options.setActiveRunId(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "记忆预览失败");
    } finally {
      setIsPreviewing(false);
    }
  };

  const commit = async () => {
    if (!run || run.status !== "previewed" || !run.preview.writable) {
      setError("请先生成可写预览，再确认写入。");
      return;
    }
    setIsCommitting(true);
    setError("");
    try {
      if (isClosurePreview && closureRun) {
        const committedClosure = await commitLearningClosure(closureRun.id);
        applyClosure(committedClosure);
        if (committedClosure.status !== "completed") {
          setError(
            committedClosure.error || committedClosure.reason || "学习整理写入失败"
          );
        } else {
          setDrafts([createMemoryDraft(0)]);
          await options.onMemoryChanged?.();
        }
        return;
      }
      const committed = await commitMemoryRun(run.id);
      setRun(committed);
      if (committed.status === "succeeded") {
        setDrafts([createMemoryDraft(0)]);
      } else if (committed.status === "partial") {
        const failed = new Set((committed.result.errors ?? []).map((item) => item.target));
        setDrafts((current) =>
          current.filter((draft) => failed.has(draft.target) && draft.content.trim())
        );
        setError(formatErrors(committed.result.errors));
      } else {
        setError(committed.reason || formatErrors(committed.result.errors));
      }
      await options.onMemoryChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "记忆提交失败");
    } finally {
      setIsCommitting(false);
    }
  };

  useEffect(() => {
    if (options.activeClosureRunId) return;
    if (!options.activeRunId || options.activeRunId === run?.id) return;
    let active = true;
    void loadMemoryRun(options.activeRunId)
      .then((restored) => {
        if (active) {
          setRun(restored);
          setDrafts(draftsFromRun(restored, "restored"));
        }
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : "记忆事务恢复失败");
          options.setActiveRunId(undefined);
        }
      });
    return () => {
      active = false;
    };
  }, [options.activeRunId, options.activeClosureRunId, run?.id]);

  useEffect(() => {
    if (!options.activeClosureRunId || options.activeClosureRunId === closureRun?.id) {
      return;
    }
    let active = true;
    void loadLearningClosure(options.activeClosureRunId)
      .then((restored) => {
        if (active) applyClosure(restored);
      })
      .catch((err) => {
        if (active) {
          setError(err instanceof Error ? err.message : "学习整理事务恢复失败");
          options.setActiveClosureRunId(undefined);
        }
      });
    return () => {
      active = false;
    };
  }, [options.activeClosureRunId, closureRun?.id]);

  const generateFromSession = async (sessionId: string) => {
    if (!sessionId) {
      setError("没有活动会话，无法生成学习整理。");
      return;
    }
    setIsPreviewing(true);
    setError("");
    try {
      applyClosure(await createLearningClosure(sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "学习整理生成失败");
    } finally {
      setIsPreviewing(false);
    }
  };

  const retryClosure = async () => {
    if (!closureRun || isPreviewing) return;
    setIsPreviewing(true);
    setError("");
    try {
      applyClosure(await retryLearningClosure(closureRun.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "学习整理重试失败");
    } finally {
      setIsPreviewing(false);
    }
  };

  const cancelClosure = async () => {
    if (!closureRun || isPreviewing || isCommitting) return;
    setIsPreviewing(true);
    setError("");
    try {
      applyClosure(await cancelLearningClosure(closureRun.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "学习整理取消失败");
    } finally {
      setIsPreviewing(false);
    }
  };

  return {
    drafts,
    run,
    closureRun,
    isClosurePreview,
    preview: run?.preview ?? null,
    commitResult: toCommitResult(run),
    isPreviewing,
    isCommitting,
    error,
    canPreview: updates.length > 0,
    updateDraft,
    addDraft,
    removeDraft,
    previewUpdates: preview,
    commitRun: commit,
    generateFromSession,
    retryClosure,
    cancelClosure,
  };
}

function toCommitResult(run: MemoryRunResponse | null): MemoryCommitResponse | null {
  if (!run || !["succeeded", "partial", "failed"].includes(run.status)) return null;
  return {
    writable: run.status !== "blocked",
    results: run.result.results ?? [],
    errors: run.result.errors?.length ? run.result.errors : undefined
  };
}

function formatErrors(errors: MemoryRunResponse["result"]["errors"] = []): string {
  return errors.length
    ? errors.map((item) => `${item.target}: ${item.error}`).join(", ")
    : "记忆提交失败";
}
