// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoryController } from "./memoryController";

const apiMocks = vi.hoisted(() => ({
  createMemoryRun: vi.fn(),
  loadMemoryRun: vi.fn(),
  commitMemoryRun: vi.fn(),
}));
const closureMocks = vi.hoisted(() => ({
  createLearningClosure: vi.fn(),
  loadLearningClosure: vi.fn(),
  retryLearningClosure: vi.fn(),
  cancelLearningClosure: vi.fn(),
  commitLearningClosure: vi.fn(),
}));

vi.mock("../../api", () => apiMocks);
vi.mock("./closureApi", () => closureMocks);

const previewedRun = {
  id: "memory_1",
  status: "previewed" as const,
  updates: [{ target: "progress", content: "remember", append: true, learner_pending: false }],
  updates_hash: "hash",
  preview: {
    writable: true,
    memory_mode: "confirm_write",
    safe_mode: false,
    updates: [{ target: "progress", path: "progress.md", action: "append", allowed: true, preview: "remember" }],
  },
  result: {},
  reason: "",
  version: 1,
  created_at: "now",
  updated_at: "now",
};

const previewSummary = {
  thread_id: "chat_1",
  status: "not_summarized" as const,
  source_thread_version: null,
  last_completed_turn_id: null,
  current_last_completed_turn_id: "turn_1",
  closure_run_id: null,
  summarized_at: null,
  can_summarize: true,
};

const closureRun = {
  id: "closure_1",
  thread_id: "chat_1",
  source_thread_version: 2,
  last_completed_turn_id: "turn_1",
  source_hash: "source-hash",
  closure_eligibility: "learning_summary",
  status: "preview_ready" as const,
  committed_snapshot: {},
  generated_result: {},
  memory_run_id: previewedRun.id,
  memory_run: previewedRun,
  thread_summary: previewSummary,
  error: "",
  reason: "",
  active_operation_id: null,
  active_operation_started_at: null,
  cancel_requested_at: null,
  created_at: "now",
  updated_at: "now",
  completed_at: null,
  version: 1,
};

describe("useMemoryController", () => {
  beforeEach(() => vi.clearAllMocks());

  it("creates a frozen server run and commits by run ID only", async () => {
    apiMocks.createMemoryRun.mockResolvedValue(previewedRun);
    apiMocks.commitMemoryRun.mockResolvedValue({
      ...previewedRun,
      status: "succeeded",
      result: { results: [{ target: "progress", action: "append", path: "progress.md" }], errors: [] },
    });
    const setActiveRunId = vi.fn();

    const { result } = renderHook(() =>
      useMemoryController({
        setActiveRunId,
        setActiveClosureRunId: vi.fn(),
        onMemoryChanged: vi.fn(),
      }),
    );

    act(() => result.current.updateDraft(result.current.drafts[0].id, "content", "remember"));
    await act(async () => {
      await result.current.previewUpdates();
    });
    await act(async () => {
      await result.current.commitRun();
    });

    expect(apiMocks.createMemoryRun).toHaveBeenCalledWith([
      { target: "progress", content: "remember", append: true, learner_pending: false },
    ]);
    expect(apiMocks.commitMemoryRun).toHaveBeenCalledWith("memory_1");
    expect(setActiveRunId).toHaveBeenCalledWith("memory_1");
  });

  it("restores the frozen payload by active run ID", async () => {
    apiMocks.loadMemoryRun.mockResolvedValue(previewedRun);

    const { result } = renderHook(() =>
      useMemoryController({
        activeRunId: "memory_1",
        setActiveRunId: vi.fn(),
        setActiveClosureRunId: vi.fn(),
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMocks.loadMemoryRun).toHaveBeenCalledWith("memory_1");
    expect(result.current.run?.updates_hash).toBe("hash");
    expect(result.current.drafts[0].content).toBe("remember");
  });

  it("restores and commits a closure through the closure owner", async () => {
    closureMocks.loadLearningClosure.mockResolvedValue(closureRun);
    const completedSummary = {
      ...previewSummary,
      status: "summarized" as const,
      source_thread_version: 2,
      last_completed_turn_id: "turn_1",
      closure_run_id: "closure_1",
      summarized_at: "now",
      can_summarize: false,
    };
    closureMocks.commitLearningClosure.mockResolvedValue({
      ...closureRun,
      status: "completed",
      thread_summary: completedSummary,
      memory_run: {
        ...previewedRun,
        status: "succeeded",
        result: {
          results: [{ target: "progress", action: "append", path: "progress.md" }],
          errors: [],
        },
      },
    });
    const setActiveRunId = vi.fn();
    const onMemoryChanged = vi.fn();
    const onSummaryChanged = vi.fn();

    const { result } = renderHook(() =>
      useMemoryController({
        activeClosureRunId: "closure_1",
        setActiveClosureRunId: vi.fn(),
        setActiveRunId,
        onMemoryChanged,
        onSummaryChanged,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.isClosurePreview).toBe(true);
    expect(result.current.drafts[0].content).toBe("remember");
    expect(onSummaryChanged).toHaveBeenCalledWith(previewSummary);

    await act(async () => {
      await result.current.commitRun();
    });

    expect(closureMocks.commitLearningClosure).toHaveBeenCalledWith("closure_1");
    expect(apiMocks.commitMemoryRun).not.toHaveBeenCalled();
    expect(onSummaryChanged).toHaveBeenLastCalledWith(completedSummary);
    expect(onMemoryChanged).toHaveBeenCalledTimes(1);
  });
});
