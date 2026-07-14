import React from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoryController } from "./memoryController";

const apiMocks = vi.hoisted(() => ({
  createMemoryRun: vi.fn(),
  loadMemoryRun: vi.fn(),
  commitMemoryRun: vi.fn()
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
    updates: [{ target: "progress", path: "progress.md", action: "append", allowed: true, preview: "remember" }]
  },
  result: {},
  reason: "",
  version: 1,
  created_at: "now",
  updated_at: "now"
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
      result: { results: [{ target: "progress", action: "append", path: "progress.md" }], errors: [] }
    });
    const setActiveRunId = vi.fn();
    let controller: ReturnType<typeof useMemoryController> | undefined;

    function Harness() {
      controller = useMemoryController({
        setActiveRunId,
        setActiveClosureRunId: vi.fn(),
        onMemoryChanged: vi.fn()
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    act(() => controller?.updateDraft(controller?.drafts[0].id, "content", "remember"));
    await act(async () => {
      await controller?.previewUpdates();
    });
    await act(async () => {
      await controller?.commitRun();
    });

    expect(apiMocks.createMemoryRun).toHaveBeenCalledWith([
      { target: "progress", content: "remember", append: true, learner_pending: false }
    ]);
    expect(apiMocks.commitMemoryRun).toHaveBeenCalledWith("memory_1");
    expect(setActiveRunId).toHaveBeenCalledWith("memory_1");
  });

  it("restores the frozen payload by active run ID", async () => {
    apiMocks.loadMemoryRun.mockResolvedValue(previewedRun);
    let controller: ReturnType<typeof useMemoryController> | undefined;

    function Harness() {
      controller = useMemoryController({
        activeRunId: "memory_1",
        setActiveRunId: vi.fn(),
        setActiveClosureRunId: vi.fn()
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMocks.loadMemoryRun).toHaveBeenCalledWith("memory_1");
    expect(controller?.run?.updates_hash).toBe("hash");
    expect(controller?.drafts[0].content).toBe("remember");
  });

  it("restores and commits a closure through the closure owner", async () => {
    closureMocks.loadLearningClosure.mockResolvedValue(closureRun);
    closureMocks.commitLearningClosure.mockResolvedValue({
      ...closureRun,
      status: "completed",
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
    let controller: ReturnType<typeof useMemoryController> | undefined;

    function Harness() {
      controller = useMemoryController({
        activeClosureRunId: "closure_1",
        setActiveClosureRunId: vi.fn(),
        setActiveRunId,
        onMemoryChanged,
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
      await Promise.resolve();
    });
    expect(controller?.isClosurePreview).toBe(true);
    expect(controller?.drafts[0].content).toBe("remember");

    await act(async () => {
      await controller?.commitRun();
    });

    expect(closureMocks.commitLearningClosure).toHaveBeenCalledWith("closure_1");
    expect(apiMocks.commitMemoryRun).not.toHaveBeenCalled();
    expect(onMemoryChanged).toHaveBeenCalledTimes(1);
  });
});
