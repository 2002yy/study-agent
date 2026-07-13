import React from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { useWebLookupController } from "./webLookupController";

const apiMocks = vi.hoisted(() => ({
  createResearchRun: vi.fn(),
  searchResearchRun: vi.fn(),
  retryResearchRun: vi.fn(),
  loadResearchRun: vi.fn(),
}));

vi.mock("./researchApi", () => apiMocks);

function runPayload(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "web_lookup_1",
    query_text: "Python docs",
    news_items: [{ title: "Python" }],
    source_block: "source",
    warnings: [],
    status: "completed",
    stage: "completed",
    query_plan: {},
    attempts: [{ attempt: 1 }],
    empty_reason: "",
    error: "",
    max_items: 8,
    version: 1,
    created_at: "2026-07-13T00:00:00+00:00",
    updated_at: "2026-07-13T00:00:01+00:00",
    completed_at: "2026-07-13T00:00:01+00:00",
    ...overrides,
  };
}

describe("useWebLookupController", () => {
  beforeEach(() => {
    operationRegistry.cancelAll();
    vi.clearAllMocks();
  });

  it("creates a durable run before search and owns the completed result", async () => {
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({ status: "pending", stage: "planned", news_items: [], source_block: "" }),
    );
    apiMocks.searchResearchRun.mockResolvedValue(runPayload());
    const errors: string[] = [];
    const setActiveRunId = vi.fn();
    let controller: ReturnType<typeof useWebLookupController> | undefined;

    function Harness() {
      controller = useWebLookupController({
        query: "Python docs",
        setOperationError: (message) => errors.push(message),
        activeRunId: undefined,
        setActiveRunId,
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    await act(async () => {
      await controller?.lookup();
    });

    expect(apiMocks.createResearchRun).toHaveBeenCalledWith(
      "Python docs",
      8,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(apiMocks.searchResearchRun).toHaveBeenCalledWith(
      "web_lookup_1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(controller?.result?.run_id).toBe("web_lookup_1");
    expect(controller?.useInChat).toBe(true);
    expect(controller?.isBusy).toBe(false);
    expect(setActiveRunId).toHaveBeenCalledWith("web_lookup_1");
    expect(errors[errors.length - 1]).toBe("");
  });

  it("rehydrates a durable run after refresh", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({ run_id: "web_lookup_saved", query_text: "saved" }),
    );
    let controller: ReturnType<typeof useWebLookupController> | undefined;

    function Harness() {
      controller = useWebLookupController({
        query: "saved",
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_saved",
        setActiveRunId: vi.fn(),
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(apiMocks.loadResearchRun).toHaveBeenCalledWith("web_lookup_saved");
    expect(controller?.result?.run_id).toBe("web_lookup_saved");
    expect(controller?.useInChat).toBe(true);
  });

  it("creates a new run instead of retrying when the query changed", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({
        run_id: "web_lookup_old",
        query_text: "old query",
        status: "failed",
        stage: "failed",
        error: "provider unavailable",
      }),
    );
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({
        run_id: "web_lookup_new",
        query_text: "new query",
        status: "pending",
        stage: "planned",
        news_items: [],
        source_block: "",
      }),
    );
    apiMocks.searchResearchRun.mockResolvedValue(
      runPayload({ run_id: "web_lookup_new", query_text: "new query" }),
    );
    let controller: ReturnType<typeof useWebLookupController> | undefined;
    let renderer: ReturnType<typeof create>;

    function Harness({ query }: { query: string }) {
      controller = useWebLookupController({
        query,
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_old",
        setActiveRunId: vi.fn(),
      });
      return null;
    }

    await act(async () => {
      renderer = create(<Harness query="old query" />);
      await Promise.resolve();
    });
    await act(async () => {
      renderer.update(<Harness query="new query" />);
    });
    await act(async () => {
      await controller?.lookup();
    });

    expect(apiMocks.retryResearchRun).not.toHaveBeenCalled();
    expect(apiMocks.createResearchRun).toHaveBeenCalledWith(
      "new query",
      8,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(controller?.result?.run_id).toBe("web_lookup_new");
  });
});
