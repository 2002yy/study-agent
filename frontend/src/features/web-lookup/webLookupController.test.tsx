import React from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { operationRegistry } from "../../app/operationRegistry";
import { useWebLookupController } from "./webLookupController";

const apiMocks = vi.hoisted(() => ({
  createResearchRun: vi.fn(),
  executeResearchRun: vi.fn(),
  retryResearchRun: vi.fn(),
  resumeResearchRun: vi.fn(),
  cancelResearchRun: vi.fn(),
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
    research_context: {},
    query_attempts: [{ status: "found" }],
    selected_sources: [],
    rejected_sources: [],
    provider_status: "found",
    stop_reason: "sources_read",
    answer_confidence: "medium",
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

  it("creates a durable run before executing research", async () => {
    apiMocks.createResearchRun.mockResolvedValue(
      runPayload({
        status: "pending",
        stage: "planned",
        news_items: [],
        source_block: "",
      }),
    );
    apiMocks.executeResearchRun.mockResolvedValue(runPayload());
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
    expect(apiMocks.executeResearchRun).toHaveBeenCalledWith(
      "web_lookup_1",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(controller?.result?.run_id).toBe("web_lookup_1");
    expect(controller?.useInChat).toBe(true);
    expect(setActiveRunId).toHaveBeenCalledWith("web_lookup_1");
    expect(errors[errors.length - 1]).toBe("");
  });

  it("rehydrates and resumes a pending run instead of creating another", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({
        run_id: "web_lookup_saved",
        query_text: "saved",
        status: "pending",
        stage: "planned",
        news_items: [],
      }),
    );
    apiMocks.resumeResearchRun.mockResolvedValue(
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
      await Promise.resolve();
    });
    await act(async () => {
      await controller?.lookup();
    });

    expect(apiMocks.loadResearchRun).toHaveBeenCalledWith("web_lookup_saved");
    expect(apiMocks.resumeResearchRun).toHaveBeenCalledWith(
      "web_lookup_saved",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(apiMocks.createResearchRun).not.toHaveBeenCalled();
  });

  it("retries a failed same-query run", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({
        run_id: "web_lookup_failed",
        status: "failed",
        stage: "failed",
        provider_status: "provider_failed",
        error: "provider unavailable",
        news_items: [],
      }),
    );
    apiMocks.retryResearchRun.mockResolvedValue(
      runPayload({ run_id: "web_lookup_failed" }),
    );
    let controller: ReturnType<typeof useWebLookupController> | undefined;

    function Harness() {
      controller = useWebLookupController({
        query: "Python docs",
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_failed",
        setActiveRunId: vi.fn(),
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
      await Promise.resolve();
    });
    await act(async () => {
      await controller?.lookup();
    });

    expect(apiMocks.retryResearchRun).toHaveBeenCalled();
    expect(apiMocks.createResearchRun).not.toHaveBeenCalled();
  });

  it("sends server cancellation before invalidating the browser request", async () => {
    apiMocks.loadResearchRun.mockResolvedValue(
      runPayload({
        status: "running",
        stage: "reading",
        active_operation_id: "op_1",
      }),
    );
    apiMocks.cancelResearchRun.mockResolvedValue(
      runPayload({
        status: "cancelled",
        stage: "cancelled",
        provider_status: "partial",
      }),
    );
    let controller: ReturnType<typeof useWebLookupController> | undefined;

    function Harness() {
      controller = useWebLookupController({
        query: "Python docs",
        setOperationError: vi.fn(),
        activeRunId: "web_lookup_1",
        setActiveRunId: vi.fn(),
      });
      return null;
    }

    await act(async () => {
      create(<Harness />);
      await Promise.resolve();
    });
    await act(async () => {
      controller?.cancel();
      await Promise.resolve();
    });

    expect(apiMocks.cancelResearchRun).toHaveBeenCalledWith("web_lookup_1");
    expect(controller?.result?.status).toBe("cancelled");
    expect(controller?.useInChat).toBe(false);
  });
});
