import React from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useMemoryController } from "./memoryController";

const apiMocks = vi.hoisted(() => ({
  createMemoryRun: vi.fn(),
  loadMemoryRun: vi.fn(),
  commitMemoryRun: vi.fn()
}));

vi.mock("../../api", () => apiMocks);

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
      controller = useMemoryController({ setActiveRunId, onMemoryChanged: vi.fn() });
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
        setActiveRunId: vi.fn()
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
});
