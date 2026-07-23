// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LocalKnowledgeInvocation } from "../../api";
import { operationRegistry } from "../../app/operationRegistry";
import type { ToolRunResponse } from "../../types";
import { useToolController } from "./toolController";

const apiMocks = vi.hoisted(() => ({
  callToolRun: vi.fn(),
  createToolRun: vi.fn(),
  getToolRun: vi.fn(),
}));

vi.mock("../../api", () => apiMocks);

function toolRun(overrides: Partial<ToolRunResponse> = {}): ToolRunResponse {
  return {
    id: "tool-server-1",
    tool_name: "retrieve_local_knowledge",
    args: { query: "RAG", retrieval_mode: "hybrid", top_k: 3, min_score: 0.1 },
    args_hash: "hash",
    status: "previewed",
    preview: { will_retrieve: true },
    result: {},
    reason: "",
    elapsed_ms: 0,
    active_operation_id: null,
    active_operation_started_at: null,
    previewed_at: "now",
    completed_at: null,
    version: 1,
    created_at: "now",
    updated_at: "now",
    ...overrides,
  };
}

const initialInvocation: LocalKnowledgeInvocation = {
  query: "RAG",
  retrievalMode: "hybrid",
  topK: 3,
  minScore: 0.1,
};

describe("useToolController", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
  });

  it("freezes preview identity and calls only by server ToolRun ID", async () => {
    apiMocks.createToolRun.mockResolvedValue(toolRun());
    apiMocks.callToolRun.mockResolvedValue(
      toolRun({ status: "succeeded", result: { status: "found" } }),
    );

    const { result } = renderHook(() => {
      const [activeRunId, setActiveRunId] = useState<string>();
      const [invocation, setInvocation] = useState(initialInvocation);
      return {
        controller: useToolController({ invocation, activeRunId, setActiveRunId }),
        setInvocation,
      };
    });

    await act(async () => result.current.controller.preview());
    expect(result.current.controller.canCall).toBe(true);

    await act(async () => {
      result.current.setInvocation((current: LocalKnowledgeInvocation) => ({ ...current, topK: 8 }));
    });
    expect(result.current.controller.canCall).toBe(false);
    expect(result.current.controller.callBlockedReason).toContain("重新预览");
    await act(async () => result.current.controller.call());
    expect(apiMocks.callToolRun).not.toHaveBeenCalled();

    await act(async () => {
      result.current.setInvocation(initialInvocation);
    });
    await act(async () => result.current.controller.call());
    expect(apiMocks.callToolRun).toHaveBeenCalledWith(
      "tool-server-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(result.current.controller.run?.status).toBe("succeeded");
  });

  it("resyncs the persisted result when the call response is lost", async () => {
    apiMocks.createToolRun.mockResolvedValue(toolRun());
    apiMocks.callToolRun.mockRejectedValue(new Error("response lost"));
    apiMocks.getToolRun.mockResolvedValue(
      toolRun({ status: "succeeded", result: { status: "found" } }),
    );

    const { result } = renderHook(() => {
      const [activeRunId, setActiveRunId] = useState<string>();
      return useToolController({ invocation: initialInvocation, activeRunId, setActiveRunId });
    });

    await act(async () => result.current.preview());
    await act(async () => result.current.call());

    expect(apiMocks.getToolRun).toHaveBeenCalledWith("tool-server-1");
    expect(result.current.run?.status).toBe("succeeded");
    expect(result.current.error).toBe("response lost");
  });
});
