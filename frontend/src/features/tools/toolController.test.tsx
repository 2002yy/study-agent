import React from "react";
import { act, create } from "react-test-renderer";
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
    args: {
      query: "RAG",
      retrieval_mode: "hybrid",
      top_k: 3,
      min_score: 0.1,
    },
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
      toolRun({ status: "succeeded", result: { status: "found" } })
    );
    let controller: ReturnType<typeof useToolController> | undefined;
    let setInvocation: React.Dispatch<React.SetStateAction<LocalKnowledgeInvocation>>;

    function Harness() {
      const [activeRunId, setActiveRunId] = React.useState<string>();
      const [invocation, setInvocationState] = React.useState(initialInvocation);
      setInvocation = setInvocationState;
      controller = useToolController({ invocation, activeRunId, setActiveRunId });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    await act(async () => controller!.preview());
    expect(controller!.canCall).toBe(true);

    await act(async () => {
      setInvocation!((current) => ({ ...current, topK: 8 }));
    });
    expect(controller!.canCall).toBe(false);
    expect(controller!.callBlockedReason).toContain("重新预览");
    await act(async () => controller!.call());
    expect(apiMocks.callToolRun).not.toHaveBeenCalled();

    await act(async () => {
      setInvocation!(initialInvocation);
    });
    await act(async () => controller!.call());
    expect(apiMocks.callToolRun).toHaveBeenCalledWith(
      "tool-server-1",
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    expect(controller!.run?.status).toBe("succeeded");
  });

  it("resyncs the persisted result when the call response is lost", async () => {
    apiMocks.createToolRun.mockResolvedValue(toolRun());
    apiMocks.callToolRun.mockRejectedValue(new Error("response lost"));
    apiMocks.getToolRun.mockResolvedValue(
      toolRun({ status: "succeeded", result: { status: "found" } })
    );
    let controller: ReturnType<typeof useToolController> | undefined;

    function Harness() {
      const [activeRunId, setActiveRunId] = React.useState<string>();
      controller = useToolController({
        invocation: initialInvocation,
        activeRunId,
        setActiveRunId,
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    await act(async () => controller!.preview());
    await act(async () => controller!.call());

    expect(apiMocks.getToolRun).toHaveBeenCalledWith("tool-server-1");
    expect(controller!.run?.status).toBe("succeeded");
    expect(controller!.error).toBe("response lost");
  });
});
