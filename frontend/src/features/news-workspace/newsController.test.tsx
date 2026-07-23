// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, renderHook } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import type { NewsRunResponse } from "../../types";
import { useNewsController } from "./newsController";

const apiMocks = vi.hoisted(() => ({
  createNewsRun: vi.fn(),
  digestNewsRun: vi.fn(),
  discussNewsRun: vi.fn(),
  enrichNewsRun: vi.fn(),
  getNewsRun: vi.fn(),
  searchNewsRun: vi.fn(),
}));

vi.mock("../../api", () => apiMocks);

function newsRun(overrides: Partial<NewsRunResponse> = {}): NewsRunResponse {
  return {
    id: "news-server-1",
    query: "AI",
    stage: "searched",
    status: "running",
    safe_mode: false,
    items: [{ title: "A" }],
    digest: "",
    source_block: "",
    article_coverage: {},
    discussion: "",
    warnings: [],
    error: "",
    group_thread_id: null,
    version: 1,
    created_at: "now",
    updated_at: "now",
    ...overrides,
  };
}

const chatSettings = {
  selectedRole: "auto",
  selectedMode: "auto",
  selectedModel: "flash",
  relationshipMode: "standard",
  contextMode: "fast",
};

describe("useNewsController", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
  });

  it("owns all stages and stores the server-issued run ID", async () => {
    apiMocks.createNewsRun.mockResolvedValue(
      newsRun({ stage: "created", status: "running", items: [] }),
    );
    apiMocks.searchNewsRun.mockResolvedValue(newsRun());
    apiMocks.enrichNewsRun.mockResolvedValue(newsRun({ stage: "enriched" }));
    apiMocks.digestNewsRun.mockResolvedValue(
      newsRun({ stage: "digested", digest: "digest", source_block: "source" }),
    );
    apiMocks.discussNewsRun.mockResolvedValue(
      newsRun({
        stage: "discussed",
        status: "completed",
        digest: "digest",
        discussion: "discussion",
        group_thread_id: "group-server-1",
      }),
    );
    const setActiveRunId = vi.fn();
    const onDiscussed = vi.fn();

    const { result } = renderHook(() => {
      const [activeRunId, setActiveRunIdState] = useState<string>();
      return useNewsController({
        query: "AI",
        readArticles: true,
        chatSettings,
        groupThreadId: "group-current",
        activeRunId,
        setActiveRunId: (runId: string) => {
          setActiveRunId(runId);
          setActiveRunIdState(runId);
        },
        onDiscussed,
      });
    });

    await act(async () => result.current.search({ preventDefault: vi.fn() } as never));
    expect(result.current.run?.stage).toBe("searched");
    expect(result.current.canEnrich).toBe(true);
    await act(async () => result.current.enrich());
    await act(async () => result.current.digest());
    await act(async () => result.current.discuss());

    expect(setActiveRunId).toHaveBeenCalledWith("news-server-1");
    expect(apiMocks.enrichNewsRun).toHaveBeenCalledWith("news-server-1", 6, expect.any(Object));
    expect(apiMocks.digestNewsRun).toHaveBeenCalledWith("news-server-1", expect.any(Object), expect.any(Object));
    expect(apiMocks.discussNewsRun).toHaveBeenCalledWith("news-server-1", "group-current", expect.any(Object), expect.any(Object));
    expect(onDiscussed).toHaveBeenCalledWith("group-server-1");
    expect(result.current.run?.stage).toBe("discussed");
    expect(operationRegistry.size).toBe(0);
  });

  it("resyncs after digest failure and does not repeat automatic enrich", async () => {
    apiMocks.createNewsRun.mockResolvedValue(newsRun({ stage: "created", items: [] }));
    apiMocks.searchNewsRun.mockResolvedValue(newsRun());
    apiMocks.enrichNewsRun.mockResolvedValue(newsRun({ stage: "enriched" }));
    apiMocks.digestNewsRun
      .mockRejectedValueOnce(new Error("digest unavailable"))
      .mockResolvedValueOnce(newsRun({ stage: "digested", digest: "digest" }));
    apiMocks.getNewsRun.mockResolvedValue(
      newsRun({ stage: "enriched", status: "failed", error: "digest unavailable" }),
    );

    const { result } = renderHook(() => {
      const [activeRunId, setActiveRunId] = useState<string>();
      return useNewsController({
        query: "AI",
        readArticles: true,
        chatSettings,
        activeRunId,
        setActiveRunId,
        onDiscussed: vi.fn(),
      });
    });

    await act(async () => result.current.search());
    await act(async () => result.current.digest());

    expect(result.current.run?.stage).toBe("enriched");
    expect(result.current.run?.status).toBe("failed");
    expect(result.current.error).toBe("digest unavailable");

    await act(async () => result.current.digest());

    expect(apiMocks.enrichNewsRun).toHaveBeenCalledTimes(1);
    expect(apiMocks.digestNewsRun).toHaveBeenCalledTimes(2);
    expect(result.current.run?.stage).toBe("digested");
  });
});
