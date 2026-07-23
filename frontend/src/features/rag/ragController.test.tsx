// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRagController } from "./ragController";

const apiMocks = vi.hoisted(() => ({
  createRagQueryRun: vi.fn(),
  loadRagRun: vi.fn(),
}));
vi.mock("../../api", () => apiMocks);

const settings = { retrievalMode: "hybrid" as const, topK: 5, chatTopK: 3, minScore: 0.01 };
const queryRun = {
  id: "rag_query_1",
  kind: "query" as const,
  status: "completed" as const,
  request: { query: "alpha" },
  result: { query: "alpha", retrieval_mode: "hybrid", result_count: 1, context: "ctx", sources: "src", results: [], debug: {} },
  error: "",
  index_version: 2,
  version: 2,
  created_at: "now",
  updated_at: "now",
};

describe("useRagController", () => {
  beforeEach(() => vi.clearAllMocks());

  it("owns query state and persists the server run id", async () => {
    apiMocks.createRagQueryRun.mockResolvedValue(queryRun);
    const setActiveRunId = vi.fn();
    const { result } = renderHook(() =>
      useRagController({ settings, setActiveRunId, setOperationError: vi.fn() }),
    );
    await act(async () => {
      await result.current.search("alpha");
    });

    expect(result.current.result?.result_count).toBe(1);
    expect(setActiveRunId).toHaveBeenCalledWith("rag_query_1");
  });

  it("restores query result after refresh", async () => {
    apiMocks.loadRagRun.mockResolvedValue(queryRun);
    const { result } = renderHook(() =>
      useRagController({
        settings,
        activeRunId: "rag_query_1",
        setActiveRunId: vi.fn(),
        setOperationError: vi.fn(),
      }),
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.result?.query).toBe("alpha");
  });
});
