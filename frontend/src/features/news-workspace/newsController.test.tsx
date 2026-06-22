import React from "react";
import { act, create } from "react-test-renderer";
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

describe("useNewsController", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
  });

  it("owns all stages and stores the server-issued run ID", async () => {
    apiMocks.createNewsRun.mockResolvedValue(newsRun());
    apiMocks.enrichNewsRun.mockResolvedValue(newsRun({ stage: "enriched" }));
    apiMocks.digestNewsRun.mockResolvedValue(
      newsRun({ stage: "digested", digest: "digest", source_block: "source" })
    );
    apiMocks.discussNewsRun.mockResolvedValue(
      newsRun({
        stage: "discussed",
        status: "completed",
        digest: "digest",
        discussion: "discussion",
        group_thread_id: "group-server-1",
      })
    );
    const setActiveRunId = vi.fn();
    const onDiscussed = vi.fn();
    let controller: ReturnType<typeof useNewsController> | undefined;

    function Harness() {
      const [activeRunId, setActiveRunIdState] = React.useState<string>();
      controller = useNewsController({
        query: "AI",
        readArticles: true,
        chatSettings: {
          selectedRole: "auto",
          selectedMode: "auto",
          selectedModel: "flash",
          relationshipMode: "standard",
          contextMode: "fast",
        },
        groupThreadId: "group-current",
        activeRunId,
        setActiveRunId: (runId) => {
          setActiveRunId(runId);
          setActiveRunIdState(runId);
        },
        onDiscussed,
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    await act(async () => controller!.search({ preventDefault: vi.fn() } as never));
    expect(controller!.run?.stage).toBe("searched");
    expect(controller!.canEnrich).toBe(true);
    await act(async () => controller!.enrich());
    await act(async () => controller!.digest());
    await act(async () => controller!.discuss());

    expect(setActiveRunId).toHaveBeenCalledWith("news-server-1");
    expect(apiMocks.enrichNewsRun).toHaveBeenCalledWith(
      "news-server-1",
      6,
      expect.any(Object)
    );
    expect(apiMocks.digestNewsRun).toHaveBeenCalledWith(
      "news-server-1",
      expect.any(Object),
      expect.any(Object)
    );
    expect(apiMocks.discussNewsRun).toHaveBeenCalledWith(
      "news-server-1",
      "group-current",
      expect.any(Object),
      expect.any(Object)
    );
    expect(onDiscussed).toHaveBeenCalledWith("group-server-1");
    expect(controller!.run?.stage).toBe("discussed");
    expect(operationRegistry.size).toBe(0);
  });
});
